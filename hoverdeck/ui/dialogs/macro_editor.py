"""Record / play / manage macros.

Record arms a global pynput capture; Stop ends it; Save names and persists
the recording. Playback previews a saved macro.
"""
from __future__ import annotations

import threading
import uuid

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.core.macro_player import MacroPlayer
from hoverdeck.core.macro_recorder import MacroRecorder
from hoverdeck.core.models import Macro, MacroEvent
from hoverdeck.storage.macro_store import MacroStore
from hoverdeck.ui import theme

_POLL_MS = 250


class MacroEditor(QDialog):
    def __init__(self, store: MacroStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._recorder = MacroRecorder()
        self._recorded: list[MacroEvent] = []
        self.setWindowTitle("Macros")
        self.setMinimumWidth(theme.AI_PANEL_WIDTH + theme.BUTTON_SIZE_DEFAULT)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection)
        layout.addWidget(self._list, 1)

        controls = QHBoxLayout()
        controls.setSpacing(theme.CONTROL_PADDING)
        self._record_btn = QPushButton("Record a macro")
        self._record_btn.setProperty("variant", "primary")
        self._record_btn.clicked.connect(self._toggle_record)
        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._play_selected)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setProperty("variant", "danger")
        self._delete_btn.clicked.connect(self._delete_selected)
        controls.addWidget(self._record_btn)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._delete_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        save_row = QHBoxLayout()
        save_row.setSpacing(theme.CONTROL_PADDING)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Name the recording")
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._save_recording)
        save_row.addWidget(self._name, 1)
        save_row.addWidget(self._save_btn)
        layout.addLayout(save_row)

        self._status = QLabel("")
        self._status.setProperty("role", "dim")
        layout.addWidget(self._status)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close_row.addWidget(close)
        layout.addLayout(close_row)

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._while_recording)

        self._reload()
        self._refresh_buttons()

    # ------------------------------------------------------------ list
    def _reload(self) -> None:
        self._list.clear()
        for macro in self._store.load_all():
            item = QListWidgetItem(f"{macro.name}  ·  {len(macro.events)} events")
            item.setData(Qt.ItemDataRole.UserRole, macro.id)
            self._list.addItem(item)

    def _selected_id(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_selection(self) -> None:
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_selection = self._selected_id() is not None
        self._play_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._save_btn.setEnabled(bool(self._recorded))

    # ------------------------------------------------------- record/play
    def _toggle_record(self) -> None:
        if self._recorder.recording:
            self._recorded = self._recorder.stop()
            self._poll.stop()
            self._record_btn.setText("Record a macro")
            self._status.setText(
                f"Recorded {len(self._recorded)} events — name it and press Save."
            )
        else:
            try:
                self._recorder.start()
            except RuntimeError as exc:
                self._status.setText(str(exc))
                self._status.setProperty("role", "fault")
                self._repolish_status()
                return
            self._record_btn.setText("Stop")
            self._status.setText("Recording — press Stop when done.")
        self._status.setProperty("role", "dim")
        self._repolish_status()
        self._refresh_buttons()

    def _while_recording(self) -> None:
        self._status.setText(
            f"Recording — {len(self._recorder._events)} events so far. "
            "Press Stop when done."
        )

    def _play_selected(self) -> None:
        macro_id = self._selected_id()
        if macro_id is None:
            return
        macro = self._store.load(macro_id)
        if macro is None:
            self._status.setText("Macro not found — it may have been deleted.")
            return
        self._status.setText(f"Playing {macro.name}…")
        threading.Thread(
            target=self._play_thread, args=(macro,), daemon=True
        ).start()

    def _play_thread(self, macro: Macro) -> None:
        try:
            MacroPlayer().play(macro)
        except RuntimeError:
            pass  # surfaced by the status below either way

    # -------------------------------------------------------- save/delete
    def _save_recording(self) -> None:
        if not self._recorded:
            return
        name = self._name.text().strip() or "Untitled macro"
        macro = Macro(id=uuid.uuid4().hex[:8], name=name, events=self._recorded)
        self._store.save(macro)
        self._recorded = []
        self._name.clear()
        self._status.setText(f"Saved {name}.")
        self._reload()
        self._refresh_buttons()

    def _delete_selected(self) -> None:
        macro_id = self._selected_id()
        if macro_id is not None:
            self._store.delete(macro_id)
            self._reload()
            self._refresh_buttons()

    def _repolish_status(self) -> None:
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def closeEvent(self, event: object) -> None:
        if self._recorder.recording:
            self._recorder.stop()
            self._poll.stop()
        super().closeEvent(event)  # type: ignore[arg-type]
