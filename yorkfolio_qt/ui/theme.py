# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Native look: follow the desktop's style (Breeze on Plasma) and color scheme.

No style sheet and no custom palette: widgets are drawn by the platform style. "Tema" only asks Qt
for a light/dark color scheme (Qt >= 6.8), or follows the system when set to "system". Colors used
by custom painting (charts, positive/negative numbers) are derived from the active palette, with
Breeze's semantic colors for gains and losses.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

MODES = ("system", "light", "dark")
CLASS_COLORS = ["#3daee9", "#27ae60", "#f67400", "#9b59b6", "#1abc9c", "#e91e8c", "#8e8e00", "#da4453", "#7f8c8d"]  # Breeze accents
_class_index: dict[str, int] = {}
_cache: tuple[int, dict[str, str]] | None = None


def colors() -> dict[str, str]:
    """Palette-derived colors as hex strings (recomputed when the palette changes)."""
    global _cache
    pal = QGuiApplication.palette()
    if _cache and _cache[0] == pal.cacheKey():
        return _cache[1]
    dark = pal.color(QPalette.Window).lightness() < 128
    text, base = pal.color(QPalette.WindowText), pal.color(QPalette.Base)

    def mix(a: QColor, b: QColor, wa: float) -> QColor:
        return QColor(*(round(x * wa + y * (1 - wa)) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3], strict=True)))

    muted, mixed = mix(text, base, 0.62), mix(text, base, 0.18)
    c = {
        "bg": pal.color(QPalette.Window).name(),
        "panel": base.name(),
        "text": text.name(),
        "muted": muted.name(),
        "border": pal.color(QPalette.Mid).name(),
        "accent": pal.color(QPalette.Highlight).name(),
        "alt": pal.color(QPalette.AlternateBase).name(),
        "grid": mixed.name(),
        "pos": "#2ecc71" if dark else "#27ae60",  # Breeze PositiveText
        "neg": "#ed8a94" if dark else "#da4453",  # Breeze NegativeText
        "ibov": "#f67400" if not dark else "#fdbc4b",
    }
    _cache = (pal.cacheKey(), c)
    return c


def class_color(name: str) -> QColor:
    idx = _class_index.setdefault(name, len(_class_index))
    return QColor(CLASS_COLORS[idx % len(CLASS_COLORS)])


def apply(mode: str) -> None:
    """mode: 'system' | 'light' | 'dark'."""
    hints = QGuiApplication.styleHints()
    if not hasattr(hints, "setColorScheme"):  # Qt < 6.8: always follow the system
        return
    scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
    hints.setColorScheme(scheme)
