# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Extrato tab: every ledger row and how it was interpreted."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from . import fmt
from .models import Column, make_table

STATUS = {
    "skip": "duplicado (liquidação já casada)", "ignore": "ignorado", "dt_part": "day trade",
    "unhandled": "não tratado", "daytrade": "day trade",
}  # fmt: skip


class ExtratoTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por ativo, tipo, instituição…")
        self.count = QLabel()
        top.addWidget(self.filter, 1)
        top.addWidget(self.count)
        lay.addLayout(top)
        cols = [
            Column("Data", "date", fmt.br_date), Column("Ativo", "code"),
            Column("Operação", lambda e: e["label"] + (f"  ({STATUS[e['action']]})" if e["action"] in STATUS else "")),
            Column("Qtd", "qty", fmt.qty, True), Column("Preço", "price", lambda v: fmt.num(v, 4), True),
            Column("Valor", "value", fmt.brl, True), Column("Origem", lambda e: f"{e['source']} {e.get('institution') or ''}".strip()),
            Column("Obs.", "note", stretch=True),
        ]  # fmt: skip
        self.view, self.model, self.proxy = make_table(cols)
        self.model.row_style = lambda e: "muted" if e["action"] in ("skip", "ignore", "dt_part") else None
        self.filter.textChanged.connect(self._apply)
        lay.addWidget(self.view)

    def _apply(self, text):
        self.proxy.setFilterFixedString(text)
        self.count.setText(f"{self.proxy.rowCount()} de {self.model.rowCount()} lançamentos")

    def set_state(self, s: dict):
        self.model.set_rows(list(reversed(s["ledger"])))
        self._apply(self.filter.text())
