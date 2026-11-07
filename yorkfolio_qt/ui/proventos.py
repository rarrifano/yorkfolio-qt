# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Proventos tab."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from . import fmt
from .charts import Chart
from .models import Column, make_table
from .widgets import Card, cards_row, heading


class ProventosTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        lay = QVBoxLayout(self)
        self.cards = [Card(t) for t in ("Últimos 12 meses", "Média mensal (12m)", "No ano", "Total recebido")]
        lay.addWidget(cards_row(self.cards))
        lay.addWidget(heading("Proventos por mês (24 meses)"))
        self.chart = Chart(200)
        lay.addWidget(self.chart)

        row = QHBoxLayout()
        self.by_year_view, self.by_year, _ = make_table([Column("Ano", "year"), Column("Total", "total", fmt.brl, True)])
        self.by_type_view, self.by_type, _ = make_table([Column("Tipo", "type"), Column("Total", "total", fmt.brl, True)])
        for title, view in (("Por ano", self.by_year_view), ("Por tipo", self.by_type_view)):
            box = QVBoxLayout()
            box.addWidget(heading(title))
            box.addWidget(view)
            row.addLayout(box)
        lay.addLayout(row, 1)
        lay.addWidget(heading("Por ativo"))
        cols = [
            Column("Ativo", "code"), Column("Pagamentos", "count", right=True),
            Column("Últimos 12m", "last12", fmt.brl, True), Column("Total", "total", fmt.brl, True),
            Column("YoC 12m", "yoc", fmt.pct, True),
        ]  # fmt: skip
        self.assets_view, self.assets, _ = make_table(cols)
        lay.addWidget(self.assets_view, 2)

    def set_state(self, s: dict):
        p = s["proventos"]
        c = self.cards
        c[0].set(fmt.brl(p["last12"]))
        c[1].set(fmt.brl(p["avg12"]))
        c[2].set(fmt.brl(p["year"]))
        c[3].set(fmt.brl(p["total"]))
        months = p["months"]
        self.chart.set_data(
            [fmt.month_label(m["month"]) for m in months],
            bars=[m["total"] for m in months],
            yfmt=lambda v: "R$ " + fmt.compact(v),
            tip=lambda i: f"{fmt.month_long(months[i]['month'])}\n{fmt.brl(months[i]['total'])}",
        )
        self.by_year.set_rows(p["by_year"])
        self.by_type.set_rows(p["by_type"])
        self.assets.set_rows(p["by_asset"])
