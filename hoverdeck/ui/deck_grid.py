"""The rows×cols grid of keycaps for one page.

ActionDispatcher bridges the pure-Python action runner into Qt: each key
press spawns a QThread that executes the step chain; runner callbacks are
routed into Qt signals (queued across threads), which drive the keycaps'
indicator LEDs. The dispatcher outlives grid rebuilds (scale changes, deck
edits) so in-flight runs never signal into dead widgets.

Edit mode: clicks open editors instead of firing, drags swap slots, and the
grid re-emits slot intents (edit/delete/swap) for the overlay to apply and
persist.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QGridLayout, QWidget

from hoverdeck.core.action_runner import ActionRunner, RunnerCallbacks
from hoverdeck.core.models import Action, Page, Settings
from hoverdeck.ui import theme
from hoverdeck.ui.deck_button import DeckButton, LedState
from hoverdeck.utils.logging import get_logger

log = get_logger("deck_grid")

_ARROW_DELTAS = {
    Qt.Key.Key_Left: (0, -1),
    Qt.Key.Key_Right: (0, 1),
    Qt.Key.Key_Up: (-1, 0),
    Qt.Key.Key_Down: (1, 0),
}


class ActionThread(QThread):
    """Runs one action's step chain off the UI thread."""

    def __init__(self, runner: ActionRunner, action: Action,
                 dispatcher: "ActionDispatcher") -> None:
        super().__init__(dispatcher)
        self._runner = runner
        self._action = action
        self._dispatcher = dispatcher

    def run(self) -> None:
        self._runner.run(
            self._action,
            RunnerCallbacks(
                on_started=self._dispatcher.started.emit,
                on_step_done=self._dispatcher.step_done.emit,
                on_finished=self._dispatcher.finished.emit,
                on_cancelled=self._dispatcher.cancelled.emit,
                on_error=self._dispatcher.error.emit,
            ),
        )


