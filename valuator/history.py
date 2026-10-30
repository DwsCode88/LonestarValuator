"""Price history series built from an item's dated sales (for the chart in the app and the PDF)."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from . import engine
from .models import Comp


@dataclass
class History:
    points: list = field(default_factory=list)   # [(date, price)] individual sales
    median: list = field(default_factory=list)   # [(date, price)] rolling median line
    start: Optional[date] = None
    end: Optional[date] = None
    change_pct: Optional[float] = None           # first vs last rolling-median value

    @property
    def usable(self) -> bool:
        return len(self.points) >= 3 and self.start != self.end


def build(comps: list[Comp], settings: dict | None = None, today: date | None = None) -> History:
    cfg = settings or {}
    today = today or date.today()
    days = int(cfg.get("chart_days", 365) or 365)
    cutoff = today - timedelta(days=days)
    sales = [c for c in comps if c.included and c.kind == "sale" and c.sale_date and c.price > 0
             and c.sale_date >= cutoff]
    sales = engine.dedupe(sales)
    sales, _ = engine.remove_outliers(sales, float(cfg.get("outlier_k", 1.5)))
    h = History()
    if not sales:
        return h
    sales.sort(key=lambda c: c.sale_date)
    h.points = [(c.sale_date, c.price) for c in sales]
    h.start, h.end = h.points[0][0], h.points[-1][0]
    span = (h.end - h.start).days
    # window scales with the span so short histories still get a line
    window = max(7, min(30, span // 4 or 7))
    step = max(1, window // 3)
    d = h.start
    while d <= h.end:
        lo, hi = d - timedelta(days=window), d
        vals = [p for (sd, p) in h.points if lo <= sd <= hi]
        if len(vals) >= 2 or (vals and len(h.points) < 8):
            h.median.append((d, round(statistics.median(vals), 2)))
        d += timedelta(days=step)
    if h.median and h.median[-1][0] != h.end:
        vals = [p for (sd, p) in h.points if h.end - timedelta(days=window) <= sd <= h.end]
        if vals:
            h.median.append((h.end, round(statistics.median(vals), 2)))
    if len(h.median) >= 2 and h.median[0][1] > 0:
        h.change_pct = (h.median[-1][1] - h.median[0][1]) / h.median[0][1] * 100
    return h


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    """Round axis ticks covering lo..hi."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            break
    start = (lo // step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 2))
        t += step
    if ticks[-1] < hi:
        ticks.append(round(ticks[-1] + step, 2))
    return ticks
