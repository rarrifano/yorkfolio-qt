"""Carteira tab: summary, history charts, allocation and positions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)  # fmt: skip

from . import fmt, theme
from .charts import Chart, StackedBar
from .models import Column, make_table
from .widgets import Card, RangeButtons, cards_row, heading

SOURCE_BADGE = {"manual": "manual", "custo": "custo", "tesouro": "Tesouro", "indexador": "estimado", "último PU": "último PU"}


def class_sort_key(name: str):
    from ..assets import STANDARD_CLASSES

    return (STANDARD_CLASSES.index(name), "") if name in STANDARD_CLASSES else (len(STANDARD_CLASSES), name)


class CarteiraTab(QWidget):
    HEADERS = ["Ativo", "Qtd", "Preço médio", "Preço", "Valor", "% classe", "% total", "Meta", "Falta p/ meta", "Resultado", "%"]

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.state = ctx, None
        lay = QVBoxLayout(self)

        self.cards = [Card(t) for t in ("Patrimônio", "Valor aplicado", "Resultado", "Proventos 12m", "Resultado realizado")]
        lay.addWidget(cards_row(self.cards))

        self.range = RangeButtons(self._draw_charts)
        lay.addWidget(self.range)
        charts = QTabWidget()
        self.patrimonio = Chart(230)
        self.rentab = Chart(230)
        self.returns_label = QLabel()
        rent_box = QWidget()
        rl = QVBoxLayout(rent_box)
        rl.setContentsMargins(0, 4, 0, 0)
        rl.addWidget(self.returns_label)
        rl.addWidget(self.rentab)
        charts.addTab(self.patrimonio, "Patrimônio")
        charts.addTab(rent_box, "Rentabilidade vs CDI e Ibovespa")
        charts.setMinimumHeight(290)
        lay.addWidget(charts)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.RichText)
        lay.addWidget(self.legend)

        self.alloc = StackedBar()
        lay.addWidget(heading("Alocação"))
        lay.addWidget(self.alloc)

        tabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.HEADERS))
        self.tree.setHeaderLabels(self.HEADERS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemDoubleClicked.connect(self._edit)
        tabs.addTab(self.tree, "Posições (duplo clique para editar)")
        cols = [
            Column("Ativo", "code"), Column("Nome", "name", stretch=True), Column("Classe", "class"),
            Column("Resultado realizado", "realized", fmt.brl, True, True),
            Column("Proventos", "proventos", fmt.brl, True), Column("Encerrada em", "last_date", fmt.br_date),
        ]  # fmt: skip
        self.closed_view, self.closed_model, _ = make_table(cols)
        tabs.addTab(self.closed_view, "Encerradas")
        tabs.setMinimumHeight(320)
        lay.addWidget(tabs, 1)

    # ------------------------------------------------------------ data
    def set_state(self, s: dict):
        self.state = s
        sm = s["summary"]
        c = self.cards
        c[0].set(fmt.brl(sm["value"]), f"{sm['n_assets']} ativos")
        c[1].set(fmt.brl(sm["cost"]))
        c[2].set(fmt.brl(sm["pnl"]), fmt.signed_pct(sm["pnl_pct"]), sm["pnl"])
        c[3].set(fmt.brl(sm.get("proventos_12m")), f"no ano: {fmt.brl(sm.get('proventos_year'))}")
        c[4].set(fmt.brl(sm["realized"]), "vendas já realizadas", sm["realized"])
        self._draw_charts()
        self._fill_tree(s)
        self.closed_model.set_rows(s["closed"])
        total = sm["value"] or 1
        self.alloc.set_segments(
            [(f"{c['name']} {fmt.pct(c['pct'], 0)}", c["value"] / total, theme.class_color(c["name"])) for c in s["classes"]]
        )

    def _draw_charts(self):
        if not self.state:
            return
        pts = self.range.slice(self.state["history"].get("points", []))
        classes = sorted({k for p in pts for k in p["classes"]}, key=class_sort_key)
        stacks = [{"name": k, "color": theme.class_color(k), "values": [p["classes"].get(k, 0) for p in pts]} for k in classes]
        c = theme.colors()
        lines = [{"color": QColor(c["text"]), "dash": True, "width": 1.6, "values": [p["cost"] for p in pts]}]

        def tip(i):
            p = pts[i]
            rows = "\n".join(f"{k}: {fmt.brl(p['classes'][k])}" for k in classes if p["classes"].get(k))
            return f"{fmt.month_long(p['month'])}\nPatrimônio: {fmt.brl(p['value'])}\nAplicado: {fmt.brl(p['cost'])}\n{rows}"

        self.patrimonio.set_data([fmt.month_label(p["month"]) for p in pts], stacks, lines, yfmt=lambda v: "R$ " + fmt.compact(v), tip=tip)
        self.legend.setText(
            "  ".join(f'<span style="color:{theme.class_color(k).name()}">■</span> {k}' for k in classes)
            + "  &nbsp;- - Valor aplicado"
        )

        acc = {"ret": 1.0, "cdi": 1.0, "ibov": 1.0}
        series = {k: [] for k in acc}
        started = False
        for p in pts:
            if p["ret"] is not None:
                started = True
                acc["ret"] *= 1 + p["ret"]
                if p["cdi"] is not None:
                    acc["cdi"] *= 1 + p["cdi"]
                if p["ibov"] is not None:
                    acc["ibov"] *= 1 + p["ibov"]
            for k in series:
                series[k].append(acc[k] - 1 if started else None)
        if not started:
            self.rentab.set_data([])
            self.returns_label.setText("")
            return
        specs = [("Carteira", "ret", c["accent"], 2.6), ("CDI", "cdi", c["muted"], 1.8), ("Ibovespa", "ibov", c["ibov"], 1.8)]
        rl = [{"name": n, "color": QColor(col), "width": w, "values": series[k]} for n, k, col, w in specs]

        def rtip(i):
            return f"{fmt.month_long(pts[i]['month'])}\n" + "\n".join(f"{x['name']}: {fmt.signed_pct(x['values'][i])}" for x in rl) + f"\nNo mês (carteira): {fmt.signed_pct(pts[i]['ret'])}"

        self.rentab.set_data([fmt.month_label(p["month"]) for p in pts], lines=rl, yfmt=lambda v: fmt.num(v * 100, 0) + "%", tip=rtip, zero_baseline=False)
        self.returns_label.setText(
            " &nbsp; ".join(f'<span style="color:{col}">■</span> {n} <b>{fmt.signed_pct(acc[k] - 1)}</b>' for n, k, col, _ in specs)
            + "<br><small>Retorno ponderado no tempo (Modified Dietz); meses sem posição não contam.</small>"
        )
        self.returns_label.setTextFormat(Qt.RichText)

    def _fill_tree(self, s: dict):
        c = theme.colors()
        self.tree.clear()
        has_targets = s["summary"]["targets_set"]
        for cls in s["classes"]:
            top = QTreeWidgetItem(
                [
                    cls["name"], "", "", "", fmt.brl(cls["value"]), "", fmt.pct(cls["pct"]),
                    fmt.pct(cls["target"]) if has_targets else "", fmt.brl(cls["gap"]) if has_targets else "",
                    fmt.brl(cls["pnl"]) if cls["cost"] else "", "",
                ]
            )  # fmt: skip
            f = top.font(0)
            f.setBold(True)
            for col in range(len(self.HEADERS)):
                top.setFont(col, f)
            top.setForeground(0, QBrush(theme.class_color(cls["name"])))
            self.tree.addTopLevelItem(top)
            for a in cls["assets"]:
                tag = SOURCE_BADGE.get(a["source"])
                label = a["code"] + (f"  [{tag}]" if tag and a["open"] else "")
                if not a["open"]:
                    label += "  (watchlist)"
                item = QTreeWidgetItem(
                    [
                        label, fmt.qty(a["qty"]) if a["open"] else "", fmt.money(a["avg_price"], "BRL") if a["open"] else "",
                        fmt.money(a["price"], a["currency"]) if a["price"] is not None else "–",
                        fmt.brl(a["value"]) if a["open"] else "", fmt.pct(a["pct_class"]) if a["open"] else "",
                        fmt.pct(a["pct_total"]) if a["open"] else "", fmt.pct(a["target_total"]) if has_targets else "",
                        fmt.brl(a["gap"]) if has_targets and a["gap"] is not None else "",
                        fmt.brl(a["pnl"]) if a["pnl"] is not None else "", fmt.signed_pct(a["pnl_pct"]) if a["pnl_pct"] is not None else "",
                    ]
                )  # fmt: skip
                item.setData(0, Qt.UserRole, a["code"])
                item.setToolTip(0, f"{a['name'] or a['type_label']}\n{a['source_note'] or ''}".strip())
                for col in range(1, len(self.HEADERS)):
                    item.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
                for col in (9, 10):
                    if a["pnl"]:
                        item.setForeground(col, QBrush(QColor(c["pos"] if a["pnl"] > 0 else c["neg"])))
                if not a["open"]:
                    for col in range(len(self.HEADERS)):
                        item.setForeground(col, QBrush(QColor(c["muted"])))
                top.addChild(item)
            for col in range(1, len(self.HEADERS)):
                top.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
            top.setExpanded(True)

    def _edit(self, item, _col):
        code = item.data(0, Qt.UserRole)
        if code:
            self.ctx.edit_asset(code)

