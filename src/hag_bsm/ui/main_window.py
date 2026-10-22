from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QStackedWidget, QStyle, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from .appicon import app_icon
from .pages.details import DetailsPage
from .pages.platforms import PlatformsPage
from .pages.projects import ProjectsPage
from .pages.prompt import PromptPage
from .pages.secrets import SecretsPage
from .pages.settings import SettingsPage
from .pages.signing import SigningPage
from .theme import COLORS
from .widgets import button

NAV = [
    ("Projects", ProjectsPage, QStyle.SP_DirHomeIcon),
    ("Application Details", DetailsPage, QStyle.SP_FileDialogDetailedView),
    ("Platforms & Stores", PlatformsPage, QStyle.SP_ComputerIcon),
    ("Signing Identities", SigningPage, QStyle.SP_DialogApplyButton),
    ("GitHub Secrets", SecretsPage, QStyle.SP_FileDialogContentsView),
    ("Generated Prompt", PromptPage, QStyle.SP_FileIcon),
    ("Settings", SettingsPage, QStyle.SP_FileDialogInfoView),
]

LEVEL_COLORS = {"success": COLORS["success"], "warning": COLORS["warning"], "error": COLORS["error"],
                "info": COLORS["info"]}


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1240, 820)
        self.setMinimumSize(900, 600)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 10, 18, 10)
        brand = QLabel(f"<span style='color:{COLORS['accent']}; font-weight:700'>HOT ATTIC GAMES</span>"
                       f"&nbsp;&nbsp;<span style='color:{COLORS['muted']}'>Build &amp; Signing Manager</span>")
        hl.addWidget(brand)
        hl.addSpacing(24)
        self.project_label = QLabel()
        self.project_label.setObjectName("ProjectTitle")
        hl.addWidget(self.project_label)
        self.dirty_label = QLabel("● Unsaved changes")
        self.dirty_label.setObjectName("Dirty")
        hl.addWidget(self.dirty_label)
        hl.addStretch(1)
        self.save_btn = button("Save Project", "Primary", "Save the open project (Ctrl+S)", self.ctx.save_profile)
        hl.addWidget(self.save_btn)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.setFixedWidth(220)
        self.nav.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        self.pages = []
        for label, cls, icon in NAV:
            item = QListWidgetItem(self.style().standardIcon(icon), label)
            self.nav.addItem(item)
            page = cls(ctx)
            self.pages.append(page)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._navigate)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage(f"Version {__version__} — private test build")

        save = QAction(self)
        save.setShortcut(QKeySequence.Save)
        save.triggered.connect(self.ctx.save_profile)
        self.addAction(save)

        self.projects_page.openRequested.connect(lambda: self.nav.setCurrentRow(1))
        ctx.profileLoaded.connect(self._update_header)
        ctx.dirtyChanged.connect(lambda _: self._update_header())
        ctx.profileEdited.connect(self._update_header)
        ctx.message.connect(self._show_message)
        ctx.busyChanged.connect(self._busy)
        self._update_header()
        self.nav.setCurrentRow(0)

    @property
    def projects_page(self) -> ProjectsPage:
        return self.pages[0]

    def open_last_profile(self):
        pid = self.ctx.settings.get("last_profile_id")
        if pid and self.ctx.store.exists(pid):
            try:
                self.ctx.open_profile(self.ctx.store.load(pid))
            except Exception:
                pass

    def _navigate(self, row):
        page = self.pages[row]
        if page.needs_profile and not self.ctx.profile:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(0)
            self.nav.blockSignals(False)
            self.stack.setCurrentIndex(0)
            self._show_message("Open or create a project first.", "info")
            return
        self.stack.setCurrentIndex(row)
        page.on_shown()

    def _update_header(self):
        p = self.ctx.profile
        self.project_label.setText((p.name or "Untitled project") if p else "No project open")
        self.dirty_label.setVisible(bool(p) and self.ctx.dirty)
        self.save_btn.setEnabled(bool(p) and self.ctx.dirty)
        for i, page in enumerate(self.pages):
            item = self.nav.item(i)
            enabled = bool(p) or not page.needs_profile
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable if enabled else Qt.NoItemFlags)
        title = f"{p.name or 'Untitled'}{' *' if self.ctx.dirty else ''} — {APP_NAME}" if p else APP_NAME
        self.setWindowTitle(title)
        if not p and self.stack.currentIndex() not in (0, len(self.pages) - 1):
            self.nav.setCurrentRow(0)

    def _show_message(self, text, level="info"):
        color = LEVEL_COLORS.get(level, COLORS["muted"])
        self.statusBar().setStyleSheet(f"QStatusBar {{ color: {color}; }}")
        self.statusBar().showMessage(text, 12000)

    def _busy(self, busy, text):
        self.progress.setVisible(busy)
        self.busy_label.setText(text if busy else "")

    def closeEvent(self, event):
        if self.ctx.busy:
            QMessageBox.warning(self, "Operation in progress",
                                "A signing operation is still running. Please wait for it to finish before closing.")
            event.ignore()
            return
        if not self.projects_page.confirm_discard():
            event.ignore()
            return
        event.accept()
