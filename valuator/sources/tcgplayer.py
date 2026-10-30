"""TCGplayer market price + latest sales (raw cards only).

Uses the same public JSON endpoints the tcgplayer.com website calls. They are
unofficial and can change; failures are reported, never fatal.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..models import Comp, Item, SourceResult
from ..net import TIMEOUT
from .base import Source

SEARCH_URL = "https://mp-search-api.tcgplayer.com/v1/search/request"
SALES_URL = "https://mpapi.tcgplayer.com/v2/product/{pid}/latestsales"
IMAGE_URL = "https://tcgplayer-cdn.tcgplayer.com/product/{pid}_in_400x400.jpg"
PRODUCT_URL = "https://www.tcgplayer.com/product/{pid}"

PRODUCT_LINES = {
    "Pokemon": "pokemon", "Magic: The Gathering": "magic", "One Piece": "one-piece-card-game",
    "Yu-Gi-Oh!": "yugioh", "Lorcana": "lorcana-tcg", "Dragon Ball Super": "dragon-ball-super-fusion-world",
    "Digimon": "digimon-card-game", "Flesh and Blood": "flesh-and-blood-tcg",
    "Star Wars Unlimited": "star-wars-unlimited",
}
CONDITION_IDS = {"Near Mint": 1, "Lightly Played": 2, "Moderately Played": 3,
                 "Heavily Played": 4, "Damaged": 5}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", (s or "").lower()).strip()


class TCGplayerSource(Source):
    name = "TCGplayer"

    def supports(self, item: Item) -> bool:
        return not item.graded and item.game != "Sports"

    def search(self, item: Item) -> list[dict]:
        q = " ".join(p for p in [item.name, item.number] if p)
        line = PRODUCT_LINES.get(item.game)
        body = {
            "algorithm": "sales_synonym_v2",
            "from": 0,
            "size": 24,
            "filters": {"term": {"productLineName": [line]} if line else {}, "range": {}, "match": {}},
            "listingSearch": {"context": {"cart": {}},
                              "filters": {"term": {"sellerStatus": "Live", "channelId": 0},
                                          "range": {"quantity": {"gte": 1}},
                                          "exclude": {"channelExclusion": 0}}},
            "context": {"cart": {}, "shippingCountry": "US", "userProfile": {}},
            "settings": {"useFuzzySearch": True, "didYouMean": {}},
            "sort": {},
        }
        r = self.session.post(SEARCH_URL, params={"q": q, "isList": "false"}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        try:
            return data["results"][0]["results"]
        except (KeyError, IndexError, TypeError):
            return []

    @staticmethod
    def score(product: dict, item: Item) -> float:
        s = 0.0
        name = _norm(product.get("productName", ""))
        want = _norm(item.name)
        if want and want in name:
            s += 5
        s += sum(1 for w in want.split() if w in name)
        num = _norm((product.get("customAttributes") or {}).get("number", ""))
        if item.number and num:
            a = re.sub(r"^0+", "", _norm(item.number).split("/")[0])
            b = re.sub(r"^0+", "", num.split("/")[0])
            if a == b or _norm(item.number) == num:
                s += 6
        if item.set_name and _norm(item.set_name) in _norm(product.get("setName", "")):
            s += 4
        if item.variant and _norm(item.variant) in name:
            s += 2
        if product.get("productTypeName", "Cards") not in ("Cards", None):
            s -= 10
        return s

    def best_match(self, item: Item, products: list[dict]) -> dict | None:
        if item.tcg_product_id:
            for p in products:
                if str(int(p.get("productId", 0))) == str(item.tcg_product_id):
                    return p
            return {"productId": int(item.tcg_product_id)}
        if not products:
            return None
        ranked = sorted(products, key=lambda p: self.score(p, item), reverse=True)
        return ranked[0] if self.score(ranked[0], item) >= 5 else None

    def latest_sales(self, pid: int, item: Item) -> list[dict]:
        body = {
            "conditions": [CONDITION_IDS[item.condition]] if item.condition in CONDITION_IDS else [],
            "languages": [1] if item.language.lower() in ("english", "en", "") else [],
            "variants": [],
            "listingType": "All",
            "offset": 0,
            "limit": 25,
        }
        r = self.session.post(SALES_URL.format(pid=pid), json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("data", []) or []

    def fetch(self, item: Item) -> SourceResult:
        products = [] if item.tcg_product_id else self.search(item)
        prod = self.best_match(item, products)
        if not prod:
            return SourceResult(self.name, ok=True, message="No confident product match "
                                "(set the TCGplayer product ID on the item to force one)")
        pid = int(prod["productId"])
        res = SourceResult(self.name, product_id=str(pid), image_url=IMAGE_URL.format(pid=pid),
                           matched_name=f"{prod.get('productName', '')} - {prod.get('setName', '')}".strip(" -"))
        purl = PRODUCT_URL.format(pid=pid)
        market = prod.get("marketPrice")
        if market and item.condition == "Near Mint":
            res.comps.append(Comp(source="TCGplayer", kind="guide", price=round(float(market), 2),
                                  title=f"TCGplayer Market Price: {res.matched_name}",
                                  sale_date=datetime.now().date(), url=purl,
                                  condition="Near Mint", note="Market price"))
        variant_want = _norm(item.variant)
        for s in self.latest_sales(pid, item):
            cond = s.get("condition", "")
            if item.condition and cond and not cond.startswith(item.condition):
                continue
            variant = s.get("variant", "") or ""
            if variant_want and variant and variant_want not in _norm(variant) \
                    and _norm(variant) not in variant_want:
                continue
            qty = max(int(s.get("quantity") or 1), 1)
            price = float(s.get("purchasePrice") or 0)
            if price <= 0:
                continue
            d = None
            od = s.get("orderDate") or ""
            try:
                d = datetime.fromisoformat(od.replace("Z", "+00:00")).date()
            except ValueError:
                pass
            res.comps.append(Comp(source="TCGplayer", price=round(price, 2),
                                  title=f"{res.matched_name} [{cond}{', ' + variant if variant else ''}]"
                                        + (f" x{qty}" if qty > 1 else ""),
                                  sale_date=d, url=purl, condition=cond,
                                  note=s.get("listingType", "") if s.get("listingType") not in (None, "ListingWithoutPhotos") else ""))
        res.message = f"Matched '{res.matched_name}': {sum(c.kind == 'sale' for c in res.comps)} sales"
        return res
