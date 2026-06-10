"""The keycap: a raised rounded-square key on the switchboard.

Construction (PLAN.md §4.2): 1px seam border + 2-stop vertical gradient so the
key reads as raised; pressing shifts it 1px down and flattens the gradient.
The signature element is the 5px indicator LED in the top-right corner —
idle (off) / running (amber pulse) / success (green blink, fade) / error
(red, holds until clicked). It is driven by the action runner's signals and
is the app's async feedback channel.

Edit mode (§8.A): bound keys get a small seam-colored pencil badge (top-left),
empty sockets invite with "+ Add a key", clicks open the editor instead of
firing, keys drag to rearrange (the key lifts; the target slot highlights
signal-amber), right-click offers Edit / Move / Delete.
"""
from __future__ import annotations

from enum import Enum, auto

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFocusEvent,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

from hoverdeck.core.models import Action
from hoverdeck.ui import edit_mode as editing
from hoverdeck.ui import theme


class LedState(Enum):
    IDLE = auto()
    RUNNING = auto()
    SUCCESS = auto()
    ERROR = auto()


_LED_COLOR = {
    LedState.RUNNING: theme.SIGNAL,
    LedState.SUCCESS: theme.LIVE,
    LedState.ERROR: theme.FAULT,
}

EMPTY_SLOT_COPY = "+ Add a key"
EDIT_BADGE_GLYPH = "✎"


