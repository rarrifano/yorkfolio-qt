from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme


class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setObjectName("cardValue")
        self.sub = QLabel("")
        self.sub.setObjectName("cardSub")
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "", sign: float | None = None):
        self.value.setText(value)
        self.sub.setText(sub)
        c = theme.colors()
        color = c["text"] if not sign else (c["pos"] if sign > 0 else c["neg"])
        self.value.setStyleSheet(f"color: {color};")


def cards_row(cards: list[Card]) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for c in cards:
        lay.addWidget(c)
    return w


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("heading")
    return label


def muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
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
