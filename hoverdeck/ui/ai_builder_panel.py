"""The AI Builder chat panel: describe an automation, get a deck key.

Bubbles read like panel readouts: user messages right-aligned on keycap
metal, agent messages left-aligned on housing metal with a seam border, JSON
in Plex Mono. The live-green ADD TO DECK lamp appears only when the agent
has produced a valid action.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Callable

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
from hoverdeck.ui.dialogs.script_review import ScriptReviewDialog
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

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        scripts_dir: Path | None = None,
        vault_unlocked: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._scripts_dir = scripts_dir
        self._vault_unlocked = vault_unlocked or (lambda: False)
        self._builder = AIBuilder(
            settings.ai_provider, settings.ai_api_key, settings.ai_model
        )
        self._context = BuilderContext()
        self._worker: _SendWorker | None = None
        self._stream_bubble: ChatBubble | None = None
        self._stream_text = ""
        self._typing: TypingIndicator | None = None
        self._pending_action: Action | None = None
        self._pending_slot: int | None = None  # user-targeted slot, if any
        self._pending_script = None          # ScriptProposal awaiting review
        self._suggestion_host: QWidget | None = None
        self._auto_replies = 0               # consecutive tool auto-answers (runaway guard)
        self._followup_request: str | None = None  # tool reply to send once idle

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

        # Review lamp: the agent wrote a script; nothing saves until reviewed.
        self._review_btn = QPushButton("REVIEW SCRIPT")
        self._review_btn.setProperty("variant", "primary")
        self._review_btn.setFont(theme.label_font(theme.TITLE_POINT_SIZE))
        self._review_btn.setVisible(False)
        self._review_btn.clicked.connect(self._review_script)
        layout.addWidget(self._review_btn)

        # The live-green confirmation lamp; appears only when ready_to_save.
        self._add_btn = QPushButton(ADD_TO_DECK_COPY)
        self._add_btn.setProperty("variant", "live")
        self._add_btn.setFont(theme.label_font(theme.TITLE_POINT_SIZE))
        self._add_btn.setVisible(False)
        self._add_btn.clicked.connect(self._add_to_deck)
        layout.addWidget(self._add_btn)

        self._add_bubble("agent", INTRO_MESSAGE)

    # ---------------------------------------------------------------- API
    def begin_session(
        self,
        macro_names: list[str],
        slot_count: int,
        free_slots: list[int] | None = None,
        scripts: list[str] | None = None,
    ) -> None:
        """Refresh what the agent knows about the deck (called on open)."""
        self._context.existing_macros = macro_names
        self._context.deck_slot_count = slot_count
        self._context.free_slots = free_slots or []
        self._context.existing_scripts = scripts or []

    def refresh_credentials(self) -> None:
        """Settings changed: new provider/key, same conversation."""
        history = self._builder.conversation_history
        self._builder = AIBuilder(
            self._settings.ai_provider, self._settings.ai_api_key,
            self._settings.ai_model,
        )
        self._builder.conversation_history = history

    def confirm_added(self, name: str) -> None:
        self._add_bubble("agent", f'Added "{name}" to the deck.')

    def show_error(self, message: str) -> None:
        self._add_bubble("agent", message, fault=True)

    # ------------------------------------------------------------- sending
    def _send(self) -> None:
        message = self._input.toPlainText().strip()
        if message:
            self._send_message(message)

    def _send_message(self, message: str, auto: bool = False) -> None:
        if self._worker is not None or not message:
            return  # one turn at a time
        if not self._settings.ai_api_key:
            self.show_error("No API key — add one in Settings.")
            return
        if auto:
            self._auto_replies += 1
            if self._auto_replies > 6:
                self.show_error(
                    "The assistant is looping on tool requests — "
                    "send a message to nudge it."
                )
                return
        else:
            self._auto_replies = 0   # a human/explicit turn resets the guard

        self._input.clear()
        self._url_chip.setVisible(False)
        self._add_btn.setVisible(False)
        self._review_btn.setVisible(False)
        self._drop_suggestions()
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
        # Tool directives shouldn't read as chatter: hide the raw show_script line
        # and show a quiet status instead.
        display = self._clean_reply(response.reply)
        if response.script_request and not display:
            display = f"↻ Reading {response.script_request}…"
        if self._stream_bubble is not None:
            self._stream_bubble.set_text(display)   # re-render (mono JSON, cleaned)
        else:
            self._add_bubble("agent", display)

        if response.ready_to_save and response.partial_action is not None:
            self._pending_action = response.partial_action
            self._pending_slot = response.target_slot
            self._add_btn.setVisible(True)
        elif "```json" in response.reply:
            self.show_error(PARSE_ERROR_COPY)

        if response.script is not None:
            self._pending_script = response.script
            self._review_btn.setText(f"REVIEW SCRIPT — {response.script.filename}")
            self._review_btn.setVisible(True)
        if response.suggestions:
            self._show_suggestions(response.suggestions)
        # Defer the tool reply until the worker is reaped (see _on_worker_finished),
        # otherwise _send_message would bail on "one turn at a time".
        if response.script_request and response.script is None:
            self._followup_request = response.script_request
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
        # Now that the turn is fully done, run any queued tool reply.
        if self._followup_request is not None:
            name, self._followup_request = self._followup_request, None
            self._answer_script_request(name)

    @staticmethod
    def _clean_reply(text: str) -> str:
        """Strip tool directives (show_script / suggestions) from displayed text."""
        out: list[str] = []
        skip_fence = False
        for line in text.splitlines():
            stripped = line.strip()
            if skip_fence:
                if stripped.startswith("```"):
                    skip_fence = False
                continue
            if re.match(r"^```\s*(show_script|suggestions)\b", stripped):
                skip_fence = True
                continue
            if re.match(r"^[`*]*\s*show_script[`*: ]+\S+\.py\b", stripped, re.I):
                continue
            out.append(line)
        return "\n".join(out).strip()

    # ------------------------------------------------------------- helpers
    def _add_to_deck(self) -> None:
        if self._pending_action is not None:
            action, self._pending_action = self._pending_action, None
            slot, self._pending_slot = self._pending_slot, None
            self._add_btn.setVisible(False)
            self.action_ready.emit((action, slot))

    def _answer_script_request(self, name: str) -> None:
        """The agent asked to read a script; reply with its contents."""
        if self._scripts_dir is None:
            return
        clean = name.strip().replace("\\", "/").lstrip("./")
        if clean.startswith("scripts/"):
            clean = clean[len("scripts/"):]
        hidden = clean.startswith("hidden/")
        if hidden and not self._vault_unlocked():
            self._send_message(f"There is no script named {clean}.", auto=True)
            return
        target = (self._scripts_dir / clean).resolve()
        try:
            target.relative_to(self._scripts_dir.resolve())  # stay inside the dir
            code = target.read_text(encoding="utf-8")
        except (OSError, ValueError):
            self._send_message(f"There is no script named {clean}.", auto=True)
            return
        self._send_message(
            f"Contents of {clean}:\n```python\n{code}\n```", auto=True
        )

    # -------------------------------------------------- suggested answers
    def _show_suggestions(self, suggestions: list[str]) -> None:
        """Tappable answer chips under the agent's question."""
        self._drop_suggestions()
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(theme.BUBBLE_PADDING, 0, theme.BUBBLE_PADDING, 0)
        column.setSpacing(theme.CONTROL_PADDING // 2 + 1)
        for text in suggestions:
            chip = QPushButton(text)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                f"text-align: left; color: {theme.SIGNAL};"
                f"border: {theme.SEAM_WIDTH}px solid {theme.SEAM};"
            )
            chip.clicked.connect(lambda _=False, t=text: self._send_message(t))
            column.addWidget(chip)
        self._suggestion_host = host
        self._chat.insertWidget(self._chat.count() - 1, host)
        self._scroll_down()

    def _drop_suggestions(self) -> None:
        if self._suggestion_host is not None:
            self._chat.removeWidget(self._suggestion_host)
            self._suggestion_host.deleteLater()
            self._suggestion_host = None

    # ------------------------------------------------------ script review
    def _review_script(self) -> None:
        if self._pending_script is None or self._scripts_dir is None:
            return
        dialog = ScriptReviewDialog(
            self._pending_script.filename,
            self._pending_script.code,
            self._scripts_dir,
            allow_hidden=self._vault_unlocked(),
            parent=self,
        )
        dialog.exec()
        if dialog.saved_path is None:
            return  # kept pending — the lamp stays lit for another look
        self._pending_script = None
        self._review_btn.setVisible(False)
        # Tell the agent where it landed so it can wire the action to it.
        self._send_message(f"Script saved as {dialog.saved_path}")

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
