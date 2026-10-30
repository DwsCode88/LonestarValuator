"""Price history chart widget: sales as dots, rolling median as a line, FMV as a dashed rule."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..history import History, nice_ticks

INK = QColor("#1F2933")
MUTED = QColor("#6B7280")
GRID = QColor("#E5E7EB")
LINE = QColor("#2F64A8")
DOT = QColor("#5E8FD6")
FMV = QColor("#C2570C")


def money_short(v: float) -> str:
    if v >= 10000:
        return f"${v/1000:,.0f}k"
    if v >= 1000:
        return f"${v/1000:,.1f}k"
    return f"${v:,.0f}" if v >= 10 else f"${v:,.2f}"


class PriceChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.h: History | None = None
        self.fmv: float | None = None
        self._dots: list[tuple[QPointF, date, float]] = []
        self.setMinimumHeight(170)
        self.setMouseTracking(True)

    def set_data(self, h: History, fmv: float | None):
        self.h, self.fmv = h, fmv
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        f = QFont(self.font()); f.setPointSizeF(8.5); p.setFont(f)
        self._dots = []
        h = self.h
        if not h or not h.usable:
            p.setPen(MUTED)
            p.drawText(self.rect(), Qt.AlignCenter, "Not enough dated sales for a price history chart")
            return
        left, right, top, bottom = 58, 14, 26, 24
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        prices = [v for _, v in h.points] + ([self.fmv] if self.fmv else [])
        ticks = nice_ticks(min(prices) * 0.95, max(prices) * 1.05)
        y0, y1 = ticks[0], ticks[-1]
        d0, d1 = h.start.toordinal(), h.end.toordinal()

        def X(d: date) -> float:
            return plot.left() + (d.toordinal() - d0) / max(d1 - d0, 1) * plot.width()

        def Y(v: float) -> float:
            return plot.bottom() - (v - y0) / max(y1 - y0, 1e-9) * plot.height()

        # grid + y labels
        for t in ticks:
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(plot.left(), Y(t)), QPointF(plot.right(), Y(t)))
            p.setPen(MUTED)
            p.drawText(QRectF(0, Y(t) - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, money_short(t))
        # x labels: start, middle, end
        p.drawText(QRectF(X(h.start), plot.bottom() + 4, 90, 16), Qt.AlignLeft, h.start.strftime("%b %d, %Y"))
        mid = date.fromordinal((d0 + d1) // 2)
        p.drawText(QRectF(X(mid) - 45, plot.bottom() + 4, 90, 16), Qt.AlignHCenter, mid.strftime("%b %d"))
        p.drawText(QRectF(X(h.end) - 90, plot.bottom() + 4, 90, 16), Qt.AlignRight, h.end.strftime("%b %d, %Y"))
        # FMV rule
        if self.fmv:
            pen = QPen(FMV, 1.5, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot.left(), Y(self.fmv)), QPointF(plot.right(), Y(self.fmv)))
        # dots (with surface ring)
        for d, v in h.points:
            pt = QPointF(X(d), Y(v))
            p.setPen(QPen(QColor("white"), 1.5)); p.setBrush(DOT)
            p.drawEllipse(pt, 4, 4)
            self._dots.append((pt, d, v))
        # rolling median line
        if len(h.median) >= 2:
            path = QPainterPath(QPointF(X(h.median[0][0]), Y(h.median[0][1])))
            for d, v in h.median[1:]:
                path.lineTo(X(d), Y(v))
            p.setPen(QPen(LINE, 2.2)); p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        # legend (top-left) – text in ink, marks carry identity
        x = plot.left()
        p.setPen(QPen(QColor("white"), 1.5)); p.setBrush(DOT); p.drawEllipse(QPointF(x + 5, 12), 4, 4)
        p.setPen(INK); p.drawText(QPointF(x + 14, 16), "Sale"); x += 52
        p.setPen(QPen(LINE, 2.2)); p.drawLine(QPointF(x, 12), QPointF(x + 16, 12))
        p.setPen(INK); p.drawText(QPointF(x + 22, 16), "Rolling median"); x += 128
        if self.fmv:
            p.setPen(QPen(FMV, 1.5, Qt.DashLine)); p.drawLine(QPointF(x, 12), QPointF(x + 16, 12))
            p.setPen(INK); p.drawText(QPointF(x + 22, 16), f"Fair market value ${self.fmv:,.2f}")
        if h.change_pct is not None:
            p.setPen(MUTED)
            p.drawText(QRectF(plot.left(), 2, plot.width(), 18), Qt.AlignRight | Qt.AlignVCenter,
                       f"{'+' if h.change_pct >= 0 else ''}{h.change_pct:.0f}% over period")

    def mouseMoveEvent(self, e):
        pos = e.position()
        best = min(self._dots, key=lambda t: (t[0] - pos).manhattanLength(), default=None)
        if best and (best[0] - pos).manhattanLength() < 14:
            QToolTip.showText(e.globalPosition().toPoint(), f"{best[1]:%b %d, %Y}\n${best[2]:,.2f}", self)
        else:
            QToolTip.hideText()
