"""App settings: General, AI Builder, Profiles, Hotkeys, About."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Callable

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hoverdeck import __version__
from hoverdeck.core.ai_builder import (
    API_KEY_URL,
    MODEL_CHOICES,
    RECOMMENDED_MODEL,
    AIBuilder,
    AIBuilderError,
)
from hoverdeck.core.models import Settings, WindowProfile
from hoverdeck.ui import screens, theme

# Wheel-ignoring inputs: scrolling the settings never changes a value by accident.
from hoverdeck.ui.widgets.no_scroll import (
    NoScrollComboBox as QComboBox,
    NoScrollSpinBox as QSpinBox,
)

_SLIDER_MIN = 60   # percent — mirrors theme.SCALE_MIN
_SLIDER_MAX = 200  # percent — mirrors theme.SCALE_MAX
_SLIDER_STEP = 5

CONNECTED_COPY = "Connected ✓"

_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
}

_MATCH_MODES = ("contains", "equals", "regex")


class _PingWorker(QThread):
    """Runs the provider ping off the UI thread."""

    succeeded = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, provider: str, api_key: str, model: str,
                 parent: QWidget) -> None:
        super().__init__(parent)
        self._provider = provider
        self._api_key = api_key
        self._model = model

    def run(self) -> None:
        try:
            asyncio.run(
                AIBuilder(self._provider, self._api_key, self._model).test_connection()
            )
        except AIBuilderError as exc:
            self.failed.emit(str(exc))
        except Exception:  # noqa: BLE001
            self.failed.emit("Connection failed — check your key and network.")
        else:
            self.succeeded.emit()


class HotkeyCapture(QLineEdit):
    """Click, then press the combo — it fills itself in (§8.E)."""

    def __init__(self, current: str = "", parent: QWidget | None = None) -> None:
        super().__init__(current, parent)
        self.setProperty("role", "mono")
        self.setPlaceholderText("Click, then press a combo")
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        if key in _MODIFIER_KEYS:
            return  # wait for the full combo
        if key == Qt.Key.Key_Escape:
            self.clearFocus()
            return
        parts: list[str] = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")
        name = QKeySequence(key).toString().lower()
        if name:
            parts.append(name)
            self.setText("+".join(parts))
        self.clearFocus()


class SettingsDialog(QDialog):
    """Edits a copy of the settings; the caller persists on accept.

    ``on_scale_preview`` is called live while the size slider moves so the
    deck resizes under the user's eyes; the caller reverts on cancel.
    """

    def __init__(
        self,
        settings: Settings,
        actions: list[tuple[str, str]],
        pages: list[tuple[str, str]],
        on_scale_preview: Callable[[float], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._actions = actions   # (action_id, name)
        self._pages = pages       # (page_id, name)
        self._on_scale_preview = on_scale_preview
        self._ping: _PingWorker | None = None
        self.setWindowTitle("Settings")
        self.setMinimumWidth(theme.AI_PANEL_WIDTH + theme.BUTTON_SIZE_DEFAULT * 2)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._ai_tab(), "AI Builder")
        tabs.addTab(self._profiles_tab(), "Profiles")
        tabs.addTab(self._hotkeys_tab(), "Hotkeys")
        tabs.addTab(self._about_tab(), "About")
        layout.addWidget(tabs, 1)

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

    # ---------------------------------------------------------------- General
    def _section(self, text: str) -> QLabel:
        """An engraved section divider for a settings form."""
        label = QLabel(text)
        label.setFont(theme.label_font(theme.LABEL_POINT_SIZE + 1))
        label.setProperty("role", "dim")
        return label

    @staticmethod
    def _form() -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(theme.CONTROL_PADDING * 2)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        return form

    def _general_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(*([theme.CONTROL_PADDING * 2] * 4))
        outer.setSpacing(theme.CONTROL_PADDING)
        form = self._form()

        form.addRow(self._section("DISPLAY"))

        self._size = QSlider(Qt.Orientation.Horizontal)
        self._size.setRange(_SLIDER_MIN, _SLIDER_MAX)
        self._size.setSingleStep(_SLIDER_STEP)
        self._size.setPageStep(_SLIDER_STEP * 2)
        self._size.setTickInterval(_SLIDER_STEP * 4)
        self._size.setValue(round(self._settings.scale * 100))
        self._size_label = QLabel(f"{self._size.value()}%")
        self._size_label.setProperty("role", "dim")
        self._size.valueChanged.connect(self._on_size_changed)
        size_box = QWidget()
        size_row = QHBoxLayout(size_box)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.addWidget(self._size, 1)
        size_row.addWidget(self._size_label)
        form.addRow("Size", size_box)

        self._monitor = QComboBox()
        self._monitor.addItem("Primary (auto)", "")
        primary = QApplication.primaryScreen()
        for screen in screens.available_screens():
            self._monitor.addItem(
                screens.describe(screen, screen is primary), screen.name()
            )
        idx = self._monitor.findData(self._settings.monitor)
        self._monitor.setCurrentIndex(max(0, idx))
        self._monitor.setToolTip("The deck docks to the right wall of this monitor.")
        form.addRow("Monitor", self._monitor)

        form.addRow(self._section("LAYOUT"))

        self._grid_rows = QSpinBox()
        self._grid_rows.setRange(1, 4)
        self._grid_rows.setValue(self._settings.grid_rows)
        self._grid_cols = QSpinBox()
        self._grid_cols.setRange(1, 4)
        self._grid_cols.setValue(self._settings.grid_cols)
        grid_box = QWidget()
        grid_row = QHBoxLayout(grid_box)
        grid_row.setContentsMargins(0, 0, 0, 0)
        grid_row.addWidget(self._grid_rows)
        times = QLabel("×")
        times.setProperty("role", "dim")
        grid_row.addWidget(times)
        grid_row.addWidget(self._grid_cols)
        grid_row.addStretch(1)
        form.addRow("Grid (rows × cols)", grid_box)

        form.addRow(self._section("BEHAVIOUR"))

        self._reduce_motion = QCheckBox("Reduce motion (state changes are instant)")
        self._reduce_motion.setChecked(self._settings.reduce_motion)
        form.addRow("", self._reduce_motion)

        self._vpn_overlay = QCheckBox("Show VPN status (on the deck and peek lamp)")
        self._vpn_overlay.setChecked(self._settings.vpn_overlay)
        form.addRow("", self._vpn_overlay)

        self._vpn_hint = QLineEdit(self._settings.vpn_adapter_hint)
        self._vpn_hint.setPlaceholderText("Auto — set only if your VPN isn't detected")
        self._vpn_hint.setToolTip(
            "Most VPNs are detected automatically. If yours isn't, type part of "
            "its network adapter name (see Windows network connections), "
            "e.g. NordLynx."
        )
        self._vpn_hint.setEnabled(self._settings.vpn_overlay)
        self._vpn_overlay.toggled.connect(self._vpn_hint.setEnabled)
        form.addRow("VPN adapter", self._vpn_hint)

        on_windows = sys.platform == "win32"
        self._autostart = QCheckBox(
            "Start with Windows" if on_windows else "Autostart (Windows only)"
        )
        self._autostart.setChecked(self._settings.autostart and on_windows)
        self._autostart.setEnabled(on_windows)
        form.addRow("", self._autostart)

        self._relock = QSpinBox()
        self._relock.setRange(30, 3600)
        self._relock.setSingleStep(30)
        self._relock.setSuffix(" seconds")
        self._relock.setValue(self._settings.relock_timeout_s)
        form.addRow("Lock vault after", self._relock)

        form.addRow(self._section("FILES"))

        self._browse_dir_label = QLabel(
            self._settings.last_browse_dir or os.path.expanduser("~")
        )
        self._browse_dir_label.setProperty("role", "dim")
        self._browse_dir_label.setFont(theme.mono_font())
        reset_browse = QPushButton("Reset to home")
        reset_browse.clicked.connect(self._reset_browse_dir)
        browse_box = QWidget()
        browse_row = QHBoxLayout(browse_box)
        browse_row.setContentsMargins(0, 0, 0, 0)
        browse_row.addWidget(self._browse_dir_label, 1)
        browse_row.addWidget(reset_browse)
        form.addRow("Last browse folder", browse_box)

        form.addRow(self._section("SCRIPTS"))

        self._script_python = QLineEdit(self._settings.script_python)
        self._script_python.setProperty("role", "mono")
        self._script_python.setPlaceholderText("Auto — HoverDeck's own Python")
        self._script_python.setToolTip(
            "Python that runs 'Run a script' steps. Point it at an environment "
            "that has your scripts' packages (e.g. pyautogui)."
        )
        py_browse = QPushButton("Browse…")
        py_browse.clicked.connect(self._browse_python)
        py_box = QWidget()
        py_row = QHBoxLayout(py_box)
        py_row.setContentsMargins(0, 0, 0, 0)
        py_row.addWidget(self._script_python, 1)
        py_row.addWidget(py_browse)
        form.addRow("Script interpreter", py_box)

        outer.addLayout(form)
        outer.addStretch(1)
        return tab

    def _browse_python(self) -> None:
        from hoverdeck.ui.dialogs.file_browser import FileBrowserDialog
        path = FileBrowserDialog.get_file(
            self, self._script_python.text().strip(), "Pick a Python interpreter"
        )
        if path:
            self._script_python.setText(path)

    def _reset_browse_dir(self) -> None:
        home = os.path.expanduser("~")
        self._browse_dir_label.setText(home)

    # ---------------------------------------------------------------- AI Builder
    def _ai_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(*([theme.CONTROL_PADDING * 2] * 4))
        outer.setSpacing(theme.CONTROL_PADDING)
        form = self._form()

        form.addRow(self._section("PROVIDER"))

        self._provider = QComboBox()
        self._provider.addItem("Anthropic", "anthropic")
        self._provider.addItem("OpenAI", "openai")
        index = self._provider.findData(self._settings.ai_provider)
        self._provider.setCurrentIndex(max(0, index))
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider", self._provider)

        self._model = QComboBox()   # fixed choice — current models per provider
        self._model.setToolTip("Pick a model. The recommended one balances cost "
                               "and reliable automation building.")
        form.addRow("Model", self._model)

        key_box = QWidget()
        key_row = QHBoxLayout(key_box)
        key_row.setContentsMargins(0, 0, 0, 0)
        self._api_key = QLineEdit(self._settings.ai_api_key)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setProperty("role", "mono")
        self._api_key.setToolTip(
            "Stored in settings.json on this machine; sent only to the provider."
        )
        self._key_help = QPushButton("Get a key…")
        self._key_help.setToolTip("Open the provider's page to create an API key.")
        self._key_help.clicked.connect(self._open_key_help)
        key_row.addWidget(self._api_key, 1)
        key_row.addWidget(self._key_help)
        form.addRow("API key", key_box)

        key_hint = QLabel("New here? Click “Get a key…”, sign in, create a key, paste it.")
        key_hint.setProperty("role", "dim")
        key_hint.setWordWrap(True)
        form.addRow("", key_hint)

        self._on_provider_changed()   # populate model list + key-help target

        self._test_btn = QPushButton("Test connection")
        self._test_btn.clicked.connect(self._test_connection)
        self._test_status = QLabel("")
        test_box = QWidget()
        test_row = QHBoxLayout(test_box)
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_status, 1)
        form.addRow("", test_box)

        form.addRow(self._section("PANEL"))

        self._panel_mode = QComboBox()
        self._panel_mode.addItem("Slide into the deck", "slide")
        self._panel_mode.addItem("Float next to the deck", "floating")
        index = self._panel_mode.findData(self._settings.ai_panel_mode)
        self._panel_mode.setCurrentIndex(max(0, index))
        form.addRow("Show as", self._panel_mode)

        self._panel_side = QComboBox()
        self._panel_side.addItem("Auto (away from the screen edge)", "auto")
        self._panel_side.addItem("Left of the deck", "left")
        self._panel_side.addItem("Right of the deck", "right")
        index = self._panel_side.findData(self._settings.ai_panel_side)
        self._panel_side.setCurrentIndex(max(0, index))
        form.addRow("Open on", self._panel_side)

        outer.addLayout(form)
        outer.addStretch(1)
        return tab

    def _on_provider_changed(self) -> None:
        """Rebuild the fixed model list for the chosen provider.

        Switching provider lands on that provider's recommended model; only the
        originally-saved provider keeps a custom/legacy saved id.
        """
        provider = self._provider.currentData()
        recommended = RECOMMENDED_MODEL.get(provider, "")
        # The saved model belongs to the saved provider only.
        saved = (
            self._settings.ai_model
            if provider == self._settings.ai_provider else ""
        )
        ids = list(MODEL_CHOICES.get(provider, []))
        if saved and saved not in ids:   # preserve a legacy/custom saved id
            ids.append(saved)
        self._model.blockSignals(True)
        self._model.clear()
        for model_id in ids:
            label = f"{model_id}  (Recommended)" if model_id == recommended else model_id
            self._model.addItem(label, model_id)
        index = self._model.findData(saved) if saved else -1
        if index < 0:
            index = self._model.findData(recommended)
        self._model.setCurrentIndex(max(0, index))
        self._model.blockSignals(False)

    def _open_key_help(self) -> None:
        url = API_KEY_URL.get(self._provider.currentData())
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ---------------------------------------------------------------- Profiles
    def _profiles_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(theme.CONTROL_PADDING)

        note = QLabel(
            "Switch to a page automatically when the foreground window matches."
        )
        note.setProperty("role", "dim")
        layout.addWidget(note)

        # Columns: Name | Pattern | Match | Page | (capture btn)
        self._prof_table = QTableWidget(0, 5)
        self._prof_table.setHorizontalHeaderLabels(
            ["Name", "Pattern", "Match", "Page", ""]
        )
        self._prof_table.verticalHeader().setVisible(False)
        hdr = self._prof_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._prof_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._prof_table.customContextMenuRequested.connect(
            self._profiles_context_menu
        )
        layout.addWidget(self._prof_table, 1)

        add_btn = QPushButton("Add profile")
        add_btn.clicked.connect(self._add_profile_row)
        layout.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignLeft)

        for profile in self._settings.profiles:
            self._insert_profile_row(profile)

        return tab

    def _insert_profile_row(self, profile: WindowProfile) -> None:
        row = self._prof_table.rowCount()
        self._prof_table.insertRow(row)

        name_item = QTableWidgetItem(profile.name)
        # Stash the id so we preserve it on apply_to.
        name_item.setData(Qt.ItemDataRole.UserRole, profile.id)
        self._prof_table.setItem(row, 0, name_item)
        self._prof_table.setItem(row, 1, QTableWidgetItem(profile.window_pattern))

        match_combo = QComboBox()
        for mode in _MATCH_MODES:
            match_combo.addItem(mode)
        match_combo.setCurrentText(profile.match_mode)
        self._prof_table.setCellWidget(row, 2, match_combo)

        page_combo = QComboBox()
        for pid, pname in self._pages:
            page_combo.addItem(pname, pid)
        idx = page_combo.findData(profile.page_id)
        if idx >= 0:
            page_combo.setCurrentIndex(idx)
        self._prof_table.setCellWidget(row, 3, page_combo)

        capture_btn = QPushButton("Capture")
        capture_btn.setProperty("variant", "glyph")
        capture_btn.clicked.connect(
            lambda _=False, r=row: self._capture_title(r)
        )
        self._prof_table.setCellWidget(row, 4, capture_btn)

    def _add_profile_row(self) -> None:
        profile = WindowProfile(
            id=uuid.uuid4().hex[:8],
            name="New profile",
            window_pattern="",
            match_mode="contains",
            page_id=self._pages[0][0] if self._pages else "",
        )
        self._insert_profile_row(profile)

    def _capture_title(self, row: int) -> None:
        """Hide the parent for 2s then capture the foreground window title."""
        from hoverdeck.utils.win import get_foreground_title

        parent = self.parentWidget()
        if parent is not None:
            parent.hide()

        def _finish() -> None:
            title = get_foreground_title()
            if parent is not None:
                parent.show()
                parent.raise_()
            if not title:
                return
            pat_item = self._prof_table.item(row, 1)
            if pat_item is None:
                pat_item = QTableWidgetItem()
                self._prof_table.setItem(row, 1, pat_item)
            pat_item.setText(title)
            match_w = self._prof_table.cellWidget(row, 2)
            if isinstance(match_w, QComboBox):
                match_w.setCurrentText("contains")

        QTimer.singleShot(2000, _finish)

    def _profiles_context_menu(self, pos: object) -> None:
        from PyQt6.QtCore import QPoint as _QPoint
        p = pos  # type: ignore[assignment]
        row = self._prof_table.rowAt(p.y())
        if row < 0:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove profile")
        action = menu.exec(self._prof_table.viewport().mapToGlobal(p))
        if action is remove:
            self._prof_table.removeRow(row)

    # ---------------------------------------------------------------- Hotkeys
    def _hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(theme.CONTROL_PADDING)

        note = QLabel("Fire a key from anywhere — the deck doesn't need focus.")
        note.setProperty("role", "dim")
        layout.addWidget(note)

        bound = {aid: hk for hk, aid in self._settings.global_hotkeys.items()}
        self._hotkey_table = QTableWidget(len(self._actions), 3)
        self._hotkey_table.setHorizontalHeaderLabels(["Action", "Hotkey", ""])
        vheader = self._hotkey_table.verticalHeader()
        vheader.setVisible(False)
        vheader.setDefaultSectionSize(theme.CONTROL_PADDING * 6)  # roomy rows
        header = self._hotkey_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self._captures: list[tuple[str, HotkeyCapture]] = []
        for row, (action_id, name) in enumerate(self._actions):
            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._hotkey_table.setItem(row, 0, item)
            capture = HotkeyCapture(bound.get(action_id, ""))
            self._hotkey_table.setCellWidget(row, 1, capture)
            clear = QPushButton("Clear")
            clear.setProperty("variant", "glyph")
            clear.setFixedWidth(theme.CONTROL_PADDING * 10)
            clear.clicked.connect(lambda _=False, c=capture: c.setText(""))
            self._hotkey_table.setCellWidget(row, 2, clear)
            self._captures.append((action_id, capture))

        layout.addWidget(self._hotkey_table, 1)
        return tab

    # ---------------------------------------------------------------- About
    def _about_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(theme.CONTROL_PADDING)

        title = QLabel("HOVERDECK")
        title.setFont(theme.title_font())
        layout.addWidget(title)

        version = QLabel(f"Version {__version__}")
        version.setProperty("role", "dim")
        layout.addWidget(version)

        desc = QLabel("A scriptable automation launcher for Windows.")
        desc.setProperty("role", "dim")
        layout.addWidget(desc)

        layout.addStretch(1)
        return tab

    # ---------------------------------------------------------------- helpers
    def _on_size_changed(self, value: int) -> None:
        value = round(value / _SLIDER_STEP) * _SLIDER_STEP
        self._size_label.setText(f"{value}%")
        self._on_scale_preview(value / 100)

    def _test_connection(self) -> None:
        self._test_btn.setEnabled(False)
        self._set_test_status("Testing…", "dim")
        self._ping = _PingWorker(
            self._provider.currentData(), self._api_key.text().strip(),
            self._model.currentData() or "", self
        )
        self._ping.succeeded.connect(lambda: self._test_done(CONNECTED_COPY, "live"))
        self._ping.failed.connect(lambda msg: self._test_done(msg, "fault"))
        self._ping.start()

    def _test_done(self, message: str, role: str) -> None:
        self._test_btn.setEnabled(True)
        self._set_test_status(message, role)

    def _set_test_status(self, message: str, role: str) -> None:
        self._test_status.setText(message)
        self._test_status.setProperty("role", role)
        self._test_status.style().unpolish(self._test_status)
        self._test_status.style().polish(self._test_status)

    def apply_to(self, settings: Settings) -> None:
        """Write the dialog's values into ``settings`` (called on accept)."""
        settings.scale = round(self._size.value() / _SLIDER_STEP) * _SLIDER_STEP / 100
        settings.monitor = self._monitor.currentData()
        settings.grid_rows = self._grid_rows.value()
        settings.grid_cols = self._grid_cols.value()
        settings.reduce_motion = self._reduce_motion.isChecked()
        settings.vpn_overlay = self._vpn_overlay.isChecked()
        settings.vpn_adapter_hint = self._vpn_hint.text().strip()
        settings.autostart = self._autostart.isChecked()
        settings.relock_timeout_s = self._relock.value()
        settings.last_browse_dir = self._browse_dir_label.text()
        settings.ai_provider = self._provider.currentData()
        settings.ai_model = self._model.currentData() or ""
        settings.ai_api_key = self._api_key.text().strip()
        settings.ai_panel_mode = self._panel_mode.currentData()
        settings.ai_panel_side = self._panel_side.currentData()
        settings.script_python = self._script_python.text().strip()

        hotkeys: dict[str, str] = {}
        for action_id, capture in self._captures:
            combo = capture.text().strip()
            if combo:
                hotkeys[combo] = action_id
        settings.global_hotkeys = hotkeys

        profiles: list[WindowProfile] = []
        for row in range(self._prof_table.rowCount()):
            name_item = self._prof_table.item(row, 0)
            pat_item  = self._prof_table.item(row, 1)
            match_w   = self._prof_table.cellWidget(row, 2)
            page_w    = self._prof_table.cellWidget(row, 3)
            if name_item is None:
                continue
            profile_id = (
                name_item.data(Qt.ItemDataRole.UserRole) or uuid.uuid4().hex[:8]
            )
            match_mode = (
                match_w.currentText() if isinstance(match_w, QComboBox) else "contains"
            )
            page_id = page_w.currentData() if isinstance(page_w, QComboBox) else ""
            profiles.append(WindowProfile(
                id=profile_id,
                name=name_item.text().strip(),
                window_pattern=pat_item.text().strip() if pat_item else "",
                match_mode=match_mode,  # type: ignore[arg-type]
                page_id=page_id or "",
            ))
        settings.profiles = profiles
