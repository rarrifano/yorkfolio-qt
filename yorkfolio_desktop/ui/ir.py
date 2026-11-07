"""IR tab: monthly apuração / DARF and the annual declaration helper."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from .. import service
from . import fmt
from .models import Column, make_table, row_at
from .widgets import Card, cards_row, muted


def bucket(name):
    return lambda m: m["categories"][name]["result"]


class IRTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.year_loaded = ctx, None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Ano-base:"))
        self.year = QComboBox()
        self.year.currentTextChanged.connect(self._load)
        top.addWidget(self.year)
        top.addStretch()
        lay.addLayout(top)
        self.cards = [Card("DARF 6015 no ano"), Card("DARF pendente (< R$ 10)")]
        lay.addWidget(cards_row(self.cards))
        lay.addWidget(muted("Ferramenta de apoio, não é consultoria tributária: confira os valores antes de declarar ou pagar."))

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        months = [
            Column("Mês", "month", fmt.month_label), Column("Vendas de ações", "share_sales", fmt.brl, True),
            Column("Isenção", lambda m: "isento (≤ R$ 20 mil)" if m["exempt"] else ""),
            Column("Swing", bucket("comum"), fmt.brl, True, True), Column("Day trade", bucket("daytrade"), fmt.brl, True, True),
            Column("FII", bucket("fii"), fmt.brl, True, True), Column("Imposto", "tax", fmt.brl, True),
            Column("IRRF", "irrf", fmt.brl, True), Column("DARF", "darf", lambda v: fmt.brl(v) if v else "–", True),
            Column("Vencimento", "due_date", fmt.br_date),
            Column("Acumulado p/ próx. mês", "darf_pending", lambda v: fmt.brl(v) if v else "", True),
        ]  # fmt: skip
        self.months_view, self.months, _ = make_table(months)
        self.tabs.addTab(self.months_view, "Renda variável (mensal)")

        bens = [
            Column("Ativo", "code"), Column("Grupo", "group"), Column("Código", "group_code"),
            Column("Em 31/12 anterior", "prev", fmt.brl, True), Column("Em 31/12", "cur", fmt.brl, True),
            Column("Discriminação", "discriminacao", stretch=True),
        ]  # fmt: skip
        box = QWidget()
        bl = QVBoxLayout(box)
        self.bens_view, self.bens, self.bens_proxy = make_table(bens)
        copy = QPushButton("Copiar discriminação da linha selecionada")
        copy.clicked.connect(self._copy)
        bl.addWidget(self.bens_view)
        bl.addWidget(copy)
        self.tabs.addTab(box, "Bens e Direitos")

        inc = [Column("Seção", "section"), Column("Ativo", "asset"), Column("Tipo", "type"), Column("Código", "code"),
               Column("Valor", "value", fmt.brl, True), Column("Observação", "label", stretch=True)]  # fmt: skip
        self.income_view, self.income, _ = make_table(inc)
        self.tabs.addTab(self.income_view, "Rendimentos")

        sales = [
            Column("Data", "date", fmt.br_date), Column("Ativo", "code"), Column("Qtd", "qty", fmt.qty, True),
            Column("Venda", "proceeds", fmt.brl, True), Column("Custo", "cost", fmt.brl, True),
            Column("Resultado", "gain", fmt.brl, True, True), Column("Day trade", lambda s: "sim" if s["daytrade"] else ""),
        ]  # fmt: skip
        self.sales_view, self.sales, _ = make_table(sales)
        self.tabs.addTab(self.sales_view, "Vendas do ano")

    def set_state(self, s: dict):
        years = [str(y) for y in s["ir_years"]]
        if [self.year.itemText(i) for i in range(self.year.count())] != years:
            self.year.blockSignals(True)
            self.year.clear()
            self.year.addItems(years)
            self.year.blockSignals(False)
            self.year_loaded = None
        self._load()

    def _load(self, *_):
        year = self.year.currentText()
        if not year:
            return
        self.ctx.run(lambda con: service.ir(con, int(year)), self._show)

    def _show(self, r: dict):
        self.cards[0].set(fmt.brl(r["darf_total"]), f"{r['year']}")
        self.cards[1].set(fmt.brl(r["pending_darf"]))
        self.months.set_rows(list(reversed(r["months"])))
        self.bens.set_rows(r["bens"])
        rows = [{**x, "section": sec} for sec, items in (("Isento", r["isentos"]), ("Tributação exclusiva", r["exclusivos"]), ("Outros", r["outros"])) for x in items]
        self.income.set_rows(rows)
        self.sales.set_rows(r["sales"])

    def _copy(self):
        idx = self.bens_view.currentIndex()
        row = row_at(self.bens_view, idx)
        if row:
            QGuiApplication.clipboard().setText(row["discriminacao"])
            self.ctx.message("Discriminação copiada.")

