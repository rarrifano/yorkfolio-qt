"""Portfolio engine (pure functions): ledger -> Book (positions, sales, proventos, cash flows)
-> carteira, proventos and balanceamento."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from . import native
from .assets import ASSET_TYPES, LISTED_TYPES, QUOTED_TYPES, STANDARD_CLASSES, currency, default_class
from .b3 import EPS, classify_movement, listed_type, norm

# Same-day ordering: money/shares in before shares out.
_ORDER = {
    "buy": 0,
    "adjust": 0,
    "bonus": 1,
    "split": 1,
    "reverse_split": 1,
    "daytrade": 2,
    "capital_return": 2,
    "provento": 3,
    "sell": 4,
    "fraction_out": 4,
}
MANUAL_LABELS = {"buy": "Compra", "sell": "Venda", "provento": "Provento", "adjust": "Ajuste de custo"}


def br_date(iso: str) -> str:
    return "/".join(reversed(iso[:10].split("-")))


# ---------------------------------------------------------------- ledger
def _amount(t: dict) -> float:
    return t["value"] if t.get("value") is not None else t["qty"] * (t.get("price") or 0.0)


def _trade_event(t: dict, **extra) -> dict:
    ev = {
        "date": t["date"],
        "code": t["ticker"],
        "name": "",
        "asset_type": listed_type(t["ticker"]),
        "action": "buy" if t["side"] == "C" else "sell",
        "label": "Compra" if t["side"] == "C" else "Venda",
        "direction": t["side"],
        "qty": t["qty"],
        "price": t["price"],
        "value": t["value"],
        "institution": t.get("institution") or "",
        "source": "Negociação",
        "note": "",
    }
    ev.update(extra)
    return ev


def build_ledger(
    trades: list[dict], movements: list[dict], manual: list[dict] = (), exclude: frozenset[str] | set[str] = frozenset()
) -> list[dict]:
    """Merge Negociação + Movimentação + manual entries into one ordered list of events.

    * `exclude`: fixed-income product kinds to ignore entirely (e.g. {"CDB"}); the raw rows stay
      in the database, so the filter also covers future imports and can be undone.
    * Negociação is the source of truth for trades. A buy and a sell of the same ticker on the
      same day at the same broker is a day trade: the matched quantity is closed at the day's
      average prices and only the remainder affects the position.
    * Each "Transferência - Liquidação" (D+2 settlement) in Movimentação is matched against the
      net traded quantity of the previous days (same ticker and broker); matched rows are
      skipped, unmatched ones (periods missing from the Negociação export) become trades.
    """
    events, index, groups = [], {}, defaultdict(list)
    for t in trades:
        market = norm(t.get("market"))
        if market and "vista" not in market and "fracion" not in market:
            events.append(_trade_event(t, action="unhandled", note=f"mercado não suportado: {t.get('market')}"))
            continue
        groups[(t["ticker"], t["date"], norm(t.get("institution")))].append(t)

    for key, group in groups.items():
        buys = [t for t in group if t["side"] == "C"]
        sells = [t for t in group if t["side"] == "V"]
        bq, sq = sum(t["qty"] for t in buys), sum(t["qty"] for t in sells)
        index[key] = [bq - sq, False]
        if not (buys and sells):
            events.extend(_trade_event(t) for t in group)
            continue
        bp, sp = sum(map(_amount, buys)) / bq, sum(map(_amount, sells)) / sq
        dq, base = min(bq, sq), group[0]
        events.extend(_trade_event(t, action="dt_part", note="parte de um day trade") for t in group)
        events.append(
            _trade_event(
                base,
                action="daytrade",
                label="Day trade",
                qty=dq,
                price=sp,
                value=dq * sp,
                buy_value=dq * bp,
                sell_value=dq * sp,
                note=f"compra média {bp:.2f} · venda média {sp:.2f}",
            )
        )
        if bq - dq > EPS:
            events.append(
                _trade_event(
                    base,
                    action="buy",
                    label="Compra (saldo do dia)",
                    direction="C",
                    qty=bq - dq,
                    price=bp,
                    value=(bq - dq) * bp,
                )
            )
        elif sq - dq > EPS:
            events.append(
                _trade_event(
                    base,
                    action="sell",
                    label="Venda (saldo do dia)",
                    direction="V",
                    qty=sq - dq,
                    price=sp,
                    value=(sq - dq) * sp,
                )
            )

    for m in movements:
        info = classify_movement(m)
        if info.get("kind") in exclude:
            continue
        ev = {
            "date": m["date"],
            "code": info["code"],
            "name": info["name"],
            "asset_type": info["asset_type"],
            "action": info["action"],
            "label": info["label"],
            "direction": m["direction"],
            "qty": m.get("qty"),
            "price": m.get("price"),
            "value": m.get("value"),
            "institution": m.get("institution") or "",
            "source": "Movimentação",
            "note": "",
            "kind": m["kind"],
        }
        if ev["action"] == "settlement":
            signed = (m.get("qty") or 0) * (1 if m["direction"] == "C" else -1)
            matched = _match_trade(index, info["code"], m["date"], norm(m.get("institution")), signed)
            if matched:
                ev["action"], ev["note"] = "skip", f"liquidação do negócio de {br_date(matched)} (já na Negociação)"
            else:
                ev["action"] = "buy" if m["direction"] == "C" else "sell"
        events.append(ev)

    for op in manual:
        events.append(manual_event(op))

    events.sort(key=lambda e: (e["date"], _ORDER.get(e["action"], 9)))
    return events


def manual_event(op: dict) -> dict:
    """User-entered operation -> event. Amounts are converted to BRL with the stored rate."""
    kind, fx = op["op"], op.get("fx") or 1.0
    qty, price, fees = op.get("qty") or 0.0, op.get("price"), op.get("fees") or 0.0
    total = op.get("total")
    if total is None:
        total = qty * (price or 0.0)
    gross = total + fees if kind in ("buy", "adjust") else total - fees if kind == "sell" else total
    return {
        "date": op["date"],
        "code": op["code"],
        "name": op.get("name") or "",
        "asset_type": op.get("asset_type") or "outro",
        "action": kind,
        "label": (op.get("kind") or "Provento") if kind == "provento" else MANUAL_LABELS[kind],
        "direction": "D" if kind == "sell" else "C",
        "qty": qty if kind != "adjust" else None,
        "price": price,
        "value": gross * fx,
        "value_ccy": gross,
        "currency": op.get("currency") or "BRL",
        "fx": fx,
        "institution": op.get("institution") or "",
        "source": "Manual",
        "note": op.get("note") or "",
        "op_id": op.get("id"),
    }


def _match_trade(index, code, settle_iso, institution, signed_qty):
    settle = date.fromisoformat(settle_iso)
    for back in range(1, 8):  # D+2 business days, up to a week with holidays
        day = (settle - timedelta(days=back)).isoformat()
        entry = index.get((code, day, institution))
        if entry and not entry[1] and abs(entry[0] - signed_qty) < 1e-6:
            entry[1] = True
            return day
    return None


# ---------------------------------------------------------------- positions
@dataclass
class Position:
    code: str
    name: str = ""
    asset_type: str = ""
    qty: float = 0.0
    cost: float = 0.0  # BRL
    cost_usd: float | None = 0.0  # USD cost for USD-quoted assets (None = bought in another currency)
    realized: float = 0.0
    realized_unknown: bool = False  # e.g. B3 "Vencimento" rows come with value 0
    proventos: float = 0.0
    first_date: str = ""
    last_date: str = ""
    institution: str = ""
    anchor: tuple | None = None  # (date, unit price) last price seen in a trade (fixed income valuation)

    @property
    def avg_price(self) -> float | None:
        return self.cost / self.qty if self.qty > EPS else None

    @property
    def avg_price_usd(self) -> float | None:
        if currency(self.asset_type) != "USD" or self.cost_usd is None or self.qty <= EPS:
            return None
        return self.cost_usd / self.qty


def _position(d: dict) -> Position:
    anchor = d.get("anchor")
    return Position(**{**d, "anchor": tuple(anchor) if anchor else None})


class Book:
    """Result of applying the ledger in date order (done by the C++ core, see core/src/book.cpp):
    weighted-average-cost positions, realized sales (for IR), proventos and external cash flows
    (for returns: + money in, - money out)."""

    def __init__(self, state: dict):
        self.positions: dict[str, Position] = {c: _position(p) for c, p in state["positions"].items()}
        self.sales: list[dict] = state.get("sales", [])
        self.proventos: list[dict] = state.get("proventos", [])
        self.flows: list[tuple[str, float]] = [tuple(f) for f in state["flows"]]
        self.warnings: list[dict] = state.get("warnings", [])
        self.names: dict[str, str] = state.get("names", {})  # names seen on any row (even skipped settlements)

    def finish(self) -> Book:
        for p in self.positions.values():
            p.name = p.name or self.names.get(p.code, "")
            if p.asset_type in LISTED_TYPES:
                p.asset_type = listed_type(p.code, p.name)
            elif not p.asset_type:
                p.asset_type = "outro"
        return self


def run(events: list[dict]) -> Book:
    book = native.NativeBook()
    book.apply_all(events)
    return Book(book.state()).finish()


def snapshots(events: list[dict], dates: list[str]) -> list[dict[str, Position]]:
    """Open positions after all events on or before each ISO date (ascending)."""
    book, out, i = native.NativeBook(), [], 0
    for d in dates:
        j = i
        while j < len(events) and events[j]["date"] <= d:
            j += 1
        book.apply_all(events[i:j])
        i = j
        out.append({c: _position(p) for c, p in book.state(full=False, open_only=True)["positions"].items()})
    return out


# ---------------------------------------------------------------- carteira
def _class_order(name: str):
    return (STANDARD_CLASSES.index(name), "") if name in STANDARD_CLASSES else (len(STANDARD_CLASSES), name)


def build_portfolio(book: Book, settings: dict[str, dict], targets: dict[str, float], valuer) -> dict:
    """Value positions, group them by class and attach targets/notas.

    settings[code]: class, nota, manual_price, manual_value, indexer, rate, quote, quote_at…
    targets[class]: target percentage (any scale; normalized here)
    valuer: valuation.Valuer (current prices, fixed income estimates, FX)
    """
    positions = book.positions
    assets, closed = [], []
    for code in sorted(set(positions) | set(settings)):
        s = settings.get(code, {})
        p = positions.get(code) or Position(
            code, name=s.get("name") or "", asset_type=s.get("asset_type") or listed_type(code)
        )
        quoted = p.asset_type in QUOTED_TYPES
        is_open = p.qty > EPS
        nota = s.get("nota")
        if nota is None:
            nota = 1.0 if quoted and is_open else 0.0
        if not (is_open or nota > 0):
            if code in positions:
                closed.append(
                    {
                        "code": code,
                        "name": p.name,
                        "class": s.get("class") or default_class(p.asset_type),
                        "realized": p.realized,
                        "realized_unknown": p.realized_unknown,
                        "proventos": p.proventos,
                        "last_date": p.last_date,
                    }
                )
            continue
        v = valuer.current(p, s)
        value = v["value"] if is_open else 0.0
        assets.append(
            {
                "code": code,
                "name": p.name,
                "asset_type": p.asset_type,
                "type_label": ASSET_TYPES.get(p.asset_type, ASSET_TYPES["outro"])["label"],
                "quoted": quoted,
                "currency": currency(p.asset_type),
                "class": s.get("class") or default_class(p.asset_type),
                "qty": p.qty,
                "avg_price": p.avg_price,
                "avg_price_usd": p.avg_price_usd,
                "cost": p.cost if is_open else 0.0,
                "price": v["price"],
                "price_brl": v["price_brl"],
                "source": v["source"],
                "source_note": v["note"],
                "quote_at": s.get("quote_at"),
                "manual_value": s.get("manual_value"),
                "manual_value_at": s.get("manual_value_at"),
                "indexer": s.get("indexer"),
                "rate": s.get("rate"),
                "value": value,
                "pnl": value - p.cost if is_open else None,
                "pnl_pct": (value - p.cost) / p.cost if is_open and p.cost > EPS else None,
                "realized": p.realized,
                "realized_unknown": p.realized_unknown,
                "proventos": p.proventos,
                "nota": nota,
                "first_date": p.first_date,
                "last_date": p.last_date,
                "open": is_open,
            }
        )

    total = sum(a["value"] for a in assets)
    target_sum = sum(max(0.0, t) for t in targets.values())
    by_class = defaultdict(list)
    for a in assets:
        by_class[a["class"]].append(a)
    for name, t in targets.items():
        if t > 0:
            by_class.setdefault(name, [])

    classes = []
    for name in sorted(by_class, key=_class_order):
        items = sorted(by_class[name], key=lambda a: -a["value"])
        value = sum(a["value"] for a in items)
        cost = sum(a["cost"] for a in items)
        target = max(0.0, targets.get(name, 0.0)) / target_sum if target_sum > 0 else 0.0
        nota_sum = sum(a["nota"] for a in items if a["nota"] > 0)
        for a in items:
            a["pct_class"] = a["value"] / value if value > EPS else 0.0
            a["pct_total"] = a["value"] / total if total > EPS else 0.0
            a["target_class"] = a["nota"] / nota_sum if a["nota"] > 0 and nota_sum > 0 else 0.0
            a["target_total"] = a["target_class"] * target
            a["gap"] = a["target_total"] * total - a["value"] if target_sum > 0 else None
        classes.append(
            {
                "name": name,
                "value": value,
                "cost": cost,
                "pnl": value - cost,
                "pct": value / total if total > EPS else 0.0,
                "target": target,
                "gap": target * total - value if target_sum > 0 else None,
                "assets": items,
            }
        )

    open_assets = [a for a in assets if a["open"]]
    cost = sum(a["cost"] for a in open_assets)
    quote_times = [a["quote_at"] for a in open_assets if a["quoted"] and a["source"] == "cotação" and a["quote_at"]]
    summary = {
        "value": total,
        "cost": cost,
        "pnl": total - cost,
        "pnl_pct": (total - cost) / cost if cost > EPS else None,
        "realized": sum(p.realized for p in positions.values()),
        "proventos_total": sum(p.proventos for p in positions.values()),
        "n_assets": len(open_assets),
        "targets_set": target_sum > 0,
        "missing_quotes": [a["code"] for a in open_assets if a["quoted"] and a["price"] is None],
        "quotes_at": min(quote_times) if quote_times else None,
    }
    class_names = sorted(set(STANDARD_CLASSES) | set(by_class) | {a["class"] for a in closed}, key=_class_order)
    return {"summary": summary, "classes": classes, "closed": closed, "class_names": class_names}


# ---------------------------------------------------------------- proventos
def summarize_proventos(items: list[dict], cost_by_code: dict[str, float], today: date) -> dict:
    items = sorted(items, key=lambda x: x["date"], reverse=True)
    start12 = (today - timedelta(days=365)).isoformat()
    by_year, by_month, by_type = defaultdict(float), defaultdict(float), defaultdict(float)
    by_asset = defaultdict(lambda: {"total": 0.0, "last12": 0.0, "count": 0})
    for x in items:
        by_year[x["date"][:4]] += x["value"]
        by_month[x["date"][:7]] += x["value"]
        by_type[x["type"]] += x["value"]
        a = by_asset[x["code"]]
        a["total"] += x["value"]
        a["count"] += 1
        if x["date"] > start12:
            a["last12"] += x["value"]

    months, (y, m) = [], (today.year, today.month)
    for _ in range(24):
        key = f"{y:04d}-{m:02d}"
        months.append({"month": key, "total": by_month.get(key, 0.0)})
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    last12 = sum(x["value"] for x in items if x["date"] > start12)
    assets = []
    for code, a in by_asset.items():
        cost = cost_by_code.get(code, 0.0)
        assets.append({"code": code, **a, "yoc": a["last12"] / cost if cost > EPS else None})
    return {
        "total": sum(by_year.values()),
        "last12": last12,
        "avg12": last12 / 12,
        "year": by_year.get(str(today.year), 0.0),
        "by_year": [{"year": k, "total": v} for k, v in sorted(by_year.items(), reverse=True)],
        "by_type": [{"type": k, "total": v} for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "months": list(reversed(months)),
        "by_asset": sorted(assets, key=lambda a: -a["total"]),
        "items": items,
    }


# ---------------------------------------------------------------- balanceamento
def waterfill(current: list[float], weights: list[float], amount: float) -> list[float]:
    """Split `amount` so the most underweight items (value / target weight) are topped up first
    (C++ core). Items with weight <= 0 never receive money."""
    return native.waterfill(current, weights, amount)


def plan_aporte(classes: list[dict], amount: float) -> dict:
    """Holder-style aporte (C++ core): money goes to the most underweight class, then to the most
    underweight assets (by nota) inside it, rounded to whole shares (crypto: fractional).
    Raises ValueError with a user-facing message on invalid input."""
    keep = ("code", "name", "value", "nota", "quoted", "price_brl", "asset_type")
    slim = [
        {
            "name": c["name"],
            "value": c["value"],
            "target": c["target"],
            "assets": [{k: a[k] for k in keep} for a in c["assets"]],
        }
        for c in classes
    ]
    return native.plan_aporte(slim, amount)
