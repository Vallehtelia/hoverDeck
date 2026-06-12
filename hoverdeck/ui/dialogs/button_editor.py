"""Edit one key: label, icon, color tint, and the bound action's steps.

A live keycap preview (a real DeckButton) shows the result while editing.
"""
from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.ui.widgets.no_scroll import NoScrollComboBox as QComboBox

from hoverdeck.core.models import Action, Deck
from hoverdeck.ui import theme
from hoverdeck.ui.deck_button import DeckButton
from hoverdeck.ui.dialogs.action_editor import ActionEditor
from hoverdeck.ui.widgets.icon_picker import IconPicker

_NEW_ACTION = "__new__"


class ButtonEditor(QDialog):
    """Returns an Action (existing or new) configured for one slot."""

    def __init__(
        self,
        deck: Deck,
        action: Action | None,
        macros: list[tuple[str, str]],
        parent: QWidget | None = None,
        allow_hidden_scripts: bool = False,
    ) -> None:
        super().__init__(parent)
        self._deck = deck
        self._macros = macros
        self._allow_hidden = allow_hidden_scripts
        self._action = action or Action(
            id=uuid.uuid4().hex[:8], name="New key", icon="", color="", steps=[]
        )
        self.setWindowTitle("Edit the key" if action else "Add a key")
        self.setMinimumWidth(theme.AI_PANEL_WIDTH + theme.BUTTON_SIZE_DEFAULT * 2)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        body = QHBoxLayout()
        body.setSpacing(theme.CONTROL_PADDING * 3)
        layout.addLayout(body, 1)

        # ----- left: the form
        form = QVBoxLayout()
        form.setSpacing(theme.CONTROL_PADDING)
        body.addLayout(form, 1)

        if not action and deck.actions:
            bind_row = QHBoxLayout()
            bind_row.addWidget(QLabel("Action"))
            self._bind = QComboBox()
            self._bind.addItem("New action", _NEW_ACTION)
            for existing in deck.actions.values():
                self._bind.addItem(existing.name, existing.id)
            self._bind.currentIndexChanged.connect(self._on_bind_changed)
            bind_row.addWidget(self._bind, 1)
            form.addLayout(bind_row)
        else:
            self._bind = None

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Label"))
        self._name = QLineEdit(self._action.name)
        self._name.textChanged.connect(self._refresh_preview)
        name_row.addWidget(self._name, 1)
        form.addLayout(name_row)

        form.addWidget(QLabel("Icon"))
        self._icon = IconPicker(self._action.icon)
        self._icon.icon_changed.connect(self._refresh_preview)
        form.addWidget(self._icon)

        tint_row = QHBoxLayout()
        tint_row.addWidget(QLabel("Tint"))
        self._tint = QComboBox()
        for label, token in theme.TINT_PRESETS:
            self._tint.addItem(label, token)
        index = self._tint.findData(self._action.color)
        self._tint.setCurrentIndex(max(0, index))
        self._tint.currentIndexChanged.connect(self._refresh_preview)
        tint_row.addWidget(self._tint, 1)
        form.addLayout(tint_row)

        self._repeat = QCheckBox("Repeat until stopped")
        self._repeat.setChecked(self._action.repeat)
        self._repeat.stateChanged.connect(self._refresh_preview)
        form.addWidget(self._repeat)

        steps_btn = QPushButton("Edit steps…")
        steps_btn.clicked.connect(self._edit_steps)
        form.addWidget(steps_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._steps_summary = QLabel()
        self._steps_summary.setProperty("role", "dim")
        form.addWidget(self._steps_summary)
        form.addStretch(1)

        # ----- right: live preview keycap
        preview_col = QVBoxLayout()
        preview_label = QLabel("Preview")
        preview_label.setProperty("role", "dim")
        preview_col.addWidget(preview_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._preview_host = QVBoxLayout()
        preview_col.addLayout(self._preview_host)
        preview_col.addStretch(1)
        body.addLayout(preview_col)
        self._preview: DeckButton | None = None

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._refresh_preview()

    # ------------------------------------------------------------- internals
    def _on_bind_changed(self) -> None:
        assert self._bind is not None
        data = self._bind.currentData()
        if data == _NEW_ACTION:
            self._action = Action(
                id=uuid.uuid4().hex[:8], name="New key", icon="", color="", steps=[]
            )
        else:
            self._action = self._deck.actions[data]
        self._name.setText(self._action.name)
        self._refresh_preview()

    def _edit_steps(self) -> None:
        # Keep the typed name when hopping into the step editor.
        self._action.name = self._name.text().strip() or self._action.name
        editor = ActionEditor(self._action, self._macros, self._allow_hidden, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._action = editor.result_action()
            self._name.setText(self._action.name)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        candidate = self.result_action(preview=True)
        if self._preview is not None:
            self._preview_host.removeWidget(self._preview)
            self._preview.deleteLater()
        self._preview = DeckButton(candidate, 0, theme.BUTTON_SIZE_DEFAULT, True, self)
        self._preview.setEnabled(False)
        self._preview_host.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignHCenter)
        count = len(candidate.steps)
        self._steps_summary.setText(
            f"{count} step{'s' if count != 1 else ''}" if count else "No steps yet"
        )

    def result_action(self, preview: bool = False) -> Action:
        action = self._action if not preview else Action(
            id=self._action.id,
            name=self._action.name,
            icon=self._action.icon,
            color=self._action.color,
            steps=self._action.steps,
            repeat=self._action.repeat,
        )
        action.name = self._name.text().strip() or "New key"
        action.icon = self._icon.icon()
        action.color = self._tint.currentData() or ""
        action.repeat = self._repeat.isChecked()
        return action
