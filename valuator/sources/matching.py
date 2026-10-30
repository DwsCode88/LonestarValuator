"""Title matching helpers shared by sale-listing sources (eBay, 130point)."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from ..models import GRADERS, Item

JUNK_WORDS = ["lot", "proxy", "custom", "orica", "digital", "reprint", "replica",
              "you pick", "you choose", "choose your", "pick your", "mystery", "repack",
              "read description", "fake", "metal card", "gold card", "coin", "sticker",
              "booster box", "booster pack", "sealed pack", "elite trainer", "bundle", "binder",
              "sleeves", "playmat", "jumbo", "oversized"]
GRADER_ALIASES = {
    "PSA": [r"psa"],
    "BGS": [r"bgs", r"beckett"],
    "CGC": [r"cgc"],
    "SGC": [r"sgc"],
    "TAG": [r"tag"],
    "ACE": [r"ace"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def number_tokens(number: str) -> list[str]:
    """Variants of a card number to look for in titles: '4/102' -> ['4/102', '004/102']."""
    n = _norm(number).lstrip("#")
    if not n:
        return []
    toks = {n}
    m = re.match(r"^0*(\d+)\s*/\s*0*(\d+)$", n)
    if m:
        a, b = m.groups()
        toks |= {f"{a}/{b}", f"{a.zfill(3)}/{b.zfill(3)}", f"{a.zfill(len(b))}/{b}"}
    return sorted(toks)


def has_grade(title: str, grader: str, grade: str) -> bool:
    t = _norm(title)
    g = re.escape(grade)
    for alias in GRADER_ALIASES.get(grader, [grader.lower()]):
        # "psa 10", "psa10", "psa gem mint 10", "bgs pristine 10"
        pat = rf"\b{alias}\s*(?:gem\s*mint|gem\s*mt|mint|pristine|black\s*label|nm-mt|nm\s*mt)?\s*{g}(?![\.\d])"
        if re.search(pat, t):
            return True
    return False


def looks_graded(title: str) -> bool:
    t = _norm(title)
    return any(re.search(rf"\b{a}\s*\d", t) for aliases in GRADER_ALIASES.values() for a in aliases) \
        or re.search(r"\b(graded|slab|slabbed)\b", t) is not None


def title_matches(title: str, item: Item) -> tuple[bool, str]:
    """Return (match, reason) for whether a sold-listing title is a comp for item."""
    t = _norm(title)
    if not t:
        return False, "empty title"
    for w in JUNK_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", t):
            return False, f"excluded word '{w}'"
    # name words must appear (ignore tiny words)
    name_words = [w for w in re.findall(r"[a-z0-9']+", _norm(item.name)) if len(w) > 1]
    missing = [w for w in name_words if w not in t]
    if missing:
        return False, f"missing '{' '.join(missing)}'"
    toks = number_tokens(item.number)
    if toks and not any(tok in t for tok in toks):
        # also allow the bare left side of a slash number as its own token
        left = toks[0].split("/")[0]
        if not ("/" in toks[0] and re.search(rf"(?<![\d/]){re.escape(left)}(?![\d/])", t)):
            return False, "card number not found"
    if item.graded:
        if not has_grade(title, item.grader, item.grade):
            return False, f"not {item.grader} {item.grade}"
        if item.grader == "BGS" and item.grade == "10" and "black" in t:
            return False, "black label"
    else:
        if looks_graded(title):
            return False, "graded listing"
    if item.language and item.language.lower() not in ("english", "en"):
        if item.language.lower()[:3] not in t:
            return False, "language not in title"
    else:
        for lang in ("japanese", "korean", "chinese", "jpn", "german", "french", "italian", "spanish"):
            if re.search(rf"\b{lang}\b", t):
                return False, f"{lang} listing"
    return True, ""


DATE_FORMATS = ["%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%a %d %b %Y",
                "%a, %d %b %Y", "%Y-%m-%dT%H:%M:%S", "%m/%d/%y"]


def parse_date(text: str) -> Optional[date]:
    if not text:
        return None
    s = re.sub(r"(?i)^\s*(sold|ended|date)[:\s]*", "", text.strip())
    s = re.sub(r"\s+", " ", s)
    # ISO with time / zone
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.search(r"([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%b %d %Y").date()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})[a-z]*\.?\s+(\d{4})", s)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %b %Y").date()
        except ValueError:
            pass
    return None


def parse_price(text: str) -> Optional[float]:
    if text is None:
        return None
    s = str(text)
    if " to " in s:      # ranges like "$10.00 to $20.00" are not single sales
        return None
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", s.replace("\xa0", " "))
    if not m:
        return None
    whole = m.group(1).replace(",", "")
    cents = m.group(2) or "0"
    try:
        return round(float(f"{whole}.{cents}"), 2)
    except ValueError:
        return None
