"""The peek button: a half-circle indicator lamp mounted on the screen edge.

Shown while the deck is tucked away (§8.B). Signal-amber — the one
exterior-facing piece of the app. Hover brightens it, dragging slides it
along its edge, a click summons the deck back.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from hoverdeck.ui import screens, theme

EDGES = ("left", "right", "top", "bottom")


class PeekButton(QWidget):
    """D-shaped lamp protruding from a screen edge; flat side sits on the edge."""

    invoked = pyqtSignal()           # click: bring the deck back
    edge_moved = pyqtSignal(int)     # emitted on every drag move; new offset (px)
    quit_requested = pyqtSignal()    # right-click menu: quit the app

    def __init__(self, edge: str = "right", screen_name: str = "") -> None:
        super().__init__(None)
        self._edge = edge if edge in EDGES else "right"
        self._screen_name = screen_name
        self._vpn_enabled = False
        self._vpn_state: bool | None = None
        self._hover = False
        self._press_global: QPoint | None = None
        self._dragged = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        r = theme.PEEK_RADIUS
        if self._edge in ("left", "right"):
            self.setFixedSize(r, r * 2)
        else:
            self.setFixedSize(r * 2, r)

    @property
    def edge(self) -> str:
        return self._edge

    # ----------------------------------------------------------- placement
    def set_screen(self, name: str) -> None:
        """Re-target the lamp at a different monitor (caller re-``place``s)."""
        self._screen_name = name

    def set_vpn(self, enabled: bool, state: bool | None) -> None:
        """Show a small VPN status dot on the lamp (enabled), True/False/None."""
        if (enabled, state) != (self._vpn_enabled, self._vpn_state):
            self._vpn_enabled = enabled
            self._vpn_state = state
            self.update()

    def place(self, offset: int) -> None:
        """Position on the screen edge, ``offset`` px along it (clamped)."""
        area = screens.screen_area(self._screen_name)
        if area.isEmpty():
            return
        if self._edge == "right":
            x = area.right() - self.width() + 1
            y = max(area.top(), min(area.bottom() - self.height(), area.top() + offset))
        elif self._edge == "left":
            x = area.left()
            y = max(area.top(), min(area.bottom() - self.height(), area.top() + offset))
        elif self._edge == "top":
            x = max(area.left(), min(area.right() - self.width(), area.left() + offset))
            y = area.top()
        else:  # bottom
            x = max(area.left(), min(area.right() - self.width(), area.left() + offset))
            y = area.bottom() - self.height() + 1
        self.move(x, y)

    def offset(self) -> int:
        """Current position along the edge, relative to the screen edge start."""
        area = screens.screen_area(self._screen_name)
        if area.isEmpty():
            return 0
        if self._edge in ("left", "right"):
            return self.y() - area.top()
        return self.x() - area.left()

    # -------------------------------------------------------------- events
    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._dragged = False
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is None:
            return
        pos = event.globalPosition().toPoint()
        delta = pos - self._press_global
        if (
            not self._dragged
            and delta.manhattanLength() < QApplication.startDragDistance()
        ):
            return
        self._dragged = True
        # Slide along the edge axis only; place() keeps the flat side flush.
        if self._edge in ("left", "right"):
            self.place(self.offset() + delta.y())
        else:
            self.place(self.offset() + delta.x())
        self._press_global = pos
        self.edge_moved.emit(self.offset())  # persist as we go, not on close
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = None
            if not self._dragged:
                self.invoked.emit()
            event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.addAction("Show deck", self.invoked.emit)
        menu.addSeparator()
        menu.addAction("Quit HoverDeck", self.quit_requested.emit)
        menu.exec(event.globalPos())

    # ------------------------------------------------------------ painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = theme.PEEK_RADIUS
        # The lamp is a full circle whose center sits on the flat (edge) side;
        # the widget rect clips it into the protruding half.
        cx, cy = self.width() / 2, self.height() / 2
        if self._edge == "right":
            cx = float(self.width())
        elif self._edge == "left":
            cx = 0.0
        elif self._edge == "top":
            cy = 0.0
        else:
            cy = float(self.height())
        center = QPointF(cx, cy)

        base = theme.qcolor(theme.SIGNAL)
        if self._hover:
            base = base.lighter(theme.PEEK_HOVER_LIGHTER)

        path = QPainterPath()
        path.addEllipse(center, r - theme.SEAM_WIDTH, r - theme.SEAM_WIDTH)

        # Lamp face: lit from the core — a domed indicator, not a flat disc.
        lamp = QRadialGradient(center, r)
        lamp.setColorAt(0.0, base.lighter(126))
        lamp.setColorAt(0.55, base)
        lamp.setColorAt(1.0, base.darker(122))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.setBrush(lamp)
        painter.drawPath(path)

        # Glass sheen: bright reflection over the top half (same language as
        # the keycaps' glass treatment).
        painter.save()
        painter.setClipPath(path)
        sheen = QLinearGradient(
            QPointF(cx, cy - r), QPointF(cx, cy)
        )
        hi = QColor(theme.INK)
        hi.setAlpha(theme.GLASS_TOP_ALPHA)
        lo = QColor(theme.INK)
        lo.setAlpha(0)
        sheen.setColorAt(0.0, hi)
        sheen.setColorAt(1.0, lo)
        painter.fillPath(path, sheen)
        painter.restore()

        # Machined inner bezel: a darker ring just inside the rim.
        bezel = QColor(theme.PANEL)
        bezel.setAlpha(90)
        painter.setPen(QPen(bezel, theme.SEAM_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner = r - theme.SEAM_WIDTH * 3
        painter.drawEllipse(center, inner, inner)

        if self._vpn_enabled:
            self._paint_vpn_ring(painter, center, r)
        self._paint_chevron(painter, cx, cy)

    def _paint_vpn_ring(self, painter: QPainter, center: QPointF, r: float) -> None:
        """VPN status as a thin arc hugging the lamp's curved rim.

        Reads as part of the instrument — a status ring, not a sticker:
        green = tunnel carries the traffic, red = it doesn't, dim = unknown.
        """
        color = (
            theme.LIVE if self._vpn_state is True
            else theme.FAULT if self._vpn_state is False
            else theme.INK_DIM
        )
        ring_w = max(2.0, r * 0.14)
        ring_r = r - theme.SEAM_WIDTH * 2 - ring_w / 2

        # The visible half-circle, per edge (Qt angles: 0° = 3 o'clock, CCW).
        start = {"right": 90, "left": 270, "top": 180, "bottom": 0}[self._edge]
        margin = 16          # leave breathing room at the screen edge
        span = 180 - margin * 2

        rect = QRectF(center.x() - ring_r, center.y() - ring_r,
                      ring_r * 2, ring_r * 2)
        # Soft under-glow first, then the crisp ring.
        glow = theme.qcolor(color, theme.LED_GLOW_ALPHA)
        pen = QPen(glow, ring_w * 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, (start + margin) * 16, span * 16)

        pen = QPen(theme.qcolor(color), ring_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, (start + margin) * 16, span * 16)

    def _paint_chevron(self, painter: QPainter, cx: float, cy: float) -> None:
        """Two strokes pointing inward — the deck slides back this way."""
        size = theme.PEEK_RADIUS * 0.30
        pen = QPen(theme.qcolor(theme.PANEL), theme.SEAM_WIDTH * 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Tip offset from the lamp center, toward screen center.
        if self._edge == "right":
            tip = QPointF(cx - theme.PEEK_RADIUS * 0.62, cy)
            a = QPointF(tip.x() + size, tip.y() - size)
            b = QPointF(tip.x() + size, tip.y() + size)
        elif self._edge == "left":
            tip = QPointF(cx + theme.PEEK_RADIUS * 0.62, cy)
            a = QPointF(tip.x() - size, tip.y() - size)
            b = QPointF(tip.x() - size, tip.y() + size)
        elif self._edge == "top":
            tip = QPointF(cx, cy + theme.PEEK_RADIUS * 0.62)
            a = QPointF(tip.x() - size, tip.y() - size)
            b = QPointF(tip.x() + size, tip.y() - size)
        else:  # bottom
            tip = QPointF(cx, cy - theme.PEEK_RADIUS * 0.62)
            a = QPointF(tip.x() - size, tip.y() + size)
            b = QPointF(tip.x() + size, tip.y() + size)
        painter.drawLine(a, tip)
        painter.drawLine(tip, b)
