# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Regenerate the AppStream screenshots (docs/screenshots/*.png) from the synthetic demo portfolio.

Use `make screenshots`: it runs this script inside the Flatpak build (so `make flatpak` first) on the
offscreen platform with the KDE platform theme and an empty configuration. Widgets are drawn by Breeze
with the default Breeze Light colors, icons and font, as on a fresh Plasma session, whatever your own
desktop settings are. Noto Sans, Plasma's default font, is not in the runtime: the Makefile copies it
from the host into $SCREENSHOT_FONTS. No network: quotes and indexes come from the demo data.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QFontDatabase, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from yorkfolio_qt import demo  # noqa: E402
from yorkfolio_qt.app import APP_ID, LOGO  # noqa: E402
from yorkfolio_qt.ui.main_window import MainWindow  # noqa: E402

SIZE = QSize(1280, 720)  # grown in height if the tallest page needs it, so no shot shows a scroll bar
SHOTS = ("carteira", "proventos", "balanceamento", "ir")  # file names; also MainWindow attributes (tabs)


def settle(app: QApplication, win: MainWindow, ready=lambda: True, timeout: float = 60.0) -> None:
    """Process events until no background work is pending and ready() holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if win._pending == 0 and ready():
            app.processEvents()
            return
        time.sleep(0.02)
    raise TimeoutError("the window did not finish loading")


def main(out: Path) -> None:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("yorkfolio-qt")
    app.setApplicationDisplayName("YorkFolio Desktop")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(LOGO))))
    fonts = os.environ.get("SCREENSHOT_FONTS")
    for font in sorted(Path(fonts).glob("*.[ot]tf")) if fonts else ():
        QFontDatabase.addApplicationFont(str(font))
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "demo.db"
        demo.build(str(path))
        win = MainWindow(path)
        win.refresh_market = lambda force=False: None
        win.resize(SIZE)
        win.show()
        settle(app, win, lambda: win.state is not None)
        pages = [win.tabs.widget(i) for i in range(win.tabs.count())]
        need = max(p.widget().minimumSizeHint().height() for p in pages)
        missing = need - win.tabs.currentWidget().viewport().height()
        if missing > 0:
            win.resize(SIZE.width(), win.height() + missing)
            settle(app, win)
        win.balanceamento.amount.setText("5.000,00")
        win.balanceamento._plan()

        for name in SHOTS:
            win.show_view(getattr(win, name))
            settle(app, win, (lambda: win.ir.months.rowCount() > 0) if name == "ir" else (lambda: True))
            image = win.grab().toImage()
            if not image.save(str(out / f"{name}.png")):
                raise OSError(f"could not write {out / name}.png")
            print(f"{out / name}.png  {image.width()}x{image.height()}")
        win.close()
        settle(app, win)
    (out / ".ok").touch()  # flatpak-builder --run does not pass the exit status through: the Makefile checks this


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")
