"""PriceCharting: guide value per grade + its sold listings (eBay, Goldin, TCGplayer…).

With an API token (paid) the official API is used for the guide value. Without one, the
public product page is read: it has the guide table (Ungraded, Grade 7…PSA 10, BGS/CGC/SGC 10)
and "Sold Listings" tables, which become sale comps.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..models import Comp, Item, SourceResult
from .base import Source
from .matching import parse_date, parse_price, title_matches

API = "https://www.pricecharting.com/api/product"
SITE = "https://www.pricecharting.com"
SEARCH = SITE + "/search-products?type=prices&q={q}"

TEN_FIELDS = {"PSA": "manual-only-price", "BGS": "bgs-10-price", "CGC": "condition-17-price",
              "SGC": "condition-18-price", "TAG": "condition-21-price", "ACE": "condition-22-price"}
GRADE_FIELDS = {
    "9.5": "box-only-price", "9": "graded-price", "8.5": "new-price", "8": "new-price",
    "7.5": "cib-price", "7": "cib-price", "6": "condition-16-price", "5": "condition-15-price",
    "4": "condition-14-price", "3": "condition-13-price", "2": "condition-12-price",
    "1": "condition-9-price",
}
GAME_WORD = {"Pokemon": "pokemon", "Magic: The Gathering": "magic", "One Piece": "one piece",
             "Yu-Gi-Oh!": "yugioh", "Lorcana": "lorcana", "Dragon Ball Super": "dragon ball",
             "Digimon": "digimon"}


def field_for(item: Item) -> str | None:
    if not item.graded:
        return "loose-price"
    if item.grade == "10":
        return TEN_FIELDS.get(item.grader)
    return GRADE_FIELDS.get(item.grade)


def page_label(item: Item) -> str:
    """Column/row label on the product page for this condition."""
    if not item.graded:
        return "Ungraded"
    if item.grade == "10":
        return f"{item.grader} 10"
    return f"Grade {item.grade}"


class PriceChartingSource(Source):
    name = "PriceCharting"
    kind = "guide"

    def fetch_item(self, item: Item) -> SourceResult:
        token = self.settings.get("pricecharting_token")
        res = self._api(item, token) if token else None
        page = None
        try:
            page = self._page(item)
        except Exception as e:
            if res is None:
                raise
            res.message += f" (sold listings unavailable: {type(e).__name__})"
        if res is None:
            return page
        if page:   # keep API guide, add the page's sold listings
            res.comps += [c for c in page.comps if c.kind == "sale"]
            n = sum(c.kind == "sale" for c in page.comps)
            res.message += f"; {n} sold listings"
        return res

    # ---------- API ----------
    def _api(self, item: Item, token: str) -> SourceResult:
        params = {"t": token}
        if item.pc_product_id and item.pc_product_id.isdigit():
            params["id"] = item.pc_product_id
        else:
            params["q"] = " ".join(p for p in [item.name, item.number, item.set_name, item.variant] if p)
        r = self.session.get(API, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return SourceResult(self.name, ok=False, message=data.get("error-message", "No match"))
        return parse_product(data, item)

    # ---------- web page ----------
    def _page(self, item: Item) -> SourceResult:
        url = item.pc_product_id if item.pc_product_id.startswith("http") else ""
        if not url:
            q = " ".join(p for p in [item.name, item.number.split("/")[0] if item.number else "",
                                     item.set_name, item.variant] if p)
            html = self.get_html(SEARCH.format(q=quote_plus(q)), wait_selector="#product_name, table#games_table")
            if "id=\"games_table\"" in html or "games_table" in html:
                url = best_search_result(html, item)
                if not url:
                    return SourceResult(self.name, ok=True, message="No confident PriceCharting match "
                                        "(paste the PriceCharting page URL into the item to force one)")
                html = self.get_html(url, wait_selector="#price_data, #full-prices")
            else:
                url = canonical_url(html) or SEARCH.format(q=quote_plus(q))
        else:
            html = self.get_html(url, wait_selector="#price_data, #full-prices")
        res = parse_page(html, item, url)
        res.product_id = url
        return res


def canonical_url(html: str) -> str:
    m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    return m.group(1) if m else ""


def best_search_result(html: str, item: Item) -> str:
    soup = BeautifulSoup(html, "html.parser")
    best, best_score = "", 0
    num = (item.number.split("/")[0].lstrip("0") or item.number) if item.number else ""
    for a in soup.select("table#games_table a[href*='/game/'], td.title a[href*='/game/']"):
        text = a.get_text(" ", strip=True).lower()
        row = a.find_parent("tr")
        console = row.get_text(" ", strip=True).lower() if row else ""
        s = 0
        if all(w in text for w in re.findall(r"[a-z0-9]+", item.name.lower()) if len(w) > 1):
            s += 5
        if num and re.search(rf"#0*{re.escape(num)}\b", text):
            s += 5
        if item.set_name:
            want_set = re.sub(r"[^a-z0-9]+", " ", item.set_name.lower()).strip()
            cell = row.find_all("td")[-1].get_text(" ", strip=True).lower() if row and row.find_all("td") else console
            cell = re.sub(r"[^a-z0-9]+", " ", cell).strip()
            gw = GAME_WORD.get(item.game, "")
            bare = re.sub(rf"^{re.escape(gw)}\s+(japanese\s+)?", "", cell) if gw else cell
            if bare == want_set:
                s += 4
            elif re.search(rf"\b{re.escape(want_set)}\b", cell):
                s += 1
        if item.variant:
            s += 2 if item.variant.lower() in text else 0
        elif "[" in text:
            s -= 1       # prefer the plain printing when no variant was given
        gw = GAME_WORD.get(item.game)
        if gw and gw not in console:
            s -= 4
        if s > best_score:
            best, best_score = urljoin(SITE, a["href"]), s
    return best if best_score >= 8 else ""


def _guide_from_page(soup: BeautifulSoup, label: str) -> float | None:
    want = label.lower()
    # 1) the headline table: header cells (Ungraded, Grade 7 … PSA 10) above a row of prices
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        heads = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if want in heads:
            idx = heads.index(want)
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if idx < len(cells):
                    m = re.search(r"\$[\d,]+(?:\.\d{2})?", cells[idx].get_text(" ", strip=True))
                    if m:
                        return parse_price(m.group(0))
    # 2) the full price list: rows of "label | price"
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2 and cells[0].get_text(" ", strip=True).lower() == want:
            m = re.search(r"\$[\d,]+(?:\.\d{2})?", cells[1].get_text(" ", strip=True))
            if m:
                return parse_price(m.group(0))
    return None


def _sold_listings(soup: BeautifulSoup, item: Item, page_url: str) -> tuple[list[Comp], int]:
    comps, skipped, seen = [], 0, set()
    for table in soup.find_all("table"):
        head = table.find("tr")
        if not head:
            continue
        heads = [c.get_text(" ", strip=True).lower() for c in head.find_all(["th", "td"])]
        if not any("sale date" in h or h == "date" for h in heads) or not any("price" in h for h in heads):
            continue
        ti = next((i for i, h in enumerate(heads) if "title" in h), None)
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            d = parse_date(cells[0].get_text(" ", strip=True))
            title_cell = cells[ti] if ti is not None and ti < len(cells) else max(
                cells, key=lambda c: len(c.get_text(strip=True)))
            title = title_cell.get_text(" ", strip=True).replace("Report It", "").strip()
            prices = [m for c in cells for m in re.findall(r"\$[\d,]+(?:\.\d{2})?", c.get_text(" ", strip=True))]
            if not prices or not title:
                continue
            price = parse_price(prices[-1])
            link = title_cell.find("a", href=True)
            url = urljoin(SITE, link["href"]) if link else page_url
            key = (title, price, d)
            if key in seen:
                continue
            ok, _ = title_matches(title, item)
            if not ok:
                skipped += 1
                continue
            seen.add(key)
            src = ""
            img = row.find("img", alt=True)
            if img and img["alt"].strip():
                src = img["alt"].strip()
            comps.append(Comp(source="PriceCharting", price=price, title=title, sale_date=d, url=url,
                              condition=item.grade_label, note=f"Sold on {src}" if src else "Sold listing"))
    return comps, skipped


def parse_page(html: str, item: Item, url: str = "") -> SourceResult:
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.select_one("#product_name, h1")
    name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True)) if name_el else "PriceCharting product"
    res = SourceResult("PriceCharting", matched_name=name, product_id=url)
    label = page_label(item)
    guide = _guide_from_page(soup, label)
    if guide and (item.graded or item.condition == "Near Mint"):
        res.comps.append(Comp(source="PriceCharting", kind="guide", price=guide,
                              title=f"PriceCharting {label} guide: {name}", sale_date=datetime.now().date(),
                              url=url, condition=item.grade_label, note="Guide value"))
    sales, skipped = _sold_listings(soup, item, url)
    res.comps += sales
    img = soup.select_one("#product_details img[src], .cover img[src], #extra-images img[src]")
    if img and img["src"].startswith("http"):
        res.image_url = img["src"]
    g = f"guide {label} ${guide:,.2f}" if guide else f"no {label} guide value"
    res.message = f"Matched '{name}': {g}; {len(sales)} sold listings ({skipped} filtered out)"
    return res


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
    res.message = f"Matched {name} (API)"
    return res
