# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Run blocking work (SQLite, network, big computations) off the UI thread."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, _Signals()

    def run(self):
        try:
            try:
                result = self.fn()
            except Exception as exc:
                traceback.print_exc()
                self.signals.failed.emit(str(exc) or type(exc).__name__)
            else:
                self.signals.done.emit(result)
        except RuntimeError:  # the window was closed while the task ran: nobody to notify
            pass


_alive: set[_Task] = set()


def run_async(fn, on_done=None, on_error=None) -> None:
    """Call fn() in the thread pool; on_done(result) / on_error(message) run on the UI thread."""
    task = _Task(fn)
    _alive.add(task)  # keep the signal object alive until delivered
    task.setAutoDelete(False)

    def finish(callback):
        def inner(value):
            _alive.discard(task)
            if callback:
                callback(value)

        return inner

    task.signals.done.connect(finish(on_done))
    task.signals.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(task)
