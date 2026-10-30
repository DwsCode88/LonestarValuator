"""Valuation engine: dedupe, outlier filtering, recency-weighted fair market value."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .models import Comp

DEFAULTS = {
    "lookback_days": 120,
    "half_life_days": 30,
    "guide_weight": 0.20,     # share of FMV from guide values when sales are plentiful
    "outlier_k": 1.5,         # IQR multiplier
}


@dataclass
class Valuation:
    fmv: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    confidence: str = "None"
    n_sales: int = 0
    sales_median: Optional[float] = None
    guide_avg: Optional[float] = None
    trend: str = ""
    by_source: dict = field(default_factory=dict)   # source -> {"n":, "median":}
    used: list = field(default_factory=list)        # comps that fed the sales value
    excluded_outliers: list = field(default_factory=list)
    method: str = ""


def dedupe(comps: list[Comp]) -> list[Comp]:
    """130point mirrors eBay sales; keep one copy, preferring 130point (has best-offer price)."""
    out: list[Comp] = []
    by_ebay_id: dict[str, int] = {}
    for c in comps:
        eid = c.ebay_item_id()
        if eid and eid in by_ebay_id:
            j = by_ebay_id[eid]
            if c.source == "130point" and out[j].source == "eBay":
                out[j] = c
            continue
        # same price, same day, near-identical title from different sources
        dup = next((k for k, o in enumerate(out)
                    if o.source != c.source and o.kind == c.kind == "sale"
                    and abs(o.price - c.price) < 0.01 and o.sale_date == c.sale_date
                    and o.title[:40].lower() == c.title[:40].lower()), None)
        if dup is not None:
            continue
        if eid:
            by_ebay_id[eid] = len(out)
        out.append(c)
    return out


def _weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Weighted percentile with linear interpolation between weight midpoints."""
    pairs = sorted(zip(values, weights))
    vals = [p[0] for p in pairs]
    ws = [max(p[1], 1e-9) for p in pairs]
    if len(vals) == 1:
        return vals[0]
    total = sum(ws)
    cum, acc = [], 0.0
    for w in ws:
        cum.append((acc + w / 2) / total)
        acc += w
    if q <= cum[0]:
        return vals[0]
    if q >= cum[-1]:
        return vals[-1]
    for i in range(1, len(vals)):
        if q <= cum[i]:
            f = (q - cum[i - 1]) / (cum[i] - cum[i - 1])
            return vals[i - 1] + f * (vals[i] - vals[i - 1])
    return vals[-1]


def remove_outliers(comps: list[Comp], k: float) -> tuple[list[Comp], list[Comp]]:
    if len(comps) < 4:
        return comps, []
    prices = sorted(c.price for c in comps)
    q = statistics.quantiles(prices, n=4, method="inclusive")
    q1, q3 = q[0], q[2]
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    # never let a tight cluster throw away reasonable sales: floor the band at +/-25% of median
    med = statistics.median(prices)
    lo, hi = min(lo, med * 0.75), max(hi, med * 1.25)
    keep = [c for c in comps if lo <= c.price <= hi]
    drop = [c for c in comps if not (lo <= c.price <= hi)]
    return keep, drop


def value(comps: list[Comp], settings: dict | None = None, today: date | None = None) -> Valuation:
    cfg = {**DEFAULTS, **(settings or {})}
    today = today or date.today()
    v = Valuation()
    included = [c for c in comps if c.included and c.price and c.price > 0]
    cutoff = today - timedelta(days=int(cfg["lookback_days"]))
    sales = [c for c in included if c.kind == "sale" and (c.sale_date is None or c.sale_date >= cutoff)]
    guides = [c for c in included if c.kind == "guide"]
    sales = dedupe(sales)
    sales, outliers = remove_outliers(sales, float(cfg["outlier_k"]))
    v.excluded_outliers = outliers
    v.used = sales
    v.n_sales = len(sales)

    hl = max(float(cfg["half_life_days"]), 1.0)

    def weight(c: Comp) -> float:
        if c.sale_date is None:
            return 0.35   # undated sales count, but less
        age = max((today - c.sale_date).days, 0)
        return 0.5 ** (age / hl)

    for src in sorted({c.source for c in sales} | {c.source for c in guides}):
        s_prices = [c.price for c in sales if c.source == src]
        g_prices = [c.price for c in guides if c.source == src]
        v.by_source[src] = {
            "n": len(s_prices),
            "median": round(statistics.median(s_prices), 2) if s_prices else None,
            "guide": round(statistics.mean(g_prices), 2) if g_prices else None,
        }

    if guides:
        v.guide_avg = round(statistics.mean(c.price for c in guides), 2)

    if sales:
        prices = [c.price for c in sales]
        weights = [weight(c) for c in sales]
        v.sales_median = round(_weighted_quantile(prices, weights, 0.5), 2)
        low = _weighted_quantile(prices, weights, 0.25)
        high = _weighted_quantile(prices, weights, 0.75)
        v.trend = _trend(sales, today)

    n = v.n_sales
    gw = float(cfg["guide_weight"])
    if n >= 3 and v.guide_avg is not None:
        v.fmv = v.sales_median * (1 - gw) + v.guide_avg * gw
        v.method = f"Recency-weighted median of {n} sales ({int((1-gw)*100)}%) blended with guide values ({int(gw*100)}%)"
    elif n >= 3:
        v.fmv = v.sales_median
        v.method = f"Recency-weighted median of {n} sales"
    elif n > 0 and v.guide_avg is not None:
        v.fmv = (v.sales_median + v.guide_avg) / 2
        v.method = f"Average of {n} sale(s) and guide values (limited sales)"
    elif n > 0:
        v.fmv = v.sales_median
        v.method = f"Median of {n} sale(s) (limited data)"
    elif v.guide_avg is not None:
        v.fmv = v.guide_avg
        low = high = None
        v.method = "Guide values only (no qualifying recent sales)"
    else:
        v.method = "No data"
        return v

    v.fmv = round(v.fmv, 2)
    if sales:
        # centre the sales interquartile range on the (possibly guide-blended) value
        shift = v.fmv - v.sales_median
        v.low = round(min(low + shift, v.fmv), 2)
        v.high = round(max(high + shift, v.fmv), 2)
    else:
        v.low = round(v.fmv * 0.85, 2)
        v.high = round(v.fmv * 1.15, 2)
    v.confidence = _confidence(sales, v, today)
    return v


def _trend(sales: list[Comp], today: date) -> str:
    recent = [c.price for c in sales if c.sale_date and (today - c.sale_date).days <= 30]
    older = [c.price for c in sales if c.sale_date and 30 < (today - c.sale_date).days <= 120]
    if len(recent) < 2 or len(older) < 2:
        return ""
    a, b = statistics.median(recent), statistics.median(older)
    if b <= 0:
        return ""
    pct = (a - b) / b * 100
    if abs(pct) < 5:
        return "Stable"
    return f"{'Up' if pct > 0 else 'Down'} {abs(pct):.0f}%"


def _confidence(sales: list[Comp], v: Valuation, today: date) -> str:
    n = len(sales)
    if n == 0:
        return "Low"
    spread = (v.high - v.low) / v.fmv if v.fmv else 1
    dated = [c.sale_date for c in sales if c.sale_date]
    fresh = bool(dated) and (today - max(dated)).days <= 30
    sources = len({c.source for c in sales})
    if n >= 8 and spread <= 0.35 and fresh:
        return "High"
    if n >= 4 and spread <= 0.6 and (fresh or sources > 1):
        return "Medium"
    if n >= 3 and sources > 1 and spread <= 0.5:
        return "Medium"
    return "Low"
