"""Clipboard helpers.

Sensitive values are copied only on an explicit click. On Windows they are flagged so that
clipboard history and cloud clipboard skip them. If a clear delay is configured, the clipboard
is cleared afterwards — but only if it still holds the exact value we put there, so unrelated
content the user copied in the meantime is never erased.

When the application quits, a secret it copied that is still on the clipboard is always removed.
Besides being safer, this releases the clipboard's reference to our QMimeData while Qt is still
running; leaving it until process exit crashes PySide6 during teardown.
"""

from PySide6.QtCore import QCoreApplication, QMimeData, QTimer
from PySide6.QtGui import QGuiApplication

_WIN_FORMAT = 'application/x-qt-windows-mime;value="{}"'
_ZERO_DWORD = b"\x00\x00\x00\x00"

_clear_seconds = 60
_pending = None   # the sensitive text we last placed on the clipboard
_timer = None     # single app-owned timer (a pending Python-lambda singleShot crashes Qt at exit)


def set_clear_seconds(seconds: int) -> None:
    global _clear_seconds
    _clear_seconds = max(0, int(seconds))


def _ensure_timer() -> QTimer:
    global _timer
    if _timer is None:
        app = QCoreApplication.instance()
        _timer = QTimer(app)
        _timer.setSingleShot(True)
        _timer.timeout.connect(clear_pending)
        app.aboutToQuit.connect(_on_quit)
    return _timer


def copy_text(text: str, sensitive: bool = False) -> None:
    global _pending
    clipboard = QGuiApplication.clipboard()
    if not sensitive:
        clipboard.setText(text)
        return
    mime = QMimeData()
    mime.setText(text)
    mime.setData(_WIN_FORMAT.format("ExcludeClipboardContentFromMonitorProcessing"), b"")
    mime.setData(_WIN_FORMAT.format("CanIncludeInClipboardHistory"), _ZERO_DWORD)
    mime.setData(_WIN_FORMAT.format("CanUploadToCloudClipboard"), _ZERO_DWORD)
    clipboard.setMimeData(mime)
    _pending = text
    timer = _ensure_timer()
    if _clear_seconds:
        timer.start(_clear_seconds * 1000)
    else:
        timer.stop()


def clear_pending() -> None:
    """Clear the clipboard if it still holds the secret we copied."""
    global _pending
    if _pending is not None and QGuiApplication.clipboard().text() == _pending:
        QGuiApplication.clipboard().clear()
    _pending = None


def shutdown() -> None:
    if _timer is not None:
        _timer.stop()
    clear_pending()


def _on_quit() -> None:
    shutdown()
