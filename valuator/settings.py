"""App settings + data paths (stored under %APPDATA%\\LonestarValuator on Windows)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_DISCLAIMER = (
    "This report provides an estimate of fair market value based on publicly available "
    "recent sales and price-guide data as of the report date. Values are opinions, not "
    "guarantees, and can change quickly. Condition was assessed visually and is not a "
    "substitute for professional third-party grading. This report is not an offer to "
    "purchase. Replacement cost for insurance purposes may differ from fair market value."
)

DEFAULTS = {
    "store_name": "LoneStar Cards",
    "store_address": "111 Hovatter Dr, Inwood, WV",
    "store_phone": "",
    "store_email": "",
    "store_website": "",
    "logo_path": "",
    "appraiser_name": "",
    "appraiser_title": "Appraiser",
    "pricecharting_token": "",
    "psa_token": "",
    "replacement_pct": 20.0,
    "chart_days": 365,
    "chart_in_pdf": True,
    "lookback_days": 120,
    "half_life_days": 30,
    "guide_weight": 0.20,
    "outlier_k": 1.5,
    "sources_enabled": {"eBay": True, "130point": True, "TCGplayer": True, "PriceCharting": True},
    "disclaimer": DEFAULT_DISCLAIMER,
    "report_prefix": "LSV",
    "show_comps_in_pdf": 8,
    "update_repo": "DwsCode88/LonestarValuator",
    "accent_color": "#1F3A5F",
}


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or (Path.home() / ".config")
    p = Path(base) / "LonestarValuator"
    p.mkdir(parents=True, exist_ok=True)
    (p / "images").mkdir(exist_ok=True)
    (p / "reports").mkdir(exist_ok=True)
    return p


def resource_path(rel: str) -> Path:
    """Path to a bundled file (works in PyInstaller one-file builds)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


class Settings(dict):
    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = path or (data_dir() / "settings.json")
        self.update(json.loads(json.dumps(DEFAULTS)))
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                for k, val in saved.items():
                    if isinstance(val, dict) and isinstance(self.get(k), dict):
                        self[k].update(val)
                    else:
                        self[k] = val
            except (OSError, json.JSONDecodeError):
                pass

    def save(self):
        self.path.write_text(json.dumps(dict(self), indent=2), encoding="utf-8")

    def logo(self) -> Path | None:
        if self.get("logo_path") and Path(self["logo_path"]).exists():
            return Path(self["logo_path"])
        bundled = resource_path("assets/logo.png")
        return bundled if bundled.exists() else None
