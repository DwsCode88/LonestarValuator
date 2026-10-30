"""130point sold-comps search (includes eBay best-offer accepted prices).

130point has no public API; this posts the same form its website uses and parses the
returned HTML table defensively. If the site changes, this source reports a failure and
the rest of the valuation continues.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Comp, Item, SourceResult
from ..net import TIMEOUT
from .base import Source
from .matching import parse_date, parse_price, title_matches

URL = "https://back.130point.com/sales/"


class OneThirtyPointSource(Source):
    name = "130point"

    def fetch_item(self, item: Item) -> SourceResult:
        q = item.search_query()
        html = self.fetch("https://130point.com/sales/", URL, "POST",
                          form={"query": q, "type": "2", "subcat": "-1"}, as_json=False)
        comps, skipped = parse_results(html, item)
        return SourceResult(self.name, comps=comps,
                            message=f"{len(comps)} matching sales ({skipped} filtered out)")


def parse_results(html: str, item: Item) -> tuple[list[Comp], int]:
    soup = BeautifulSoup(html, "html.parser")
    comps, skipped = [], 0
    rows = soup.select("tr[id^=dRow], tr[data-price], tr")
    seen = set()
    for row in rows:
        link = row.find("a", href=re.compile(r"ebay\.|/itm/|goldin|pwcc|fanatics|heritage", re.I)) \
            or row.find("a", href=True)
        if not link:
            continue
        title = (row.select_one("#titleText, .titleText") or link).get_text(" ", strip=True)
        text = row.get_text(" ", strip=True)
        price = None
        if row.has_attr("data-price"):
            price = parse_price(row["data-price"])
        if price is None:
            m = re.search(r"(?:Sale Price|Sold(?: For)?|Price)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)", text, re.I)
            price = parse_price(m.group(1)) if m else None
        currency = (row.get("data-currency") or "USD").upper()
        if price is None or price <= 0 or currency != "USD":
            continue
        date_el = row.select_one("#dateText, .dateText")
        dtext = date_el.get_text(" ", strip=True) if date_el else ""
        if not dtext:
            m = re.search(r"(?:Date|Sold|Ended)\s*:?\s*([A-Za-z]{3},?\s*\d{1,2}\s*[A-Za-z]{3}\s*\d{4}|"
                          r"[A-Za-z]{3}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})", text)
            dtext = m.group(1) if m else ""
        url = link["href"].split("?")[0]
        key = (url, price)
        if key in seen:
            continue
        ok, _ = title_matches(title, item)
        if not ok:
            skipped += 1
            continue
        seen.add(key)
        note = "Best offer accepted" if re.search(r"best offer", text, re.I) else ""
        comps.append(Comp(source="130point", price=price, title=title, sale_date=parse_date(dtext),
                          url=url, condition=item.grade_label, note=note))
    return comps, skipped
