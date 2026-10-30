"""Branded customer appraisal PDF."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from . import engine, history
from .models import Comp, Item, replacement_value
from .pdf_chart import history_drawing

MUTED = colors.HexColor("#5B6573")
LINE = colors.HexColor("#D5DAE1")
SOFT = colors.HexColor("#F3F5F8")


def money(v: Optional[float]) -> str:
    return "—" if v is None else f"${v:,.2f}"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles(accent):
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=12.5)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=10.5),
        "cellr": ParagraphStyle("cellr", parent=base, fontSize=8.5, leading=10.5, alignment=TA_RIGHT),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=20,
                                leading=24, textColor=accent),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16,
                             textColor=accent, spaceBefore=6, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                             spaceBefore=4, spaceAfter=3),
        "label": ParagraphStyle("label", parent=base, fontSize=7.5, leading=9, textColor=MUTED),
        "big": ParagraphStyle("big", parent=base, fontName="Helvetica-Bold", fontSize=22, leading=26,
                              textColor=accent),
        "bigc": ParagraphStyle("bigc", parent=base, fontName="Helvetica-Bold", fontSize=24, leading=28,
                               textColor=accent, alignment=TA_CENTER),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT, fontSize=8.5, leading=11,
                                textColor=MUTED),
    }


def _img(path: Optional[Path], max_w: float, max_h: float):
    if not path:
        return ""
    try:
        ir = ImageReader(str(path))
        w, h = ir.getSize()
        scale = min(max_w / w, max_h / h)
        return Image(str(path), width=w * scale, height=h * scale)
    except Exception:
        return ""


class ReportPDF:
    def __init__(self, settings: dict, report: dict, items: list[Item],
                 comps_by_item: dict[int, list[Comp]], images: dict[int, Optional[Path]],
                 logo: Optional[Path] = None):
        self.s = settings
        self.r = report
        self.items = items
        self.comps = comps_by_item
        self.images = images
        self.logo = logo
        self.accent = colors.HexColor(settings.get("accent_color") or "#1F3A5F")
        self.st = _styles(self.accent)
        self.show_rv = bool(report.get("show_replacement"))
        pct = report.get("replacement_pct")
        self.rv_pct = float(pct if pct is not None else settings.get("replacement_pct", 20) or 0)

    def rv(self, v):
        return replacement_value(v, self.rv_pct)

    # ---------- page chrome ----------
    def _page(self, canvas, doc):
        canvas.saveState()
        w, h = letter
        canvas.setFillColor(self.accent)
        canvas.rect(0, h - 0.18 * inch, w, 0.18 * inch, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.6 * inch, 0.45 * inch,
                          f"{self.s.get('store_name', '')} · Valuation Report {self.r.get('number', '')}")
        canvas.drawRightString(w - 0.6 * inch, 0.45 * inch, f"Page {doc.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(0.6 * inch, 0.6 * inch, w - 0.6 * inch, 0.6 * inch)
        canvas.restoreState()

    # ---------- sections ----------
    def _header(self):
        st = self.st
        store_lines = [f"<b>{_esc(self.s.get('store_name', ''))}</b>"]
        for k in ("store_address", "store_phone", "store_email", "store_website"):
            if self.s.get(k):
                store_lines.append(_esc(self.s[k]))
        logo = _img(self.logo, 1.9 * inch, 0.95 * inch)
        t = Table([[logo, Paragraph("<br/>".join(store_lines), st["right"])]],
                  colWidths=[3.6 * inch, 3.7 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        return [t, Spacer(1, 14), Paragraph("Trading Card Valuation Report", st["title"]), Spacer(1, 8)]

    def _info_block(self, total, low, high):
        st = self.st
        created = self.r.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created).strftime("%B %d, %Y")
        except ValueError:
            created = date.today().strftime("%B %d, %Y")

        def kv(label, val):
            return [Paragraph(label.upper(), st["label"]), Paragraph(_esc(val) or "—", st["base"])]

        cust = [self.r.get("customer_name", "")]
        for k in ("customer_address", "customer_phone", "customer_email"):
            if self.r.get(k):
                cust.append(self.r[k])
        left = Table([kv("Report number", self.r.get("number", "")), kv("Report date", created),
                      kv("Purpose", self.r.get("purpose", "")),
                      [Paragraph("PREPARED FOR", st["label"]),
                       Paragraph("<br/>".join(_esc(c) for c in cust if c) or "—", st["base"])]],
                     colWidths=[1.25 * inch, 2.5 * inch])
        left.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        n_cards = sum(i.qty for i in self.items)
        lc = ParagraphStyle("lc", parent=st["label"], alignment=TA_CENTER)
        sc = ParagraphStyle("sc", parent=st["small"], alignment=TA_CENTER)
        rows = [[Paragraph("TOTAL ESTIMATED FAIR MARKET VALUE", lc)],
                [Paragraph(money(total), st["bigc"])],
                [Paragraph(f"Range {money(low)} – {money(high)}", sc)]]
        if self.show_rv:
            rvc = ParagraphStyle("rvc", parent=st["base"], alignment=TA_CENTER, fontSize=11, leading=15)
            rows += [[Spacer(1, 4)],
                     [Paragraph("INSURANCE REPLACEMENT VALUE", lc)],
                     [Paragraph(f"<b>{money(self.rv(total))}</b>", rvc)],
                     [Paragraph(f"Fair market value + {self.rv_pct:g}% replacement cost", sc)]]
        rows.append([Paragraph(f"{len(self.items)} line item(s) · {n_cards} card(s)", sc)])
        right = Table(rows, colWidths=[3.3 * inch])
        right.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                   ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                   ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
        t = Table([[left, right]], colWidths=[3.9 * inch, 3.4 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return [t, Spacer(1, 16)]

    def _summary_table(self):
        st = self.st
        head = ["#", "", "Card", "Condition", "Qty", "Unit value", "Total"]
        if self.show_rv:
            head.append("Replacement")
        head.append("Confidence")
        hs = ParagraphStyle("hs", parent=st["cell"], fontSize=7.5, leading=9)
        hsr = ParagraphStyle("hsr", parent=hs, alignment=TA_RIGHT)
        right_cols = {"Qty", "Unit value", "Total", "Replacement"}
        rows = [[Paragraph(f"<b>{h}</b>", hsr if h in right_cols else hs) for h in head]]
        for n, it in enumerate(self.items, 1):
            unit = it.final_value
            line = unit * it.qty if unit is not None else None
            sub = " · ".join(x for x in [it.set_name, it.game] if x)
            extra = []
            if it.graded and it.cert:
                extra.append(f"Cert {_esc(it.cert)}")
            if it.pop_label:
                extra.append(_esc(it.pop_label))
            row = [
                Paragraph(str(n), st["cell"]),
                _img(self.images.get(it.id), 0.38 * inch, 0.52 * inch),
                Paragraph(f"<b>{_esc(it.display_name)}</b><br/><font color='#5B6573' size='7.5'>{_esc(sub)}</font>",
                          st["cell"]),
                Paragraph(_esc(it.grade_label) + "".join(f"<br/><font size='7' color='#5B6573'>{x}</font>"
                                                         for x in extra), st["cell"]),
                Paragraph(str(it.qty), st["cellr"]),
                Paragraph(money(unit), st["cellr"]),
                Paragraph(money(line), st["cellr"]),
            ]
            if self.show_rv:
                row.append(Paragraph(money(self.rv(line)), st["cellr"]))
            row.append(Paragraph("Manual" if it.value_override is not None else (it.confidence or "—"), st["cell"]))
            rows.append(row)
        widths = (0.3, 0.45, 1.95, 1.0, 0.35, 0.8, 0.8, 0.85, 0.8) if self.show_rv \
            else (0.3, 0.5, 2.2, 1.05, 0.4, 0.85, 0.85, 0.95)
        t = Table(rows, colWidths=[w * inch for w in widths], repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 1, self.accent),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return [Paragraph("Summary of Items", st["h2"]), t]

    def _item_detail(self, n: int, it: Item):
        st = self.st
        comps = self.comps.get(it.id, [])
        v = engine.value(comps, self.s)
        pop = ""
        if it.graded and it.pop_total is not None:
            pop = f"{it.pop_total:,} at {it.grader} {it.grade}"
            if it.pop_higher is not None:
                pop += f", {it.pop_higher:,} graded higher"
            if it.pop_source:
                pop += f"<br/><font size='7' color='#5B6573'>{_esc(it.pop_source)}</font>"
        details = [
            ("Game", it.game), ("Year", it.year), ("Set", it.set_name), ("Card number", it.number),
            ("Variant", it.variant), ("Language", it.language),
            ("Condition" if not it.graded else "Grade",
             it.grade_label + (f" ({it.cert_desc})" if it.graded and it.cert_desc
                               and it.cert_desc.upper() != it.grade_label.upper() else "")),
            ("Cert number", it.cert if it.graded else ""), ("Population", "__POP__" if pop else ""),
            ("Quantity", str(it.qty)),
        ]
        drows = [[Paragraph(k.upper(), st["label"]),
                  Paragraph(pop if val == "__POP__" else _esc(val), st["cell"])]
                 for k, val in details if val]
        dt = Table(drows, colWidths=[0.95 * inch, 1.75 * inch])
        dt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        if it.value_override is not None:
            val_lines = [[Paragraph("ESTIMATED FAIR MARKET VALUE (EACH)", st["label"])],
                         [Paragraph(money(it.value_override), st["big"])],
                         [Paragraph("Appraiser-determined value" +
                                    (f": {_esc(it.override_note)}" if it.override_note else ""), st["small"])]]
            if it.fmv is not None:
                val_lines.append([Paragraph(f"Market data indicated {money(it.fmv)} "
                                            f"(range {money(it.low)} – {money(it.high)})", st["small"])])
        else:
            val_lines = [[Paragraph("ESTIMATED FAIR MARKET VALUE (EACH)", st["label"])],
                         [Paragraph(money(it.fmv), st["big"])],
                         [Paragraph(f"Range {money(it.low)} – {money(it.high)}", st["small"])],
                         [Paragraph(f"Confidence: <b>{_esc(it.confidence or '—')}</b> · "
                                    f"{it.n_sales} qualifying sale(s)"
                                    + (f" · Trend: {_esc(it.trend)}" if it.trend else ""), st["small"])]]
        if it.qty > 1 and it.final_value is not None:
            val_lines.append([Paragraph(f"Line total ({it.qty}): <b>{money(it.final_value * it.qty)}</b>",
                                        st["small"])])
        if self.show_rv and it.final_value is not None:
            rv_line = f"Insurance replacement value: <b>{money(self.rv(it.final_value))}</b> each"
            if it.qty > 1:
                rv_line += f" · {money(self.rv(it.final_value * it.qty))} total"
            val_lines.append([Paragraph(rv_line, st["cell"])])
        vt = Table(val_lines, colWidths=[2.55 * inch])
        vt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                ("TOPPADDING", (0, 0), (0, 0), 7),
                                ("BOTTOMPADDING", (0, -1), (-1, -1), 8)]))
        img = _img(self.images.get(it.id), 1.75 * inch, 2.45 * inch) or Paragraph("No image", st["small"])
        top = Table([[img, dt, vt]], colWidths=[1.95 * inch, 2.75 * inch, 2.6 * inch])
        top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        flow = [Paragraph(f"Item {n}: {_esc(it.display_name)}", st["h2"]), top, Spacer(1, 10)]

        if self.s.get("chart_in_pdf", True):
            h = history.build(comps, self.s)
            chart = history_drawing(h, it.final_value, 7.3 * inch, 125)
            if chart:
                span = (h.end - h.start).days
                flow += [Paragraph(f"Price history (last {span} days, {len(h.points)} sales)", st["h3"]),
                         chart, Spacer(1, 8)]

        if v.by_source:
            rows = [[Paragraph(f"<b>{h}</b>", st["cell"]) for h in
                     ("Source", "Qualifying sales", "Median sale", "Guide / market value")]]
            for src, d in v.by_source.items():
                rows.append([Paragraph(src, st["cell"]), Paragraph(str(d["n"]), st["cellr"]),
                             Paragraph(money(d["median"]), st["cellr"]),
                             Paragraph(money(d["guide"]), st["cellr"])])
            t = Table(rows, colWidths=[2.0 * inch, 1.5 * inch, 1.6 * inch, 2.2 * inch])
            t.setStyle(self._grid())
            flow += [Paragraph("Data sources", st["h3"]), t, Spacer(1, 8)]

        show_n = int(self.s.get("show_comps_in_pdf", 8) or 0)
        used = sorted(v.used, key=lambda c: c.sale_date or date.min, reverse=True)[:show_n]
        if used:
            rows = [[Paragraph(f"<b>{h}</b>", st["cell"]) for h in ("Date", "Source", "Listing", "Price")]]
            for c in used:
                rows.append([Paragraph(c.sale_date.strftime("%m/%d/%Y") if c.sale_date else "—", st["cell"]),
                             Paragraph(_esc(c.source), st["cell"]),
                             Paragraph(_esc(c.title[:95]), st["cell"]),
                             Paragraph(money(c.price), st["cellr"])])
            t = Table(rows, colWidths=[0.85 * inch, 0.85 * inch, 4.75 * inch, 0.85 * inch], repeatRows=1)
            t.setStyle(self._grid())
            flow += [Paragraph(f"Recent comparable sales (showing {len(used)} of {v.n_sales})", st["h3"]), t]
        if v.method:
            flow += [Spacer(1, 5), Paragraph(f"Method: {_esc(v.method)}.", st["small"])]
        if it.notes:
            flow += [Spacer(1, 4), Paragraph(f"Notes: {_esc(it.notes)}", st["small"])]
        return flow

    def _grid(self):
        return TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, self.accent),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])

    def _closing(self):
        st = self.st
        method = (
            "Values are estimated from recent completed sales of the same card in the same condition "
            "or grade, gathered from eBay, 130point, and TCGplayer, together with price-guide values "
            "from PriceCharting and TCGplayer market prices. Listings that do not match the card, "
            "condition, grade or language are excluded, duplicate listings are merged, and statistical "
            "outliers are removed. More recent sales carry more weight. Confidence reflects the number, "
            "consistency and recency of qualifying sales."
        )
        if self.show_rv:
            method += (f" Insurance replacement value is fair market value plus {self.rv_pct:g}%, reflecting "
                       "the typical additional cost of re-acquiring an equivalent card at retail (dealer "
                       "margin, sales tax, shipping and insurance in transit).")
        if any(i.graded and i.pop_total is not None for i in self.items):
            method += (" Population figures are the number of cards the grading company reports at the "
                       "stated grade and higher, as of the date shown, and change as more cards are graded.")
        if self.r.get("notes"):
            yield Paragraph("Notes", st["h2"])
            yield Paragraph(_esc(self.r["notes"]).replace("\n", "<br/>"), st["base"])
        yield Paragraph("Methodology", st["h2"])
        yield Paragraph(method, st["base"])
        yield Paragraph("Disclaimer", st["h2"])
        yield Paragraph(_esc(self.s.get("disclaimer", "")), st["small"])
        sig = Table([["", "", ""],
                     [Paragraph(f"{_esc(self.s.get('appraiser_name', ''))}<br/>"
                                f"<font color='#5B6573' size='8'>{_esc(self.s.get('appraiser_title', ''))}, "
                                f"{_esc(self.s.get('store_name', ''))}</font>", st["base"]),
                      "", Paragraph("Date", st["base"])]],
                    colWidths=[3.4 * inch, 0.5 * inch, 1.8 * inch], rowHeights=[0.45 * inch, None])
        sig.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.8, colors.black),
                                 ("LINEBELOW", (2, 0), (2, 0), 0.8, colors.black),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        yield Spacer(1, 18)
        yield KeepTogether([sig])

    def build(self, out_path: Path) -> Path:
        doc = SimpleDocTemplate(str(out_path), pagesize=letter, leftMargin=0.6 * inch,
                                rightMargin=0.6 * inch, topMargin=0.55 * inch, bottomMargin=0.8 * inch,
                                title=f"Valuation Report {self.r.get('number', '')}",
                                author=self.s.get("store_name", ""))
        vals = [(i.final_value, i.qty, i) for i in self.items]
        total = sum(v * q for v, q, _ in vals if v is not None)
        low = sum((i.value_override if i.value_override is not None else (i.low or 0)) * i.qty
                  for _, _, i in vals)
        high = sum((i.value_override if i.value_override is not None else (i.high or 0)) * i.qty
                   for _, _, i in vals)
        story = self._header() + self._info_block(total, low, high) + self._summary_table()
        for n, it in enumerate(self.items, 1):
            story += [PageBreak()] + self._item_detail(n, it)
        story.append(PageBreak())
        story += list(self._closing())
        doc.build(story, onFirstPage=self._page, onLaterPages=self._page)
        return out_path
