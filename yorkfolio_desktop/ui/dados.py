"""Dados tab: B3 import, manual entries, warnings, filters and maintenance."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)  # fmt: skip

from .. import db, engine, service
from . import fmt
from .models import Column, make_table, row_at
from .widgets import muted

OPS = engine.MANUAL_LABELS


class DadosTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.state, self.kind_boxes = ctx, None, {}
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)

        # -- import
        box = QGroupBox("Importar extratos da B3")
        bl = QVBoxLayout(box)
        bl.addWidget(muted(
            "1. Acesse investidor.b3.com.br → Extratos.\n2. Em Movimentação e Negociação, filtre o período "
            "(quanto mais histórico, melhor) e baixe em Excel.\n3. Importe os arquivos aqui (ou arraste-os para a janela). "
            "Arquivos repetidos ou períodos sobrepostos são ignorados com segurança.", wrap=True))
        btn = QPushButton("Escolher arquivos .xlsx…")
        btn.setObjectName("primary")
        btn.clicked.connect(ctx.import_dialog)
        bl.addWidget(btn, 0, Qt.AlignLeft)
        self.results = QLabel()
        self.results.setTextFormat(Qt.RichText)
        self.results.setWordWrap(True)
        bl.addWidget(self.results)
        lay.addWidget(box)

        # -- manual entry
        box = QGroupBox("Lançamento manual — exterior, cripto, previdência… ou ajustes (taxas, custo de bonificação)")
        ml = QVBoxLayout(box)
        grid = QGridLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.op = QComboBox()
        for k, label in OPS.items():
            self.op.addItem(label, k)
        self.asset_type = QComboBox()
        from ..assets import ASSET_TYPES

        for k, meta in ASSET_TYPES.items():
            self.asset_type.addItem(meta["label"], k)
        self.fields = {n: QLineEdit() for n in ("code", "qty", "price", "total", "fees", "fx", "name")}
        self.fields["code"].setPlaceholderText("AAPL, BTC, PETR4…")
        self.fields["total"].setPlaceholderText("opcional")
        self.fields["fees"].setPlaceholderText("0")
        self.fields["fx"].setPlaceholderText("auto (PTAX)")
        self.fields["name"].setPlaceholderText("opcional")
        self.currency = QComboBox()
        self.currency.addItems(["BRL", "USD"])
        self.kind = QComboBox()
        self.kind.addItems(["Dividendo", "JCP", "Rendimento", "Juros"])
        for n, (label, w) in enumerate((
            ("Data", self.date), ("Operação", self.op), ("Tipo de ativo", self.asset_type), ("Ativo", self.fields["code"]),
            ("Quantidade", self.fields["qty"]), ("Preço unitário", self.fields["price"]), ("Valor total", self.fields["total"]),
            ("Taxas", self.fields["fees"]), ("Moeda", self.currency), ("Câmbio (R$ por US$)", self.fields["fx"]),
            ("Tipo de provento", self.kind), ("Nome / descrição", self.fields["name"]),
        )):  # fmt: skip
            grid.addWidget(QLabel(label), n // 3, (n % 3) * 2)
            grid.addWidget(w, n // 3, (n % 3) * 2 + 1)
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)
        ml.addLayout(grid)
        add = QPushButton("Adicionar lançamento")
        add.setObjectName("primary")
        add.clicked.connect(self._add_manual)
        ml.addWidget(add, 0, Qt.AlignLeft)
        cols = [
            Column("Data", "date", fmt.br_date), Column("Operação", lambda m: OPS.get(m["op"], m["op"])),
            Column("Ativo", "code"), Column("Qtd", "qty", fmt.qty, True), Column("Preço", "price", lambda v: fmt.num(v, 4), True),
            Column("Total", "total", fmt.num, True), Column("Moeda", "currency"), Column("Câmbio", "fx", lambda v: fmt.num(v, 4), True),
        ]  # fmt: skip
        self.manual_view, self.manual, _ = make_table(cols)
        self.manual_view.setMinimumHeight(160)
        ml.addWidget(self.manual_view)
        delete = QPushButton("Excluir lançamento selecionado")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete_manual)
        ml.addWidget(delete, 0, Qt.AlignLeft)
        lay.addWidget(box)

        # -- warnings
        box = QGroupBox("Avisos")
        wl = QVBoxLayout(box)
        cols = [
            Column("", "level", lambda v: "atenção" if v == "warn" else "info"), Column("Data", "date", fmt.br_date),
            Column("Ativo", "code"), Column("Mensagem", "msg", stretch=True),
        ]  # fmt: skip
        self.warn_view, self.warnings, _ = make_table(cols)
        self.warn_view.setMinimumHeight(150)
        wl.addWidget(self.warn_view)
        lay.addWidget(box)

        # -- filters
        self.filters_box = QGroupBox("Filtros — ignorar tipos de renda fixa")
        self.filters_layout = QHBoxLayout(self.filters_box)
        lay.addWidget(self.filters_box)

        # -- maintenance
        box = QGroupBox("Dados")
        dl = QVBoxLayout(box)
        self.info = muted("")
        dl.addWidget(self.info)
        row = QHBoxLayout()
        for text, slot, name in (
            ("Rebaixar histórico de preços", lambda: ctx.refresh_market(force=True), ""),
            ("Apagar extratos importados", lambda: self._reset(False), "danger"),
            ("Apagar tudo (lançamentos, metas e notas)", lambda: self._reset(True), "danger"),
        ):
            b = QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        dl.addLayout(row)
        lay.addWidget(box)
        lay.addStretch()

    # ------------------------------------------------------------ state
    def set_state(self, s: dict):
        self.state = s
        self.manual.set_rows(list(reversed(s["manual"])))
        self.warnings.set_rows(s["warnings"])
        c = s["counts"]
        self.info.setText(
            f"{c['trades']} negócios, {c['movements']} movimentações"
            + (f" ({c['excluded']} ignoradas pelos filtros)" if c["excluded"] else "")
            + f" e {c['manual']} lançamentos manuais — guardados num SQLite local:\n{self.ctx.db_path}"
            + (f"\nDados de mercado atualizados em {fmt.br_date(s['summary']['market_at'])} {s['summary']['market_at'][11:16]}." if s["summary"].get("market_at") else "")
        )
        while self.filters_layout.count():
            item = self.filters_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.kind_boxes = {}
        kinds = s["filters"]["kinds"]
        if not kinds:
            self.filters_layout.addWidget(muted("Nenhum produto de renda fixa importado."))
        for kind, n in kinds.items():
            cb = QCheckBox(f"{kind} ({n})")
            cb.setChecked(kind in s["filters"]["exclude"])
            cb.toggled.connect(self._save_filters)
            self.kind_boxes[kind] = cb
            self.filters_layout.addWidget(cb)
        self.filters_layout.addStretch()

    def show_imports(self, results: list[dict]):
        lines = []
        for r in results:
            if r.get("error"):
                lines.append(f"<span style='color:#b91c1c'>{r['file']}: {r['error']}</span>")
            else:
                kind = "Negociação" if r["kind"] == "negociacao" else "Movimentação"
                lines.append(f"{r['file']} — {kind}: {r['rows']} linhas, <b>{r['inserted']} novas</b>, {r['duplicates']} já existentes")
        self.results.setText("<br>".join(lines))

    # ------------------------------------------------------------ actions
    def _save_filters(self):
        exclude = [k for k, cb in self.kind_boxes.items() if cb.isChecked()]
        self.ctx.run(lambda con: service.set_filters(con, exclude), reload=True)

    def _add_manual(self):
        data = {k: w.text() for k, w in self.fields.items()}
        d = self.date.date()
        data.update(
            date=date(d.year(), d.month(), d.day()).isoformat(), op=self.op.currentData(),
            asset_type=self.asset_type.currentData(), currency=self.currency.currentText(), kind=self.kind.currentText(),
        )  # fmt: skip
        self.ctx.run(
            lambda con: service.add_manual(con, data),
            self._clear_form,
            reload=True,
            busy="Adicionando lançamento…",
        )

    def _clear_form(self, _result=None):
        for w in self.fields.values():
            w.clear()

    def _delete_manual(self):
        row = row_at(self.manual_view, self.manual_view.currentIndex())
        if row:
            self.ctx.run(lambda con: db.delete_manual(con, row["id"]), reload=True)

    def _reset(self, everything: bool):
        what = "TODOS os dados (extratos, lançamentos manuais, metas e notas)" if everything else "os extratos importados"
        if QMessageBox.question(self, "Confirmar", f"Apagar {what}? Isso não pode ser desfeito.") == QMessageBox.Yes:
            self.ctx.run(lambda con: db.reset(con, everything), reload=True)
