"""PriceCharting guide values (official API, requires a subscription token).

Prices come back in pennies. Card grade -> field mapping from the PriceCharting API docs.
"""
from __future__ import annotations

from datetime import datetime

from ..models import Comp, Item, SourceResult
from ..net import TIMEOUT
from .base import Source

API = "https://www.pricecharting.com/api/product"

TEN_FIELDS = {"PSA": "manual-only-price", "BGS": "bgs-10-price", "CGC": "condition-17-price",
              "SGC": "condition-18-price", "TAG": "condition-21-price", "ACE": "condition-22-price"}
GRADE_FIELDS = {
    "9.5": "box-only-price", "9": "graded-price", "8.5": "new-price", "8": "new-price",
    "7.5": "cib-price", "7": "cib-price", "6": "condition-16-price", "5": "condition-15-price",
    "4": "condition-14-price", "3": "condition-13-price", "2": "condition-12-price",
    "1": "condition-9-price",
}


def field_for(item: Item) -> str | None:
    if not item.graded:
        return "loose-price"
    if item.grade == "10":
        return TEN_FIELDS.get(item.grader)
    return GRADE_FIELDS.get(item.grade)


class PriceChartingSource(Source):
    name = "PriceCharting"
    kind = "guide"

    def supports(self, item: Item) -> bool:
        return bool(self.settings.get("pricecharting_token"))

    def fetch(self, item: Item) -> SourceResult:
        token = self.settings["pricecharting_token"]
        params = {"t": token}
        if item.pc_product_id:
            params["id"] = item.pc_product_id
        else:
            params["q"] = " ".join(p for p in [item.name, item.number, item.set_name,
                                                item.variant] if p)
        r = self.session.get(API, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return SourceResult(self.name, ok=False, message=data.get("error-message", "No match"))
        return parse_product(data, item)


def parse_product(data: dict, item: Item) -> SourceResult:
    name = f"{data.get('product-name', '')} ({data.get('console-name', '')})"
    pid = str(data.get("id", ""))
    res = SourceResult("PriceCharting", product_id=pid, matched_name=name)
    if not item.graded and item.condition != "Near Mint":
        res.message = f"Matched {name}; ungraded guide value assumes NM, skipped for {item.condition}"
        return res
    f = field_for(item)
    pennies = data.get(f) if f else None
    if not pennies:
        res.message = f"Matched {name}; no value for {item.grade_label}"
        return res
    res.comps.append(Comp(source="PriceCharting", kind="guide", price=round(int(pennies) / 100, 2),
                          title=f"PriceCharting {item.grade_label} guide: {name}",
                          sale_date=datetime.now().date(),
                          url=f"https://www.pricecharting.com/game/{pid}" if pid else "",
                          condition=item.grade_label, note="Guide value"))
    res.message = f"Matched {name}"
    return res
