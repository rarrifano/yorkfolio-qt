# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Lightweight QPainter charts: stacked areas + lines (history) and bars (proventos)."""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import theme


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step) * step
    ticks, v = [], first
    while v <= hi + step * 1e-9:
        ticks.append(round(v, 10))
        v += step
    return ticks


class Chart(QWidget):
    """series: {'name', 'color': QColor, 'values': [float|None], 'width', 'dash'}.
    stacks: same shape, drawn as stacked areas below the lines.
    kind='bars' draws the first stack/line series as bars."""

    def __init__(self, height: int = 240, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)
        self.setAccessibleName("Gráfico")
        self.labels: list[str] = []
        self.stacks: list[dict] = []
        self.lines: list[dict] = []
        self.bars: list[float] = []
        self.yfmt: Callable[[float], str] = lambda v: f"{v:g}"
        self.tip: Callable[[int], str] | None = None
        self.zero_baseline = True
        self._hover: int | None = None
        self._plot = QRectF()

    def set_data(self, labels, stacks=(), lines=(), bars=(), yfmt=None, tip=None, zero_baseline=True):
        self.labels, self.stacks, self.lines, self.bars = list(labels), list(stacks), list(lines), list(bars)
        self.yfmt = yfmt or self.yfmt
        self.tip, self.zero_baseline, self._hover = tip, zero_baseline, None
        if self.tip and self.labels:  # screen readers: first and last data point
            self.setAccessibleDescription(f"{self.tip(0)} … {self.tip(len(self.labels) - 1)}".replace("<br>", "; "))
        self.update()

    # ------------------------------------------------------------ geometry
    def _x(self, i: int) -> float:
        n = len(self.labels)
        r = self._plot
        if self.bars:
            return r.left() + (i + 0.5) * r.width() / n
        return r.left() + (r.width() * i / (n - 1) if n > 1 else r.width() / 2)

    def _range(self) -> tuple[float, float]:
        vals: list[float] = []
        if self.bars:
            vals += self.bars
        if self.stacks:
            vals += [sum(s["values"][i] or 0 for s in self.stacks) for i in range(len(self.labels))]
        for ln in self.lines:
            vals += [v for v in ln["values"] if v is not None]
        if not vals:
            return 0.0, 1.0
        lo, hi = min(vals), max(vals)
        if self.zero_baseline:
            lo = min(lo, 0.0)
        if hi == lo:
            hi = lo + 1
        pad = (hi - lo) * 0.05
        return (lo if self.zero_baseline and lo == 0 else lo - pad), hi + pad

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        c = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        p.setFont(font)
        fm = p.fontMetrics()
        n = len(self.labels)
        if n == 0:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Sem dados")
            return
        lo, hi = self._range()
        ticks = nice_ticks(lo, hi)
        left = max(fm.horizontalAdvance(self.yfmt(t)) for t in ticks) + 14
        self._plot = QRectF(left, 8, self.width() - left - 10, self.height() - 8 - fm.height() - 10)
        r = self._plot
        y = lambda v: r.bottom() - (v - lo) / (hi - lo) * r.height()

        p.setPen(QPen(QColor(c["grid"]), 1))
        for t in ticks:
            p.drawLine(QPointF(r.left(), y(t)), QPointF(r.right(), y(t)))
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(0, y(t) - 9, left - 6, 18), Qt.AlignRight | Qt.AlignVCenter, self.yfmt(t))
            p.setPen(QPen(QColor(c["grid"]), 1))
        step = max(1, math.ceil(n / max(1, int(r.width() // 52))))
        p.setPen(QColor(c["muted"]))
        for i in range(0, n, step):
            p.drawText(QRectF(self._x(i) - 30, r.bottom() + 4, 60, fm.height()), Qt.AlignCenter, self.labels[i])

        if self.bars:
            bw = max(2.0, r.width() / n * 0.62)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            for i, v in enumerate(self.bars):
                if v:
                    p.drawRoundedRect(QRectF(self._x(i) - bw / 2, y(v), bw, y(0) - y(v)), 2, 2)

        if self.stacks:
            base = [0.0] * n
            for s in self.stacks:
                top = [base[i] + (s["values"][i] or 0) for i in range(n)]
                path = QPainterPath(QPointF(self._x(0), y(base[0])))
                for i in range(n):
                    path.lineTo(self._x(i), y(top[i]))
                for i in reversed(range(n)):
                    path.lineTo(self._x(i), y(base[i]))
                path.closeSubpath()
                color = QColor(s["color"])
                color.setAlpha(190)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawPath(path)
                base = top

        for ln in self.lines:
            pen = QPen(QColor(ln["color"]), ln.get("width", 2))
            if ln.get("dash"):
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path, pen_down = QPainterPath(), False
            for i, v in enumerate(ln["values"]):
                if v is None:
                    pen_down = False
                    continue
                pt = QPointF(self._x(i), y(v))
                if pen_down:
                    path.lineTo(pt)
                else:
                    path.moveTo(pt)
                    pen_down = True
            p.drawPath(path)

        if self._hover is not None:
            p.setPen(QPen(QColor(c["muted"]), 1, Qt.DotLine))
            x = self._x(self._hover)
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            for ln in self.lines:
                v = ln["values"][self._hover]
                if v is not None:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(ln["color"]))
                    p.drawEllipse(QPointF(x, y(v)), 3.5, 3.5)

    # ------------------------------------------------------------ hover
    def mouseMoveEvent(self, e):
        n = len(self.labels)
        if not n or not self._plot.contains(e.position()):
            self.leaveEvent(None)
            return
        best = min(range(n), key=lambda i: abs(self._x(i) - e.position().x()))
        if best != self._hover:
            self._hover = best
            self.update()
        if self.tip:
            QToolTip.showText(e.globalPosition().toPoint(), self.tip(best), self)

    def leaveEvent(self, _):
        if self._hover is not None:
            self._hover = None
            self.update()
        QToolTip.hideText()


class StackedBar(QWidget):
    """One horizontal bar split in segments [(label, fraction, QColor)] with optional target ticks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.segments: list[tuple[str, float, QColor]] = []

    def set_segments(self, segments):
        self.segments = [s for s in segments if s[1] > 0]
        self.setAccessibleName("Alocação")
        self.setAccessibleDescription("; ".join(f"{s[0]} {s[1] / (sum(x[1] for x in self.segments) or 1):.0%}" for s in self.segments))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(s[1] for s in self.segments) or 1.0
        x = 0.0
        w = self.width()
        for label, frac, color in self.segments:
            seg_w = w * frac / total
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRect(QRectF(x, 0, max(seg_w - 1, 1), self.height()))
            if seg_w > 60:
                p.setPen(QColor("black") if color.lightness() > 150 else QColor("white"))
                p.drawText(QRectF(x + 6, 0, seg_w - 8, self.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
            x += seg_w
