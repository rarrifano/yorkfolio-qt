"""Headless UI smoke tests (QT_QPA_PLATFORM=offscreen) on a synthetic portfolio."""

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.test_logic import MOV_HEADER, NEG_HEADER, make_xlsx  # noqa: E402
from yorkfolio_desktop import db, demo, native  # noqa: E402
from yorkfolio_desktop.ui import fmt, theme  # noqa: E402
from yorkfolio_desktop.ui.main_window import MainWindow  # noqa: E402

app = QApplication.instance() or QApplication([])


def wait(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


class FormatTests(unittest.TestCase):
    def test_pt_br(self):
        self.assertEqual(fmt.brl(1234.5), "R$ 1.234,50")
        self.assertEqual(fmt.brl(-0.001), "R$ 0,00")
        self.assertEqual(fmt.brl(-3), "-R$ 3,00")
        self.assertEqual(fmt.qty(10), "10")
        self.assertEqual(fmt.qty(0.5), "0,5")
        self.assertEqual(fmt.signed_pct(0.1234), "+12,34%")
        self.assertEqual(fmt.month_label("2024-03"), "mar/24")
        self.assertEqual(fmt.parse_number("1.234,50"), 1234.5)
        self.assertIsNone(fmt.parse_number(" "))


class NativeTests(unittest.TestCase):
    def test_version_and_errors(self):
        self.assertTrue(native.version())
        with self.assertRaises(ValueError):
            native.plan_aporte([], 0)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "p.db"
        theme.apply(app, False)

    def tearDown(self):
        self.tmp.cleanup()

    def open(self) -> MainWindow:
        win = MainWindow(self.path)
        self.addCleanup(win.close)
        self.assertTrue(wait(lambda: win.state is not None), "state never loaded")
        return win

    def test_empty_portfolio_opens_on_data_tab(self):
        win = self.open()
        self.assertIs(win.tabs.currentWidget(), win.dados)

    def test_demo_portfolio_populates_every_tab(self):
        demo.build(str(self.path))
        win = self.open()
        self.assertGreater(win.state["summary"]["value"], 0)
        self.assertEqual(win.carteira.tree.topLevelItemCount(), len(win.state["classes"]))
        self.assertGreater(win.extrato.model.rowCount(), 0)
        self.assertGreater(win.proventos.assets.rowCount(), 0)
        self.assertTrue(wait(lambda: win.ir.months.rowCount() > 0), "IR tab never loaded")
        for i in range(win.tabs.count()):
            win.tabs.setCurrentIndex(i)
            win.grab()  # exercises paint code

    def test_aporte_plan(self):
        demo.build(str(self.path))
        win = self.open()
        win.balanceamento.amount.setText("1.000,00")
        win.balanceamento._plan()
        self.assertGreater(win.balanceamento.plan.topLevelItemCount(), 0)

    def test_save_targets_roundtrip(self):
        demo.build(str(self.path))
        win = self.open()
        item = win.balanceamento.tree.topLevelItem(0)
        name = item.text(0)
        item.setText(2, "70,5")
        win.balanceamento._save()
        self.assertTrue(wait(lambda: win.state["targets"].get(name) == 70.5))

    def test_import_xlsx(self):
        mov = make_xlsx([MOV_HEADER, ["Credito", "10/03/2024", "Dividendo", "PETR4 - PETROBRAS", "XP", 100, 0.5, 50.0]])
        neg = make_xlsx([NEG_HEADER, ["05/03/2024", "Compra", "Mercado à Vista", "", "XP", "PETR4", 100, 30.0, 3000.0]])
        files = []
        for name, data in (("movimentacao.xlsx", mov), ("negociacao.xlsx", neg), ("broken.xlsx", b"nope")):
            f = Path(self.tmp.name) / name
            f.write_bytes(data)
            files.append(f)
        win = self.open()
        win.refresh_market = lambda force=False: None  # no network in tests
        win.import_files(files)
        self.assertTrue(wait(lambda: win.state["counts"]["trades"] == 1 and win.import_results), "import did not finish")
        self.assertEqual(sum(1 for r in win.import_results if "error" in r), 1)
        self.assertEqual(win.state["classes"][0]["assets"][0]["code"], "PETR4")
        con = db.connect(self.path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM movements").fetchone()[0], 1)
        con.close()

    def test_manual_entry_and_asset_edit(self):
        win = self.open()
        win.dados.fields["code"].setText("BTC")
        win.dados.asset_type.setCurrentIndex(win.dados.asset_type.findData("crypto"))
        win.dados.fields.update()
        win.dados.fields["qty"].setText("0,5")
        win.dados.fields["price"].setText("100000")
        win.dados.currency.setCurrentText("BRL")
        win.dados._add_manual()
        self.assertTrue(wait(lambda: win.state["counts"]["manual"] == 1), "manual op not stored")
        win.run(lambda con: db.update_asset(con, "BTC", {"manual_price": 120000.0}), reload=True)
        self.assertTrue(wait(lambda: win.state["classes"] and win.state["classes"][0]["assets"][0]["price"] == 120000.0))


if __name__ == "__main__":
    unittest.main()
