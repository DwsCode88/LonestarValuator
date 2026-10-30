"""Main window: report list on the left, selected report on the right."""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import __app_name__, __version__, updater
from ..db import DB
from ..gather import cache_image
from ..models import PURPOSES, Item, replacement_value
from ..report_pdf import ReportPDF, money
from ..settings import Settings, data_dir
from .item_dialog import ItemDialog
from .settings_dialog import SettingsDialog
from .workers import GatherWorker, start_worker

ITEM_COLS = ["Card", "Set", "Game", "Condition / Grade", "Qty", "Value (each)", "Line total",
             "Confidence", "Sales", "Valued"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.db = DB(data_dir() / "valuator.db")
        self.rid: int | None = None
        self.items: list[Item] = []
        self.thread = None
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1400, 850)
        self._menu()
        self._build()
        self.setStatusBar(QStatusBar())
        self._load_reports()
        if self.rlist.count():
            self.rlist.setCurrentRow(0)

    # ---------- UI ----------
    def _menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        for text, slot, key in [("New report", self._new_report, QKeySequence.New),
                                ("Export PDF…", self._export_pdf, "Ctrl+P"),
                                ("Export items CSV…", self._export_csv, None),
                                ("Open data folder", lambda: QDesktopServices.openUrl(
                                    QUrl.fromLocalFile(str(data_dir()))), None),
                                ("Settings…", self._settings, "Ctrl+,"),
                                ("Exit", self.close, None)]:
            a = QAction(text, self)
            if key:
                a.setShortcut(key)
            a.triggered.connect(slot)
            fm.addAction(a)
        hm = mb.addMenu("&Help")
        a = QAction("Check for updates", self); a.triggered.connect(self._check_updates); hm.addAction(a)
        a = QAction("About", self); a.triggered.connect(lambda: QMessageBox.about(
            self, __app_name__, f"{__app_name__} {__version__}\nTCG valuation reports for "
            f"{self.settings.get('store_name', '')}.\nData: eBay, 130point, TCGplayer, PriceCharting."))
        hm.addAction(a)

    def _build(self):
        split = QSplitter(Qt.Horizontal)
        self.setCentralWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search reports / customers…")
        self.search.textChanged.connect(self._load_reports)
        self.rlist = QListWidget(); self.rlist.currentItemChanged.connect(self._select_report)
        rb = QHBoxLayout()
        for text, slot in [("New", self._new_report), ("Duplicate", self._dup_report), ("Delete", self._del_report)]:
            b = QPushButton(text); b.clicked.connect(slot); rb.addWidget(b)
        lv.addWidget(self.search); lv.addWidget(self.rlist, 1); lv.addLayout(rb)
        split.addWidget(left)

        self.right = QWidget(); rv = QVBoxLayout(self.right)
        head = QGroupBox("Report"); hf = QHBoxLayout(head)
        f1, f2 = QFormLayout(), QFormLayout()
        self.number = QLabel("—"); self.number.setStyleSheet("font-weight:700;")
        self.cust = QLineEdit(); self.email = QLineEdit(); self.phone = QLineEdit(); self.addr = QLineEdit()
        self.purpose = QComboBox(); self.purpose.addItems(PURPOSES); self.purpose.setEditable(True)
        self.status_cb = QComboBox(); self.status_cb.addItems(["Draft", "Final", "Delivered"])
        self.notes = QPlainTextEdit(); self.notes.setMaximumHeight(60)
        self.show_rv = QCheckBox("Show insurance replacement value")
        self.rv_pct = QDoubleSpinBox(); self.rv_pct.setRange(0, 200); self.rv_pct.setSuffix(" % over FMV")
        self.rv_pct.setDecimals(1); self.rv_pct.setSingleStep(5)
        rv_row = QHBoxLayout(); rv_row.addWidget(self.show_rv); rv_row.addWidget(self.rv_pct); rv_row.addStretch()
        f1.addRow("Report #", self.number); f1.addRow("Customer", self.cust); f1.addRow("Email", self.email)
        f1.addRow("Phone", self.phone); f1.addRow("Insurance", rv_row)
        self.show_rv.toggled.connect(self.rv_pct.setEnabled)
        self.show_rv.toggled.connect(self._save_header)
        self.rv_pct.valueChanged.connect(self._save_header)
        self.purpose.currentTextChanged.connect(self._purpose_changed)
        f2.addRow("Address", self.addr); f2.addRow("Purpose", self.purpose); f2.addRow("Status", self.status_cb)
        f2.addRow("Report notes", self.notes)
        hf.addLayout(f1, 1); hf.addLayout(f2, 1)
        for w in (self.cust, self.email, self.phone, self.addr):
            w.editingFinished.connect(self._save_header)
        self.purpose.currentTextChanged.connect(self._save_header)
        self.status_cb.currentTextChanged.connect(self._save_header)
        self.notes.textChanged.connect(self._save_header)
        rv.addWidget(head)

        bar = QHBoxLayout()
        self.b_add = QPushButton("+ Add card"); self.b_add.clicked.connect(self._add_item)
        b_edit = QPushButton("Edit / review comps"); b_edit.clicked.connect(self._edit_item)
        b_rm = QPushButton("Remove"); b_rm.clicked.connect(self._remove_item)
        self.b_val = QPushButton("⟳ Value selected"); self.b_val.clicked.connect(lambda: self._value(False))
        self.b_all = QPushButton("⟳ Value all"); self.b_all.clicked.connect(lambda: self._value(True))
        b_pdf = QPushButton("Export PDF"); b_pdf.setStyleSheet("font-weight:600; padding:6px 16px;")
        b_pdf.clicked.connect(self._export_pdf)
        for b in (self.b_add, b_edit, b_rm, self.b_val, self.b_all):
            bar.addWidget(b)
        bar.addStretch(); bar.addWidget(b_pdf)
        rv.addLayout(bar)

        self.table = QTableWidget(0, len(ITEM_COLS))
        self.table.setHorizontalHeaderLabels(ITEM_COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit_item())
        rv.addWidget(self.table, 1)
        self.total = QLabel(""); self.total.setAlignment(Qt.AlignRight)
        self.total.setStyleSheet("font-size:18px; font-weight:700; color:#1F3A5F; padding:6px;")
        rv.addWidget(self.total)
        split.addWidget(self.right)
        split.setSizes([300, 1100])
        self.right.setEnabled(False)

    # ---------- reports ----------
    def _load_reports(self, *_):
        keep = self.rid
        self.rlist.blockSignals(True)
        self.rlist.clear()
        for r in self.db.list_reports(self.search.text().strip()):
            li = QListWidgetItem(f"{r['number']}  ·  {r['status']}\n{r['customer_name'] or '(no customer)'}"
                                 f"  —  {r['n_items']} item(s), {money(r['total'])}")
            li.setData(Qt.UserRole, r["id"])
            self.rlist.addItem(li)
            if r["id"] == keep:
                self.rlist.setCurrentItem(li)
        self.rlist.blockSignals(False)
        cur = self.rlist.currentItem()
        if cur and cur.data(Qt.UserRole) != getattr(self, "_shown_rid", None):
            self._select_report(cur)

    def _select_report(self, cur, _prev=None):
        if not cur:
            self.rid = None
            self.right.setEnabled(False)
            return
        self.rid = cur.data(Qt.UserRole)
        self._shown_rid = self.rid
        r = self.db.get_report(self.rid)
        self._loading = True
        self.number.setText(r["number"]); self.cust.setText(r["customer_name"]); self.email.setText(r["customer_email"])
        self.phone.setText(r["customer_phone"]); self.addr.setText(r["customer_address"])
        self.purpose.setCurrentText(r["purpose"]); self.status_cb.setCurrentText(r["status"])
        self.notes.setPlainText(r["notes"])
        self.show_rv.setChecked(bool(r.get("show_replacement")))
        pct = r.get("replacement_pct")
        self.rv_pct.setValue(float(pct if pct is not None else self.settings.get("replacement_pct", 20)))
        self.rv_pct.setEnabled(self.show_rv.isChecked())
        self._loading = False
        self.right.setEnabled(True)
        self._load_items()

    def _save_header(self, *_):
        if not self.rid or getattr(self, "_loading", False):
            return
        self.db.update_report(self.rid, customer_name=self.cust.text().strip(),
                              customer_email=self.email.text().strip(), customer_phone=self.phone.text().strip(),
                              customer_address=self.addr.text().strip(), purpose=self.purpose.currentText(),
                              status=self.status_cb.currentText(), notes=self.notes.toPlainText(),
                              show_replacement=int(self.show_rv.isChecked()),
                              replacement_pct=round(self.rv_pct.value(), 1))
        self._update_total()
        cur = self.rlist.currentItem()
        if cur:
            r = next((x for x in self.db.list_reports() if x["id"] == self.rid), None)
            if r:
                cur.setText(f"{r['number']}  ·  {r['status']}\n{r['customer_name'] or '(no customer)'}"
                            f"  —  {r['n_items']} item(s), {money(r['total'])}")

    def _purpose_changed(self, text: str):
        if not getattr(self, "_loading", False) and text == "Insurance" and not self.show_rv.isChecked():
            self.show_rv.setChecked(True)

    def _new_report(self):
        self.search.clear()
        self.rid = self.db.create_report(self.settings.get("report_prefix") or "LSV")
        self._load_reports()
        self.cust.setFocus()

    def _dup_report(self):
        if self.rid:
            self.rid = self.db.duplicate_report(self.rid, self.settings.get("report_prefix") or "LSV")
            self._load_reports()

    def _del_report(self):
        if self.rid and QMessageBox.question(self, "Delete report",
                                             f"Delete report {self.number.text()} and all its items?") \
                == QMessageBox.Yes:
            self.db.delete_report(self.rid)
            self.rid = None
            self._load_reports()
            if self.rlist.count():
                self.rlist.setCurrentRow(0)
            else:
                self.right.setEnabled(False)

    # ---------- items ----------
    def _load_items(self):
        self.items = self.db.items(self.rid)
        self.table.setRowCount(0)
        total = low = high = 0.0
        for it in self.items:
            r = self.table.rowCount(); self.table.insertRow(r)
            unit = it.final_value
            vals = [it.display_name, it.set_name, it.game,
                    it.grade_label + (f" (cert {it.cert})" if it.graded and it.cert else "")
                    + (f" · {it.pop_label}" if it.pop_label else ""),
                    str(it.qty), money(unit), money(unit * it.qty if unit is not None else None),
                    "Manual" if it.value_override is not None else it.confidence,
                    str(it.n_sales), (it.valued_at or "").replace("T", " ")]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (4, 5, 6, 8):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 7 and v == "Low":
                    cell.setForeground(Qt.darkRed)
                self.table.setItem(r, c, cell)
            if unit is not None:
                total += unit * it.qty
                low += (it.value_override if it.value_override is not None else (it.low or unit)) * it.qty
                high += (it.value_override if it.value_override is not None else (it.high or unit)) * it.qty
        self._totals = (total, low, high)
        self._update_total()

    def _update_total(self):
        total, low, high = getattr(self, "_totals", (0.0, 0.0, 0.0))
        text = f"Total: {money(total)}    (range {money(low)} – {money(high)})"
        if self.show_rv.isChecked():
            text += f"    ·    Replacement: {money(replacement_value(total, self.rv_pct.value()))}"
        self.total.setText(text)

    def _selected_items(self) -> list[Item]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows]

    def _add_item(self):
        it = Item(report_id=self.rid)
        if self.items:   # default the game to the last card's game
            it.game = self.items[-1].game
        if ItemDialog(self, self.db, self.settings, it).exec():
            self._refresh()

    def _edit_item(self):
        sel = self._selected_items()
        if sel and ItemDialog(self, self.db, self.settings, sel[0]).exec():
            self._refresh()

    def _remove_item(self):
        sel = self._selected_items()
        if sel and QMessageBox.question(self, "Remove", f"Remove {len(sel)} card(s) from this report?") \
                == QMessageBox.Yes:
            for it in sel:
                self.db.delete_item(it.id)
            self._refresh()

    def _refresh(self):
        self._load_items()
        self._save_header()

    # ---------- batch valuation ----------
    def _value(self, all_items: bool):
        items = self.items if all_items else self._selected_items()
        if not items:
            return
        if self.thread is not None:
            return
        self.b_val.setEnabled(False); self.b_all.setEnabled(False)
        self.worker = GatherWorker([(it, self.db.comps(it.id)) for it in items], dict(self.settings))
        self.worker.progress.connect(lambda m: self.statusBar().showMessage(m))
        self.worker.item_done.connect(self._item_valued)
        self.worker.finished.connect(self._value_done)
        self.thread = start_worker(self, self.worker)

    def _item_valued(self, item, comps, results):
        self.db.save_item(item)
        self.db.replace_comps(item.id, comps)
        if item.report_id == self.rid:
            self._load_items()

    def _value_done(self):
        self.thread = None
        self.b_val.setEnabled(True); self.b_all.setEnabled(True)
        self.statusBar().showMessage("Valuation complete – review Low-confidence cards before exporting.", 8000)
        self._save_header()

    # ---------- export ----------
    def _export_pdf(self):
        if not self.rid:
            return
        items = self.db.items(self.rid)
        if not items:
            QMessageBox.information(self, "Export", "Add at least one card first.")
            return
        missing = [i.display_name for i in items if i.final_value is None]
        if missing and QMessageBox.question(
                self, "Unvalued cards", f"{len(missing)} card(s) have no value yet:\n" +
                "\n".join(missing[:8]) + "\n\nExport anyway?") != QMessageBox.Yes:
            return
        rep = self.db.get_report(self.rid)
        safe = "".join(ch for ch in (rep["customer_name"] or "") if ch.isalnum() or ch in " -_").strip()
        default = data_dir() / "reports" / f"{rep['number']}{(' - ' + safe) if safe else ''}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save valuation report", str(default), "PDF (*.pdf)")
        if not path:
            return
        self.statusBar().showMessage("Building PDF…")
        imgs = {i.id: cache_image(i, data_dir() / "images") for i in items}
        comps = {i.id: self.db.comps(i.id) for i in items}
        try:
            ReportPDF(self.settings, rep, items, comps, imgs, self.settings.logo()).build(Path(path))
        except PermissionError:
            QMessageBox.warning(self, "Export", "Couldn't write the file – is it open in another program?")
            return
        self.statusBar().showMessage(f"Saved {path}", 6000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _export_csv(self):
        if not self.rid:
            return
        rep = self.db.get_report(self.rid)
        path, _ = QFileDialog.getSaveFileName(self, "Export items", str(data_dir() / "reports" /
                                                                       f"{rep['number']}.csv"), "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Game", "Name", "Set", "Number", "Variant", "Language", "Condition/Grade", "Cert",
                        "Qty", "Value each", "Low", "High", "Confidence", "Sales used", "Line total"])
            for i in self.db.items(self.rid):
                v = i.final_value
                w.writerow([i.game, i.name, i.set_name, i.number, i.variant, i.language, i.grade_label, i.cert,
                            i.qty, v, i.low, i.high, i.confidence, i.n_sales, (v or 0) * i.qty])
        self.statusBar().showMessage(f"Saved {path}", 6000)

    # ---------- misc ----------
    def _settings(self):
        if SettingsDialog(self, self.settings).exec():
            self.statusBar().showMessage("Settings saved", 4000)

    def _check_updates(self):
        try:
            info = updater.check(self.settings.get("update_repo", ""))
        except Exception as e:
            QMessageBox.warning(self, "Updates", f"Couldn't check for updates:\n{e}")
            return
        if not info:
            QMessageBox.information(self, "Updates", f"You're on the latest version ({__version__}).")
            return
        if QMessageBox.question(self, "Update available",
                                f"Version {info['version']} is available.\n\n{info['notes'][:600]}\n\n"
                                "Download and restart now?") == QMessageBox.Yes:
            if updater.install(info["url"]):
                self.close()
            else:
                QDesktopServices.openUrl(QUrl(info["url"]))
