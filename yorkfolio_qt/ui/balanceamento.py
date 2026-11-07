# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Balanceamento tab: targets per class, notas per asset and the aporte plan."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)  # fmt: skip

from .. import db, engine
from . import fmt
from .widgets import heading, muted

COL_CLASS, COL_VALUE, COL_EDIT = 0, 1, 2


class BalanceamentoTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.state = ctx, None
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(heading("Metas e notas"))
        ll.addWidget(muted("Edite a meta (%) de cada classe e a nota de cada ativo (0 = não comprar mais). Notas e metas são relativas."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Classe / ativo", "Valor atual", "Meta % / nota", "Atual %", "Falta p/ meta"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(lambda item, col: col == COL_EDIT and self.tree.editItem(item, col))
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        ll.addWidget(self.tree, 1)
        save = QPushButton("Salvar metas e notas")
        save.setIcon(QIcon.fromTheme("document-save"))
        save.setDefault(True)
        save.clicked.connect(self._save)
        ll.addWidget(save)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(heading("Plano de aporte"))
        row = QHBoxLayout()
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Valor do aporte, ex.: 1.500,00")
        self.amount.returnPressed.connect(self._plan)
        go = QPushButton("Calcular")
        go.clicked.connect(self._plan)
        row.addWidget(QLabel("R$"))
        row.addWidget(self.amount, 1)
        row.addWidget(go)
        rl.addLayout(row)
        self.plan = QTreeWidget()
        self.plan.setHeaderLabels(["Classe / ativo", "Qtd", "Preço", "Valor"])
        self.plan.setAlternatingRowColors(True)
        self.plan.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        rl.addWidget(self.plan, 1)
        self.plan_note = muted("")
        rl.addWidget(self.plan_note)
        split.addWidget(right)
        split.setSizes([620, 480])

    # ------------------------------------------------------------ targets/notas
    def set_state(self, s: dict):
        self.state = s
        self.tree.clear()
        raw = s["targets"]
        for cls in s["classes"]:
            top = QTreeWidgetItem([cls["name"], fmt.brl(cls["value"]), fmt.num(raw.get(cls["name"], 0), 2), fmt.pct(cls["pct"]), fmt.brl(cls["gap"]) if cls["gap"] is not None else ""])
            top.setData(COL_CLASS, Qt.UserRole, ("class", cls["name"]))
            top.setFlags(top.flags() | Qt.ItemIsEditable)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for a in cls["assets"]:
                child = QTreeWidgetItem([a["code"], fmt.brl(a["value"]), fmt.num(a["nota"], 2), fmt.pct(a["pct_class"]), fmt.brl(a["gap"]) if a["gap"] is not None else ""])
                child.setData(COL_CLASS, Qt.UserRole, ("asset", a["code"]))
                child.setFlags(child.flags() | Qt.ItemIsEditable)
                top.addChild(child)
            top.setExpanded(True)
        for i in range(1, 5):
            for item in self._items():
                item.setTextAlignment(i, Qt.AlignRight | Qt.AlignVCenter)

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def _save(self):
        try:
            targets, notas = {}, {}
            for item in self._items():
                kind, key = item.data(COL_CLASS, Qt.UserRole)
                value = fmt.parse_number(item.text(COL_EDIT)) or 0.0
                (targets if kind == "class" else notas)[key] = value
        except ValueError as exc:
            return self.ctx.message(str(exc), error=True)

        original = {a["code"]: a["nota"] for c in self.state["classes"] for a in c["assets"]}

        def work(con):
            db.set_targets(con, targets)
            for code, nota in notas.items():
                if abs(original.get(code, 0) - nota) > 1e-9:
                    db.update_asset(con, code, {"nota": nota})

        self.ctx.run(work, lambda _: self.ctx.message("Metas e notas salvas."), reload=True)

    # ------------------------------------------------------------ plan
    def _plan(self):
        try:
            amount = fmt.parse_number(self.amount.text()) or 0.0
            result = engine.plan_aporte(self.state["classes"], amount)
        except ValueError as exc:
            self.plan.clear()
            return self.ctx.message(str(exc), error=True)
        self.plan.clear()
        for c in result["classes"]:
            top = QTreeWidgetItem([c["class"], "", "", fmt.brl(c["budget"])])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.plan.addTopLevelItem(top)
            if c.get("note"):
                top.addChild(QTreeWidgetItem([c["note"]]))
            for a in c["assets"]:
                top.addChild(QTreeWidgetItem([a["code"], fmt.qty(a["qty"]) if a["qty"] is not None else "", fmt.brl(a["price"]) if a["price"] else "", fmt.brl(a["amount"])]))
            top.setExpanded(True)
        for item in [self.plan.topLevelItem(i) for i in range(self.plan.topLevelItemCount())]:
            for col in (1, 2, 3):
                item.setTextAlignment(col, Qt.AlignRight)
                for j in range(item.childCount()):
                    item.child(j).setTextAlignment(col, Qt.AlignRight)
        self.plan_note.setText(f"Aporte de {fmt.brl(result['amount'])}; sobra {fmt.brl(result['leftover'])} (arredondamento para ações inteiras).")

