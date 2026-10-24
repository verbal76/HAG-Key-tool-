import logging
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, PUBLISHER, __version__
from ..paths import default_paths
from ..redact import redact, setup_logging
from .appicon import app_icon
from .context import AppContext
from .main_window import MainWindow
from .theme import STYLESHEET, apply_palette

log = logging.getLogger(__name__)


def _excepthook(exc_type, exc, tb):
    text = redact("".join(traceback.format_exception(exc_type, exc, tb)))
    log.error("Unhandled error:\n%s", text)
    app = QApplication.instance()
    if app:
        QMessageBox.critical(None, "Unexpected error",
                             f"Something went wrong: {redact(str(exc))}\n\nDetails were written to the log file. "
                             "No passwords or keys are included in logs.")


def create_app(argv=None):
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(PUBLISHER)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(STYLESHEET)
    return app


def dispose(app) -> None:
    """Tear down widgets while Qt is still fully alive.

    Left to interpreter shutdown, PySide destroys the QApplication first and then deletes the
    remaining Python-owned windows in arbitrary order, which can crash (seen as a segfault or
    "pure virtual method called" on exit). Background tasks are awaited for the same reason.
    """
    import shiboken6
    from PySide6.QtCore import QThreadPool
    from . import clipboard

    QThreadPool.globalInstance().waitForDone()
    clipboard.shutdown()
    for w in app.topLevelWidgets():
        if shiboken6.isValid(w) and w.parent() is None:
            shiboken6.delete(w)
    app.processEvents()


def run(argv=None) -> int:
    paths = default_paths()
    try:
        setup_logging(paths.logs_dir)
    except OSError:
        pass
    sys.excepthook = _excepthook
    app = create_app(argv)
    ctx = AppContext(paths)
    win = MainWindow(ctx)
    win.open_last_profile()
    win.show()
    QTimer.singleShot(500, lambda: win.projects_page.scan_profiles(quiet=True))
    log.info("Started %s %s", APP_NAME, __version__)
    code = app.exec()
    dispose(app)
    return code


def self_test(result_path: str) -> int:
    """Start the full UI, visit every page, and write PASS/FAIL to `result_path`. Used by CI on the built exe."""
    import tempfile
    import os
    from pathlib import Path

    lines = []
    code = 1
    try:
        os.environ["HAGBSM_HOME"] = tempfile.mkdtemp(prefix="hagbsm-selftest-")
        app = create_app([sys.argv[0]])
        ctx = AppContext(default_paths())
        win = MainWindow(ctx)
        win.show()
        from ..model import Profile
        p = Profile(name="Self Test Game", android_package="com.hotatticgames.selftest")
        p.platforms["android"]["enabled"] = True
        p.stores = ["private"]
        ctx.store.save(p)
        ctx.open_profile(p)
        for row in range(win.nav.count()):
            win.nav.setCurrentRow(row)
            app.processEvents()
            if win.stack.currentIndex() != row:
                raise RuntimeError(f"navigation to page {row} failed")
        prompt_text = win.pages[5].text.toPlainText()
        if "Self Test Game" not in prompt_text:
            raise RuntimeError("prompt was not generated")
        lines.append(f"keytool: {ctx.tools.keytool}")
        lines.append(f"apksigner: {ctx.tools.apksigner_jar}")
        lines.append(f"pages: {win.nav.count()}")
        QTimer.singleShot(0, app.quit)
        app.exec()
        dispose(app)
        lines.insert(0, "PASS")
        code = 0
    except Exception:
        lines.insert(0, "FAIL")
        lines.append(traceback.format_exc())
    Path(result_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code
