# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Synthetic demo portfolio (random, not real data) for screenshots, development and UI tests.

    python -m yorkfolio_qt.demo /tmp/demo.db && python -m yorkfolio_qt --db /tmp/demo.db
"""

from __future__ import annotations

import hashlib
import random
import sys
from datetime import date

from . import b3, db
from .assets import IBOV_SYMBOL, yahoo_symbol

ASSETS = [  # code, name, start price, drift/month
    ("PETR4", "PETROLEO BRASILEIRO S.A. PETROBRAS", 28.0, 0.006),
    ("ITUB4", "ITAU UNIBANCO HOLDING S.A.", 24.0, 0.008),
    ("WEGE3", "WEG S.A.", 36.0, 0.010),
    ("HGLG11", "FDO INV IMOB CSHG LOGISTICA", 160.0, 0.003),
    ("MXRF11", "FDO INV IMOB MAXI RENDA", 10.0, 0.001),
    ("BOVA11", "ISHARES IBOVESPA FUNDO DE INDICE", 105.0, 0.007),
]


def _months(first: date, last: date):
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def build(path: str, seed: int = 1, today: date | None = None) -> None:
    rng, today = random.Random(seed), today or date.today()
    con = db.connect(path)
    db.reset(con, everything=True)
    start = date(today.year - 4, 1, 1)
    trades, movements, prices = [], [], {c: p for c, _, p, _ in ASSETS}
    monthly: dict[str, list[tuple[str, float]]] = {yahoo_symbol(c, b3.listed_type(c, n)): [] for c, n, _, _ in ASSETS}
    ibov, level = [], 100_000.0
    held = dict.fromkeys(prices, 0)
    for y, m in _months(start, today):
        ym = f"{y:04d}-{m:02d}"
        level *= 1 + rng.gauss(0.007, 0.05)
        ibov.append((ym, level))
        for code, name, _, drift in ASSETS:
            prices[code] *= 1 + rng.gauss(drift, 0.06)
            monthly[yahoo_symbol(code, b3.listed_type(code, name))].append((ym, round(prices[code], 2)))
            if rng.random() < 0.7:
                qty = rng.choice([10, 20, 50, 100])
                d = date(y, m, rng.randint(2, 27)).isoformat()
                if d > today.isoformat():
                    continue
                sell = held[code] > qty * 2 and rng.random() < 0.15
                side = "V" if sell else "C"
                held[code] += -qty if sell else qty
                trades.append({
                    "date": d, "side": side, "market": "Mercado à Vista", "maturity": None, "institution": "CORRETORA DEMO",
                    "ticker": code, "raw_ticker": code, "qty": float(qty), "price": round(prices[code], 2),
                    "value": round(qty * prices[code], 2), "source": "demo",
                })  # fmt: skip
            if held[code] and rng.random() < 0.5:
                kind = "Rendimento" if code.endswith("11") else rng.choice(["Dividendo", "Juros Sobre Capital Próprio"])
                value = round(held[code] * prices[code] * rng.uniform(0.002, 0.008), 2)
                movements.append({
                    "date": date(y, m, min(28, 15)).isoformat(), "direction": "C", "kind": kind, "product": f"{code} - {name}",
                    "institution": "CORRETORA DEMO", "qty": float(held[code]), "price": None, "value": value, "source": "demo",
                })  # fmt: skip
    for kind, rows in (("negociacao", trades), ("movimentacao", movements)):
        for r in rows:
            r["uid"] = hashlib.sha1(f"demo|{kind}|{sorted(r.items())}".encode()).hexdigest()
        db.insert_records(con, kind, rows)
    for symbol, rows in monthly.items():
        db.save_series(con, f"Y:{symbol}", rows, replace=True)
    db.save_series(con, f"Y:{IBOV_SYMBOL}", ibov, replace=True)
    cdi = []
    for y, m in _months(start, today):
        for day in range(1, 29, 1):
            cdi.append((date(y, m, day).isoformat(), 0.04))  # ~0.04% per day
    db.save_series(con, "BCB:12", cdi, replace=True)
    db.save_quotes(con, {c: round(p, 2) for c, p in prices.items()})
    db.set_targets(con, {"Ações": 50, "FIIs": 30, "ETFs": 20})
    db.set_meta(con, "market_at", db.now())
    con.close()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "demo.db"
    build(out)
    print(f"demo portfolio written to {out}")
