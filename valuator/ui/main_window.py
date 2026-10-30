"""Main window: report list on the left; selected report with quick-add bar and live card list."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import __app_name__, __version__, browser as browser_mod, updater
from ..db import DB
from ..gather import cache_image
from ..models import GRADERS, GRADES, PURPOSES, RAW_CONDITIONS, Item, replacement_value
from ..report_pdf import ReportPDF, money
from ..settings import Settings, data_dir
from .find_card import FindCardDialog, apply_product
from .item_dialog import ItemDialog
from .jobs import JobQueue
from .settings_dialog import SettingsDialog
from .workers import FuncWorker, start_worker

ITEM_COLS = ["", "Card", "Condition / Grade", "Qty", "Value (each)", "Line total", "Confidence", "Status"]
CONF_COLORS = {"High": "#DCFCE7", "Medium": "#FEF3C7", "Low": "#FEE2E2", "Manual": "#E0E7FF"}
SIGN_INS = [("Card Ladder", "https://app.cardladder.com/login"), ("eBay", "https://signin.ebay.com/"),
            ("PSA", "https://www.psacard.com/myaccount"), ("TCGplayer", "https://www.tcgplayer.com/login"),
            ("PriceCharting", "https://www.pricecharting.com/login")]


def cached_thumb(item: Item) -> Path | None:
    """Local image if already downloaded (never hits the network)."""
    if item.image_path and Path(item.image_path).exists():
        return Path(item.image_path)
    if item.image_url:
        import hashlib
        p = data_dir() / "images" / f"img_{hashlib.md5(item.image_url.encode()).hexdigest()[:16]}.jpg"
        if p.exists() and p.stat().st_size:
            return p
    return None


class MainWindow(QMainWindow):
    attention = Signal(str)
    attention_done = Signal()

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.db = DB(data_dir() / "valuator.db")
        self.rid: int | None = None
        self.items: list[Item] = []
        self.row_status: dict[int, str] = {}
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1440, 880)
        self._menu()
        self._build()
        self.setStatusBar(QStatusBar())
        self._start_jobs()
        self._hook_browser()
        self._load_reports()
        if self.rlist.count():
            self.rlist.setCurrentRow(0)

    # ---------- background ----------
    def _start_jobs(self):
        self.jobs = JobQueue(dict(self.settings))
        self.jobs.status.connect(self._row_status)
        self.jobs.item_done.connect(self._item_valued)
        self.jobs.cert_done.connect(self._cert_done)
        self.jobs.image_ready.connect(self._image_ready)
        self.jobs.idle.connect(self._jobs_idle)
        self.job_thread = QThread(self)
        self.jobs.moveToThread(self.job_thread)
        self.job_thread.started.connect(self.jobs.run)
        self.job_thread.start()

    def _jobs_idle(self):
        self.statusBar().showMessage("All cards done – review any Low confidence cards before exporting.", 8000)

    def _hook_browser(self):
        self.attention.connect(self._show_banner)
        self.attention_done.connect(self.banner.hide)
        svc = browser_mod.service(self.settings)
        if svc is not None:
            svc.on_attention = self.attention.emit
            svc.on_attention_done = self.attention_done.emit

    def closeEvent(self, e):
        self.jobs.stop()
        self.job_thread.quit()
        self.job_thread.wait(2000)
        browser_mod.shutdown()
        super().closeEvent(e)

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
        bm = mb.addMenu("&Chrome")
        a = QAction("Show Chrome window", self); a.triggered.connect(lambda: self._chrome_show(None)); bm.addAction(a)
        a = QAction("Hide Chrome window", self); a.triggered.connect(self._chrome_hide); bm.addAction(a)
        bm.addSeparator()
        sm = bm.addMenu("Sign in to…")
        for name, url in SIGN_INS:
            sm.addAction(name, lambda u=url: self._chrome_show(u))
        bm.addSeparator()
        a = QAction("Test Chrome connection", self); a.triggered.connect(self._chrome_test); bm.addAction(a)
        hm = mb.addMenu("&Help")
        a = QAction("Check for updates", self); a.triggered.connect(self._check_updates); hm.addAction(a)
        a = QAction("About", self); a.triggered.connect(lambda: QMessageBox.about(
            self, __app_name__, f"{__app_name__} {__version__}\nTCG valuation reports for "
            f"{self.settings.get('store_name', '')}.\nData: eBay, 130point, TCGplayer, PriceCharting, "
            "Card Ladder (capture), PSA/CGC."))
        hm.addAction(a)

    def _build(self):
        split = QSplitter(Qt.Horizontal)
        self.setCentralWidget(split)

        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(10, 10, 4, 10)
        title = QLabel("Reports"); title.setObjectName("h1")
        self.search = QLineEdit(); self.search.setPlaceholderText("Search reports / customers…")
        self.search.textChanged.connect(self._load_reports)
        self.rlist = QListWidget(); self.rlist.currentItemChanged.connect(self._select_report)
        self.rlist.setObjectName("reports")
        b_new = QPushButton("+  New report"); b_new.setObjectName("primary"); b_new.clicked.connect(self._new_report)
        rb = QHBoxLayout()
        for text, slot in [("Duplicate", self._dup_report), ("Delete", self._del_report)]:
            b = QPushButton(text); b.clicked.connect(slot); rb.addWidget(b)
        lv.addWidget(title); lv.addWidget(b_new); lv.addWidget(self.search); lv.addWidget(self.rlist, 1)
        lv.addLayout(rb)
        split.addWidget(left)

        self.right = QWidget(); rv = QVBoxLayout(self.right); rv.setContentsMargins(4, 10, 10, 6)
        self.banner = QLabel(""); self.banner.setObjectName("banner"); self.banner.setWordWrap(True)
        self.banner.hide()
        rv.addWidget(self.banner)

        head = QGroupBox("Customer and report"); hf = QHBoxLayout(head)
        f1, f2 = QFormLayout(), QFormLayout()
        self.number = QLabel("—"); self.number.setObjectName("strong")
        self.cust = QLineEdit(); self.email = QLineEdit(); self.phone = QLineEdit(); self.addr = QLineEdit()
        self.purpose = QComboBox(); self.purpose.addItems(PURPOSES); self.purpose.setEditable(True)
        self.status_cb = QComboBox(); self.status_cb.addItems(["Draft", "Final", "Delivered"])
        self.notes = QPlainTextEdit(); self.notes.setMaximumHeight(54)
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

        # quick add
        qa = QFrame(); qa.setObjectName("quickadd"); ql = QHBoxLayout(qa); ql.setContentsMargins(10, 8, 10, 8)
        self.qa_text = QLineEdit()
        self.qa_text.setPlaceholderText("Scan or type a cert #, or type a card name — then Enter")
        self.qa_text.returnPressed.connect(self._quick_add)
        self.qa_type = QComboBox(); self.qa_type.addItems(["Raw"] + GRADERS)
        self.qa_cond = QComboBox()
        self.qa_qty = QSpinBox(); self.qa_qty.setRange(1, 9999); self.qa_qty.setPrefix("× ")
        self.qa_type.currentTextChanged.connect(self._qa_type_changed)
        self._qa_type_changed("Raw")
        b_qa = QPushButton("Add && value"); b_qa.setObjectName("primary"); b_qa.clicked.connect(self._quick_add)
        lab = QLabel("Add card"); lab.setObjectName("strong")
        ql.addWidget(lab); ql.addWidget(self.qa_text, 1); ql.addWidget(self.qa_type); ql.addWidget(self.qa_cond)
        ql.addWidget(self.qa_qty); ql.addWidget(b_qa)
        rv.addWidget(qa)

        bar = QHBoxLayout()
        b_add = QPushButton("+ Add manually…"); b_add.clicked.connect(self._add_item)
        b_edit = QPushButton("Review comps…"); b_edit.clicked.connect(self._edit_item)
        b_rm = QPushButton("Remove"); b_rm.clicked.connect(self._remove_item)
        self.b_val = QPushButton("⟳ Re-value selected"); self.b_val.clicked.connect(lambda: self._value(False))
        self.b_all = QPushButton("⟳ Re-value all"); self.b_all.clicked.connect(lambda: self._value(True))
        b_pdf = QPushButton("Export PDF"); b_pdf.setObjectName("primary"); b_pdf.clicked.connect(self._export_pdf)
        for b in (b_add, b_edit, b_rm, self.b_val, self.b_all):
            bar.addWidget(b)
        bar.addStretch(); bar.addWidget(b_pdf)
        rv.addLayout(bar)

        self.table = QTableWidget(0, len(ITEM_COLS))
        self.table.setHorizontalHeaderLabels(ITEM_COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setIconSize(QSize(40, 56))
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(7, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 52); self.table.setColumnWidth(7, 260)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit_item())
        rv.addWidget(self.table, 1)
        self.total = QLabel(""); self.total.setAlignment(Qt.AlignRight); self.total.setObjectName("total")
        rv.addWidget(self.total)
        split.addWidget(self.right)
        split.setSizes([290, 1150])
        self.right.setEnabled(False)

    def _show_banner(self, text: str):
        self.banner.setText(f"⚠  {text}")
        self.banner.show()

    # ---------- reports ----------
    def _report_label(self, r: dict) -> str:
        return (f"{r['number']}  ·  {r['status']}\n{r['customer_name'] or '(no customer)'}"
                f"  —  {r['n_items']} card(s), {money(r['total'])}")

    def _load_reports(self, *_):
        keep = self.rid
        self.rlist.blockSignals(True)
        self.rlist.clear()
        for r in self.db.list_reports(self.search.text().strip()):
            li = QListWidgetItem(self._report_label(r))
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
                cur.setText(self._report_label(r))

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
                                             f"Delete report {self.number.text()} and all its cards?") \
                == QMessageBox.Yes:
            self.db.delete_report(self.rid)
            self.rid = None
            self._load_reports()
            if self.rlist.count():
                self.rlist.setCurrentRow(0)
            else:
                self.right.setEnabled(False)

    # ---------- quick add ----------
    def _qa_type_changed(self, t: str):
        self.qa_cond.clear()
        self.qa_cond.addItems(RAW_CONDITIONS if t == "Raw" else GRADES)
        self.qa_cond.setCurrentIndex(0)

    def _quick_add(self):
        if not self.rid:
            return
        text = self.qa_text.text().strip()
        if not text:
            self.qa_text.setFocus()
            return
        kind = self.qa_type.currentText()
        last_game = self.items[-1].game if self.items else "Pokemon"
        digits = re.sub(r"\D", "", text)
        if digits and len(digits) >= 6 and len(digits) >= len(text.replace(" ", "")) - 1:
            grader = kind if kind != "Raw" else "PSA"
            it = Item(report_id=self.rid, game=last_game, graded=True, grader=grader, cert=digits,
                      grade=self.qa_cond.currentText() if kind != "Raw" else "10",
                      name=f"{grader} cert {digits}", qty=self.qa_qty.value())
            self.db.save_item(it)
            self._load_items()
            self.jobs.add("cert", it)
        else:
            dlg = FindCardDialog(self, dict(self.settings), text, last_game)
            if not dlg.exec() or not dlg.chosen:
                return
            it = Item(report_id=self.rid, game=dlg.game.currentText(), qty=self.qa_qty.value())
            apply_product(it, dlg.chosen)
            if kind == "Raw":
                it.condition = self.qa_cond.currentText()
            else:
                it.graded, it.grader, it.grade = True, kind, self.qa_cond.currentText()
            self.db.save_item(it)
            self._load_items()
            self.jobs.add("gather", it)
        self.qa_text.clear()
        self.qa_qty.setValue(1)
        self.qa_text.setFocus()
        self._save_header()

    # ---------- items ----------
    def _load_items(self):
        keep = {i.row() for i in self.table.selectedIndexes()}
        self.items = self.db.items(self.rid)
        self.table.setRowCount(0)
        total = low = high = 0.0
        for it in self.items:
            r = self.table.rowCount(); self.table.insertRow(r)
            unit = it.final_value
            conf = "Manual" if it.value_override is not None else (it.confidence or "")
            sub = " · ".join(x for x in [it.set_name, it.game, it.year] if x)
            cond = it.grade_label + (f"\ncert {it.cert}" if it.graded and it.cert else "") + \
                (f"\n{it.pop_label}" if it.pop_label else "")
            vals = ["", f"{it.display_name}\n{sub}", cond, str(it.qty), money(unit),
                    money(unit * it.qty if unit is not None else None), conf,
                    self.row_status.get(it.id) or (f"{it.n_sales} sales · {it.valued_at.replace('T', ' ')}"
                                                   if it.valued_at else "Not valued yet")]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (3, 4, 5):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 6 and conf in CONF_COLORS:
                    cell.setBackground(QColor(CONF_COLORS[conf]))
                    cell.setTextAlignment(Qt.AlignCenter)
                if c == 7 and v.startswith("✗"):
                    cell.setForeground(QColor("#B91C1C"))
                self.table.setItem(r, c, cell)
            p = cached_thumb(it)
            if p:
                self.table.item(r, 0).setIcon(QIcon(QPixmap(str(p))))
            elif it.image_url:
                self.jobs.image(it)
            if unit is not None:
                total += unit * it.qty
                low += (it.value_override if it.value_override is not None else (it.low or unit)) * it.qty
                high += (it.value_override if it.value_override is not None else (it.high or unit)) * it.qty
        for row in keep:
            if row < self.table.rowCount():
                self.table.selectRow(row)
        self._totals = (total, low, high)
        self._update_total()

    def _update_total(self):
        total, low, high = getattr(self, "_totals", (0.0, 0.0, 0.0))
        text = f"Total {money(total)}   ·   range {money(low)} – {money(high)}"
        if self.show_rv.isChecked():
            text += f"   ·   Replacement {money(replacement_value(total, self.rv_pct.value()))}"
        self.total.setText(text)

    def _row_for(self, item_id: int) -> int:
        return next((i for i, it in enumerate(self.items) if it.id == item_id), -1)

    def _row_status(self, item_id: int, text: str):
        self.row_status[item_id] = text
        r = self._row_for(item_id)
        if r >= 0 and self.table.item(r, 7):
            self.table.item(r, 7).setText(text)
            self.table.item(r, 7).setForeground(QColor("#B91C1C") if text.startswith("✗") else QColor("#111827"))
        self.statusBar().showMessage(text, 4000)

    def _image_ready(self, item_id: int, path: str):
        r = self._row_for(item_id)
        if r >= 0 and self.table.item(r, 0):
            self.table.item(r, 0).setIcon(QIcon(QPixmap(path)))

    def _cert_done(self, item, info):
        cur = self.db.get_item(item.id)
        if cur is None:
            return
        if info.ok:
            item.qty = cur.qty
            self.db.save_item(item)
            if item.report_id == self.rid:
                self._load_items()

    def _selected_items(self) -> list[Item]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows]

    def _add_item(self):
        it = Item(report_id=self.rid)
        if self.items:
            it.game = self.items[-1].game
        if ItemDialog(self, self.db, self.settings, it).exec():
            self.row_status.pop(it.id, None)
            self._refresh()

    def _edit_item(self):
        sel = self._selected_items()
        if not sel:
            return
        if sel[0].id in self.jobs.pending:
            QMessageBox.information(self, "Busy", "That card is still being valued – try again in a moment.")
            return
        if ItemDialog(self, self.db, self.settings, sel[0]).exec():
            self.row_status.pop(sel[0].id, None)
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
        for it in items:
            if it.id in self.jobs.pending:
                continue
            if it.graded and it.cert and it.name.startswith(f"{it.grader} cert"):
                self.jobs.add("cert", it)
            else:
                self.jobs.add("gather", it, self.db.comps(it.id))

    def _item_valued(self, item, comps, results):
        cur = self.db.get_item(item.id)
        if cur is None:       # removed while it was being valued
            return
        item.qty, item.notes = cur.qty, cur.notes
        item.value_override, item.override_note = cur.value_override, cur.override_note
        self.db.save_item(item)
        self.db.replace_comps(item.id, comps)
        if item.report_id == self.rid:
            self._load_items()
            self._save_header()

    # ---------- Chrome ----------
    def _chrome_call(self, fn, done_msg: str = ""):
        svc = browser_mod.service(self.settings)
        if svc is None:
            QMessageBox.warning(self, "Chrome", "Chrome mode is off – turn it on in Settings → Browser.")
            return
        self.statusBar().showMessage("Starting Chrome…")

        def job():
            try:
                fn(svc)
                return ""
            except Exception as e:
                return str(e)
        self._chrome_done_msg = done_msg
        w = FuncWorker(job)
        w.done.connect(self._chrome_finished)
        self._chrome_worker = w
        start_worker(self, w)

    def _chrome_finished(self, err):
        if err:
            QMessageBox.warning(self, "Chrome", err)
        else:
            self.statusBar().showMessage(self._chrome_done_msg, 6000)

    def _chrome_show(self, url):
        self._chrome_call(lambda s: s.show(url), "Chrome is open – sign in, then come back here. "
                          "Your sign-in is remembered.")

    def _chrome_hide(self):
        self._chrome_call(lambda s: s.hide(), "Chrome hidden")

    def _chrome_test(self):
        def t(s):
            s.ensure_started()
            s.get_html("https://www.ebay.com/", site="eBay")
        self._chrome_call(t, "✓ Chrome is working")

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
                        "Population", "Qty", "Value each", "Low", "High", "Confidence", "Sales used", "Line total"])
            for i in self.db.items(self.rid):
                v = i.final_value
                w.writerow([i.game, i.name, i.set_name, i.number, i.variant, i.language, i.grade_label, i.cert,
                            i.pop_label, i.qty, v, i.low, i.high, i.confidence, i.n_sales, (v or 0) * i.qty])
        self.statusBar().showMessage(f"Saved {path}", 6000)

    # ---------- misc ----------
    def _settings(self):
        if SettingsDialog(self, self.settings).exec():
            self.jobs.settings = dict(self.settings)
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
