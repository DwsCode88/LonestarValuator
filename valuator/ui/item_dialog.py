"""Add / edit a card, review gathered comps, and set the value."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import certs, engine, history
from ..gather import apply_valuation, cache_image, comps_from_csv
from ..models import GAMES, GRADERS, GRADES, RAW_CONDITIONS, Comp, Item
from ..report_pdf import money
from ..settings import data_dir
from .chart import PriceChart
from .workers import FuncWorker, GatherWorker, start_worker

COLS = ["Use", "Date", "Source", "Type", "Title", "Condition", "Price", "Note"]


class ManualCompDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add comparable sale")
        f = QFormLayout(self)
        self.source = QComboBox(); self.source.setEditable(True)
        self.source.addItems(["Card Ladder", "In-store sale", "Facebook", "Card show", "Goldin",
                              "Heritage", "PWCC / Fanatics Collect", "Whatnot", "Other"])
        self.price = QDoubleSpinBox(); self.price.setMaximum(10_000_000); self.price.setPrefix("$")
        self.price.setDecimals(2)
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True)
        self.title = QLineEdit(); self.url = QLineEdit()
        self.kind = QComboBox(); self.kind.addItems(["sale", "guide"])
        f.addRow("Source", self.source); f.addRow("Price", self.price); f.addRow("Date", self.date)
        f.addRow("Title / description", self.title); f.addRow("Link", self.url); f.addRow("Type", self.kind)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)

    def comp(self) -> Comp:
        q = self.date.date()
        return Comp(source=self.source.currentText(), price=round(self.price.value(), 2),
                    kind=self.kind.currentText(), title=self.title.text(),
                    sale_date=date(q.year(), q.month(), q.day()), url=self.url.text(),
                    manual=True, note="Manual entry")


class ItemDialog(QDialog):
    def __init__(self, parent, db, settings, item: Item):
        super().__init__(parent)
        self.db, self.settings, self.item = db, settings, item
        self.comps: list[Comp] = db.comps(item.id) if item.id else []
        self.thread = None
        self.setWindowTitle("Card valuation")
        self.resize(1250, 800)
        self._build()
        self._load()
        self._refresh_comps()

    # ---------- layout ----------
    def _build(self):
        root = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # left: card details
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 6, 0)
        self.img = QLabel("No image"); self.img.setAlignment(Qt.AlignCenter)
        self.img.setFixedSize(170, 236); self.img.setStyleSheet("border:1px solid #ccd; background:#f6f7f9;")
        ib = QHBoxLayout()
        b_photo = QPushButton("Use my photo…"); b_photo.clicked.connect(self._pick_photo)
        b_clear = QPushButton("Clear photo"); b_clear.clicked.connect(self._clear_photo)
        ib.addWidget(b_photo); ib.addWidget(b_clear)
        lv.addWidget(self.img, 0, Qt.AlignHCenter); lv.addLayout(ib)

        g = QGroupBox("Card"); f = QFormLayout(g)
        self.game = QComboBox(); self.game.addItems(GAMES); self.game.setEditable(True)
        self.name = QLineEdit(); self.name.setPlaceholderText("e.g. Charizard ex")
        self.set_name = QLineEdit(); self.number = QLineEdit(); self.number.setPlaceholderText("e.g. 199/165 or OP05-119")
        self.variant = QComboBox(); self.variant.setEditable(True)
        self.variant.addItems(["", "Holofoil", "Reverse Holofoil", "1st Edition", "Unlimited", "Shadowless",
                               "Foil", "Alt Art", "Manga Rare", "Parallel", "Serialized", "Promo"])
        self.language = QComboBox(); self.language.setEditable(True)
        self.language.addItems(["English", "Japanese", "Korean", "Chinese", "German", "French", "Italian", "Spanish"])
        self.qty = QSpinBox(); self.qty.setRange(1, 9999)
        self.graded = QCheckBox("Graded (slab)")
        self.condition = QComboBox(); self.condition.addItems(RAW_CONDITIONS)
        self.grader = QComboBox(); self.grader.addItems(GRADERS)
        self.grade = QComboBox(); self.grade.addItems(GRADES)
        self.cert = QLineEdit(); self.cert.setPlaceholderText("PSA / CGC cert #")
        self.b_cert = QPushButton("Look up"); self.b_cert.clicked.connect(self._lookup_cert)
        self.cert.returnPressed.connect(self._lookup_cert)
        cert_row = QHBoxLayout(); cert_row.setContentsMargins(0, 0, 0, 0)
        self.b_cert_page = QPushButton("↗"); self.b_cert_page.setToolTip("Open the grader's cert page / pop report")
        self.b_cert_page.setFixedWidth(30); self.b_cert_page.clicked.connect(self._open_cert_page)
        cert_row.addWidget(self.cert, 1); cert_row.addWidget(self.b_cert); cert_row.addWidget(self.b_cert_page)
        self.year = QLineEdit(); self.year.setPlaceholderText("e.g. 1999")
        self.pop_total = QSpinBox(); self.pop_total.setRange(-1, 10_000_000); self.pop_total.setSpecialValueText("—")
        self.pop_higher = QSpinBox(); self.pop_higher.setRange(-1, 10_000_000); self.pop_higher.setSpecialValueText("—")
        pop_row = QHBoxLayout(); pop_row.setContentsMargins(0, 0, 0, 0)
        pop_row.addWidget(QLabel("at grade")); pop_row.addWidget(self.pop_total, 1)
        pop_row.addWidget(QLabel("higher")); pop_row.addWidget(self.pop_higher, 1)
        self.pop_note = QLabel(""); self.pop_note.setStyleSheet("color:#667; font-size:11px;")
        self.tcg_id = QLineEdit(); self.tcg_id.setPlaceholderText("optional – forces exact product")
        self.pc_id = QLineEdit(); self.pc_id.setPlaceholderText("optional")
        f.addRow("", self.graded)
        f.addRow("Grader", self.grader); f.addRow("Cert #", cert_row)
        for lab, w in [("Game", self.game), ("Card name", self.name), ("Year", self.year), ("Set", self.set_name),
                       ("Number", self.number), ("Variant", self.variant), ("Language", self.language),
                       ("Quantity", self.qty), ("Condition", self.condition), ("Grade", self.grade)]:
            f.addRow(lab, w)
        f.addRow("Population", pop_row); f.addRow("", self.pop_note)
        f.addRow("TCGplayer ID", self.tcg_id); f.addRow("PriceCharting ID", self.pc_id)
        self.pop_total.valueChanged.connect(self._pop_edited)
        self.pop_higher.valueChanged.connect(self._pop_edited)
        self.graded.toggled.connect(self._toggle_graded)
        lv.addWidget(g)
        self.notes = QPlainTextEdit(); self.notes.setPlaceholderText("Notes shown on report (centering, print lines…)")
        self.notes.setMaximumHeight(70)
        lv.addWidget(self.notes)
        lv.addStretch()
        split.addWidget(left)

        # right: comps + value
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(6, 0, 0, 0)
        bar = QHBoxLayout()
        self.b_fetch = QPushButton("⟳  Gather sales data"); self.b_fetch.setDefault(False)
        self.b_fetch.setStyleSheet("font-weight:600; padding:6px 14px;")
        self.b_fetch.clicked.connect(self._fetch)
        b_add = QPushButton("+ Manual comp"); b_add.clicked.connect(self._add_manual)
        b_csv = QPushButton("Import CSV…"); b_csv.clicked.connect(self._import_csv)
        b_del = QPushButton("Delete selected"); b_del.clicked.connect(self._delete_comps)
        b_open = QPushButton("Open link"); b_open.clicked.connect(self._open_link)
        for b in (self.b_fetch, b_add, b_csv, b_del, b_open):
            bar.addWidget(b)
        bar.addStretch()
        rv.addLayout(bar)
        self.status = QLabel(""); self.status.setWordWrap(True); self.status.setStyleSheet("color:#556;")
        rv.addWidget(self.status)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._toggle_use)
        self.table.cellDoubleClicked.connect(lambda r, c: self._open_link())
        rv.addWidget(self.table, 1)
        self.chart = PriceChart(); self.chart.setFixedHeight(190)
        rv.addWidget(self.chart)

        val = QGroupBox("Valuation"); vg = QGridLayout(val)
        self.l_fmv = QLabel("—"); self.l_fmv.setStyleSheet("font-size:26px; font-weight:700; color:#1F3A5F;")
        self.l_range = QLabel(""); self.l_conf = QLabel(""); self.l_method = QLabel("")
        self.l_method.setWordWrap(True); self.l_src = QLabel(""); self.l_src.setWordWrap(True)
        vg.addWidget(QLabel("Fair market value (each)"), 0, 0); vg.addWidget(self.l_fmv, 1, 0, 2, 1)
        vg.addWidget(self.l_range, 0, 1); vg.addWidget(self.l_conf, 1, 1); vg.addWidget(self.l_src, 2, 1)
        vg.addWidget(self.l_method, 3, 0, 1, 2)
        self.use_override = QCheckBox("Override value")
        self.override = QDoubleSpinBox(); self.override.setMaximum(10_000_000); self.override.setPrefix("$")
        self.override_note = QLineEdit(); self.override_note.setPlaceholderText("Reason shown on report")
        ov = QHBoxLayout(); ov.addWidget(self.use_override); ov.addWidget(self.override)
        ov.addWidget(self.override_note, 1)
        vg.addLayout(ov, 4, 0, 1, 2)
        self.use_override.toggled.connect(self.override.setEnabled)
        self.use_override.toggled.connect(self.override_note.setEnabled)
        self.use_override.toggled.connect(lambda *_: self._refresh_chart())
        self.override.editingFinished.connect(self._refresh_chart)
        rv.addWidget(val)
        split.addWidget(right)
        split.setSizes([360, 890])

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ---------- data <-> widgets ----------
    def _load(self):
        it = self.item
        self.game.setCurrentText(it.game); self.name.setText(it.name); self.set_name.setText(it.set_name)
        self.number.setText(it.number); self.variant.setCurrentText(it.variant)
        self.language.setCurrentText(it.language or "English"); self.qty.setValue(it.qty or 1)
        self.graded.setChecked(it.graded); self.condition.setCurrentText(it.condition or "Near Mint")
        self.grader.setCurrentText(it.grader or "PSA"); self.grade.setCurrentText(it.grade or "10")
        self.cert.setText(it.cert); self.tcg_id.setText(it.tcg_product_id); self.pc_id.setText(it.pc_product_id)
        self.notes.setPlainText(it.notes)
        self.year.setText(it.year)
        self._pop_source = it.pop_source
        self._setting_pop = True
        self.pop_total.setValue(it.pop_total if it.pop_total is not None else -1)
        self.pop_higher.setValue(it.pop_higher if it.pop_higher is not None else -1)
        self._setting_pop = False
        self.pop_note.setText(it.pop_source)
        self._cert_desc = it.cert_desc
        self.use_override.setChecked(it.value_override is not None)
        self.override.setValue(it.value_override or 0); self.override_note.setText(it.override_note)
        self.override.setEnabled(it.value_override is not None)
        self.override_note.setEnabled(it.value_override is not None)
        self._toggle_graded(it.graded)
        self._remember_key()
        self._show_image()

    def _remember_key(self):
        it = self.item
        self._loaded_key = (it.game, it.name.lower(), it.number.lower(), it.set_name.lower(), it.variant.lower())
        self._loaded_ids = (it.tcg_product_id, it.pc_product_id)

    def _read(self) -> Item:
        it = self.item
        it.game = self.game.currentText(); it.name = self.name.text().strip()
        it.set_name = self.set_name.text().strip(); it.number = self.number.text().strip()
        it.variant = self.variant.currentText().strip(); it.language = self.language.currentText().strip()
        it.qty = self.qty.value(); it.graded = self.graded.isChecked()
        it.condition = self.condition.currentText(); it.grader = self.grader.currentText()
        it.grade = self.grade.currentText(); it.cert = self.cert.text().strip()
        new_tcg, new_pc = self.tcg_id.text().strip(), self.pc_id.text().strip()
        it.tcg_product_id, it.pc_product_id = new_tcg, new_pc
        it.notes = self.notes.toPlainText().strip()
        it.year = self.year.text().strip()
        it.pop_total = self.pop_total.value() if self.pop_total.value() >= 0 else None
        it.pop_higher = self.pop_higher.value() if self.pop_higher.value() >= 0 else None
        it.pop_source = self._pop_source if it.pop_total is not None else ""
        it.cert_desc = self._cert_desc
        it.value_override = round(self.override.value(), 2) if self.use_override.isChecked() else None
        it.override_note = self.override_note.text().strip()
        return it

    def _toggle_graded(self, on: bool):
        self.condition.setEnabled(not on)
        for w in (self.grade, self.pop_total, self.pop_higher):
            w.setEnabled(on)

    def _pop_edited(self, *_):
        if not getattr(self, "_setting_pop", False):
            self._pop_source = f"Entered manually {date.today():%m/%d/%Y}" if self.pop_total.value() >= 0 else ""
            self.pop_note.setText(self._pop_source)

    # ---------- cert lookup ----------
    def _lookup_cert(self):
        if not self.graded.isChecked():
            self.graded.setChecked(True)
        grader, cert = self.grader.currentText(), self.cert.text().strip()
        if not cert:
            self.status.setText("Enter a cert number first.")
            return
        self.b_cert.setEnabled(False)
        self.status.setText(f"Looking up {grader} cert {cert}…")
        self._cert_worker = FuncWorker(certs.lookup, grader, cert, dict(self.settings))
        self._cert_worker.done.connect(self._cert_found)
        self._cert_worker.finished.connect(lambda: self.b_cert.setEnabled(True))
        start_worker(self, self._cert_worker)

    def _open_cert_page(self):
        url = certs.cert_page_url(self.grader.currentText(), self.cert.text())
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _cert_found(self, info: certs.CertInfo):
        if not info.ok:
            self.status.setText(f"✗ Cert lookup: {info.message}\nClick ↗ to open the cert page and type the details in.")
            return
        for widget, val in ((self.name, info.name), (self.set_name, info.set_name), (self.number, info.number),
                            (self.year, info.year)):
            if val:
                widget.setText(val)
        if info.variant:
            self.variant.setCurrentText(info.variant)
        if info.language:
            self.language.setCurrentText(info.language)
        if info.game:
            self.game.setCurrentText(info.game)
        if info.grade:
            if self.grade.findText(info.grade) < 0:
                self.grade.addItem(info.grade)
            self.grade.setCurrentText(info.grade)
        self._cert_desc = info.grade_desc
        if info.pop_total is not None:
            self._setting_pop = True
            self.pop_total.setValue(info.pop_total)
            self.pop_higher.setValue(info.pop_higher if info.pop_higher is not None else -1)
            self._setting_pop = False
            self._pop_source = info.pop_source
            self.pop_note.setText(info.pop_source)
        self.status.setText(f"✓ {info.message}\nCheck the card details, then Gather sales data.")

    def _show_image(self):
        p = cache_image(self.item, data_dir() / "images")
        if p:
            pm = QPixmap(str(p))
            if not pm.isNull():
                self.img.setPixmap(pm.scaled(self.img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.img.setPixmap(QPixmap()); self.img.setText("No image")

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Card photo", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.item.image_path = path
            self._show_image()

    def _clear_photo(self):
        self.item.image_path = ""
        self._show_image()

    # ---------- comps table ----------
    def _refresh_comps(self):
        v = apply_valuation(self.item, self.comps, self.settings)
        used_ids = {id(c) for c in v.used}
        outlier_ids = {id(c) for c in v.excluded_outliers}
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        order = sorted(self.comps, key=lambda c: (c.kind != "guide", -(c.sale_date.toordinal() if c.sale_date else 0)))
        self._row_comps = order
        for c in order:
            r = self.table.rowCount(); self.table.insertRow(r)
            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if c.included else Qt.Unchecked)
            self.table.setItem(r, 0, chk)
            note = c.note
            if id(c) in outlier_ids:
                note = ("Outlier – not used. " + note).strip()
            elif c.included and c.kind == "sale" and id(c) not in used_ids:
                note = ("Not used (older than lookback or duplicate). " + note).strip()
            vals = [c.sale_date.strftime("%Y-%m-%d") if c.sale_date else "", c.source,
                    "Guide" if c.kind == "guide" else "Sale", c.title, c.condition, money(c.price), note]
            for i, val in enumerate(vals, 1):
                cell = QTableWidgetItem(val)
                if i == 6:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not c.included or id(c) in outlier_ids:
                    cell.setForeground(Qt.gray)
                cell.setToolTip(c.url or val)
                self.table.setItem(r, i, cell)
        self.table.blockSignals(False)
        self._show_valuation(v)
        final = round(self.override.value(), 2) if self.use_override.isChecked() else v.fmv
        self.chart.set_data(history.build(self.comps, self.settings), final)

    def _refresh_chart(self):
        if hasattr(self, "chart"):
            final = round(self.override.value(), 2) if self.use_override.isChecked() else self.item.fmv
            self.chart.set_data(history.build(self.comps, self.settings), final)

    def _show_valuation(self, v: engine.Valuation):
        self.l_fmv.setText(money(v.fmv))
        self.l_range.setText(f"Range: {money(v.low)} – {money(v.high)}")
        trend = f"   ·   Trend: {v.trend}" if v.trend else ""
        self.l_conf.setText(f"Confidence: <b>{v.confidence}</b>   ·   {v.n_sales} sales used{trend}")
        parts = []
        for s, d in v.by_source.items():
            bits = []
            if d["n"]:
                bits.append(f"{d['n']} sales, median {money(d['median'])}")
            if d["guide"] is not None:
                bits.append(f"guide {money(d['guide'])}")
            parts.append(f"<b>{s}</b>: {'; '.join(bits)}")
        self.l_src.setText("<br>".join(parts))
        self.l_method.setText(f"<i>{v.method}</i>")

    def _toggle_use(self, cell: QTableWidgetItem):
        if cell.column() != 0:
            return
        c = self._row_comps[cell.row()]
        c.included = cell.checkState() == Qt.Checked
        self._refresh_comps()

    def _selected_comps(self) -> list[Comp]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._row_comps[r] for r in rows]

    def _delete_comps(self):
        sel = self._selected_comps()
        if sel:
            ids = {id(c) for c in sel}
            self.comps = [c for c in self.comps if id(c) not in ids]
            self._refresh_comps()

    def _open_link(self):
        sel = self._selected_comps()
        if sel and sel[0].url:
            QDesktopServices.openUrl(QUrl(sel[0].url))

    def _add_manual(self):
        dlg = ManualCompDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.price.value() > 0:
            self.comps.append(dlg.comp())
            self._refresh_comps()

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import comps CSV", "", "CSV (*.csv *.txt)")
        if not path:
            return
        new = comps_from_csv(Path(path).read_text(encoding="utf-8-sig", errors="replace"), "Card Ladder")
        if not new:
            QMessageBox.warning(self, "Import", "No rows with a price were found.\n"
                                "Expected columns like Date, Price, Title, Source.")
            return
        self.comps.extend(new)
        self._refresh_comps()
        self.status.setText(f"Imported {len(new)} comps from {Path(path).name}")

    # ---------- gathering ----------
    def _fetch(self):
        item = self._read()
        if not item.name:
            QMessageBox.warning(self, "Missing info", "Enter at least the card name.")
            return
        key = (item.game, item.name.lower(), item.number.lower(), item.set_name.lower(), item.variant.lower())
        if key != self._loaded_key:
            # card changed since the last match: drop auto-found IDs/image unless typed in by hand
            if item.tcg_product_id == self._loaded_ids[0]:
                item.tcg_product_id = ""
            if item.pc_product_id == self._loaded_ids[1]:
                item.pc_product_id = ""
            item.image_url = ""
        self.b_fetch.setEnabled(False)
        self.status.setText("Gathering…")
        self._log = []
        self.worker = GatherWorker([(item, list(self.comps))], dict(self.settings))
        self.worker.progress.connect(self._progress)
        self.worker.item_done.connect(self._fetched)
        self.worker.finished.connect(self._fetch_done)
        self.thread = start_worker(self, self.worker)

    def _fetch_done(self):
        self.b_fetch.setEnabled(True)
        self.thread = None

    def _progress(self, msg: str):
        self._log.append(msg)
        self.status.setText("\n".join(self._log[-6:]))

    def _fetched(self, item, comps, results):
        self.comps = comps
        self.tcg_id.setText(item.tcg_product_id); self.pc_id.setText(item.pc_product_id)
        self._remember_key()
        fails = [r for r in results if not r.ok]
        lines = [f"{'✗' if not r.ok else '✓'} {r.source}: {r.message}" for r in results]
        self.status.setText("\n".join(lines))
        if fails and not comps:
            self.status.setText(self.status.text() + "\nNo data gathered – add manual comps or check settings.")
        self._show_image()
        self._refresh_comps()

    # ---------- save ----------
    def _save(self):
        item = self._read()
        if not item.name:
            QMessageBox.warning(self, "Missing info", "Enter at least the card name.")
            return
        apply_valuation(item, self.comps, self.settings)
        self.db.save_item(item)
        self.db.replace_comps(item.id, self.comps)
        self.accept()

    def reject(self):
        if self.thread is not None:
            self.worker.stop()
            for sig, slot in ((self.worker.progress, self._progress), (self.worker.item_done, self._fetched),
                              (self.worker.finished, self._fetch_done)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        super().reject()
