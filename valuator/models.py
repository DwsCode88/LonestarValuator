"""Core data models."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

GAMES = ["Pokemon", "Magic: The Gathering", "One Piece", "Yu-Gi-Oh!", "Lorcana",
         "Dragon Ball Super", "Digimon", "Flesh and Blood", "Star Wars Unlimited",
         "Sports", "Other"]
RAW_CONDITIONS = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"]
GRADERS = ["PSA", "BGS", "CGC", "SGC", "TAG", "ACE"]
GRADES = ["10", "9.5", "9", "8.5", "8", "7.5", "7", "6.5", "6", "5.5", "5", "4", "3", "2", "1.5", "1"]
PURPOSES = ["Insurance", "Estate / Probate", "Sale / Consignment", "Donation", "General Appraisal"]


@dataclass
class Item:
    id: Optional[int] = None
    report_id: Optional[int] = None
    game: str = "Pokemon"
    name: str = ""
    set_name: str = ""
    number: str = ""
    variant: str = ""          # Holo, Reverse Holo, 1st Edition, Alt Art...
    language: str = "English"
    graded: bool = False
    condition: str = "Near Mint"
    grader: str = "PSA"
    grade: str = "10"
    cert: str = ""
    qty: int = 1
    image_path: str = ""
    image_url: str = ""
    notes: str = ""
    value_override: Optional[float] = None
    override_note: str = ""
    fmv: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    confidence: str = ""
    n_sales: int = 0
    trend: str = ""
    valued_at: str = ""
    tcg_product_id: str = ""
    pc_product_id: str = ""
    year: str = ""
    pop_total: Optional[int] = None     # population at this grade
    pop_higher: Optional[int] = None    # population graded higher
    pop_source: str = ""                # "PSA (as of 2026-10-29)", "Manual"...
    cert_desc: str = ""                 # grader's label description

    @property
    def pop_label(self) -> str:
        if not self.graded or self.pop_total is None:
            return ""
        s = f"Pop {self.pop_total:,}"
        if self.pop_higher is not None:
            s += f" · {self.pop_higher:,} higher"
        return s

    @property
    def grade_label(self) -> str:
        return f"{self.grader} {self.grade}" if self.graded else self.condition

    @property
    def final_value(self) -> Optional[float]:
        return self.value_override if self.value_override is not None else self.fmv

    @property
    def display_name(self) -> str:
        bits = [self.name]
        if self.number:
            bits.append(f"#{self.number}")
        if self.variant:
            bits.append(f"({self.variant})")
        return " ".join(b for b in bits if b)

    def search_query(self, include_grade: bool = True) -> str:
        parts = [self.name]
        if self.number:
            parts.append(self.number)
        if self.set_name:
            parts.append(self.set_name)
        if self.variant and self.variant.lower() not in ("normal", "unlimited"):
            parts.append(self.variant)
        if self.language and self.language.lower() not in ("english", "en"):
            parts.append(self.language)
        if self.graded and include_grade:
            parts.append(f"{self.grader} {self.grade}")
        return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()

    def to_dict(self) -> dict:
        return asdict(self)


def replacement_value(value: Optional[float], pct: float) -> Optional[float]:
    """Insurance replacement value = FMV plus the cost to re-acquire (dealer markup, tax, shipping)."""
    if value is None:
        return None
    return round(value * (1 + (pct or 0) / 100), 2)


@dataclass
class Comp:
    source: str                    # "eBay", "TCGplayer", "PriceCharting", "130point", "Manual"
    price: float
    kind: str = "sale"             # "sale" or "guide"
    title: str = ""
    sale_date: Optional[date] = None
    condition: str = ""
    url: str = ""
    included: bool = True
    manual: bool = False
    note: str = ""                 # e.g. "Best offer accepted", "Market price"
    id: Optional[int] = None
    item_id: Optional[int] = None

    def ebay_item_id(self) -> Optional[str]:
        m = re.search(r"/itm/(?:[^/]+/)?(\d{9,15})", self.url or "")
        if m:
            return m.group(1)
        m = re.search(r"[?&](?:item|itemId)=(\d{9,15})", self.url or "")
        return m.group(1) if m else None


@dataclass
class SourceResult:
    source: str
    comps: list = field(default_factory=list)
    ok: bool = True
    message: str = ""
    image_url: str = ""
    product_id: str = ""
    matched_name: str = ""
