"""The AI Builder chat panel: describe an automation, get a deck key.

Bubbles read like panel readouts: user messages right-aligned on keycap
metal, agent messages left-aligned on housing metal with a seam border, JSON
in Plex Mono. The live-green ADD TO DECK lamp appears only when the agent
has produced a valid action.
"""
from __future__ import annotations

import asyncio

from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QThread, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.core.ai_builder import (
    AIBuilder,
    AIBuilderError,
    BuilderContext,
    BuilderResponse,
    INTRO_MESSAGE,
    _URL_RE,
)
from hoverdeck.core.models import Action, Settings
from hoverdeck.ui import theme
from hoverdeck.utils.logging import get_logger

log = get_logger("ai_panel")

PARSE_ERROR_COPY = "Could not parse action JSON — ask the agent to try again."
URL_CHIP_COPY = "URL captured — will be inserted into action"
ADD_TO_DECK_COPY = "ADD TO DECK"
_MAX_INPUT_LINES = 3


class _SendWorker(QThread):
    """Runs one builder turn (async + streaming) off the UI thread."""

    chunk = pyqtSignal(str)
    done = pyqtSignal(object)   # BuilderResponse
    failed = pyqtSignal(str)

    def __init__(self, builder: AIBuilder, message: str, context: BuilderContext,
                 parent: QWidget) -> None:
        super().__init__(parent)
        self._builder = builder
        self._message = message
        self._context = context

    def run(self) -> None:
        try:
            response = asyncio.run(
                self._builder.send(self._message, self._context,
                                   on_chunk=self.chunk.emit)
            )
        except AIBuilderError as exc:
            self.failed.emit(str(exc))
        except Exception:  # noqa: BLE001 - the panel must never crash
            log.exception("AI builder turn crashed")
            self.failed.emit("Connection failed — check your key and network.")
        else:
            self.done.emit(response)


