"""IR (Brazilian income tax) support for B3 variable income: monthly apuração/DARF and the
annual declaration helper. A decision-support tool, not tax advice.

Rules implemented
* Swing trade ("operações comuns"): 15%. Shares (tickers ending 3–8) are exempt when the month's
  share sales are ≤ R$ 20.000; units, ETFs and BDRs are never exempt (conservative for units).
* Day trade: 20%. FIIs: 20%, no exemption. Each bucket carries its own losses forward.
* IRRF ("dedo-duro"): 0.005% of swing sales per day/broker when above R$ 1, 1% of positive
  day-trade results; deducted from the tax due, leftover carried within the same year.
* DARF (code 6015) below R$ 10 is carried to the following months.
Fees aren't in the B3 files: add them as "ajuste de custo" manual entries if you want them.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date

from .engine import snapshots

RATES = {"comum": 0.15, "daytrade": 0.20, "fii": 0.20}
EXEMPTION = 20_000.0
DARF_MIN = 10.0
_SHARE = re.compile(r"^[A-Z0-9]{4}[3-8]$")
_EXEMPT_FIXED_INCOME = ("LCI", "LCA", "CRI", "CRA")

# Bens e Direitos (DIRPF 2023+): suggestions only — always confirm in the Receita program.
BENS = {
    "acao": ("03", "01", "Ações"),
    "fii": ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
    "etf": ("07", "", "Fundos de índice (ETF) — confira o código no programa"),
    "bdr": ("04", "04", "Ativos negociados em bolsa no Brasil (BDRs e outros)"),
    "tesouro": ("04", "02", "Títulos sujeitos à tributação (Tesouro Direto, CDB…)"),
    "rf": ("04", "02", "Títulos sujeitos à tributação (Tesouro Direto, CDB…)"),
    "rf_isento": ("04", "03", "Títulos isentos (LCI, LCA, CRI, CRA)"),
    "stock": ("03", "01", "Ações — localização: Estados Unidos"),
    "reit": ("07", "", "REIT no exterior — confira o código no programa"),
    "etf_us": ("07", "", "ETF no exterior — confira o código no programa"),
    "crypto": ("08", "01/02", "Criptoativos (01 Bitcoin, 02 demais)"),
    "outro": ("", "", "Outros — confira"),
}


def category(sale: dict) -> str | None:
    t = sale["asset_type"]
    if t == "fii":
        return "fii"
    if t in ("acao", "etf", "bdr"):
        return "daytrade" if sale["daytrade"] else "comum"
    return None  # fixed income is taxed at source; exterior/crypto are outside this report


def exempt_eligible(sale: dict) -> bool:
    return sale["asset_type"] == "acao" and not sale["daytrade"] and bool(_SHARE.match(sale["code"]))


def due_date(month: str) -> str:
    """Last weekday of the following month (holidays not considered)."""
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d = d.replace(day=d.day - 1)
    return d.isoformat()


def _months(first: str, last: str):
    y, m = int(first[:4]), int(first[5:7])
    while f"{y:04d}-{m:02d}" <= last:
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _irrf(sales: list[dict]) -> float:
    swing, daytrade = defaultdict(float), defaultdict(float)
    for s in sales:
        key = (s["date"], s["institution"])
        if s["daytrade"]:
            daytrade[key] += s["gain"]
        else:
            swing[key] += s["proceeds"]
    return sum(v * 0.00005 for v in swing.values() if v * 0.00005 > 1.0) + sum(
        g * 0.01 for g in daytrade.values() if g > 0
    )


def monthly(sales: list[dict]) -> list[dict]:
    """Month-by-month apuração from the first to the last month with B3 variable-income sales."""
    rv = [s for s in sales if category(s)]
    if not rv:
        return []
    by_month = defaultdict(list)
    for s in rv:
        by_month[s["date"][:7]].append(s)

    carry = dict.fromkeys(RATES, 0.0)
    darf_carry = irrf_carry = 0.0
    year, rows = None, []
    for month in _months(min(by_month), max(by_month)):
        if month[:4] != year:
            year, irrf_carry = month[:4], 0.0
        ss = by_month.get(month, [])
        shares = [s for s in ss if exempt_eligible(s)]
        share_sales = sum(s["proceeds"] for s in shares)
        share_gain = sum(s["gain"] for s in shares)
        exempt = share_sales <= EXEMPTION
        others = sum(s["gain"] for s in ss if category(s) == "comum" and not exempt_eligible(s))
        result = {
            "comum": others + (min(share_gain, 0.0) if exempt else share_gain),
            "daytrade": sum(s["gain"] for s in ss if category(s) == "daytrade"),
            "fii": sum(s["gain"] for s in ss if category(s) == "fii"),
        }
        detail, tax = {}, 0.0
        for bucket, r in result.items():
            if r > 0:
                used = min(r, carry[bucket])
                base = r - used
                carry[bucket] -= used
            else:
                used, base = 0.0, 0.0
                carry[bucket] -= r
            detail[bucket] = {
                "result": r,
                "compensated": used,
                "base": base,
                "tax": base * RATES[bucket],
                "carry": carry[bucket],
            }
            tax += base * RATES[bucket]
        irrf = _irrf(ss)
        due = tax - irrf - irrf_carry
        irrf_carry = max(0.0, -due)
        total = max(0.0, due) + darf_carry
        pay = total if total >= DARF_MIN else 0.0
        darf_carry = total - pay
        rows.append(
            {
                "month": month,
                "share_sales": share_sales,
                "exempt": exempt and share_sales > 0,
                "exempt_gain": max(share_gain, 0.0) if exempt else 0.0,
                "categories": detail,
                "tax": tax,
                "irrf": irrf,
                "darf": pay,
                "darf_pending": darf_carry,
                "due_date": due_date(month) if pay else None,
                "n_sales": len(ss),
                "sales": sorted(ss, key=lambda s: s["date"]),
            }
        )
    return rows


def years(events: list[dict], today: date) -> list[int]:
    if not events:
        return []
    return list(range(today.year, int(events[0]["date"][:4]) - 1, -1))


def annual(year: int, events: list[dict], book, months: list[dict]) -> dict:
    """Declaração anual helper: Bens e Direitos (custo em 31/12), rendimentos isentos,
    tributação exclusiva and the year's renda variável months."""
    prev_snap, cur_snap = snapshots(events, [f"{year - 1}-12-31", f"{year}-12-31"])
    bens = []
    for code in sorted(set(prev_snap) | set(cur_snap)):
        final, prev, cur = book.positions.get(code), prev_snap.get(code), cur_snap.get(code)
        t = final.asset_type if final else (cur or prev).asset_type
        kind = "rf_isento" if t == "rf" and code.startswith(_EXEMPT_FIXED_INCOME) else t
        group, code_ir, label = BENS.get(kind, BENS["outro"])
        name = (final.name if final else "") or ""
        title = (f"{code} – {name}" if name and name != code else code).rstrip(". ")
        custody = f" Custódia: {cur.institution.rstrip('. ')}." if cur and cur.institution else ""
        if cur and t in ("rf", "outro"):
            disc = f"{title}. Valor aplicado (custo).{custody}"
        elif cur:
            unit = {
                "acao": "ações",
                "stock": "ações",
                "fii": "cotas",
                "etf": "cotas",
                "etf_us": "cotas",
                "reit": "cotas",
                "bdr": "BDRs",
                "crypto": "unidades",
            }.get(t, "títulos")
            qty = f"{cur.qty:,.8f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
            avg = f"{cur.cost / cur.qty:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            disc = f"{qty} {unit} de {title}. Custo médio R$ {avg}.{custody}"
        else:
            disc = f"{title}. Posição encerrada em {year}."
        bens.append(
            {
                "code": code,
                "name": name,
                "asset_type": t,
                "group": group,
                "group_code": code_ir,
                "label": label,
                "qty": cur.qty if cur else 0.0,
                "prev": prev.cost if prev else 0.0,
                "cur": cur.cost if cur else 0.0,
                "discriminacao": disc,
            }
        )

    y = str(year)
    isentos, exclusivos, outros = [], [], []
    totals = defaultdict(float)
    for x in book.proventos:
        if x["date"][:4] == y:
            totals[(x["code"], x["type"], x.get("asset_type") or "")] += x["value"]
    for (code, kind, t), v in sorted(totals.items()):
        row = {"asset": code, "type": kind, "value": v}
        if kind == "JCP":
            exclusivos.append({**row, "code": "10", "label": "Juros sobre capital próprio"})
        elif t == "bdr":
            outros.append({**row, "code": "", "label": "Dividendos de BDR são tributáveis (carnê-leão)"})
        elif t == "fii":
            isentos.append({**row, "code": "99", "label": "Rendimentos de FII — confira o código no programa"})
        elif kind in ("Dividendo", "Rendimento"):
            isentos.append({**row, "code": "09", "label": "Lucros e dividendos recebidos"})
        elif kind == "Juros":
            exclusivos.append({**row, "code": "06", "label": "Rendimentos de aplicações financeiras"})
        else:
            outros.append({**row, "code": "", "label": f"{kind} — confira o enquadramento"})

    ym = [m for m in months if m["month"][:4] == y]
    exempt_gains = sum(m["exempt_gain"] for m in ym)
    if exempt_gains > 0:
        isentos.append(
            {
                "asset": "",
                "type": "Vendas ≤ R$ 20 mil/mês",
                "value": exempt_gains,
                "code": "20",
                "label": "Ganhos líquidos em ações (vendas até R$ 20 mil no mês)",
            }
        )
    fixed = [s for s in book.sales if s["date"][:4] == y and s["asset_type"] in ("rf", "tesouro") and s["known"]]
    lci = sum(s["gain"] for s in fixed if s["code"].startswith(_EXEMPT_FIXED_INCOME))
    taxed = sum(s["gain"] for s in fixed if not s["code"].startswith(_EXEMPT_FIXED_INCOME))
    if lci:
        isentos.append(
            {
                "asset": "",
                "type": "LCI/LCA/CRI/CRA",
                "value": lci,
                "code": "12",
                "label": "Rendimento bruto estimado — confira com o informe da instituição",
            }
        )
    if taxed:
        exclusivos.append(
            {
                "asset": "",
                "type": "CDB/Tesouro",
                "value": taxed,
                "code": "06",
                "label": "Rendimento bruto estimado (o IR retido está no informe da instituição)",
            }
        )
    return {
        "year": year,
        "bens": bens,
        "isentos": isentos,
        "exclusivos": exclusivos,
        "outros": outros,
        "months": [{k: v for k, v in m.items() if k != "sales"} for m in ym],
        "sales": [s for m in ym for s in m["sales"]],
        "darf_total": sum(m["darf"] for m in ym),
    }
