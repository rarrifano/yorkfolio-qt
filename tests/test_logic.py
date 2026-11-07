import http.cookiejar
import io
import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape

from yorkfolio_desktop import b3, db, engine, fixed_income, history, market, tax
from yorkfolio_desktop.engine import Position
from yorkfolio_desktop.valuation import Valuer


def make_xlsx(rows) -> bytes:
    """Build a minimal .xlsx (shared strings + numeric cells, like B3 exports)."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    strings, xml_rows = [], []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(v, int | float):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif v is not None:
                if v not in strings:
                    strings.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{strings.index(v)}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
        )
        z.writestr(
            "xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>"
        )
    return buf.getvalue()


MOV_HEADER = [
    "Entrada/Saída",
    "Data",
    "Movimentação",
    "Produto",
    "Instituição",
    "Quantidade",
    "Preço unitário",
    "Valor da Operação",
]
NEG_HEADER = [
    "Data do Negócio",
    "Tipo de Movimentação",
    "Mercado",
    "Prazo/Vencimento",
    "Instituição",
    "Código de Negociação",
    "Quantidade",
    "Preço",
    "Valor",
]
BROKER = "CORRETORA X"


def T(d, side, ticker, qty, price, market="Mercado à Vista"):
    return {
        "date": d,
        "side": side,
        "market": market,
        "institution": BROKER,
        "ticker": b3.base_ticker(ticker),
        "raw_ticker": ticker,
        "qty": qty,
        "price": price,
        "value": round(qty * price, 2),
    }


def M(d, direction, kind, product, qty=None, price=None, value=None):
    return {
        "date": d,
        "direction": direction,
        "kind": kind,
        "product": product,
        "institution": BROKER,
        "qty": qty,
        "price": price,
        "value": value,
    }


def sale(d, code, asset_type, proceeds, cost, daytrade=False):
    return {
        "date": d,
        "code": code,
        "asset_type": asset_type,
        "qty": 1,
        "proceeds": proceeds,
        "cost": cost,
        "gain": proceeds - cost,
        "known": True,
        "daytrade": daytrade,
        "institution": BROKER,
    }


class ParsingTests(unittest.TestCase):
    def test_numbers_and_dates(self):
        self.assertEqual(b3.parse_num("1.234,56"), 1234.56)
        self.assertEqual(b3.parse_num("1,234.56"), 1234.56)
        self.assertEqual(b3.parse_num("16,69"), 16.69)
        self.assertEqual(b3.parse_num("4.000"), 4000)  # pt-BR thousands
        self.assertEqual(b3.parse_num("1.234.567"), 1234567)
        self.assertEqual(b3.parse_num("0.005"), 0.005)
        self.assertEqual(b3.parse_num("250.50"), 250.5)
        self.assertEqual(b3.parse_num(16.69), 16.69)
        self.assertIsNone(b3.parse_num("-"))
        self.assertEqual(b3.parse_date("05/10/2026"), "2026-10-05")
        self.assertEqual(b3.parse_date(45000.0), "2023-03-15")  # Excel serial

    def test_tickers_and_products(self):
        self.assertEqual(b3.base_ticker("ABEV3F"), "ABEV3")
        self.assertEqual(b3.base_ticker("BOVA11F"), "BOVA11")
        p = b3.parse_product("SBSP3 - CIA SANEAMENTO BASICO EST. SAO PAULO - SABESP")
        self.assertEqual((p["code"], p["asset_type"]), ("SBSP3", "acao"))
        self.assertEqual(b3.parse_product("CDB - CDB1234ABCD - BANCO EXEMPLO S.A.")["code"], "CDB1234ABCD")
        self.assertEqual(b3.parse_product("LCI - 24A00000001 - BCO EXEMPLO - S/A")["code"], "LCI 24A00000001")
        self.assertEqual(b3.parse_product("Tesouro Selic 2031")["asset_type"], "tesouro")
        self.assertEqual(b3.listed_type("MXRF11", "MAXI RENDA FDO INV IMOB - FII"), "fii")
        self.assertEqual(b3.listed_type("BOVA11", "ISHARES BOVA FUNDO DE INDICE"), "etf")
        self.assertEqual(b3.listed_type("TAEE11", "TRANSMISSORA ALIANCA DE ENERGIA ELETRICA S.A."), "acao")
        self.assertEqual(b3.listed_type("AAPL34"), "bdr")

    def test_classify_movement(self):
        c = lambda kind, product="ITUB3 - ITAU", d="C": b3.classify_movement(M("2024-01-01", d, kind, product))
        self.assertEqual(c("Juros Sobre Capital Próprio")["label"], "JCP")
        self.assertEqual(c("Dividendo - Transferido")["action"], "provento")
        self.assertEqual(c("Transferência - Liquidação")["action"], "settlement")
        self.assertEqual(c("Atualização")["action"], "ignore")
        self.assertEqual(c("RESGATE ANTECIPADO/", "CDB - CDB1 - BANCO", "D")["action"], "sell")
        self.assertEqual(c("Compra", "Tesouro IPCA+ 2050")["action"], "buy")
        self.assertEqual(c("Cisão")["action"], "unhandled")

    def test_parse_file_detects_kind_and_dedupes(self):
        row = [
            "Credito",
            "15/03/2024",
            "Juros Sobre Capital Próprio",
            "ABCD3 - ABCD SA",
            BROKER,
            100,
            0.15,
            12.75,
        ]
        kind, recs = b3.parse_file(make_xlsx([MOV_HEADER, row, row, ["Debito", "-", "x", "y"]]))
        self.assertEqual((kind, len(recs)), ("movimentacao", 2))
        self.assertNotEqual(recs[0]["uid"], recs[1]["uid"])
        _, again = b3.parse_file(make_xlsx([MOV_HEADER, row, row]))
        self.assertEqual([r["uid"] for r in recs], [r["uid"] for r in again])
        kind, recs = b3.parse_file(
            make_xlsx(
                [NEG_HEADER, ["10/05/2024", "Compra", "Mercado Fracionário", "-", BROKER, "ABCD3F", 7, 12.34, 86.38]]
            )
        )
        self.assertEqual((kind, recs[0]["ticker"]), ("negociacao", "ABCD3"))
        with self.assertRaises(ValueError):
            b3.parse_file(b"not a zip")


class EngineTests(unittest.TestCase):
    trades = [
        T("2024-01-10", "C", "ABCD3", 100, 10.0),
        T("2024-01-10", "C", "ABCD3F", 10, 10.0),
        T("2024-02-09", "V", "ABCD3", 50, 12.0),
    ]
    movements = [
        M("2024-01-12", "C", "Transferência - Liquidação", "ABCD3 - ABCD SA", 110, 10.0, 1100.0),
        M("2024-02-14", "D", "Transferência - Liquidação", "ABCD3 - ABCD SA", 50, 12.0, 600.0),
        M("2023-05-03", "C", "Transferência - Liquidação", "WXYZ3 - WXYZ SA", 10, 20.0, 200.0),
        M("2024-03-01", "C", "Dividendo", "ABCD3 - ABCD SA", 60, 0.5, 30.0),
        M("2024-03-05", "C", "Bonificação em Ativos", "ABCD3 - ABCD SA", 6),
        M("2024-04-01", "C", "Restituição de Capital", "ABCD3 - ABCD SA", 66, 0.1, 6.6),
        M("2024-01-05", "C", "APLICAÇÃO", "CDB - CDB123", 1000, 1.0, 1000.0),
        M("2024-06-05", "D", "RESGATE ANTECIPADO/", "CDB - CDB123 - BANCO X", 400, 1.05, 420.0),
    ]

    def test_ledger_and_positions(self):
        events = engine.build_ledger(self.trades, self.movements)
        self.assertEqual(sum(e["action"] == "skip" for e in events), 2)
        filtered = engine.build_ledger(self.trades, self.movements, exclude={"CDB"})
        self.assertFalse(any(e["code"] == "CDB123" for e in filtered))
        self.assertEqual(len(events) - len(filtered), 2)
        book = engine.run(events)
        abcd = book.positions["ABCD3"]
        self.assertAlmostEqual(abcd.qty, 66)
        self.assertAlmostEqual(abcd.realized, 100.0)
        self.assertAlmostEqual(abcd.cost, 600 - 6.6)
        self.assertEqual(abcd.name, "ABCD SA")
        cdb = book.positions["CDB123"]
        self.assertAlmostEqual((cdb.qty, cdb.cost, cdb.realized), (600, 600.0, 20.0))
        self.assertEqual(cdb.anchor, ("2024-06-05", 1.05))
        self.assertEqual([s["code"] for s in book.sales], ["ABCD3", "CDB123"])
        self.assertAlmostEqual(sum(a for _, a in book.flows), 200 + 1100 + 1000 - 600 - 30 - 6.6 - 420)

    def test_day_trade(self):
        trades = [T("2024-05-02", "C", "ABCD3", 100, 10.0), T("2024-05-02", "V", "ABCD3", 60, 11.0)]
        settle = [M("2024-05-06", "C", "Transferência - Liquidação", "ABCD3 - ABCD SA", 40, 10.0, 400.0)]
        events = engine.build_ledger(trades, settle)
        self.assertEqual(sorted(e["action"] for e in events), ["buy", "daytrade", "dt_part", "dt_part", "skip"])
        book = engine.run(events)
        self.assertAlmostEqual(book.positions["ABCD3"].qty, 40)
        self.assertAlmostEqual(book.positions["ABCD3"].cost, 400)
        [dt] = book.sales
        self.assertTrue(dt["daytrade"])
        self.assertAlmostEqual(dt["gain"], 60.0)

    def test_manual_usd(self):
        ops = [
            {
                "id": 1,
                "date": "2024-03-01",
                "op": "buy",
                "code": "AAPL",
                "asset_type": "stock",
                "qty": 10,
                "price": 100.0,
                "total": None,
                "fees": 1.0,
                "currency": "USD",
                "fx": 5.0,
            },
            {
                "id": 2,
                "date": "2024-04-01",
                "op": "provento",
                "code": "AAPL",
                "asset_type": "stock",
                "total": 2.0,
                "currency": "USD",
                "fx": 5.5,
                "kind": "Dividendo",
            },
            {
                "id": 3,
                "date": "2024-04-02",
                "op": "adjust",
                "code": "AAPL",
                "asset_type": "stock",
                "total": 10.0,
                "currency": "BRL",
                "fx": 1.0,
            },
        ]
        book = engine.run(engine.build_ledger([], [], ops))
        p = book.positions["AAPL"]
        self.assertAlmostEqual(p.cost, 1001 * 5.0 + 10)
        self.assertIsNone(p.cost_usd)  # a BRL adjustment makes the USD cost unknown
        self.assertAlmostEqual(book.proventos[0]["value"], 11.0)

    def test_portfolio_and_plan(self):
        book = engine.run(engine.build_ledger(self.trades, self.movements))
        settings = {"ABCD3": {"quote": 11.0, "quote_at": "2024-07-01T10:00:00"}, "CDB123": {"manual_value": 650.0}}
        valuer = Valuer(settings, {}, today=date(2024, 7, 1))
        pf = engine.build_portfolio(book, settings, {"Ações": 70, "Renda Fixa": 30}, valuer)
        self.assertEqual(pf["summary"]["missing_quotes"], ["WXYZ3"])
        self.assertAlmostEqual(pf["summary"]["value"], 66 * 11.0 + 200.0 + 650.0)
        plan = engine.plan_aporte(pf["classes"], 1000)
        spent = sum(c["spent"] for c in plan["classes"])
        self.assertAlmostEqual(spent + plan["leftover"], 1000)
        for c in plan["classes"]:
            for a in c["assets"]:
                if a["qty"] is not None:
                    self.assertAlmostEqual(a["amount"], a["qty"] * a["price"])

    def test_waterfill(self):
        self.assertEqual(engine.waterfill([0, 0], [1, 1], 100), [50, 50])
        self.assertEqual(engine.waterfill([100, 0], [1, 1], 300), [100, 200])
        self.assertEqual(engine.waterfill([0, 0, 0], [1, 0, 3], 40), [10, 0, 30])
        alloc = engine.waterfill([700, 100, 50, 0], [4, 3, 2, 1], 1000)
        self.assertAlmostEqual(sum(alloc), 1000)
        for cur, w, a in zip([700, 100, 50, 0], [0.4, 0.3, 0.2, 0.1], alloc, strict=False):
            self.assertLessEqual(cur + a, max(cur, w * 1850) + 1e-9)


class TaxTests(unittest.TestCase):
    def test_monthly(self):
        sales = [
            sale("2026-01-10", "PETR4", "acao", 15_000, 14_000),  # ≤ 20k: exempt gain
            sale("2026-02-10", "VALE3", "acao", 30_000, 32_000),  # loss carried
            sale("2026-03-10", "ITUB4", "acao", 25_000, 22_000),  # gain 3000 - 2000 carried = 1000 base
            sale("2026-04-10", "MXRF11", "fii", 1_000, 960),  # FII 20% = 8 → below DARF minimum
            sale("2026-05-10", "PETR4", "acao", 1_050, 1_000, True),  # day trade 20% = 10, IRRF 0.50
            sale("2026-06-10", "TAEE11", "acao", 5_000, 4_800),  # unit: never exempt
        ]
        rows = {r["month"]: r for r in tax.monthly(sales)}
        jan, feb, mar, apr, may, jun = (rows[f"2026-0{m}"] for m in range(1, 7))
        self.assertTrue(jan["exempt"])
        self.assertAlmostEqual(jan["exempt_gain"], 1000)
        self.assertEqual(jan["tax"], 0)
        self.assertAlmostEqual(feb["categories"]["comum"]["carry"], 2000)
        self.assertAlmostEqual(mar["categories"]["comum"]["base"], 1000)
        self.assertAlmostEqual(mar["irrf"], 1.25)
        self.assertAlmostEqual(
            mar["darf"], 150 - 1.25 - 1.50
        )  # February's IRRF (0.005% of 30k) carried within the year
        self.assertEqual(mar["due_date"], "2026-04-30")
        self.assertEqual(apr["darf"], 0)
        self.assertAlmostEqual(apr["darf_pending"], 8)
        self.assertAlmostEqual(may["darf"], 10 - 0.5 + 8)
        self.assertFalse(jun["exempt"])
        self.assertAlmostEqual(jun["darf"], 30)

    def test_annual(self):
        trades = [T("2025-03-10", "C", "ABCD3", 100, 10.0), T("2026-02-10", "V", "ABCD3", 40, 12.0)]
        movements = [
            M("2026-04-01", "C", "Juros Sobre Capital Próprio", "ABCD3 - ABCD SA", 60, 0.5, 25.5),
            M("2026-05-01", "C", "Dividendo", "ABCD3 - ABCD SA", 60, 0.5, 30.0),
        ]
        events = engine.build_ledger(trades, movements)
        book = engine.run(events)
        rep = tax.annual(2026, events, book, tax.monthly(book.sales))
        [bem] = rep["bens"]
        self.assertEqual((bem["group"], bem["group_code"]), ("03", "01"))
        self.assertAlmostEqual((bem["prev"], bem["cur"]), (1000, 600))
        self.assertIn("60 ações de ABCD3", bem["discriminacao"])
        codes = {r["code"]: r["value"] for r in rep["isentos"] + rep["exclusivos"]}
        self.assertAlmostEqual(codes["09"], 30.0)
        self.assertAlmostEqual(codes["10"], 25.5)
        self.assertAlmostEqual(codes["20"], 80.0)  # 40 × (12 - 10), sales ≤ 20k


class FixedIncomeTests(unittest.TestCase):
    cdi = [("2024-01-02", 0.05), ("2024-01-03", 0.05)]

    def test_daily_compound(self):
        f = fixed_income.daily_compound
        self.assertAlmostEqual(f(self.cdi, 100, "2024-01-02", "2024-01-04"), 1.0005**2)
        self.assertAlmostEqual(f(self.cdi, 110, "2024-01-02", "2024-01-04"), (1 + 0.0005 * 1.1) ** 2)
        self.assertAlmostEqual(f(self.cdi, 100, "2024-01-02", "2024-01-08"), 1.0005**4)  # Thu/Fri extrapolated

    def test_pre_and_ipca(self):
        series = {"BCB:12": self.cdi, "BCB:433": [("2024-01-01", 1.0)]}
        self.assertAlmostEqual(fixed_income.accrual("pre", 10, "2024-01-02", "2024-01-04", series), 1.1 ** (2 / 252))
        self.assertAlmostEqual(fixed_income.ipca_factor(series["BCB:433"], "2024-01-01", "2024-02-01"), 1.01)
        self.assertIsNone(fixed_income.accrual("selic", 100, "2024-01-02", "2024-01-04", series))


class ValuationTests(unittest.TestCase):
    def test_valuer(self):
        series = {
            "TD:Tesouro Selic 2029": [("2024-01-30", 14000.0), ("2024-01-31", 14010.0)],
            "Y:ABCD3.SA": [("2024-01", 10.0)],
            "BCB:12": [("2024-01-02", 0.05), ("2024-01-03", 0.05)],
        }
        v = Valuer({}, series, fx_now=5.0, today=date(2024, 2, 1))
        td = Position("Tesouro Selic 2029", asset_type="tesouro", qty=2, cost=27000)
        self.assertAlmostEqual(v.current(td, {})["value"], 28020)
        aapl = Position("AAPL", asset_type="stock", qty=3, cost=1000)
        cur = v.current(aapl, {"quote": 100.0})
        self.assertAlmostEqual((cur["value"], cur["price_brl"]), (1500, 500))
        cdb = Position("CDB1", asset_type="rf", qty=1000, cost=1000, anchor=("2024-01-02", 1.0))
        # 2 published days + 20 extrapolated weekdays (4 Jan → 31 Jan)
        self.assertAlmostEqual(v.current(cdb, {"indexer": "cdi", "rate": 100})["value"], 1000 * 1.0005**22, places=6)
        stock = Position("ABCD3", asset_type="acao", qty=5, cost=40)
        self.assertEqual(v.at(stock, "2024-01-31", "2024-01"), 50)
        self.assertEqual(v.at(stock, "2024-02-29", "2024-02"), 50)  # previous month's close
        self.assertEqual(v.at(stock, "2024-04-30", "2024-04"), 40)  # too old: cost


class HistoryTests(unittest.TestCase):
    def test_history_returns(self):
        class Stub:
            series = {"BCB:12": [("2024-02-01", 0.05)]}
            closes = {"2024-01": 10.0, "2024-02": 11.0}

            def current(self, p, s):
                return {"value": p.qty * 12.0}

            def at(self, p, iso, month):
                return p.qty * self.closes[month]

        events = engine.build_ledger([T("2024-01-15", "C", "ABCD3", 100, 10.0)], [])
        pts = history.build_history(events, engine.run(events), {}, Stub(), date(2024, 3, 10))["points"]
        self.assertEqual([p["month"] for p in pts], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual([p["value"] for p in pts], [1000, 1100, 1200])
        self.assertAlmostEqual(pts[0]["ret"], 0.0)
        self.assertAlmostEqual(pts[1]["ret"], 0.10)
        self.assertAlmostEqual(pts[2]["ret"], 1200 / 1100 - 1)
        self.assertAlmostEqual(pts[1]["cdi"], 0.0005)
        self.assertEqual(pts[0]["classes"], {"Ações": 1000})


class MarketTests(unittest.TestCase):
    def test_unadjust_splits(self):
        bars = [("2024-03", "2024-03-31", 28.31), ("2024-04", "2024-04-30", 27.42)]
        self.assertEqual(market.unadjust(bars, [("2024-04-16", 2.0)]), [("2024-03", 56.62), ("2024-04", 27.42)])

    def test_parse_tesouro(self):
        text = (
            "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
            "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
            "Tesouro Selic;01/03/2029;31/01/2024;0,06;0,07;14.020,10;14.010,00;14.010,00\n"
            "Tesouro Selic;01/03/2029;30/01/2024;0,06;0,07;14.010,10;14.000,00;14.000,00\n"
            "Tesouro IPCA+;15/05/2029;30/01/2024;5,1;5,2;3.000,00;2.990,00;2.990,00\n"
        )
        out = market.parse_tesouro(text, {"Tesouro Selic 2029"})
        self.assertEqual(out, {"Tesouro Selic 2029": [("2024-01-30", 14000.0), ("2024-01-31", 14010.0)]})


class DbTests(unittest.TestCase):
    def test_schema_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            con = sqlite3.connect(path)
            con.execute(
                "CREATE TABLE assets (code TEXT PRIMARY KEY, name TEXT, class TEXT, nota REAL, manual_price REAL,"
                " manual_value REAL, manual_value_at TEXT, quote REAL, quote_at TEXT)"
            )
            con.execute("INSERT INTO assets (code, nota) VALUES ('ABCD3', 2)")
            con.commit()
            con.close()
            con = db.connect(path)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(assets)")}
            self.assertTrue({"indexer", "rate", "asset_type"} <= cols)
            self.assertEqual(con.execute("SELECT nota FROM assets").fetchone()[0], 2)
            con.close()