class DeckButton(QWidget):
    """One key. ``action`` may be None: the slot renders as a recessed socket."""

    activated = pyqtSignal(str)        # action id (normal mode)
    edit_requested = pyqtSignal(int)   # slot index (edit mode click / Edit)
    delete_requested = pyqtSignal(int)
    move_requested = pyqtSignal(int)
    swap_requested = pyqtSignal(int, int)  # source slot, target slot (drop)

    def __init__(
        self,
        action: Action | None,
        slot_index: int = 0,
        size: int | None = None,
        reduce_motion: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._action = action
        self._slot_index = slot_index
        self._size = size or theme.BUTTON_SIZE_DEFAULT
        self._reduce_motion = reduce_motion

        self._pressed = False
        self._hover = False
        self._edit_mode = False
        self._drop_hover = False
        self._press_pos: QPoint | None = None
        self._led = LedState.IDLE
        self._led_level = 0.0  # 0..1 lamp brightness

        self.setFixedSize(self._size, self._size)
        self.setAcceptDrops(True)
        self._apply_interactivity()

        # Amber pulse while running: bright -> dim -> bright, mechanical ease.
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, theme.LED_PULSE_FLOOR)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(theme.LED_PULSE_MS)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._set_led_level)

        # Green success lamp fading back to off.
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setDuration(theme.SUCCESS_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._fade.valueChanged.connect(self._set_led_level)
        self._fade.finished.connect(self._after_fade)

        self._led_timer = QTimer(self)
        self._led_timer.setSingleShot(True)
        self._led_timer.timeout.connect(self._after_blink)

        self._depress_timer = QTimer(self)
        self._depress_timer.setSingleShot(True)
        self._depress_timer.setInterval(theme.KEY_DEPRESS_MS)
        self._depress_timer.timeout.connect(self._release_and_fire)

    # ------------------------------------------------------------------ API
    @property
    def action(self) -> Action | None:
        return self._action

    @property
    def slot_index(self) -> int:
        return self._slot_index

    def set_action(self, action: Action | None) -> None:
        self._action = action
        self.set_led_state(LedState.IDLE)
        self._apply_interactivity()
        self.update()

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self._apply_interactivity()
        self.update()

    def cancel_press(self) -> None:
        """Abort an in-flight press (e.g. it turned into a page swipe)."""
        self._pressed = False
        self._press_pos = None
        self.update()

    def set_led_state(self, state: LedState) -> None:
        """Drive the indicator lamp (wired to the runner's signals)."""
        self._pulse.stop()
        self._fade.stop()
        self._led_timer.stop()
        self._led = state

        if state is LedState.IDLE:
            self._led_level = 0.0
        elif state is LedState.RUNNING:
            self._led_level = 1.0
            if not self._reduce_motion:
                self._pulse.start()
        elif state is LedState.SUCCESS:
            self._led_level = 1.0
            if self._reduce_motion:
                self._led_timer.start(theme.SUCCESS_BLINK_MS + theme.SUCCESS_FADE_MS)
            else:
                self._led_timer.start(theme.SUCCESS_BLINK_MS)
        elif state is LedState.ERROR:
            self._led_level = 1.0  # holds until clicked
        self.update()

    def _apply_interactivity(self) -> None:
        interactive = self._action is not None or self._edit_mode
        if interactive:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.unsetCursor()
        if self._action is not None:
            self.setToolTip(self._action.name)
            self.setAccessibleName(self._action.name)
        else:
            self.setToolTip(EMPTY_SLOT_COPY if self._edit_mode else "")
            self.setAccessibleName(EMPTY_SLOT_COPY)

    # ------------------------------------------------------- LED internals
    def _set_led_level(self, value: object) -> None:
        self._led_level = float(value)  # type: ignore[arg-type]
        self.update()

    def _after_blink(self) -> None:
        if self._led is not LedState.SUCCESS:
            return
        if self._reduce_motion:
            self.set_led_state(LedState.IDLE)
        else:
            self._fade.start()

    def _after_fade(self) -> None:
        if self._led is LedState.SUCCESS:
            self.set_led_state(LedState.IDLE)

    # ------------------------------------------------------------ firing
    def _fire(self) -> None:
        if self._edit_mode:
            self.edit_requested.emit(self._slot_index)
            return
        if self._action is None:
            return
        if self._led is LedState.ERROR:  # a click acknowledges the fault
            self.set_led_state(LedState.IDLE)
        self.activated.emit(self._action.id)

    def _release_and_fire(self) -> None:
        self._pressed = False
        self.update()
        self._fire()

    # ------------------------------------------------------------- events
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._action is not None or self._edit_mode:
                self._pressed = True
                self._press_pos = event.position().toPoint()
                self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            if self._edit_mode and self._action is not None:
                self._show_key_menu(event.globalPosition().toPoint())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._edit_mode
            and self._pressed
            and self._action is not None
            and self._press_pos is not None
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._pressed = False
            self.update()
            editing.start_slot_drag(self, self._slot_index)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self._press_pos = None
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self._fire()
        super().mouseReleaseEvent(event)

    def _show_key_menu(self, global_pos: QPoint) -> None:
        choice = editing.show_key_menu(self, global_pos)
        if choice == "edit":
            self.edit_requested.emit(self._slot_index)
        elif choice == "move":
            self.move_requested.emit(self._slot_index)
        elif choice == "delete":
            self.delete_requested.emit(self._slot_index)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._action is None and not self._edit_mode:
                return
            if self._reduce_motion or self._edit_mode:
                self._fire()
            elif not self._depress_timer.isActive():
                self._pressed = True  # brief visual depress, then fire
                self.update()
                self._depress_timer.start()
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusOutEvent(event)

    # -------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        source = editing.slot_from_mime(event.mimeData())
        if self._edit_mode and source is not None and source != self._slot_index:
            self._drop_hover = True
            self.update()
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drop_hover = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_hover = False
        self.update()
        source = editing.slot_from_mime(event.mimeData())
        if source is not None and source != self._slot_index:
            event.acceptProposedAction()
            self.swap_requested.emit(source, self._slot_index)

    # ------------------------------------------------------------ painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1px slack at the bottom so the cap can sink without clipping.
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -1.5)
        radius = theme.key_radius(self._size)

        if self._action is None:
            self._paint_socket(painter, rect, radius)
            return

        if self._pressed:
            painter.translate(0, 1)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # Keycap face: raised 2-stop gradient (flattens while pressed).
        base = theme.KEYCAP_HOVER if self._hover else theme.KEYCAP
        if self._action.color:
            base = theme.tinted_keycap(base, self._action.color)
        top, bottom = theme.keycap_gradient(base, self._pressed)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(path, gradient)

        # Machined glint under the top edge.
        if not self._pressed:
            painter.save()
            painter.setClipPath(path)
            glint = QColor(theme.INK)
            glint.setAlpha(theme.TOP_HIGHLIGHT_ALPHA)
            painter.setPen(QPen(glint, 1))
            inset = radius * 0.7
            painter.drawLine(
                QPointF(rect.left() + inset, rect.top() + 1.5),
                QPointF(rect.right() - inset, rect.top() + 1.5),
            )
            painter.restore()

        # Seam border; focus ring and drop target are the same line in amber.
        border = (
            theme.SIGNAL if (self.hasFocus() or self._drop_hover) else theme.SEAM
        )
        painter.setPen(QPen(theme.qcolor(border), theme.FOCUS_RING_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        self._paint_legend(painter, rect)
        self._paint_led(painter, rect)
        if self._edit_mode:
            self._paint_edit_badge(painter, rect)
        painter.end()

    def _paint_socket(self, painter: QPainter, rect: QRectF, radius: int) -> None:
        """Empty slot: a recessed socket; in edit mode it invites a key."""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, theme.qcolor(theme.PANEL).darker(theme.SOCKET_DARKER))
        border = theme.SIGNAL if (self._drop_hover or self.hasFocus()) else theme.SEAM
        alpha = 255 if (self._drop_hover or self.hasFocus()) else 160
        painter.setPen(QPen(theme.qcolor(border, alpha), theme.SEAM_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if self._edit_mode:
            painter.setFont(theme.body_font(theme.LABEL_POINT_SIZE))
            painter.setPen(theme.qcolor(theme.INK_DIM))
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                EMPTY_SLOT_COPY,
            )
        painter.end()

    def _paint_legend(self, painter: QPainter, rect: QRectF) -> None:
        """Glyph (backlit symbol) + label plate lettering."""
        assert self._action is not None
        name = self._action.name
        glyph = self._action.icon

        if glyph:
            painter.setFont(theme.glyph_font(round(self._size * theme.ICON_SIZE_RATIO)))
            painter.setPen(theme.qcolor(theme.INK))
            glyph_rect = QRectF(rect.left(), rect.top() + rect.height() * 0.12,
                                rect.width(), rect.height() * 0.46)
            painter.drawText(glyph_rect, Qt.AlignmentFlag.AlignCenter, glyph)

        font = theme.label_font()
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.INK_DIM if glyph else theme.INK))
        metrics = painter.fontMetrics()
        pad = rect.width() * 0.08
        text = metrics.elidedText(
            name, Qt.TextElideMode.ElideRight, round(rect.width() - 2 * pad)
        )
        label_rect = (
            QRectF(rect.left() + pad, rect.top() + rect.height() * 0.62,
                   rect.width() - 2 * pad, rect.height() * 0.30)
            if glyph
            else QRectF(rect.left() + pad, rect.top(), rect.width() - 2 * pad,
                        rect.height())
        )
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_led(self, painter: QPainter, rect: QRectF) -> None:
        """The 5px indicator lamp in the top-right corner."""
        center = QPointF(rect.right() - theme.LED_INSET, rect.top() + theme.LED_INSET)
        r = theme.LED_DIAMETER / 2

        painter.setPen(Qt.PenStyle.NoPen)
        if self._led is LedState.IDLE or self._led_level <= 0.0:
            painter.setBrush(theme.qcolor(theme.SEAM, theme.LED_IDLE_ALPHA))
            painter.drawEllipse(center, r, r)
            return

        color = theme.qcolor(_LED_COLOR[self._led])
        level = max(0.0, min(1.0, self._led_level))

        halo = QColor(color)
        halo.setAlpha(round(theme.LED_GLOW_ALPHA * level))
        painter.setBrush(halo)
        painter.drawEllipse(center, r * 2.2, r * 2.2)

        lamp = QColor(color)
        lamp.setAlpha(round(255 * level))
        painter.setBrush(lamp)
        painter.drawEllipse(center, r, r)

    def _paint_edit_badge(self, painter: QPainter, rect: QRectF) -> None:
        """Small seam-colored pencil, top-left: this key is editable."""
        painter.setFont(theme.glyph_font(theme.EDIT_BADGE_SIZE))
        painter.setPen(QPen(theme.qcolor(theme.SEAM).lighter(theme.EDIT_BADGE_LIGHTER), 1))
        badge = QRectF(
            rect.left() + theme.EDIT_BADGE_INSET / 2,
            rect.top() + theme.EDIT_BADGE_INSET / 2,
            theme.EDIT_BADGE_SIZE * 1.6,
            theme.EDIT_BADGE_SIZE * 1.6,
        )
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, EDIT_BADGE_GLYPH)
