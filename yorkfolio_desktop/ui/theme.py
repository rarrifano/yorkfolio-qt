"""Light/dark palettes and the application style sheet."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f4f6f9", "panel": "#ffffff", "text": "#1e293b", "muted": "#64748b", "border": "#dbe1ea",
    "accent": "#1d4ed8", "pos": "#15803d", "neg": "#b91c1c", "alt": "#f8fafc", "ibov": "#ea580c", "grid": "#e2e8f0",
}  # fmt: skip
DARK = {
    "bg": "#0b1220", "panel": "#131c2e", "text": "#e2e8f0", "muted": "#94a3b8", "border": "#25324a",
    "accent": "#60a5fa", "pos": "#4ade80", "neg": "#f87171", "alt": "#17223a", "ibov": "#fb923c", "grid": "#25324a",
}  # fmt: skip
CLASS_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#db2777", "#65a30d", "#dc2626", "#64748b"]

_current = dict(LIGHT)
_class_index: dict[str, int] = {}


def colors() -> dict[str, str]:
    return _current


def class_color(name: str) -> QColor:
    idx = _class_index.setdefault(name, len(_class_index))
    return QColor(CLASS_COLORS[idx % len(CLASS_COLORS)])


def apply(app: QApplication, dark: bool) -> None:
    c = DARK if dark else LIGHT
    _current.clear()
    _current.update(c)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in (
        (QPalette.Window, "bg"), (QPalette.Base, "panel"), (QPalette.AlternateBase, "alt"),
        (QPalette.WindowText, "text"), (QPalette.Text, "text"), (QPalette.ButtonText, "text"),
        (QPalette.Button, "panel"), (QPalette.ToolTipBase, "panel"), (QPalette.ToolTipText, "text"),
        (QPalette.Highlight, "accent"), (QPalette.PlaceholderText, "muted"),
    ):  # fmt: skip
        pal.setColor(role, QColor(c[key]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff" if not dark else "#0b1220"))
    app.setPalette(pal)
    app.setStyleSheet(
        f"""
        QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; background: {c['bg']}; top: -1px; }}
        QTabBar::tab {{ padding: 7px 16px; border: 1px solid transparent; color: {c['muted']}; }}
        QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
        QHeaderView::section {{ background: {c['alt']}; color: {c['muted']}; border: 0;
            border-bottom: 1px solid {c['border']}; padding: 5px 8px; font-weight: 600; }}
        QTableView, QTreeWidget, QTreeView {{ border: 1px solid {c['border']}; border-radius: 6px;
            gridline-color: {c['border']}; alternate-background-color: {c['alt']}; }}
        QFrame#card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QLabel#cardTitle {{ color: {c['muted']}; font-size: 11px; }}
        QLabel#cardValue {{ font-size: 20px; font-weight: 700; }}
        QLabel#cardSub {{ color: {c['muted']}; font-size: 11px; }}
        QLabel#heading {{ font-size: 14px; font-weight: 700; }}
        QLabel#muted {{ color: {c['muted']}; }}
        QPushButton {{ padding: 6px 14px; border: 1px solid {c['border']}; border-radius: 6px; background: {c['panel']}; }}
        QPushButton:hover {{ border-color: {c['accent']}; }}
        QPushButton:checked {{ background: {c['accent']}; color: white; }}
        QPushButton#primary {{ background: {c['accent']}; color: white; border-color: {c['accent']}; font-weight: 600; }}
        QPushButton#danger {{ color: {c['neg']}; }}
        QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit {{ padding: 5px 8px; border: 1px solid {c['border']}; border-radius: 6px; }}
        QGroupBox {{ font-weight: 700; border: 1px solid {c['border']}; border-radius: 8px; margin-top: 12px; padding: 14px 10px 10px 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        QToolBar {{ border: 0; spacing: 6px; padding: 4px; }}
        """
    )
