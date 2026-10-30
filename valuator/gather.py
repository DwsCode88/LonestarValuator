"""Run every enabled source for an item, merge results, compute the valuation."""
from __future__ import annotations

import csv
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import engine
from .models import Comp, Item, SourceResult
from .net import TIMEOUT, make_session
from .sources import enabled_sources
from .sources.matching import parse_date, parse_price


def gather(item: Item, settings: dict, existing: list[Comp] | None = None,
           progress: Optional[Callable[[str], None]] = None) -> tuple[list[Comp], list[SourceResult]]:
    """Fetch fresh comps. Manual comps and include/exclude choices on kept comps survive a refresh."""
    srcs = [cls(settings) for cls in enabled_sources(settings)]
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=len(srcs) or 1) as ex:
        futs = {ex.submit(s.run, item): s for s in srcs}
        for f, s in futs.items():
            r = f.result()
            results.append(r)
            if progress:
                progress(f"{s.name}: {r.message}")
    fresh = [c for r in results for c in r.comps]
    prior = existing or []
    excluded_keys = {(c.source, c.url, c.price, c.sale_date) for c in prior if not c.included and not c.manual}
    for c in fresh:
        if (c.source, c.url, c.price, c.sale_date) in excluded_keys:
            c.included = False
    manual = [c for c in prior if c.manual]
    for r in results:
        if r.image_url and not item.image_url:
            item.image_url = r.image_url
        if r.source == "TCGplayer" and r.product_id and not item.tcg_product_id:
            item.tcg_product_id = r.product_id
        if r.source == "PriceCharting" and r.product_id and not item.pc_product_id:
            item.pc_product_id = r.product_id
    return manual + fresh, results


def apply_valuation(item: Item, comps: list[Comp], settings: dict) -> engine.Valuation:
    v = engine.value(comps, settings)
    item.fmv, item.low, item.high = v.fmv, v.low, v.high
    item.confidence, item.n_sales, item.trend = v.confidence, v.n_sales, v.trend
    item.valued_at = datetime.now().isoformat(timespec="minutes")
    return v


def cache_image(item: Item, folder: Path) -> Optional[Path]:
    """Download item.image_url once; return local path (user photo wins if set)."""
    if item.image_path and Path(item.image_path).exists():
        return Path(item.image_path)
    if not item.image_url:
        return None
    name = f"img_{hashlib.md5(item.image_url.encode()).hexdigest()[:16]}.jpg"
    p = folder / name
    if p.exists() and p.stat().st_size > 0:
        return p
    try:
        r = make_session().get(item.image_url, timeout=TIMEOUT)
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", "image"):
            return None
        p.write_bytes(r.content)
        return p
    except Exception:
        return None


def comps_from_csv(text: str, default_source: str = "Manual") -> list[Comp]:
    """Import comps pasted/exported from Card Ladder, spreadsheets, etc.

    Recognised headers (case-insensitive): date/sold date, price/sold price/sale price,
    title/name/description, url/link, source/platform, condition/grade.
    """
    reader = csv.DictReader(io.StringIO(text.strip()))
    out = []
    for row in reader:
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}

        def pick(*names):
            for n in names:
                if low.get(n):
                    return low[n]
            return ""
        price = parse_price(pick("price", "sold price", "sale price", "amount", "final price"))
        if not price:
            continue
        out.append(Comp(source=pick("source", "platform", "marketplace") or default_source,
                        price=price, title=pick("title", "name", "description", "card"),
                        sale_date=parse_date(pick("date", "sold date", "sale date", "date sold")),
                        url=pick("url", "link"), condition=pick("condition", "grade"),
                        manual=True, note="Imported"))
    return out
