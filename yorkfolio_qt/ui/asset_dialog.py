# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from . import fmt
from .widgets import muted

INDEXERS = {"cdi": "% do CDI", "selic": "% da Selic", "ipca": "IPCA + taxa a.a.", "pre": "Prefixado (taxa a.a.)"}


class AssetDialog(QDialog):
    """Per-asset settings: manual value, class, nota and (for fixed income) the indexer."""

    def __init__(self, asset: dict, class_names: list[str], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.setWindowTitle(asset["code"])
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        title = QLabel(f"<b>{asset['code']}</b> — {asset['name'] or asset['type_label']}")
        lay.addWidget(title)
        lay.addWidget(QLabel(f"Valor atual: <b>{fmt.brl(asset['value'])}</b> ({asset['source']})"))
        if asset["source_note"]:
            lay.addWidget(muted(asset["source_note"]))
        form = QFormLayout()
        fixed = asset["asset_type"] in ("rf", "tesouro")
        self.indexer = self.rate = None
        if asset["asset_type"] == "tesouro":
            lay.addWidget(muted("Títulos do Tesouro são avaliados automaticamente pelo preço oficial (Tesouro Transparente)."))
        elif fixed:
            self.indexer = QComboBox()
            self.indexer.addItem("— sem estimativa —", "")
            for k, label in INDEXERS.items():
                self.indexer.addItem(label, k)
            self.indexer.setCurrentIndex(max(0, self.indexer.findData(asset["indexer"] or "")))
            self.rate = QLineEdit("" if asset["rate"] is None else str(asset["rate"]).replace(".", ","))
            self.rate.setPlaceholderText("ex.: 110")
            form.addRow("Indexador", self.indexer)
            form.addRow("Taxa", self.rate)
            lay.addWidget(muted("% do CDI/Selic: informe o percentual (ex.: 110). IPCA+ e prefixado: taxa ao ano (ex.: 6,5). A estimativa parte do último preço unitário informado pela B3."))
        self.cls = QComboBox()
        self.cls.setEditable(True)
        self.cls.addItems(class_names)
        self.cls.setCurrentText(asset["class"])
        form.addRow("Classe", self.cls)
        self.nota = QLineEdit(fmt.num(asset["nota"], 2))
        form.addRow("Nota", self.nota)
        self.manual = QLineEdit("" if asset["manual_value"] is None else str(asset["manual_value"]).replace(".", ","))
        self.manual.setPlaceholderText("vazio = automático")
        form.addRow("Valor atual manual (tem prioridade)", self.manual)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.fields: dict = {}

    def _accept(self):
        try:
            fields = {"manual_value": fmt.parse_number(self.manual.text()), "nota": fmt.parse_number(self.nota.text()) or 0.0}
            if self.indexer is not None:
                fields.update(indexer=self.indexer.currentData() or None, rate=fmt.parse_number(self.rate.text()))
        except ValueError as exc:
            self.setWindowTitle(str(exc))
            return
        cls = self.cls.currentText().strip()
        from ..assets import default_class

        fields["class"] = None if cls == default_class(self.asset["asset_type"]) else cls
        self.fields = fields
        self.accept()
