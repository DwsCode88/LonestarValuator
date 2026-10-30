"""Find the exact card (printing) from TCGplayer's catalog, with pictures, so comps match the right card."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal, QObject
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..models import GAMES, Item
from ..net import make_session
from ..sources.tcgplayer import IMAGE_URL, TCGplayerSource
from .workers import FuncWorker, start_worker

THUMB = "https://tcgplayer-cdn.tcgplayer.com/product/{pid}_in_200x200.jpg"


def search_catalog(query: str, game: str, settings: dict) -> list[dict]:
    src = TCGplayerSource(settings)
    item = Item(name=query, game=game)
    return src.search(item)


class _ThumbLoader(QObject):
    loaded = Signal(int, bytes)
    finished = Signal()

    def __init__(self, pids: list[int]):
        super().__init__()
        self.pids = pids
        self.stop = False

    def run(self):
        s = make_session()
        for pid in self.pids:
            if self.stop:
                break
            try:
                r = s.get(THUMB.format(pid=pid), timeout=10)
                if r.ok:
                    self.loaded.emit(pid, r.content)
            except Exception:
                pass
        self.finished.emit()


class FindCardDialog(QDialog):
    """Returns the chosen TCGplayer product dict in .chosen"""

    def __init__(self, parent, settings: dict, query: str = "", game: str = "Pokemon"):
        super().__init__(parent)
        self.settings = settings
        self.chosen: dict | None = None
        self.rows: list[dict] = []
        self.setWindowTitle("Find card")
        self.resize(900, 620)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.game = QComboBox(); self.game.addItems(GAMES); self.game.setCurrentText(game or "Pokemon")
        self.q = QLineEdit(query); self.q.setPlaceholderText("Card name and number, e.g. Charizard ex 199")
        self.q.returnPressed.connect(self.search)
        b = QPushButton("Search"); b.clicked.connect(self.search)
        bar.addWidget(self.game); bar.addWidget(self.q, 1); bar.addWidget(b)
        v.addLayout(bar)
        self.status = QLabel("Type a name and press Enter."); self.status.setObjectName("muted")
        v.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Card", "Set", "Number / rarity", "Market"])
        self.table.setIconSize(QSize(64, 64))
        self.table.verticalHeader().setDefaultSectionSize(72)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents); hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.cellDoubleClicked.connect(lambda *_: self.accept_choice())
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this card")
        bb.accepted.connect(self.accept_choice); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._loader = None
        if query:
            self.search()

    def search(self):
        q = self.q.text().strip()
        if not q:
            return
        self.status.setText("Searching TCGplayer…")
        self.table.setRowCount(0)
        w = FuncWorker(self._safe_search, q, self.game.currentText())
        w.done.connect(self._show)
        self._worker = w
        start_worker(self, w)

    def _safe_search(self, q, game):
        try:
            return search_catalog(q, game, self.settings), ""
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"

    def _show(self, result):
        rows, err = result
        rows = [r for r in rows if r.get("productTypeName", "Cards") in ("Cards", None)] or rows
        self.rows = rows
        if err:
            self.status.setText(f"Search failed: {err}")
            return
        self.status.setText(f"{len(rows)} result(s). Double-click the exact printing." if rows else
                            "No results – try fewer words, or just the name.")
        for r in rows:
            n = self.table.rowCount(); self.table.insertRow(n)
            attrs = r.get("customAttributes") or {}
            cells = ["", r.get("productName", ""), r.get("setName", ""),
                     " · ".join(x for x in [attrs.get("number") or "", r.get("rarityName") or ""] if x),
                     f"${r['marketPrice']:,.2f}" if r.get("marketPrice") else "—"]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(val)
                if c == 4:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(n, c, it)
        if rows:
            self.table.selectRow(0)
            if self._loader:
                self._loader.stop = True
            self._loader = _ThumbLoader([int(r["productId"]) for r in rows])
            self._loader.loaded.connect(self._thumb)
            start_worker(self, self._loader)

    def _thumb(self, pid: int, data: bytes):
        for i, r in enumerate(self.rows):
            if int(r.get("productId", 0)) == pid and self.table.item(i, 0):
                pm = QPixmap(); pm.loadFromData(data)
                self.table.item(i, 0).setIcon(QIcon(pm))

    def accept_choice(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        self.chosen = self.rows[rows[0]]
        self.accept()


def apply_product(item: Item, p: dict):
    """Copy a TCGplayer product onto an item."""
    attrs = p.get("customAttributes") or {}
    name = p.get("productName", "")
    # TCGplayer names often carry the number/variant: "Charizard ex - 199/165"
    base = name.split(" - ")[0].strip()
    item.name = base or name
    item.set_name = p.get("setName", "") or item.set_name
    item.number = attrs.get("number") or item.number
    if "(" in name and ")" in name and not item.variant:
        item.variant = name[name.rfind("(") + 1:name.rfind(")")]
        item.name = item.name.split("(")[0].strip()
    item.tcg_product_id = str(int(p["productId"]))
    item.image_url = IMAGE_URL.format(pid=item.tcg_product_id)
