"""Review a script the AI wrote before it touches disk.

The agent proposes code; nothing runs or saves until the user reads it here
and chooses where it lives: the normal scripts folder, or — only while the
vault is unlocked — the hidden one. The code is editable, so the user can fix
or trim it before saving.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.ui import theme


class ScriptReviewDialog(QDialog):
    """Shows AI-written code; the user edits, then saves it (or doesn't).

    After ``exec()``, :attr:`saved_path` is the path *relative to the scripts
    dir* (e.g. ``foo.py`` or ``hidden/foo.py``), or None if cancelled.
    """

    def __init__(
        self,
        filename: str,
        code: str,
        scripts_dir: Path,
        allow_hidden: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scripts_dir = scripts_dir
        self.saved_path: str | None = None
        self._original = filename
        # Updating? The same name already exists (normal or hidden side).
        self._updates_normal = (scripts_dir / filename).is_file()
        self._updates_hidden = (scripts_dir / "hidden" / filename).is_file()

        self.setWindowTitle("Review the script")
        self.setMinimumWidth(theme.AI_PANEL_WIDTH * 2)
        self.setMinimumHeight(theme.AI_PANEL_WIDTH + theme.BUTTON_SIZE_DEFAULT)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        note = QLabel(
            "The AI wrote this. Read it before saving — scripts run with your "
            "user's full permissions. You can edit it right here."
        )
        note.setProperty("role", "dim")
        note.setWordWrap(True)
        layout.addWidget(note)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("File name"))
        self._name = QLineEdit(filename)
        self._name.setProperty("role", "mono")
        name_row.addWidget(self._name, 1)
        layout.addLayout(name_row)

        self._code = QPlainTextEdit(code)
        self._code.setProperty("role", "mono")
        self._code.setFont(theme.mono_font())
        self._code.setTabStopDistance(theme.CONTROL_PADDING * 4)
        layout.addWidget(self._code, 1)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        if allow_hidden:
            hidden_btn = QPushButton(
                "Update hidden script" if self._updates_hidden else "Save as hidden"
            )
            hidden_btn.setToolTip(
                "Vault-only: visible and runnable only from hidden (vault) keys."
            )
            hidden_btn.clicked.connect(lambda: self._save(hidden=True))
            buttons.addWidget(hidden_btn)
        save = QPushButton(
            "Update script" if self._updates_normal else "Save script"
        )
        save.setProperty("variant", "primary")
        save.clicked.connect(lambda: self._save(hidden=False))
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self, hidden: bool) -> None:
        name = self._name.text().strip().replace("\\", "/").split("/")[-1]
        if not name:
            return
        if not name.endswith(".py"):
            name += ".py"
        folder = self._scripts_dir / "hidden" if hidden else self._scripts_dir
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        # Updating the script it was proposed as is the point — don't nag.
        deliberate_update = name == self._original and (
            self._updates_hidden if hidden else self._updates_normal
        )
        if target.exists() and not deliberate_update:
            overwrite = QMessageBox.question(
                self, "Scripts", f"{name} already exists. Overwrite?"
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        try:
            target.write_text(self._code.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Scripts", f"Could not save: {exc}")
            return
        self.saved_path = f"hidden/{name}" if hidden else name
        self.accept()
