# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Application services shared by the desktop UI (all functions take an open sqlite3 connection)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta

from . import b3, db, engine, history, market, tax
from .assets import ASSET_TYPES, FX_SYMBOL, IBOV_SYMBOL, QUOTED_TYPES, currency, yahoo_symbol
from .b3 import EPS, parse_date, parse_num
from .valuation import Valuer

STALE = timedelta(hours=12)  # monthly history, Tesouro prices and BCB series refresh at most twice a day


def excluded_kinds(meta: dict) -> set[str]:
    """Fixed-income product kinds the user chose to ignore (e.g. {'CDB'})."""
    try:
        return set(json.loads(meta.get("exclude_kinds") or "[]"))
    except ValueError:
        return set()


def _context(con, today: date | None = None):
    today = today or date.today()
    data = db.load(con)
    events = engine.build_ledger(data["trades"], data["movements"], data["manual"], excluded_kinds(data["meta"]))
    book = engine.run(events)
    fx = data["meta"].get("usdbrl")
    valuer = Valuer(data["settings"], data["series"], float(fx) if fx else None, today)
    return data, events, book, valuer, today


def state(con) -> dict:
    data, events, book, valuer, today = _context(con)
    pf = engine.build_portfolio(book, data["settings"], data["targets"], valuer)
    costs = {code: p.cost for code, p in book.positions.items() if p.qty > EPS}
    prov = engine.summarize_proventos(book.proventos, costs, today)
    pf["summary"].update(
        proventos_12m=prov["last12"],
        proventos_year=prov["year"],
        usdbrl=valuer.fx_now,
        market_at=data["meta"].get("market_at"),
    )
    kinds = Counter(b3.parse_product(m["product"]).get("kind") for m in data["movements"])
    kinds.pop(None, None)
    exclude = excluded_kinds(data["meta"])
    return {
        **pf,
        "proventos": prov,
        "history": history.build_history(events, book, data["settings"], valuer, today),
        "ledger": events,
        "warnings": book.warnings,
        "targets": data["targets"],
        "manual": data["manual"],
        "ir_years": tax.years(events, today),
        "asset_types": [{"type": t, **m} for t, m in ASSET_TYPES.items()],
        "filters": {"exclude": sorted(exclude), "kinds": dict(sorted(kinds.items()))},
        "counts": {
            "trades": len(data["trades"]),
            "movements": len(data["movements"]),
            "manual": len(data["manual"]),
            "excluded": sum(n for k, n in kinds.items() if k in exclude),
        },
    }


def set_filters(con, exclude: list[str]) -> dict:
    kinds = sorted({str(k).strip().upper() for k in exclude if str(k).strip()})
    db.set_meta(con, "exclude_kinds", json.dumps(kinds))
    return {"exclude": kinds}


def ir(con, year: int | None = None) -> dict:
    data, events, book, valuer, today = _context(con)
    months = tax.monthly(book.sales)
    report = tax.annual(int(year or today.year), events, book, months)
    report["pending_darf"] = months[-1]["darf_pending"] if months else 0.0
    return report


def import_file(con, filename: str, content: bytes) -> dict:
    kind, records = b3.parse_file(content, source=filename)
    inserted = db.insert_records(con, kind, records)
    return {
        "file": filename,
        "kind": kind,
        "rows": len(records),
        "inserted": inserted,
        "duplicates": len(records) - inserted,
    }


def aporte(con, amount: float) -> dict:
    return engine.plan_aporte(state(con)["classes"], amount)


# ------------------------------------------------------------ market data
def _stale(stamp: str | None) -> bool:
    try:
        return not stamp or datetime.now() - datetime.fromisoformat(stamp) > STALE
    except ValueError:
        return True


