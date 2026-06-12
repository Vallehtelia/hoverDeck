"""Manage the Python scripts that 'Run a script' steps can reference.

Scripts live in the user's scripts dir (``config.SCRIPTS_DIR``); a step with a
relative path resolves against it, so a script saved here is referable by name
alone. This dialog lists them, edits them in place, and adds/removes them.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.core.script_catalog import join_docstring, split_docstring
from hoverdeck.core.steps.run_script import resolve_interpreter
from hoverdeck.ui import theme


class _PipWorker(QThread):
    """Runs ``<interpreter> -m pip install <packages>`` off the UI thread."""

    done = pyqtSignal(int, str)  # returncode, combined output

    def __init__(self, interpreter: str, packages: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._interpreter = interpreter
        self._packages = packages

    def run(self) -> None:
        try:
            result = subprocess.run(
                [self._interpreter, "-m", "pip", "install", *self._packages],
                capture_output=True, text=True, timeout=600,
            )
        except Exception as exc:  # noqa: BLE001 — report any launch failure
            self.done.emit(1, str(exc))
            return
        self.done.emit(result.returncode, (result.stdout or "") + (result.stderr or ""))

_NEW_TEMPLATE = '"""New HoverDeck script."""\n\n\nprint("hello from HoverDeck")\n'


class ScriptManager(QDialog):
    """List + edit + add/delete the .py files in the scripts dir."""

    def __init__(self, scripts_dir: Path, python_exe: str = "",
                 vault_unlocked: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_dir = scripts_dir
        self._hidden_dir = scripts_dir / "hidden"
        self._vault_unlocked = vault_unlocked
        self._dir = self._base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._current: Path | None = None
        self._python = resolve_interpreter(python_exe or None)
        self._pip: _PipWorker | None = None

        self.setAcceptDrops(True)  # drop .py files here to import them
        self.setWindowTitle("Scripts")
        self.setMinimumWidth(theme.AI_PANEL_WIDTH * 2 + theme.BUTTON_SIZE_DEFAULT)
        self.setMinimumHeight(theme.AI_PANEL_WIDTH + theme.BUTTON_SIZE_DEFAULT)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        note = QLabel(
            f"Saved in {self._dir}. A 'Run a script' step can use just the "
            "file name from here. Drag .py files onto this window to import them."
        )
        note.setProperty("role", "dim")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Hidden scripts: only offered while the vault is unlocked.
        if self._vault_unlocked:
            self._hidden_toggle = QCheckBox("Hidden scripts (vault only)")
            self._hidden_toggle.setToolTip(
                "Scripts kept out of the normal list; visible only while the "
                "vault is unlocked. Reference them as hidden/<name> in a step."
            )
            self._hidden_toggle.toggled.connect(self._on_hidden_toggled)
            layout.addWidget(self._hidden_toggle)

        body = QHBoxLayout()
        body.setSpacing(theme.CONTROL_PADDING * 2)
        layout.addLayout(body, 1)

        # ----- left: the file list + add/delete
        left = QVBoxLayout()
        left.setSpacing(theme.CONTROL_PADDING)
        self._list = QListWidget()
        self._list.setMinimumWidth(theme.AI_PANEL_WIDTH // 2)
        self._list.currentItemChanged.connect(self._on_select)
        left.addWidget(self._list, 1)

        list_buttons = QHBoxLayout()
        new_btn = QPushButton("New…")
        new_btn.clicked.connect(self._new)
        del_btn = QPushButton("Delete")
        del_btn.setProperty("variant", "danger")
        del_btn.clicked.connect(self._delete)
        list_buttons.addWidget(new_btn)
        list_buttons.addWidget(del_btn)
        list_buttons.addStretch(1)
        left.addLayout(list_buttons)
        body.addLayout(left)

        # ----- right: the editor
        right = QVBoxLayout()
        right.setSpacing(theme.CONTROL_PADDING)
        self._name_label = QLabel("No script selected")
        self._name_label.setFont(theme.mono_font())
        self._name_label.setProperty("role", "dim")
        right.addWidget(self._name_label)

        desc_row = QHBoxLayout()
        desc_row.setSpacing(theme.CONTROL_PADDING)
        desc_row.addWidget(QLabel("Description"))
        self._desc = QLineEdit()
        self._desc.setPlaceholderText("What it does + its args — shown to the AI")
        self._desc.setToolTip(
            "Saved as the script's docstring. It's how the AI knows what this "
            "script is for and how to call it."
        )
        self._desc.setEnabled(False)
        self._desc.textChanged.connect(self._on_edit)
        desc_row.addWidget(self._desc, 1)
        right.addLayout(desc_row)

        self._editor = QPlainTextEdit()
        self._editor.setProperty("role", "mono")
        self._editor.setFont(theme.mono_font())
        self._editor.setTabStopDistance(theme.CONTROL_PADDING * 4)
        self._editor.setEnabled(False)
        self._editor.textChanged.connect(self._on_edit)
        right.addWidget(self._editor, 1)
        body.addLayout(right, 1)

        # ----- packages: pip install into the interpreter scripts run with
        pkg_row = QHBoxLayout()
        pkg_row.setSpacing(theme.CONTROL_PADDING)
        pkg_row.addWidget(QLabel("Install package"))
        self._pkg = QLineEdit()
        self._pkg.setProperty("role", "mono")
        self._pkg.setPlaceholderText("e.g. pyautogui requests")
        self._pkg.returnPressed.connect(self._install)
        self._pkg_btn = QPushButton("Install")
        self._pkg_btn.clicked.connect(self._install)
        self._pkg_status = QLabel("")
        self._pkg_status.setProperty("role", "dim")
        pkg_row.addWidget(self._pkg, 1)
        pkg_row.addWidget(self._pkg_btn)
        pkg_row.addWidget(self._pkg_status)
        layout.addLayout(pkg_row)

        interp_note = QLabel(f"Installs into: {self._python}")
        interp_note.setProperty("role", "dim")
        interp_note.setFont(theme.mono_font(max(6, theme.MONO_POINT_SIZE - 2)))
        layout.addWidget(interp_note)

        # ----- footer
        footer = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        footer.addWidget(self._save_btn)
        footer.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        self._reload()

    # ---- drag & drop import ----------------------------------------------
    @staticmethod
    def _dropped_scripts(event: QDragEnterEvent | QDropEvent) -> list[Path]:
        data = event.mimeData()
        if not data.hasUrls():
            return []
        out: list[Path] = []
        for url in data.urls():
            local = url.toLocalFile()
            if local and local.lower().endswith(".py"):
                out.append(Path(local))
        return out

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_scripts(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        added: str | None = None
        for src in self._dropped_scripts(event):
            if not src.is_file():
                continue
            dest = self._dir / src.name
            if dest.exists() and dest.resolve() != src.resolve():
                overwrite = QMessageBox.question(
                    self, "Scripts", f"{src.name} already exists here. Overwrite?"
                )
                if overwrite != QMessageBox.StandardButton.Yes:
                    continue
            try:
                shutil.copy2(src, dest)
                added = src.name
            except OSError as exc:
                QMessageBox.warning(self, "Scripts", f"Could not import {src.name}: {exc}")
        if added:
            self._reload(select=added)
        event.acceptProposedAction()

    def _on_hidden_toggled(self, hidden: bool) -> None:
        self._dir = self._hidden_dir if hidden else self._base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._reload()

    # ---- data -------------------------------------------------------------
    def _reload(self, select: str | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for path in sorted(self._dir.glob("*.py"), key=lambda p: p.name.lower()):
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self._list.addItem(item)
        self._list.blockSignals(False)
        if select:
            matches = self._list.findItems(select, Qt.MatchFlag.MatchExactly)
            if matches:
                self._list.setCurrentItem(matches[0])
                return
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._show(None)

    def _show(self, path: Path | None) -> None:
        self._current = path
        if path is None:
            self._name_label.setText("No script selected")
            self._desc.clear()
            self._desc.setEnabled(False)
            self._editor.clear()
            self._editor.setEnabled(False)
            self._save_btn.setEnabled(False)
            return
        self._name_label.setText(path.name)
        try:
            description, body = split_docstring(path.read_text(encoding="utf-8"))
        except OSError as exc:
            description, body = "", f"# Could not read file: {exc}"
        self._desc.setText(description)
        self._editor.setPlainText(body)
        self._desc.setEnabled(True)
        self._editor.setEnabled(True)
        self._save_btn.setEnabled(True)

    # ---- actions ----------------------------------------------------------
    def _on_edit(self) -> None:
        if self._current is not None:
            self._save_btn.setText("Save")
            self._save_btn.setEnabled(True)

    def _install(self) -> None:
        packages = self._pkg.text().split()
        if not packages or self._pip is not None:
            return
        self._set_pkg_status("Installing…", "dim")
        self._pkg_btn.setEnabled(False)
        self._pip = _PipWorker(self._python, packages, self)
        self._pip.done.connect(self._install_done)
        self._pip.start()

    def _install_done(self, code: int, output: str) -> None:
        self._pip = None
        self._pkg_btn.setEnabled(True)
        if code == 0:
            self._set_pkg_status("Installed ✓", "live")
            self._pkg.clear()
        else:
            tail = (output.strip().splitlines() or ["pip failed"])[-1]
            self._set_pkg_status("Failed — hover for details", "fault")
            self._pkg_status.setToolTip(output.strip() or tail)

    def _set_pkg_status(self, text: str, role: str) -> None:
        self._pkg_status.setText(text)
        self._pkg_status.setToolTip("")
        self._pkg_status.setProperty("role", role)
        self._pkg_status.style().unpolish(self._pkg_status)
        self._pkg_status.style().polish(self._pkg_status)

    def _on_select(self, current: QListWidgetItem | None, _prev: object) -> None:
        if current is None:
            self._show(None)
        else:
            self._show(Path(current.data(Qt.ItemDataRole.UserRole)))

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "New script", "File name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if not name.endswith(".py"):
            name += ".py"
        path = self._dir / name
        if path.exists():
            QMessageBox.warning(self, "Scripts", f"{name} already exists.")
            return
        try:
            path.write_text(_NEW_TEMPLATE, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Scripts", f"Could not create {name}: {exc}")
            return
        self._reload(select=name)

    def _save(self) -> None:
        if self._current is None:
            return
        content = join_docstring(self._desc.text(), self._editor.toPlainText())
        try:
            self._current.write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Scripts", f"Could not save: {exc}")
            return
        self._save_btn.setText("Saved ✓")
        self._save_btn.setEnabled(False)

    def _delete(self) -> None:
        if self._current is None:
            return
        name = self._current.name
        confirm = QMessageBox.question(
            self, "Delete script", f"Delete {name}? This cannot be undone."
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._current.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Scripts", f"Could not delete: {exc}")
            return
        self._reload()
