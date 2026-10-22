"""Run blocking work (keytool, apksigner, scrypt) off the UI thread."""

import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except BaseException as exc:  # reported to the UI, never swallowed
            log.error("Background task failed: %s\n%s", exc, traceback.format_exc())
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


_active = set()


def run_task(fn, on_done, on_error):
    """Run `fn()` on the thread pool; callbacks run on the UI thread."""
    task = _Task(fn)
    task.setAutoDelete(False)
    _active.add(task)

    def finish(cb, value):
        _active.discard(task)
        cb(value)

    task.signals.done.connect(lambda r: finish(on_done, r))
    task.signals.failed.connect(lambda e: finish(on_error, e))
    QThreadPool.globalInstance().start(task)
    return task