def refresh_market(con, force: bool = False) -> dict:
    """Quotes now; monthly price history, Tesouro prices and BCB rates when stale (or forced)."""
    data, events, book, valuer, today = _context(con)
    settings, meta, stamp = data["settings"], data["meta"], db.now()
    types = {code: p.asset_type for code, p in book.positions.items()}
    for code, s in settings.items():
        types.setdefault(code, s.get("asset_type") or b3.listed_type(code))
    report = {"updated": {}, "errors": {}, "warnings": {}}  # errors: quotes; warnings: background data
    uses_usd = any(currency(t) == "USD" for t in types.values())
    first = date.fromisoformat(events[0]["date"]) if events else today

    # 1. current quotes: held assets + watchlist (nota > 0)
    wanted = {}
    for code, t in types.items():
        held = code in book.positions and book.positions[code].qty > EPS
        if t in QUOTED_TYPES and (held or (settings.get(code, {}).get("nota") or 0) > 0):
            wanted[yahoo_symbol(code, t)] = code
    if uses_usd:
        wanted[FX_SYMBOL] = None
    prices, errors = market.parallel(market.fetch_quote, wanted)
    db.save_quotes(con, {wanted[s]: v for s, v in prices.items() if wanted[s]})
    if FX_SYMBOL in prices:
        db.set_meta(con, "usdbrl", str(prices[FX_SYMBOL]))
    report["updated"] = {wanted[s]: v for s, v in prices.items() if wanted[s]}
    report["errors"].update({wanted.get(s) or s: e for s, e in errors.items()})

    # 2. monthly closes for everything ever held (+ Ibovespa and USD/BRL)
    symbols = {yahoo_symbol(c, t) for c, t in types.items() if t in QUOTED_TYPES and c in book.positions}
    symbols |= {IBOV_SYMBOL} | ({FX_SYMBOL} if uses_usd else set())
    due = [s for s in symbols if force or _stale(meta.get(f"fetched:Y:{s}"))]
    got, errors = market.parallel(lambda s: market.fetch_monthly(s, first), due)
    for symbol, rows in got.items():
        db.save_series(con, f"Y:{symbol}", rows, replace=True)
        db.set_meta(con, f"fetched:Y:{symbol}", stamp)
    report["warnings"].update({f"histórico {s}": e for s, e in errors.items()})

    # 3. Tesouro Direto prices for bonds ever held
    bonds = {c for c, t in types.items() if t == "tesouro" and c in book.positions}
    if bonds and (force or _stale(meta.get("fetched:TD"))):
        try:
            since = (first - timedelta(days=40)).isoformat()
            for name, rows in market.parse_tesouro(market.fetch_tesouro(), bonds).items():
                db.save_series(con, f"TD:{name}", [r for r in rows if r[0] >= since], replace=True)
            db.set_meta(con, "fetched:TD", stamp)
        except Exception as exc:
            report["warnings"]["Tesouro Direto"] = f"{type(exc).__name__}: {exc}"

    # 4. Banco Central series: CDI (benchmark + % CDI bonds), Selic / IPCA when some bond uses them
    needed = {market.CDI}
    for s in settings.values():
        needed |= {"selic": {market.SELIC}, "ipca": {market.IPCA}}.get(s.get("indexer") or "", set())
    for n in needed:
        key = f"BCB:{n}"
        if not (force or _stale(meta.get(f"fetched:{key}"))):
            continue
        try:
            start = first.replace(day=1) - timedelta(days=31)
            cached = data["series"].get(key, [])
            if cached and not force and cached[0][0] <= (start + timedelta(days=10)).isoformat():
                begin, replace = date.fromisoformat(cached[-1][0]) + timedelta(days=1), False  # incremental
            else:
                begin, replace = start, True
            if begin <= today:
                db.save_series(con, key, market.fetch_bcb(n, begin, today), replace=replace)
            db.set_meta(con, f"fetched:{key}", stamp)
        except Exception as exc:
            report["warnings"][key] = f"{type(exc).__name__}: {exc}"

    db.set_meta(con, "market_at", stamp)
    return report


# ------------------------------------------------------------ manual entries
def add_manual(con, data: dict) -> dict:
    op = (data.get("op") or "").strip()
    if op not in engine.MANUAL_LABELS:
        raise ValueError("operação inválida")
    asset_type = data.get("asset_type") or "outro"
    if asset_type not in ASSET_TYPES:
        raise ValueError("tipo de ativo inválido")
    code = (data.get("code") or "").strip()
    code = code.upper() if asset_type in QUOTED_TYPES else code
    if not code:
        raise ValueError("informe o ativo")
    day = parse_date(data.get("date"))
    if not day:
        raise ValueError("data inválida")
    num = lambda key: parse_num(data.get(key)) if data.get(key) not in (None, "") else None
    qty, price, total, fees = num("qty"), num("price"), num("total"), num("fees") or 0.0
    if op in ("buy", "sell"):
        if not qty or qty <= 0:
            raise ValueError("informe a quantidade")
        if total is None and price is None:
            raise ValueError("informe o preço unitário ou o valor total")
        total = qty * price if total is None else total
        price = total / qty if price is None else price
    elif total is None:
        if qty and price:
            total = qty * price
        else:
            raise ValueError("informe o valor total")
    ccy = (data.get("currency") or "BRL").upper()
    fx = 1.0 if ccy == "BRL" else num("fx")
    if not fx and ccy == "USD":
        fx = market.fetch_ptax(date.fromisoformat(day)) or (float(db.get_meta(con, "usdbrl") or 0) or None)
    if not fx:
        raise ValueError("informe o câmbio (R$ por unidade da moeda)")
    row = {
        "date": day,
        "op": op,
        "code": code,
        "name": (data.get("name") or "").strip() or None,
        "asset_type": asset_type,
        "qty": qty,
        "price": price,
        "total": total,
        "fees": fees,
        "currency": ccy,
        "fx": fx,
        "kind": (data.get("kind") or "Dividendo") if op == "provento" else None,
        "institution": (data.get("institution") or "").strip() or None,
        "note": (data.get("note") or "").strip() or None,
    }
    return {"id": db.add_manual(con, row), "fx": fx}
