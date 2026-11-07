"""A small table model driven by column specs, with sorting and text filtering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from . import theme

SORT_ROLE = Qt.UserRole + 1
ROW_ROLE = Qt.UserRole + 2


@dataclass
class Column:
    title: str
    value: str | Callable[[dict], Any]  # key, or function row -> raw value
    fmt: Callable[[Any], str] | None = None
    right: bool = False  # numeric: right-aligned
    signed: bool = False  # color by sign
    tip: Callable[[dict], str | None] | None = None
    stretch: bool = False

    def raw(self, row: dict):
        return self.value(row) if callable(self.value) else row.get(self.value)


class DictTableModel(QAbstractTableModel):
    def __init__(self, columns: list[Column], parent=None):
        super().__init__(parent)
        self.columns, self.rows = columns, []
        self.row_style: Callable[[dict], str | None] | None = None  # "muted" | "bold"

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.columns[section].title
            if role == Qt.TextAlignmentRole and self.columns[section].right:
                return int(Qt.AlignRight | Qt.AlignVCenter)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = self.rows[index.row()], self.columns[index.column()]
        if role == ROW_ROLE:
            return row
        raw = col.raw(row)
        if role == Qt.DisplayRole:
            return col.fmt(raw) if col.fmt else ("" if raw is None else str(raw))
        if role == SORT_ROLE:
            return (0, "") if raw is None else (1, raw if not isinstance(raw, bool) else int(raw))
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col.right else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            c = theme.colors()
            if col.signed and isinstance(raw, int | float) and round(raw, 6) != 0:
                return QBrush(QColor(c["pos"] if raw > 0 else c["neg"]))
            if self.row_style and self.row_style(row) == "muted":
                return QBrush(QColor(c["muted"]))
        if role == Qt.ToolTipRole and col.tip:
            return col.tip(row)


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def make_table(columns: list[Column], sortable: bool = True, filterable: bool = False):
    """Returns (view, model, proxy)."""
    model = DictTableModel(columns)
    proxy = _Proxy()
    proxy.setSourceModel(model)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    view = QTableView()
    view.setModel(proxy)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.setSortingEnabled(sortable)
    view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)  # keep the natural order until a header is clicked
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(26)
    view.setWordWrap(False)
    header = view.horizontalHeader()
    header.setStretchLastSection(True)
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    for i, c in enumerate(columns):
        if c.stretch:
            header.setSectionResizeMode(i, QHeaderView.Stretch)
    return view, model, proxy


def row_at(view: QTableView, index: QModelIndex) -> dict | None:
    return index.data(ROW_ROLE) if index.isValid() else None
