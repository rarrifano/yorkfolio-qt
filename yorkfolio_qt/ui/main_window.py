from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QTabWidget, QToolBar

from .. import __version__, db, service
from . import theme
from .asset_dialog import AssetDialog
from .balanceamento import BalanceamentoTab
from .carteira import CarteiraTab
from .dados import DadosTab
from .extrato import ExtratoTab
from .ir import IRTab
from .proventos import ProventosTab
from .workers import run_async

LOGO = Path(__file__).resolve().parent.parent / "logo.svg"


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path
        self.state: dict | None = None
        self.import_results: list[dict] = []
        self._pending = 0
        self.settings = QSettings("yorkfolio", "yorkfolio-qt")
        self.setWindowTitle("YorkFolio Desktop")
        self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(1280, 860)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.carteira, self.proventos = CarteiraTab(self), ProventosTab(self)
        self.balanceamento, self.ir = BalanceamentoTab(self), IRTab(self)
        self.extrato, self.dados = ExtratoTab(self), DadosTab(self)
        self.views = [self.carteira, self.proventos, self.balanceamento, self.ir, self.extrato, self.dados]
        for view, name in zip(self.views, ("Carteira", "Proventos", "Balanceamento", "IR", "Extrato", "Dados"), strict=True):
            self.tabs.addTab(view, name)
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self.status = QLabel("")
        self.statusBar().addPermanentWidget(self.status)

        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.state and self._show_state(self.state))
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self.reload()

    # ------------------------------------------------------------ menus & toolbar (KDE HIG layout)
    def _action(self, text, slot, icon=None, shortcut=None, checkable=False) -> QAction:
        act = QAction(QIcon.fromTheme(icon) if icon else QIcon(), text, self)
        act.triggered.connect(lambda _=False: slot())
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.setCheckable(checkable)
        return act

    def _build_actions(self) -> None:
        SK = QKeySequence
        self.act_import = self._action("&Importar extratos da B3…", self.import_dialog, "document-import", SK.Open)
        self.act_quit = self._action("&Sair", self.close, "application-exit", SK.Quit)
        self.act_market = self._action("&Atualizar cotações", lambda: self.refresh_market(), "view-refresh", SK.Refresh)
        self.act_history = self._action("Rebaixar &histórico de preços", lambda: self.refresh_market(force=True), "download")
        self.act_about = self._action("&Sobre o YorkFolio Desktop", self.about, "help-about")
        self.act_about_qt = self._action("Sobre o &Qt", QApplication.aboutQt, "help-about")

        file_menu = self.menuBar().addMenu("&Arquivo")
        file_menu.addActions([self.act_import])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        view_menu = self.menuBar().addMenu("&Exibir")
        view_menu.addActions([self.act_market, self.act_history])
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu(QIcon.fromTheme("preferences-desktop-color"), "&Tema de cores")
        self.theme_group = QActionGroup(self)
        current = self.settings.value("theme", "system")
        for mode, label in (("system", "Seguir o sistema"), ("light", "Claro"), ("dark", "Escuro")):
            act = self._action(label, lambda m=mode: self.set_theme(m), checkable=True)
            act.setChecked(mode == current)
            self.theme_group.addAction(act)
            theme_menu.addAction(act)
        for i in range(self.tabs.count()):
            if i == 0:
                view_menu.addSeparator()
            act = self._action(self.tabs.tabText(i), lambda i=i: self.tabs.setCurrentIndex(i), shortcut=f"Ctrl+{i + 1}")
            view_menu.addAction(act)

        help_menu = self.menuBar().addMenu("A&juda")
        help_menu.addActions([self.act_about, self.act_about_qt])

        bar = QToolBar("Ações")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonFollowStyle)
        bar.addActions([self.act_import, self.act_market])
        self.addToolBar(bar)

    # ------------------------------------------------------------ context API used by tabs
    def message(self, text: str, error: bool = False) -> None:
        if error:
            QMessageBox.warning(self, "YorkFolio", text)
        else:
            self.statusBar().showMessage(text, 6000)

    def run(self, fn, done=None, reload: bool = False, busy: str | None = None) -> None:
        """Run fn(con) on a worker thread with its own SQLite connection."""

        def work():
            con = db.connect(self.db_path)
            try:
                return fn(con)
            finally:
                con.close()

        def finished(result):
            self._busy(-1)
            if done:
                done(result)
            if reload:
                self.reload()

        def failed(msg):
            self._busy(-1)
            self.message(msg, error=True)

        self._busy(+1, busy)
        run_async(work, finished, failed)

    def _busy(self, delta: int, text: str | None = None) -> None:
        self._pending += delta
        self.status.setText(text or "Trabalhando…" if self._pending else "")
        QApplication.setOverrideCursor(Qt.BusyCursor) if delta > 0 else QApplication.restoreOverrideCursor()

    def reload(self) -> None:
        self.run(service.state, self._show_state)

    def _show_state(self, state: dict) -> None:
        self.state = state
        for view in self.views:
            view.set_state(state)
        self.dados.show_imports(self.import_results)
        if not (state["counts"]["trades"] + state["counts"]["movements"] + state["counts"]["manual"]):
            self.tabs.setCurrentWidget(self.dados)
            self.statusBar().showMessage("Comece importando os extratos Excel da B3 (Negociação e Movimentação).")

    # ------------------------------------------------------------ actions
    def import_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Extratos da B3", "", "Excel (*.xlsx)")
        if files:
            self.import_files([Path(f) for f in files])

    def import_files(self, paths: list[Path]) -> None:
        def work(con):
            out = []
            for path in paths:
                try:
                    out.append(service.import_file(con, path.name, path.read_bytes()))
                except Exception as exc:
                    out.append({"file": path.name, "error": str(exc)})
            return out

        def done(results):
            self.import_results = results
            self.tabs.setCurrentWidget(self.dados)
            if any("error" not in r and r["inserted"] for r in results):
                self.refresh_market()

        self.run(work, done, reload=True, busy="Importando…")

    def refresh_market(self, force: bool = False) -> None:
        def done(report):
            problems = {**report["errors"], **report["warnings"]}
            n = len(report["updated"])
            if problems:
                text = "\n".join(f"{k}: {v}" for k, v in list(problems.items())[:12])
                self.message(f"{n} cotações atualizadas. Problemas:\n{text}", error=True)
            else:
                self.message(f"{n} cotações atualizadas.")

        self.run(lambda con: service.refresh_market(con, force), done, reload=True, busy="Buscando cotações e índices…")

    def edit_asset(self, code: str) -> None:
        asset = next((a for c in self.state["classes"] for a in c["assets"] if a["code"] == code), None)
        if not asset:
            return
        dlg = AssetDialog(asset, self.state["class_names"], self)
        if dlg.exec():
            fields = dlg.fields
            self.run(lambda con: db.update_asset(con, code, fields), reload=True)

    def set_theme(self, mode: str) -> None:
        self.settings.setValue("theme", mode)
        theme.apply(mode)

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)

    def about(self) -> None:
        from .. import native

        QMessageBox.about(
            self, "YorkFolio Desktop",
            f"<b>YorkFolio Desktop {__version__}</b><br>Carteira de investimentos para investidores da B3.<br>"
            f"Núcleo C++ {native.version()} · Python · Qt/PySide6<br><br>Banco de dados:<br>{self.db_path}",
        )  # fmt: skip

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".xlsx") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".xlsx")]
        if paths:
            self.import_files(paths)