class ActionDispatcher(QObject):
    """Owns the runner threads and the Qt signals they report through."""

    started = pyqtSignal(str)              # action_id
    step_done = pyqtSignal(str, int, str)  # action_id, step index, description
    finished = pyqtSignal(str)             # action_id
    cancelled = pyqtSignal(str)            # action_id — repeat loop stopped by user
    error = pyqtSignal(str, int, str)      # action_id, step index, message

    def __init__(self, runner: ActionRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._threads: list[ActionThread] = []

    def run(self, action: Action) -> None:
        if self._runner.is_running(action.id):
            if action.repeat:
                self._runner.cancel(action.id)  # second press stops the loop
            return
        thread = ActionThread(self._runner, action, self)
        thread.finished.connect(lambda t=thread: self._reap(t))
        self._threads.append(thread)
        thread.start()

    def cancel(self, action: Action) -> None:
        self._runner.cancel(action.id)

    def _reap(self, thread: ActionThread) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        thread.deleteLater()


class DeckGrid(QWidget):
    """Lays out a Page's slots as keycaps and dispatches their actions."""

    edit_slot = pyqtSignal(int)        # open the button editor for this slot
    delete_slot = pyqtSignal(int)      # remove the key in this slot
    swap_slots = pyqtSignal(int, int)  # rearrange request (source, target)
    swiped = pyqtSignal(int)           # horizontal swipe: -1 prev page, +1 next

    def __init__(
        self,
        page: Page,
        actions: dict[str, Action],
        settings: Settings,
        dispatcher: ActionDispatcher,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page = page
        self._actions = actions
        self._dispatcher = dispatcher
        self._edit_mode = False
        self._move_source: int | None = None
        self._swipe_origin: QPoint | None = None
        self._swipe_fired = False

        dispatcher.started.connect(self._on_started)
        dispatcher.step_done.connect(self._on_step_done)
        dispatcher.finished.connect(self._on_finished)
        dispatcher.cancelled.connect(self._on_cancelled)
        dispatcher.error.connect(self._on_error)

        layout = QGridLayout(self)
        layout.setSpacing(theme.GRID_GUTTER)
        layout.setContentsMargins(0, 0, 0, 0)

        size = theme.scaled(settings.button_size)
        self._buttons: list[DeckButton] = []
        self._by_action: dict[str, DeckButton] = {}
        for index in range(page.rows * page.cols):
            button = DeckButton(
                self._action_at(index), index, size, settings.reduce_motion, self
            )
            button.activated.connect(self._dispatch)
            button.edit_requested.connect(self._on_edit_requested)
            button.delete_requested.connect(self.delete_slot)
            button.move_requested.connect(self._arm_move)
            button.swap_requested.connect(self._on_swap)
            button.installEventFilter(self)
            layout.addWidget(button, index // page.cols, index % page.cols)
            self._buttons.append(button)
        self._reindex()

    # ------------------------------------------------------------- binding
    def _action_at(self, index: int) -> Action | None:
        return self._actions.get(self._page.slots.get(index, ""))

    def _reindex(self) -> None:
        self._by_action = {
            b.action.id: b for b in self._buttons if b.action is not None
        }

    def refresh(self) -> None:
        """Re-resolve slot bindings after the deck changed (edit/swap/add)."""
        for index, button in enumerate(self._buttons):
            button.set_action(self._action_at(index))
            button.set_edit_mode(self._edit_mode)
        self._reindex()

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self._move_source = None
        for button in self._buttons:
            button.set_edit_mode(enabled)

    # -------------------------------------------------------------- firing
    def _dispatch(self, action_id: str) -> None:
        button = self._by_action.get(action_id)
        if button is not None and button.action is not None:
            self._dispatcher.run(button.action)

    # ----------------------------------------------------------- edit mode
    def _on_edit_requested(self, slot: int) -> None:
        if self._move_source is not None:
            source, self._move_source = self._move_source, None
            if source != slot:
                self.swap_slots.emit(source, slot)
            return
        self.edit_slot.emit(slot)

    def _arm_move(self, slot: int) -> None:
        """Move via menu: the next clicked slot receives the key."""
        self._move_source = slot

    def _on_swap(self, source: int, target: int) -> None:
        self._move_source = None
        self.swap_slots.emit(source, target)

    # ----------------------------------------------------- LED feedback
    def _on_started(self, action_id: str) -> None:
        if button := self._by_action.get(action_id):
            button.set_led_state(LedState.RUNNING)

    def _on_step_done(self, action_id: str, index: int, description: str) -> None:
        log.debug("%s: step %d done (%s)", action_id, index, description)

    def _on_finished(self, action_id: str) -> None:
        if button := self._by_action.get(action_id):
            button.set_led_state(LedState.SUCCESS)
            if button.action is not None:
                button.setToolTip(button.action.name)

    def _on_cancelled(self, action_id: str) -> None:
        if button := self._by_action.get(action_id):
            button.set_led_state(LedState.IDLE)

    def _on_error(self, action_id: str, index: int, message: str) -> None:
        log.warning("%s: step %d failed: %s", action_id, index, message)
        if button := self._by_action.get(action_id):
            button.set_led_state(LedState.ERROR)
            button.setToolTip(message)  # hover the red lamp to read the fault

    # --------------------------------------------- keyboard nav + swiping
    def eventFilter(self, watched: QObject, event: object) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            delta = _ARROW_DELTAS.get(Qt.Key(event.key()))
            if delta and isinstance(watched, DeckButton):
                self._move_focus(self._buttons.index(watched), *delta)
                return True
        if isinstance(event, QMouseEvent) and isinstance(watched, DeckButton):
            if self._track_swipe(watched, event):
                return True
        return super().eventFilter(watched, event)

    def _track_swipe(self, button: DeckButton, event: QMouseEvent) -> bool:
        """Normal-mode horizontal drag across a key flips the page (§8.D).

        Edit-mode drags stay rearranges; this only watches normal mode.
        """
        if self._edit_mode:
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            self._swipe_origin = event.globalPosition().toPoint()
            self._swipe_fired = False
            return False
        if event.type() == QEvent.Type.MouseMove and self._swipe_origin is not None:
            delta = event.globalPosition().toPoint() - self._swipe_origin
            if (
                not self._swipe_fired
                and abs(delta.x()) >= theme.SWIPE_THRESHOLD
                and abs(delta.x()) > abs(delta.y())
            ):
                self._swipe_fired = True
                button.cancel_press()
                self.swiped.emit(-1 if delta.x() > 0 else 1)
            return self._swipe_fired
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._swipe_origin = None
            if self._swipe_fired:
                self._swipe_fired = False
                return True  # swallow: the swipe already consumed this press
        return False

    def _move_focus(self, index: int, drow: int, dcol: int) -> None:
        """Step in (drow, dcol) to the next focusable key.

        Empty sockets are skipped in normal mode but focusable in edit mode.
        """
        cols = self._page.cols
        row, col = index // cols, index % cols
        while True:
            row, col = row + drow, col + dcol
            if not (0 <= row < self._page.rows and 0 <= col < cols):
                return
            target = self._buttons[row * cols + col]
            if target.action is not None or self._edit_mode:
                target.setFocus(Qt.FocusReason.OtherFocusReason)
                return
