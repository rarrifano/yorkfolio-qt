"""Application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, db, native
from .ui import theme
from .ui.main_window import MainWindow

APP_ID = "io.github.rarrifano.YorkFolioQt"
LOGO = Path(__file__).resolve().parent / "logo.svg"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="yorkfolio-qt", description="Desktop portfolio tracker for B3 investors")
    ap.add_argument("--db", help="path of the SQLite database (default: per-user data directory)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    try:
        native.version()
    except native.NativeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("YorkFolio Desktop")
    app.setApplicationDisplayName("YorkFolio Desktop")
    app.setDesktopFileName(APP_ID)  # matches the .desktop file / Flatpak app id (icon + taskbar grouping on Plasma)
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(LOGO))))
    theme.apply(QSettings("yorkfolio", "yorkfolio-qt").value("theme", "system"))
    window = MainWindow(Path(args.db) if args.db else db.default_db_path())
    window.show()
    return app.exec()
