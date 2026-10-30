"""Background workers so network calls never freeze the UI."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from ..gather import apply_valuation, gather
from ..models import Comp, Item


class GatherWorker(QObject):
    progress = Signal(str)
    item_done = Signal(object, object, object)   # item, comps, results
    finished = Signal()

    def __init__(self, items: list[tuple[Item, list[Comp]]], settings: dict):
        super().__init__()
        self.items = items
        self.settings = settings
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for n, (item, existing) in enumerate(self.items, 1):
            if self._stop:
                break
            self.progress.emit(f"[{n}/{len(self.items)}] Gathering data for {item.display_name}…")
            comps, results = gather(item, self.settings, existing, progress=self.progress.emit)
            apply_valuation(item, comps, self.settings)
            self.item_done.emit(item, comps, results)
        self.finished.emit()


class FuncWorker(QObject):
    """Run one blocking call off the UI thread."""
    done = Signal(object)
    finished = Signal()

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        finally:
            self.finished.emit()


_running: set = set()


def start_worker(parent, worker: QObject) -> QThread:
    # Parent the thread to the application so closing a dialog mid-fetch can't destroy a running thread.
    thread = QThread(QCoreApplication.instance())
    _running.add((thread, worker))
    thread.finished.connect(lambda: _running.discard((thread, worker)))
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
