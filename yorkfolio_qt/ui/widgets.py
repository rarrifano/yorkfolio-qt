from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme


def _font(label: QLabel, scale: float = 1.0, bold: bool = False) -> None:
    f = label.font()
    f.setPointSizeF(f.pointSizeF() * scale)
    f.setBold(bold)
    label.setFont(f)


def _dim(label: QLabel) -> None:
    label.setForegroundRole(QPalette.PlaceholderText)


class Card(QFrame):
    """Native framed panel with a small title, a big value and a subtitle."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title, self.value, self.sub = QLabel(title), QLabel("–"), QLabel("")
        _dim(self.title)
        _dim(self.sub)
        _font(self.title, 0.9)
        _font(self.sub, 0.9)
        _font(self.value, 1.6, bold=True)
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "", sign: float | None = None):
        self.value.setText(value)
        self.sub.setText(sub)
        color = theme.colors()["text"] if not sign else (theme.colors()["pos"] if sign > 0 else theme.colors()["neg"])
        pal = self.value.palette()
        pal.setColor(QPalette.WindowText, QColor(color))
        self.value.setPalette(pal)


def cards_row(cards: list[Card]) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for c in cards:
        lay.addWidget(c)
    return w


def heading(text: str) -> QLabel:
    label = QLabel(text)
    _font(label, 1.1, bold=True)
    return label


def muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    _dim(label)
    label.setWordWrap(wrap)
    return label


class RangeButtons(QWidget):
    """Segmented 12m / 24m / 5a / Tudo selector."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = "all"
        self.buttons = {}
        for key, label in (("12", "12m"), ("24", "24m"), ("60", "5a"), ("all", "Tudo")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == self.value)
            b.clicked.connect(lambda _=False, k=key: self._pick(k, on_change))
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch()

    def _pick(self, key: str, on_change):
        self.value = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        on_change()

    def slice(self, points: list) -> list:
        return points if self.value == "all" else points[-int(self.value) :]


__all__ = ["Card", "RangeButtons", "cards_row", "heading", "muted"]
