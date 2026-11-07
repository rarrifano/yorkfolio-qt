"""The C++ core must agree with the original pure-Python engine (kept in tests/reference)."""

import random
import unittest
from datetime import date, timedelta

from tests.reference import engine as ref_engine
from tests.reference import tax as ref_tax
from yorkfolio_qt import engine, tax

CODES = [("PETR4", "acao"), ("VALE3", "acao"), ("HGLG11", "fii"), ("BOVA11", "etf"), ("AAPL", "stock"), ("BTC", "crypto")]


def random_events(rng: random.Random, n: int) -> list[dict]:
    day = date(2021, 1, 4)
    events = []
    for _ in range(n):
        day += timedelta(days=rng.choice([0, 0, 1, 3, 9, 20]))
        code, atype = rng.choice(CODES)
        action = rng.choices(
            ["buy", "sell", "bonus", "split", "reverse_split", "capital_return", "provento", "adjust", "daytrade",
             "fraction_out", "unhandled", "skip"],
            [30, 24, 2, 2, 2, 2, 8, 3, 6, 2, 1, 1],
        )[0]
        qty = float(rng.randint(1, 200))
        price = round(rng.uniform(5, 80), 2)
        ev = {
            "date": day.isoformat(),
            "code": code,
            "name": rng.choice(["", f"{code} S.A."]),
            "asset_type": atype,
            "action": action,
            "label": action.title(),
            "kind": "Foo",
            "direction": rng.choice(["C", "D"]),
            "qty": qty,
            "price": rng.choice([price, None, 0]),
            "value": rng.choice([round(qty * price, 2), round(qty * price, 2), None, 0]),
            "institution": rng.choice(["XP", "Rico", ""]),
            "source": rng.choice(["Negociação", "Movimentação"]),
            "note": "",
        }
        if action == "daytrade":
            ev["buy_value"], ev["sell_value"] = round(qty * price, 2), round(qty * price * rng.uniform(0.9, 1.1), 2)
        if atype in ("stock", "crypto"):
            ev["currency"] = rng.choice(["USD", "BRL"])
            ev["value_ccy"] = round((ev["value"] or 0) / 5, 2)
        events.append(ev)
    return events


def position_dict(p) -> dict:
    d = dict(vars(p))
    d["anchor"] = tuple(d["anchor"]) if d["anchor"] else None
    return d


class ParityTests(unittest.TestCase):
    def assertClose(self, a, b, path=""):
        if isinstance(a, dict):
            self.assertEqual(set(a), set(b), path)
            for k in a:
                self.assertClose(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list | tuple):
            self.assertEqual(len(a), len(b), path)
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                self.assertClose(x, y, f"{path}[{i}]")
        elif isinstance(a, float) or isinstance(b, float):
            self.assertAlmostEqual(a, b, places=6, msg=path)
        else:
            self.assertEqual(a, b, path)

    def test_book(self):
        for seed in range(40):
            events = random_events(random.Random(seed), 150)
            want, got = ref_engine.run(events), engine.run(events)
            self.assertClose({c: position_dict(p) for c, p in want.positions.items()},
                             {c: position_dict(p) for c, p in got.positions.items()}, f"seed {seed}")
            self.assertClose(want.sales, got.sales, f"sales {seed}")
            self.assertClose(want.proventos, got.proventos, f"proventos {seed}")
            self.assertClose(want.flows, got.flows, f"flows {seed}")
            self.assertClose(want.warnings, got.warnings, f"warnings {seed}")

    def test_snapshots(self):
        events = random_events(random.Random(7), 200)
        dates = ["2021-06-30", "2022-12-31", "2099-01-01"]
        want, got = ref_engine.snapshots(events, dates), engine.snapshots(events, dates)
        for w, g in zip(want, got, strict=True):
            self.assertClose({c: position_dict(p) for c, p in w.items()}, {c: position_dict(p) for c, p in g.items()})

    def test_tax_monthly(self):
        for seed in range(40):
            sales = ref_engine.run(random_events(random.Random(seed), 300)).sales
            self.assertClose(ref_tax.monthly(sales), tax.monthly(sales), f"seed {seed}")

    def test_plan_aporte(self):
        rng = random.Random(3)
        for _ in range(60):
            classes = []
            for c in range(rng.randint(1, 5)):
                assets = [
                    {
                        "code": f"A{c}{i}",
                        "name": "n",
                        "value": rng.choice([0.0, rng.uniform(0, 5000)]),
                        "nota": rng.choice([0, 1, 2, 5]),
                        "quoted": rng.random() < 0.8,
                        "price_brl": rng.choice([None, rng.uniform(5, 300)]),
                        "asset_type": rng.choice(["acao", "fii", "crypto"]),
                    }
                    for i in range(rng.randint(0, 5))
                ]
                classes.append({"name": f"C{c}", "value": sum(a["value"] for a in assets),
                                "target": rng.choice([0, 10, 25, 40]) / 100, "assets": assets})
            amount = rng.uniform(1, 20000)
            try:
                want = ref_engine.plan_aporte(classes, amount)
            except ValueError as exc:
                with self.assertRaises(ValueError) as ctx:
                    engine.plan_aporte(classes, amount)
                self.assertEqual(str(ctx.exception), str(exc))
                continue
            self.assertClose(want, engine.plan_aporte(classes, amount))


if __name__ == "__main__":
    unittest.main()
