"""PIN entry for the hidden vault: a compact panel that slides up from the
bottom of the overlay housing.

The numpad keys use the same keycap construction as deck keys (raised
gradient, seam border, press depress) but carry no LED — they are input, not
actions. Wrong PIN: the dot row shakes once, flashes fault-red, clears, and
says only "Wrong code." Nothing hints at how important the vault is.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from hoverdeck.ui import theme

PIN_MIN = 4
PIN_MAX = 6
WRONG_CODE_COPY = "Wrong code."

_BACK = "back"
_OK = "ok"


class PinKey(QWidget):
    """One numpad keycap: same construction as a deck key, no LED."""

    tapped = pyqtSignal(str)

    def __init__(self, label: str, value: str, size: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._value = value
        self._pressed = False
        self._hover = False
        self._size = size or theme.PIN_KEY_SIZE
        self.setFixedSize(self._size, self._size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.tapped.emit(self._value)

    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -1.5)
        if self._pressed:
            painter.translate(0, 1)
        radius = theme.key_radius(self._size)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        base = theme.KEYCAP_HOVER if self._hover else theme.KEYCAP
        top, bottom = theme.keycap_gradient(base, self._pressed)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setFont(theme.label_font(theme.TITLE_POINT_SIZE))
        painter.setPen(theme.qcolor(theme.INK))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)


class PinDots(QWidget):
    """4-6 fill dots; amber when filled; flashes and shakes as one unit."""

    def __init__(self, reduce_motion: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduce_motion = reduce_motion
        self._count = 0
        self._flash: str | None = None  # None | "live" | "fault"
        self._dx = 0.0
        d, gap = theme.PIN_DOT_DIAMETER, theme.PIN_DOT_GAP
        self.setFixedHeight(d * 3)
        self.setMinimumWidth(PIN_MAX * d + (PIN_MAX - 1) * gap + theme.SHAKE_AMPLITUDE * 2)

        amp = float(theme.SHAKE_AMPLITUDE)
        self._shake = QVariantAnimation(self)
        self._shake.setDuration(theme.SHAKE_MS)
        self._shake.setStartValue(0.0)
        for fraction, value in ((0.2, -amp), (0.4, amp),
                                (0.6, -amp * 0.75), (0.8, amp * 0.75)):
            self._shake.setKeyValueAt(fraction, value)
        self._shake.setEndValue(0.0)
        self._shake.valueChanged.connect(self._on_shake)

    def set_count(self, count: int) -> None:
        self._count = count
        self._flash = None
        self.update()

    def flash(self, kind: str) -> None:
        self._flash = kind
        self.update()

    def shake(self) -> None:
        if not self._reduce_motion:
            self._shake.start()

    def _on_shake(self, value: object) -> None:
        self._dx = float(value)  # type: ignore[arg-type]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self._dx, 0)
        painter.setPen(Qt.PenStyle.NoPen)

        d, gap = theme.PIN_DOT_DIAMETER, theme.PIN_DOT_GAP
        shown = max(PIN_MIN, min(PIN_MAX, max(self._count, PIN_MIN)))
        total = shown * d + (shown - 1) * gap
        x = self.width() / 2 - total / 2
        y = self.height() / 2 - d / 2
        for i in range(shown):
            if self._flash == "fault":
                token = theme.FAULT
            elif self._flash == "live":
                token = theme.LIVE
            elif i < self._count:
                token = theme.SIGNAL
            else:
                token = theme.SEAM
            painter.setBrush(theme.qcolor(token))
            painter.drawEllipse(QRectF(x, y, d, d))
            x += d + gap


class PinPad(QWidget):
    """The slide-up PIN panel. The overlay validates; this widget only collects."""

    pin_submitted = pyqtSignal(str)
    dismissed = pyqtSignal()

    def __init__(self, reduce_motion: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self._reduce_motion = reduce_motion
        self._pin = ""
        self._slide: QPropertyAnimation | None = None

        layout = QVBoxLayout(self)
        pad = theme.OVERLAY_PADDING
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(theme.SECTION_SPACING)

        self._dots = PinDots(reduce_motion, self)
        layout.addWidget(self._dots, 0, Qt.AlignmentFlag.AlignHCenter)

        self._message = QLabel("")
        self._message.setFont(theme.mono_font(theme.LABEL_POINT_SIZE + 1))
        self._message.setStyleSheet(f"color: {theme.FAULT};")  # token-sourced
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setFixedHeight(self._message.sizeHint().height())
        self._message.setText("")
        layout.addWidget(self._message)

        self._grid = QGridLayout()
        self._grid.setSpacing(theme.GRID_GUTTER // 2 + 1)
        layout.addLayout(self._grid)
        self._build_keys(theme.PIN_KEY_SIZE)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(theme.WRONG_CODE_HOLD_MS)
        self._message_timer.timeout.connect(lambda: self._message.setText(""))

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    def _build_keys(self, size: int) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        keys = [
            ("1", "1"), ("2", "2"), ("3", "3"),
            ("4", "4"), ("5", "5"), ("6", "6"),
            ("7", "7"), ("8", "8"), ("9", "9"),
            ("⌫", _BACK), ("0", "0"), ("↵", _OK),
        ]
        for index, (label, value) in enumerate(keys):
            key = PinKey(label, value, size, self)
            key.tapped.connect(self._on_key)
            self._grid.addWidget(key, index // 3, index % 3,
                                 Qt.AlignmentFlag.AlignCenter)

    def _fit_keys(self, parent: QWidget) -> None:
        """Shrink the numpad keys so the whole pad fits inside the housing."""
        overhead = (
            theme.OVERLAY_PADDING * 2
            + self._dots.height()
            + self._message.height()
            + theme.SECTION_SPACING * 2
            + self._grid.spacing() * 3
        )
        available = parent.height() - overhead
        size = max(theme.PIN_KEY_SIZE // 2, min(theme.PIN_KEY_SIZE, available // 4))
        self._build_keys(size)

    # ------------------------------------------------------------ open/close
    def open(self) -> None:
        """Slide up from the bottom of the housing."""
        self._pin = ""
        self._dots.set_count(0)
        self._message.setText("")
        parent = self.parentWidget()
        self._fit_keys(parent)
        self.setFixedWidth(parent.width())
        self.adjustSize()
        self.setFixedHeight(min(self.height(), parent.height()))
        end = QPoint(0, parent.height() - self.height())
        if self._reduce_motion:
            self.move(end)
            self.show()
            self.raise_()
            self.setFocus()
            return
        self.move(QPoint(0, parent.height()))
        self.show()
        self.raise_()
        self.setFocus()
        self._animate(end)

    def close_pad(self) -> None:
        parent = self.parentWidget()
        if self._reduce_motion:
            self.hide()
            self.dismissed.emit()
            return
        self._animate(QPoint(0, parent.height()), then_hide=True)

    def _animate(self, end: QPoint, then_hide: bool = False) -> None:
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(theme.PIN_SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setEndValue(end)
        if then_hide:
            self._slide.finished.connect(self.hide)
            self._slide.finished.connect(self.dismissed)
        self._slide.start()

    # ------------------------------------------------------------- feedback
    def reject_wrong_code(self) -> None:
        """Shake once, flash fault, clear. Say only 'Wrong code.' (§4.4)."""
        self._pin = ""
        self._dots.flash("fault")
        self._dots.shake()
        self._message.setText(WRONG_CODE_COPY)
        self._message_timer.start()
        QTimer.singleShot(theme.PIN_FLASH_MS, lambda: self._dots.set_count(0))

    def accept_unlock(self) -> None:
        """Brief live-green flash, then slide away."""
        self._dots.flash("live")
        QTimer.singleShot(theme.PIN_FLASH_MS, self.close_pad)

    # ---------------------------------------------------------------- input
    def _on_key(self, value: str) -> None:
        if value == _BACK:
            self._pin = self._pin[:-1]
        elif value == _OK:
            self._submit()
            return
        elif len(self._pin) < PIN_MAX:
            self._pin += value
        self._dots.set_count(len(self._pin))

    def _submit(self) -> None:
        if PIN_MIN <= len(self._pin) <= PIN_MAX:
            pin, self._pin = self._pin, ""
            self.pin_submitted.emit(pin)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_pad()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
        elif key == Qt.Key.Key_Backspace:
            self._on_key(_BACK)
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self._on_key(chr(key))
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------- painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(theme.qcolor(theme.PANEL))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)
