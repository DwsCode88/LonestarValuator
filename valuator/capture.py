"""Turn whatever sales page is open in Chrome (Card Ladder, Goldin, Fanatics, Heritage, eBay…) into comps.

Site-agnostic: looks for repeated rows (table rows, list items, grid rows) that each contain one
price and one date, and takes the row's longest text as the title. Rows are returned as manual
comps so the appraiser reviews them like any other.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import Comp, Item
from .sources.matching import parse_date, parse_price, title_matches

PRICE_RE = re.compile(r"(?:US\s*)?\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b", re.I)
SITE_NAMES = {"cardladder": "Card Ladder", "goldin": "Goldin", "fanaticscollect": "Fanatics Collect",
              "pwcc": "Fanatics Collect", "ha.com": "Heritage", "ebay": "eBay", "130point": "130point",
              "pricecharting": "PriceCharting", "tcgplayer": "TCGplayer", "whatnot": "Whatnot",
              "alt.xyz": "Alt", "myslabs": "MySlabs"}
ROW_SELECTORS = "tr, li, [role=row], div[class*=row], div[class*=Row], div[class*=sale], div[class*=Sale], " \
                "div[class*=item], div[class*=card]"


def site_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for key, name in SITE_NAMES.items():
        if key in host:
            return name
    return host.replace("www.", "") or "Captured"


def _norm_price(text: str):
    m = PRICE_RE.findall(text)
    if len(m) != 1:
        return None
    return parse_price(m[0])


def capture(html: str, url: str, item: Item | None = None, filter_titles: bool = True) -> tuple[list[Comp], int]:
    """Return (comps, rows_skipped)."""
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript", "svg", "nav", "header", "footer"]):
        bad.decompose()
    source = site_name(url)
    comps, seen, skipped = [], set(), 0
    candidates = soup.select(ROW_SELECTORS)
    # innermost rows first so a container holding many sales isn't read as one sale
    for row in candidates:
        if row.select_one(ROW_SELECTORS) and len(PRICE_RE.findall(row.get_text(" ", strip=True))) > 1:
            continue
        text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
        if len(text) < 12 or len(text) > 600:
            continue
        price = _norm_price(text)
        dm = DATE_RE.search(text)
        if price is None or not dm:
            continue
        d = parse_date(dm.group(0))
        if d is None:
            continue
        # title: longest text chunk that isn't the price or date
        chunks = [c.strip() for c in row.stripped_strings]
        chunks = [c for c in chunks if not PRICE_RE.fullmatch(c.replace(" ", "")) and not DATE_RE.fullmatch(c)
                  and len(c) > 3]
        title = max(chunks, key=len) if chunks else text
        link = row.find("a", href=True)
        href = urljoin(url, link["href"]) if link else url
        key = (title[:80], price, d)
        if key in seen:
            continue
        seen.add(key)
        if item is not None and filter_titles and len(title) > 15:
            ok, _ = title_matches(title, item)
            if not ok:
                skipped += 1
                continue
        note = "Best offer accepted" if re.search(r"best offer", text, re.I) else ""
        comps.append(Comp(source=source, price=price, title=title[:200], sale_date=d, url=href,
                          condition=item.grade_label if item else "", manual=True,
                          note=(f"Captured from {source}. " + note).strip()))
    return comps, skipped
