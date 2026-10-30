"""eBay sold/completed listings (scraped from the public search results page)."""
from __future__ import annotations

from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..models import Comp, Item, SourceResult
from ..net import TIMEOUT
from .base import Source
from .matching import parse_date, parse_price, title_matches

SEARCH_URL = "https://www.ebay.com/sch/i.html"
NEGATIVE_RAW = "-psa -bgs -cgc -sgc -graded -slab -lot -proxy"
NEGATIVE_GRADED = "-lot -proxy"


class EbaySource(Source):
    name = "eBay"

    def build_url(self, item: Item) -> str:
        q = item.search_query()
        q += " " + (NEGATIVE_GRADED if item.graded else NEGATIVE_RAW)
        params = {
            "_nkw": q,
            "LH_Sold": "1",
            "LH_Complete": "1",
            "_ipg": "120",
            "_sop": "13",     # ended recently first
            "rt": "nc",
        }
        if item.language.lower() in ("english", "en", ""):
            params["LH_PrefLoc"] = "1"  # US only, keeps currency in USD
        return f"{SEARCH_URL}?{urlencode(params)}"

    def fetch(self, item: Item) -> SourceResult:
        url = self.build_url(item)
        r = self.session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        comps, skipped = parse_results(r.text, item)
        msg = f"{len(comps)} matching sales ({skipped} listings filtered out)"
        if "captcha" in r.text.lower()[:20000] and not comps:
            return SourceResult(self.name, ok=False, message="eBay returned a bot check; try again later")
        return SourceResult(self.name, comps=comps, message=msg)


def parse_results(html: str, item: Item) -> tuple[list[Comp], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.s-card, li.s-item, div.s-item__wrapper")
    comps: list[Comp] = []
    seen = set()
    skipped = 0
    for card in cards:
        title_el = card.select_one(".s-card__title, .s-item__title")
        price_el = card.select_one(".s-card__price, .s-item__price")
        link_el = card.select_one("a.su-link[href*='/itm/'], a.s-item__link, a[href*='/itm/']")
        if not title_el or not price_el:
            continue
        title = title_el.get_text(" ", strip=True)
        title = title.replace("Opens in a new window or tab", "").replace("New Listing", "").strip()
        if not title or title.lower().startswith("shop on ebay"):
            continue
        url = (link_el.get("href") if link_el else "") or ""
        url = url.split("?")[0]
        if url in seen:
            continue
        price = parse_price(price_el.get_text(" ", strip=True))
        if price is None or price <= 0:
            skipped += 1
            continue
        # sold date lives in a caption / tag block, e.g. "Sold  Oct 12, 2026"
        date_text = ""
        for sel in (".s-card__caption", ".s-item__caption", ".s-item__title--tagblock",
                    ".s-item__ended-date", ".POSITIVE"):
            el = card.select_one(sel)
            if el and "sold" in el.get_text(" ", strip=True).lower():
                date_text = el.get_text(" ", strip=True)
                break
        sold = parse_date(date_text)
        ok, reason = title_matches(title, item)
        if not ok:
            skipped += 1
            continue
        best_offer = bool(card.find(string=lambda s: s and "best offer accepted" in s.lower()))
        note = "Best offer accepted (actual price may be lower)" if best_offer else ""
        seen.add(url)
        comps.append(Comp(source="eBay", price=price, title=title, sale_date=sold,
                          url=url, condition=item.grade_label, note=note,
                          # best-offer prices shown on eBay are the list price, so exclude by default
                          included=not best_offer))
    return comps, skipped