class ChatBubble(QFrame):
    """One message. Agent bubbles are housing metal; user bubbles keycap metal."""

    def __init__(self, role: str, text: str = "", fault: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._role = role
        self._fault = fault
        self._layout = QVBoxLayout(self)
        pad = theme.BUBBLE_PADDING
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(theme.CONTROL_PADDING // 2)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        # Alternate prose/code on the fences; JSON readouts go mono (§8.C).
        for index, segment in enumerate(text.split("```")):
            is_code = index % 2 == 1
            if is_code and segment.startswith(("json\n", "json\r\n")):
                segment = segment.split("\n", 1)[1] if "\n" in segment else ""
            segment = segment.strip("\n")
            if not segment.strip():
                continue
            label = QLabel(segment)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setFont(theme.mono_font() if is_code else theme.body_font())
            if is_code:
                label.setProperty("role", "dim")
            self._layout.addWidget(label)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = theme.KEYCAP if self._role == "user" else theme.PANEL
        border = theme.FAULT if self._fault else theme.SEAM
        painter.setBrush(theme.qcolor(fill))
        painter.setPen(QPen(theme.qcolor(border), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, theme.BUBBLE_RADIUS, theme.BUBBLE_RADIUS)


class TypingIndicator(QWidget):
    """Three seam-colored dots, pulsing while we wait for the first token."""

    def __init__(self, reduce_motion: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        dot = theme.LED_DIAMETER
        self.setFixedSize(dot * 7, dot * 3)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(theme.LED_PULSE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        if not reduce_motion:
            self._anim.start()

    def _tick(self, value: object) -> None:
        self._phase = float(value)  # type: ignore[arg-type]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        dot = theme.LED_DIAMETER
        for i in range(3):
            offset = (self._phase + i / 3) % 1.0
            level = theme.LED_PULSE_FLOOR + (1 - theme.LED_PULSE_FLOOR) * abs(1 - 2 * offset)
            painter.setBrush(theme.qcolor(theme.SEAM, round(255 * level)))
            painter.drawEllipse(QRectF(i * dot * 2.2 + dot, dot, dot, dot))

    def stop(self) -> None:
        self._anim.stop()


class _ChatInput(QPlainTextEdit):
    """Multi-line input, capped at 3 lines; Enter sends, Shift+Enter breaks."""

    submitted = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        metrics = self.fontMetrics()
        pad = theme.CONTROL_PADDING * 2
        self.setFixedHeight(metrics.lineSpacing() * _MAX_INPUT_LINES + pad * 2)
        self.setPlaceholderText("Describe what you want to automate")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AIBuilderPanel(QWidget):
    """The chat column. The overlay decides whether it slides in or floats."""

    action_ready = pyqtSignal(object)  # Action confirmed by the user
    closed = pyqtSignal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._builder = AIBuilder(settings.ai_provider, settings.ai_api_key)
        self._context = BuilderContext()
        self._worker: _SendWorker | None = None
        self._stream_bubble: ChatBubble | None = None
        self._stream_text = ""
        self._typing: TypingIndicator | None = None
        self._pending_action: Action | None = None

        self.setFixedWidth(theme.AI_PANEL_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SECTION_SPACING)

        # Header: an engraved label plate with the one amber accent.
        header = QHBoxLayout()
        title = QLabel("AI Builder")
        title.setFont(theme.title_font())
        title.setStyleSheet(f"color: {theme.SIGNAL};")  # token-sourced
        close = QToolButton()
        close.setText("✕")
        close.clicked.connect(self.closed)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close)
        layout.addLayout(header)

        # Chat history.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        host = QWidget()
        self._chat = QVBoxLayout(host)
        self._chat.setContentsMargins(0, 0, theme.CONTROL_PADDING, 0)
        self._chat.setSpacing(theme.CONTROL_PADDING)
        self._chat.addStretch(1)
        self._scroll.setWidget(host)
        # New messages keep the latest turn in view.
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(hi))
        layout.addWidget(self._scroll, 1)

        # URL chip (visual feedback only; BuilderContext does the real work).
        self._url_chip = QLabel(URL_CHIP_COPY)
        self._url_chip.setProperty("role", "dim")
        self._url_chip.setVisible(False)
        layout.addWidget(self._url_chip)

        # Input row.
        input_row = QHBoxLayout()
        input_row.setSpacing(theme.CONTROL_PADDING)
        self._input = _ChatInput()
        self._input.submitted.connect(self._send)
        self._input.textChanged.connect(self._detect_url)
        self._send_btn = QPushButton("Send")
        self._send_btn.setProperty("variant", "primary")
        self._send_btn.clicked.connect(self._send)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(input_row)

        # The live-green confirmation lamp; appears only when ready_to_save.
        self._add_btn = QPushButton(ADD_TO_DECK_COPY)
        self._add_btn.setProperty("variant", "live")
        self._add_btn.setFont(theme.label_font(theme.TITLE_POINT_SIZE))
        self._add_btn.setVisible(False)
        self._add_btn.clicked.connect(self._add_to_deck)
        layout.addWidget(self._add_btn)

        self._add_bubble("agent", INTRO_MESSAGE)

    # ---------------------------------------------------------------- API
    def begin_session(self, macro_names: list[str], slot_count: int) -> None:
        """Refresh what the agent knows about the deck (called on open)."""
        self._context.existing_macros = macro_names
        self._context.deck_slot_count = slot_count

    def refresh_credentials(self) -> None:
        """Settings changed: new provider/key, same conversation."""
        history = self._builder.conversation_history
        self._builder = AIBuilder(
            self._settings.ai_provider, self._settings.ai_api_key
        )
        self._builder.conversation_history = history

    def confirm_added(self, name: str) -> None:
        self._add_bubble("agent", f'Added "{name}" to the deck.')

    def show_error(self, message: str) -> None:
        self._add_bubble("agent", message, fault=True)

    # ------------------------------------------------------------- sending
    def _send(self) -> None:
        if self._worker is not None:
            return  # one turn at a time
        message = self._input.toPlainText().strip()
        if not message:
            return
        if not self._settings.ai_api_key:
            self.show_error("No API key — add one in Settings.")
            return

        self._input.clear()
        self._url_chip.setVisible(False)
        self._add_btn.setVisible(False)
        self._add_bubble("user", message)

        self._typing = TypingIndicator(self._settings.reduce_motion)
        self._chat.insertWidget(self._chat.count() - 1, self._typing)
        self._send_btn.setEnabled(False)
        self._scroll_down()

        self._stream_text = ""
        self._stream_bubble = None
        self._worker = _SendWorker(self._builder, message, self._context, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_chunk(self, text: str) -> None:
        self._drop_typing()
        if self._stream_bubble is None:
            self._stream_bubble = self._add_bubble("agent", "")
        self._stream_text += text
        self._stream_bubble.set_text(self._stream_text)
        self._scroll_down()

    def _on_done(self, response: BuilderResponse) -> None:
        self._drop_typing()
        if self._stream_bubble is not None:
            self._stream_bubble.set_text(response.reply)  # re-render with mono JSON
        else:
            self._add_bubble("agent", response.reply)

        if response.ready_to_save and response.partial_action is not None:
            self._pending_action = response.partial_action
            self._add_btn.setVisible(True)
        elif "```json" in response.reply:
            self.show_error(PARSE_ERROR_COPY)
        self._scroll_down()

    def _on_failed(self, message: str) -> None:
        self._drop_typing()
        self.show_error(message)

    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._send_btn.setEnabled(True)
        self._stream_bubble = None

    # ------------------------------------------------------------- helpers
    def _add_to_deck(self) -> None:
        if self._pending_action is not None:
            action, self._pending_action = self._pending_action, None
            self._add_btn.setVisible(False)
            self.action_ready.emit(action)

    def _detect_url(self) -> None:
        self._url_chip.setVisible(
            _URL_RE.search(self._input.toPlainText()) is not None
        )

    def _add_bubble(self, role: str, text: str, fault: bool = False) -> ChatBubble:
        bubble = ChatBubble(role, text, fault)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        indent = theme.BUBBLE_PADDING * 3
        if role == "user":
            row.addSpacing(indent)
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
            row.addSpacing(indent)
        host = QWidget()
        host.setLayout(row)
        self._chat.insertWidget(self._chat.count() - 1, host)
        self._scroll_down()
        return bubble

    def _drop_typing(self) -> None:
        if self._typing is not None:
            self._typing.stop()
            self._typing.deleteLater()
            self._typing = None

    def _scroll_down(self) -> None:
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def paintEvent(self, event: QPaintEvent) -> None:
        # Docked, the overlay housing shows through; floating, the panel is
        # its own piece of housing metal.
        if self.isWindow():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(theme.qcolor(theme.PANEL))
            painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
            painter.drawRoundedRect(rect, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)
        super().paintEvent(event)
