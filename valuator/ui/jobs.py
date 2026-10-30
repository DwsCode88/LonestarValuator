"""Long-running background queue: cert lookups and data gathering, one card at a time.

The worker never touches the database (SQLite connections belong to the UI thread); it gets copies
of items + comps and hands results back through signals for the UI thread to save.
"""
from __future__ import annotations

import copy
import queue

from PySide6.QtCore import QObject, Signal

from .. import certs
from ..gather import apply_valuation, cache_image, gather
from ..models import Item
from ..settings import data_dir


def apply_cert(item: Item, info: certs.CertInfo):
    for f in ("name", "set_name", "number", "year", "variant", "language", "game"):
        v = getattr(info, f)
        if v:
            setattr(item, f, v)
    if info.grade:
        item.grade = info.grade
    item.graded = True
    item.cert_desc = info.grade_desc or item.cert_desc
    if info.pop_total is not None:
        item.pop_total, item.pop_higher, item.pop_source = info.pop_total, info.pop_higher, info.pop_source


class JobQueue(QObject):
    status = Signal(int, str)                 # item_id, text
    item_done = Signal(object, object, object)  # item, comps, results
    cert_done = Signal(object, object)        # item, CertInfo
    image_ready = Signal(int, str)            # item_id, path
    idle = Signal()
    finished = Signal()

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.q: queue.Queue = queue.Queue()
        self._stop = False
        self.pending: set[int] = set()

    # called from the UI thread
    def add(self, kind: str, item: Item, comps=None):
        self.pending.add(item.id)
        self.status.emit(item.id, "Queued")
        self.q.put((kind, copy.deepcopy(item), copy.deepcopy(comps or [])))

    def image(self, item: Item):
        self.q.put(("image", copy.deepcopy(item), None))

    def stop(self):
        self._stop = True
        self.q.put(None)

    def run(self):
        while not self._stop:
            job = self.q.get()
            if job is None:
                break
            kind, item, comps = job
            try:
                if kind == "image":
                    p = cache_image(item, data_dir() / "images")
                    if p:
                        self.image_ready.emit(item.id, str(p))
                    continue
                if kind == "cert":
                    self.status.emit(item.id, f"Looking up {item.grader} cert…")
                    info = certs.lookup(item.grader, item.cert, self.settings)
                    if info.ok:
                        apply_cert(item, info)
                    self.cert_done.emit(item, info)
                    if not info.ok:
                        self.status.emit(item.id, f"✗ Cert: {info.message[:90]}")
                        self.pending.discard(item.id)
                        continue
                self.status.emit(item.id, "Gathering sales…")
                new_comps, results = gather(item, self.settings, comps,
                                            progress=lambda m, i=item.id: self.status.emit(i, m[:90]))
                apply_valuation(item, new_comps, self.settings)
                self.item_done.emit(item, new_comps, results)
                bad = [r.source for r in results if not r.ok]
                msg = f"✓ {item.n_sales} sales" + (f" · {', '.join(bad)} failed" if bad else "")
                self.status.emit(item.id, msg)
                p = cache_image(item, data_dir() / "images")
                if p:
                    self.image_ready.emit(item.id, str(p))
            except Exception as e:
                self.status.emit(item.id, f"✗ {type(e).__name__}: {str(e)[:80]}")
            finally:
                if kind != "image":
                    self.pending.discard(item.id)
                    if not self.pending:
                        self.idle.emit()
        self.finished.emit()
