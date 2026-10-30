from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..certs import clean_token
from ..settings import DEFAULT_DISCLAIMER


class SettingsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Settings")
        self.resize(640, 560)
        root = QVBoxLayout(self)
        tabs = QTabWidget(); root.addWidget(tabs)

        # Store / branding
        w = QWidget(); f = QFormLayout(w)
        self.fields = {}
        for key, label in [("store_name", "Store name"), ("store_address", "Address"),
                           ("store_phone", "Phone"), ("store_email", "Email"), ("store_website", "Website"),
                           ("appraiser_name", "Appraiser name"), ("appraiser_title", "Appraiser title"),
                           ("report_prefix", "Report # prefix"), ("accent_color", "Accent color (hex)")]:
            e = QLineEdit(str(settings.get(key, ""))); self.fields[key] = e; f.addRow(label, e)
        lrow = QHBoxLayout()
        self.logo = QLineEdit(settings.get("logo_path", ""))
        b = QPushButton("Browse…"); b.clicked.connect(self._logo)
        lrow.addWidget(self.logo); lrow.addWidget(b)
        f.addRow("Logo (PNG/JPG)", lrow)
        tabs.addTab(w, "Store && branding")

        # Data sources
        w = QWidget(); f = QFormLayout(w)
        self.src_checks = {}
        for name in ("eBay", "130point", "TCGplayer", "PriceCharting"):
            c = QCheckBox(f"Use {name}"); c.setChecked(settings["sources_enabled"].get(name, True))
            self.src_checks[name] = c; f.addRow(c)
        self.pc_token = QLineEdit(settings.get("pricecharting_token", ""))
        self.pc_token.setEchoMode(QLineEdit.Password)
        self.pc_token.setPlaceholderText("From pricecharting.com → Subscription → API/Download")
        f.addRow("PriceCharting API token", self.pc_token)
        self.psa_token = QLineEdit(settings.get("psa_token", ""))
        self.psa_token.setEchoMode(QLineEdit.Password)
        self.psa_token.setPlaceholderText("Optional – only works if PSA has approved your API access")
        f.addRow("PSA API token", self.psa_token)
        self.gemrate = QLineEdit(settings.get("gemrate_key", ""))
        self.gemrate.setEchoMode(QLineEdit.Password)
        self.gemrate.setPlaceholderText("Optional – adds PSA/BGS/SGC/CGC population (key from GemRate)")
        f.addRow("GemRate API key", self.gemrate)
        tabs.addTab(w, "Data sources")

        # Valuation math
        w = QWidget(); f = QFormLayout(w)
        self.lookback = QSpinBox(); self.lookback.setRange(7, 730); self.lookback.setValue(int(settings["lookback_days"]))
        self.lookback.setSuffix(" days")
        self.half = QSpinBox(); self.half.setRange(1, 365); self.half.setValue(int(settings["half_life_days"]))
        self.half.setSuffix(" days")
        self.gw = QDoubleSpinBox(); self.gw.setRange(0, 1); self.gw.setSingleStep(0.05)
        self.gw.setValue(float(settings["guide_weight"]))
        self.k = QDoubleSpinBox(); self.k.setRange(0.5, 5); self.k.setSingleStep(0.25)
        self.k.setValue(float(settings["outlier_k"]))
        self.show_n = QSpinBox(); self.show_n.setRange(0, 25); self.show_n.setValue(int(settings["show_comps_in_pdf"]))
        f.addRow("Only use sales from the last", self.lookback)
        f.addRow("Recency half-life (sale weight halves every)", self.half)
        f.addRow("Guide value weight (0–1)", self.gw)
        f.addRow("Outlier strictness (IQR ×, lower = stricter)", self.k)
        f.addRow("Comparable sales listed per card in PDF", self.show_n)
        self.rv = QDoubleSpinBox(); self.rv.setRange(0, 200); self.rv.setSuffix(" %")
        self.rv.setValue(float(settings.get("replacement_pct", 20)))
        f.addRow("Default insurance replacement markup", self.rv)
        self.chart_days = QSpinBox(); self.chart_days.setRange(30, 1095); self.chart_days.setSuffix(" days")
        self.chart_days.setValue(int(settings.get("chart_days", 365)))
        f.addRow("Price history chart covers", self.chart_days)
        self.chart_pdf = QCheckBox("Include price history chart in PDF")
        self.chart_pdf.setChecked(bool(settings.get("chart_in_pdf", True)))
        f.addRow(self.chart_pdf)
        tabs.addTab(w, "Valuation")

        # Disclaimer
        w = QWidget(); v = QVBoxLayout(w)
        self.disc = QPlainTextEdit(settings.get("disclaimer", ""))
        rb = QPushButton("Reset to default"); rb.clicked.connect(lambda: self.disc.setPlainText(DEFAULT_DISCLAIMER))
        v.addWidget(self.disc); v.addWidget(rb)
        tabs.addTab(w, "Disclaimer")

        # Updates
        w = QWidget(); f = QFormLayout(w)
        self.repo = QLineEdit(settings.get("update_repo", ""))
        f.addRow("GitHub repo for updates (owner/name)", self.repo)
        tabs.addTab(w, "Updates")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _logo(self):
        p, _ = QFileDialog.getOpenFileName(self, "Logo", "", "Images (*.png *.jpg *.jpeg)")
        if p:
            self.logo.setText(p)

    def _save(self):
        for k, e in self.fields.items():
            self.s[k] = e.text().strip()
        self.s["logo_path"] = self.logo.text().strip()
        self.s["sources_enabled"] = {k: c.isChecked() for k, c in self.src_checks.items()}
        self.s["pricecharting_token"] = self.pc_token.text().strip()
        self.s["psa_token"] = clean_token(self.psa_token.text())
        self.s["gemrate_key"] = self.gemrate.text().strip()
        self.s["replacement_pct"] = round(self.rv.value(), 1)
        self.s["chart_days"] = self.chart_days.value()
        self.s["chart_in_pdf"] = self.chart_pdf.isChecked()
        self.s["lookback_days"] = self.lookback.value()
        self.s["half_life_days"] = self.half.value()
        self.s["guide_weight"] = round(self.gw.value(), 2)
        self.s["outlier_k"] = round(self.k.value(), 2)
        self.s["show_comps_in_pdf"] = self.show_n.value()
        self.s["disclaimer"] = self.disc.toPlainText().strip()
        self.s["update_repo"] = self.repo.text().strip()
        self.s.save()
        self.accept()
