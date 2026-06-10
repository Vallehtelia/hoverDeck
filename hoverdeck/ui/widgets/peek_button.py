"""The peek button: a half-circle indicator lamp mounted on the screen edge.

Shown while the deck is tucked away (§8.B). Signal-amber — the one
exterior-facing piece of the app. Hover brightens it, dragging slides it
along its edge, a click summons the deck back.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from hoverdeck.ui import theme

EDGES = ("left", "right", "top", "bottom")


class PeekButton(QWidget):
    """D-shaped lamp protruding from a screen edge; flat side sits on the edge."""

    invoked = pyqtSignal()           # click: bring the deck back
    edge_moved = pyqtSignal(int)     # emitted on every drag move; new offset (px)

    def __init__(self, edge: str = "right") -> None:
        super().__init__(None)
        self._edge = edge if edge in EDGES else "right"
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
    def place(self, offset: int) -> None:
        """Position on the screen edge, ``offset`` px along it (clamped)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
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
        screen = QApplication.primaryScreen()
        if screen is None:
            return 0
        area = screen.availableGeometry()
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

        lamp = theme.qcolor(theme.SIGNAL)
        if self._hover:
            lamp = lamp.lighter(theme.PEEK_HOVER_LIGHTER)

        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), r - theme.SEAM_WIDTH, r - theme.SEAM_WIDTH)
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.setBrush(lamp)
        painter.drawPath(path)

        self._paint_chevron(painter, cx, cy)

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
