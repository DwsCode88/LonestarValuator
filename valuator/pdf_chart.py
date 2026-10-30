"""Price history chart drawn as vector graphics for the PDF (same encoding as the in-app chart)."""
from __future__ import annotations

from datetime import date

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, String
from reportlab.lib import colors

from .history import History, nice_ticks

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
GRID = colors.HexColor("#E5E7EB")
LINE = colors.HexColor("#2F64A8")
DOT = colors.HexColor("#5E8FD6")
FMV = colors.HexColor("#C2570C")


def _money(v: float) -> str:
    if v >= 10000:
        return f"${v/1000:,.0f}k"
    if v >= 1000:
        return f"${v/1000:,.1f}k"
    return f"${v:,.0f}" if v >= 10 else f"${v:,.2f}"


def history_drawing(h: History, fmv: float | None, width: float, height: float = 150) -> Drawing | None:
    if not h or not h.usable:
        return None
    d = Drawing(width, height)
    left, right, top, bottom = 44, 6, 20, 18
    pw, ph = width - left - right, height - top - bottom
    prices = [v for _, v in h.points] + ([fmv] if fmv else [])
    ticks = nice_ticks(min(prices) * 0.95, max(prices) * 1.05)
    y0, y1 = ticks[0], ticks[-1]
    d0, d1 = h.start.toordinal(), h.end.toordinal()

    def X(day: date) -> float:
        return left + (day.toordinal() - d0) / max(d1 - d0, 1) * pw

    def Y(v: float) -> float:
        return bottom + (v - y0) / max(y1 - y0, 1e-9) * ph

    for t in ticks:
        d.add(Line(left, Y(t), left + pw, Y(t), strokeColor=GRID, strokeWidth=0.6))
        d.add(String(left - 5, Y(t) - 2.5, _money(t), fontName="Helvetica", fontSize=7,
                     fillColor=MUTED, textAnchor="end"))
    for day, anchor in ((h.start, "start"), (date.fromordinal((d0 + d1) // 2), "middle"), (h.end, "end")):
        d.add(String(X(day), 4, day.strftime("%b %d, %Y"), fontName="Helvetica", fontSize=7,
                     fillColor=MUTED, textAnchor=anchor))
    if fmv:
        d.add(Line(left, Y(fmv), left + pw, Y(fmv), strokeColor=FMV, strokeWidth=1, strokeDashArray=[4, 3]))
    for day, v in h.points:
        d.add(Circle(X(day), Y(v), 2.6, fillColor=DOT, strokeColor=colors.white, strokeWidth=0.8))
    if len(h.median) >= 2:
        pts = []
        for day, v in h.median:
            pts += [X(day), Y(v)]
        d.add(PolyLine(pts, strokeColor=LINE, strokeWidth=1.6))
    # legend
    lx, ly = left, height - 9
    d.add(Circle(lx + 3, ly + 2.5, 2.6, fillColor=DOT, strokeColor=colors.white, strokeWidth=0.8))
    d.add(String(lx + 9, ly, "Sale", fontName="Helvetica", fontSize=7.5, fillColor=INK))
    lx += 36
    d.add(Line(lx, ly + 2.5, lx + 12, ly + 2.5, strokeColor=LINE, strokeWidth=1.6))
    d.add(String(lx + 16, ly, "Rolling median", fontName="Helvetica", fontSize=7.5, fillColor=INK))
    lx += 78
    if fmv:
        d.add(Line(lx, ly + 2.5, lx + 12, ly + 2.5, strokeColor=FMV, strokeWidth=1, strokeDashArray=[4, 3]))
        d.add(String(lx + 16, ly, "Fair market value", fontName="Helvetica", fontSize=7.5, fillColor=INK))
    if h.change_pct is not None:
        d.add(String(left + pw, ly, f"{'+' if h.change_pct >= 0 else ''}{h.change_pct:.0f}% over period",
                     fontName="Helvetica", fontSize=7.5, fillColor=MUTED, textAnchor="end"))
    return d
