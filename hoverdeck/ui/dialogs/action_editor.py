"""Build an action's step chain: one row per step, reorder/add/delete.

Step types: Run a script, Send keys, Wait, Run a macro, Run a command,
Open an app or address, and If… (window title / pixel color / file exists /
time window) with nested then/else chains.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTime, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Wheel-ignoring inputs: scrolling the step list never changes a step's type
# or a spin value by accident (only click/dropdown/keyboard do).
from hoverdeck.ui.widgets.no_scroll import (
    NoScrollComboBox as QComboBox,
    NoScrollSpinBox as QSpinBox,
    NoScrollTimeEdit as QTimeEdit,
)

from hoverdeck.core.conditions import (
    Condition,
    FileExistsCondition,
    PixelColorCondition,
    TimeWindowCondition,
    WindowTitleCondition,
)
from hoverdeck.core.models import Action
from hoverdeck.core.steps import (
    ConditionStep,
    DelayStep,
    KeyMacroStep,
    LaunchStep,
    RunMacroStep,
    RunScriptStep,
    ShellStep,
    Step,
)
from hoverdeck.core.steps.launch import _APP_EXTENSIONS
from hoverdeck.ui import theme
from hoverdeck.ui.dialogs.file_browser import FileBrowserDialog

EMPTY_STEPS_COPY = "No steps yet — add one below."

# (step type, menu label) — what the user controls, not internals (§4.4).
STEP_CHOICES: list[tuple[str, str]] = [
    ("run_script", "Run a script"),
    ("key_macro", "Send keys"),
    ("delay", "Wait"),
    ("run_macro", "Run a macro"),
    ("shell", "Run a command"),
    ("launch", "Open an app or address"),
    ("condition", "If…"),
]

COND_CHOICES: list[tuple[str, str]] = [
    ("window_title", "Window title"),
    ("pixel_color", "Pixel color"),
    ("file_exists", "File exists"),
    ("time_window", "Time of day"),
]

_PICK_PIXEL_DELAY_MS = 2000

# Auto-inserted gap between consecutive steps (editable in the list afterward).
_AUTO_GAP_MS = 300


def _mono_edit(placeholder: str) -> QLineEdit:
    edit = QLineEdit()
    edit.setProperty("role", "mono")
    edit.setPlaceholderText(placeholder)
    return edit


class ConditionForm(QWidget):
    """Type selector + per-type fields for one Condition."""

    def __init__(self, cond: Condition | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)

        self._type = QComboBox()
        for cond_type, label in COND_CHOICES:
            self._type.addItem(label, cond_type)
        layout.addWidget(self._type)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # window_title
        window = QWidget()
        row = QHBoxLayout(window)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.CONTROL_PADDING)
        self._wt_mode = QComboBox()
        for mode in ("contains", "equals", "regex"):
            self._wt_mode.addItem(mode)
        self._wt_value = QLineEdit()
        self._wt_value.setPlaceholderText("Window title to match")
        row.addWidget(self._wt_mode)
        row.addWidget(self._wt_value, 1)
        self._stack.addWidget(window)

        # pixel_color
        pixel = QWidget()
        row = QHBoxLayout(pixel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.CONTROL_PADDING)
        self._px_x = QSpinBox()
        self._px_x.setRange(0, 99_999)
        self._px_x.setPrefix("x ")
        self._px_y = QSpinBox()
        self._px_y.setRange(0, 99_999)
        self._px_y.setPrefix("y ")
        self._px_color = _mono_edit("#RRGGBB")
        self._px_color.setMinimumWidth(theme.CONTROL_PADDING * 14)
        self._px_tol = QSpinBox()
        self._px_tol.setRange(0, 255)
        self._px_tol.setValue(10)
        self._px_tol.setPrefix("± ")
        pick = QPushButton("Pick pixel")
        pick.clicked.connect(self._pick_pixel)
        row.addWidget(self._px_x)
        row.addWidget(self._px_y)
        row.addWidget(self._px_color, 1)
        row.addWidget(self._px_tol)
        row.addWidget(pick)
        self._stack.addWidget(pixel)

        # file_exists
        file_w = QWidget()
        row = QHBoxLayout(file_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.CONTROL_PADDING)
        self._fe_path = _mono_edit("Path to check")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_file)
        row.addWidget(self._fe_path, 1)
        row.addWidget(browse)
        self._stack.addWidget(file_w)

        # time_window
        time_w = QWidget()
        row = QHBoxLayout(time_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.CONTROL_PADDING)
        self._tw_start = QTimeEdit(QTime(9, 0))
        self._tw_end = QTimeEdit(QTime(17, 0))
        for widget in (self._tw_start, self._tw_end):
            widget.setDisplayFormat("HH:mm")
            widget.setFont(theme.mono_font())
        row.addWidget(QLabel("between"))
        row.addWidget(self._tw_start)
        row.addWidget(QLabel("and"))
        row.addWidget(self._tw_end)
        row.addStretch(1)
        self._stack.addWidget(time_w)

        self._type.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._load(cond)

    # ------------------------------------------------------------ pick pixel
    def _pick_pixel(self) -> None:
        """Hide the editor for 2s; capture the pixel under the cursor."""
        window = self.window()
        window.hide()
        QTimer.singleShot(_PICK_PIXEL_DELAY_MS, lambda: self._capture_pixel(window))

    def _capture_pixel(self, window: QWidget) -> None:
        pos = QCursor.pos()
        color = self._grab_color(pos)
        window.show()
        self._px_x.setValue(max(0, pos.x()))
        self._px_y.setValue(max(0, pos.y()))
        if color:
            self._px_color.setText(color)

    @staticmethod
    def _grab_color(pos: QPoint) -> str:
        try:
            import mss

            with mss.mss() as sct:
                shot = sct.grab(
                    {"left": pos.x(), "top": pos.y(), "width": 1, "height": 1}
                )
                r, g, b = shot.pixel(0, 0)
                return f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            from PyQt6.QtWidgets import QApplication

            screen = QApplication.primaryScreen()
            if screen is None:
                return ""
            image = screen.grabWindow(0, pos.x(), pos.y(), 1, 1).toImage()
            return image.pixelColor(0, 0).name().upper()

    def _browse_file(self) -> None:
        path = FileBrowserDialog.get_file(self, "", "Pick a file")
        if path:
            self._fe_path.setText(path)

    # ------------------------------------------------------------- load/save
    def _select(self, cond_type: str) -> None:
        index = self._type.findData(cond_type)
        self._type.setCurrentIndex(max(0, index))
        self._stack.setCurrentIndex(max(0, index))

    def _load(self, cond: Condition | None) -> None:
        if isinstance(cond, WindowTitleCondition):
            self._select("window_title")
            self._wt_mode.setCurrentText(cond.mode)
            self._wt_value.setText(cond.value)
        elif isinstance(cond, PixelColorCondition):
            self._select("pixel_color")
            self._px_x.setValue(cond.x)
            self._px_y.setValue(cond.y)
            self._px_color.setText(cond.color)
            self._px_tol.setValue(cond.tolerance)
        elif isinstance(cond, FileExistsCondition):
            self._select("file_exists")
            self._fe_path.setText(cond.path)
        elif isinstance(cond, TimeWindowCondition):
            self._select("time_window")
            self._tw_start.setTime(QTime.fromString(cond.start, "HH:mm"))
            self._tw_end.setTime(QTime.fromString(cond.end, "HH:mm"))
        else:
            self._select("window_title")

    def condition(self) -> Condition:
        cond_type = self._type.currentData()
        if cond_type == "pixel_color":
            return PixelColorCondition(
                x=self._px_x.value(),
                y=self._px_y.value(),
                color=self._px_color.text().strip() or PixelColorCondition().color,
                tolerance=self._px_tol.value(),
            )
        if cond_type == "file_exists":
            return FileExistsCondition(path=self._fe_path.text().strip())
        if cond_type == "time_window":
            return TimeWindowCondition(
                start=self._tw_start.time().toString("HH:mm"),
                end=self._tw_end.time().toString("HH:mm"),
            )
        return WindowTitleCondition(
            mode=self._wt_mode.currentText(),
            value=self._wt_value.text().strip(),
        )


class StepRow(QWidget):
    """One step: type selector + type-specific fields + reorder/delete."""

    changed = pyqtSignal()
    remove_me = pyqtSignal(object)
    move_me = pyqtSignal(object, int)  # widget, direction (-1 up / +1 down)

    def __init__(self, step: Step, macros: list[tuple[str, str]],
                 allow_hidden_scripts: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._macros = macros  # (macro_id, name)
        self._allow_hidden = allow_hidden_scripts
        self._then: list[Step] = []
        self._else: list[Step] = []

        # A row is a small card: a header (type + reorder/delete) with the
        # type-specific fields on their own full-width line beneath it — so
        # nothing (e.g. a Browse button) gets pushed off the right edge.
        self.setObjectName("StepRow")
        self.setStyleSheet(
            f"#StepRow {{ background: {theme.KEYCAP}; "
            f"border: {theme.SEAM_WIDTH}px solid {theme.SEAM}; "
            f"border-radius: {theme.CONTROL_RADIUS}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*([theme.CONTROL_PADDING] * 4))
        outer.setSpacing(theme.CONTROL_PADDING)

        header = QHBoxLayout()
        header.setSpacing(theme.CONTROL_PADDING)
        self._type = QComboBox()
        for step_type, label in STEP_CHOICES:
            self._type.addItem(label, step_type)
        self._type.setMinimumWidth(theme.AI_PANEL_WIDTH // 2)
        header.addWidget(self._type)
        header.addStretch(1)

        up = QToolButton()
        up.setText("↑")
        up.clicked.connect(lambda: self.move_me.emit(self, -1))
        down = QToolButton()
        down.setText("↓")
        down.clicked.connect(lambda: self.move_me.emit(self, 1))
        remove = QToolButton()
        remove.setText("✕")
        remove.clicked.connect(lambda: self.remove_me.emit(self))
        for tool_button in (up, down, remove):
            header.addWidget(tool_button)
        outer.addLayout(header)

        self._stack = QStackedWidget()
        self._build_forms(step)
        outer.addWidget(self._stack)

        self._type.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._type.currentIndexChanged.connect(self.changed)
        self._load(step)

    # ------------------------------------------------------------- forms
    def _build_forms(self, step: Step) -> None:
        # run_script
        script = QWidget()
        layout = QHBoxLayout(script)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)
        self._script_path = _mono_edit("Path to a .py file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_script)
        self._script_args = _mono_edit("Arguments (optional)")
        layout.addWidget(self._script_path, 2)
        layout.addWidget(browse)
        layout.addWidget(self._script_args, 1)
        self._stack.addWidget(script)

        # key_macro
        keys = QWidget()
        layout = QHBoxLayout(keys)
        layout.setContentsMargins(0, 0, 0, 0)
        self._keys = _mono_edit("Combos, comma-separated: ctrl+shift+s, alt+f4")
        layout.addWidget(self._keys)
        self._stack.addWidget(keys)

        # delay
        delay = QWidget()
        layout = QHBoxLayout(delay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)
        self._delay_ms = QSpinBox()
        self._delay_ms.setRange(0, 600_000)
        self._delay_ms.setSingleStep(50)
        self._delay_ms.setSuffix(" ms")
        layout.addWidget(self._delay_ms)
        layout.addStretch(1)
        self._stack.addWidget(delay)

        # run_macro
        macro = QWidget()
        layout = QHBoxLayout(macro)
        layout.setContentsMargins(0, 0, 0, 0)
        self._macro = QComboBox()
        if self._macros:
            for macro_id, name in self._macros:
                self._macro.addItem(name, macro_id)
        else:
            self._macro.addItem("No macros yet — record one first", "")
            self._macro.setEnabled(False)
        layout.addWidget(self._macro)
        self._stack.addWidget(macro)

        # shell
        shell = QWidget()
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)
        self._shell_cmd = _mono_edit("Command to run")
        self._shell_cwd = _mono_edit("Working folder (optional)")
        cwd_browse = QPushButton("Browse…")
        cwd_browse.clicked.connect(self._browse_cwd)
        self._shell_timeout = QSpinBox()
        self._shell_timeout.setRange(100, 600_000)
        self._shell_timeout.setSingleStep(500)
        self._shell_timeout.setValue(10_000)
        self._shell_timeout.setSuffix(" ms")
        layout.addWidget(self._shell_cmd, 2)
        layout.addWidget(self._shell_cwd, 1)
        layout.addWidget(cwd_browse)
        layout.addWidget(self._shell_timeout)
        self._stack.addWidget(shell)

        # launch
        launch = QWidget()
        layout = QHBoxLayout(launch)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)
        self._launch_target = _mono_edit("App name/path or URL")
        self._launch_args = _mono_edit("Flags (e.g. -private-window)")
        self._launch_mode = QComboBox()
        for mode in ("auto", "url", "app", "file"):
            self._launch_mode.addItem(mode)
        app_browse = QPushButton("Browse…")
        app_browse.clicked.connect(self._browse_app)
        layout.addWidget(self._launch_target, 2)
        layout.addWidget(self._launch_args, 1)
        layout.addWidget(self._launch_mode)
        layout.addWidget(app_browse)
        self._stack.addWidget(launch)

        # condition
        cond_w = QWidget()
        layout = QHBoxLayout(cond_w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)
        initial = step.cond if isinstance(step, ConditionStep) else None
        self._cond_form = ConditionForm(initial)
        then_btn = QPushButton("Then…")
        then_btn.clicked.connect(lambda: self._edit_branch("then"))
        else_btn = QPushButton("Else…")
        else_btn.clicked.connect(lambda: self._edit_branch("else"))
        layout.addWidget(self._cond_form, 1)
        layout.addWidget(then_btn)
        layout.addWidget(else_btn)
        self._stack.addWidget(cond_w)

    def _browse_script(self) -> None:
        from hoverdeck import config
        from pathlib import Path as _Path
        # Vault keys browse the hidden folder; normal keys the base folder.
        hidden_dir = (config.SCRIPTS_DIR / "hidden").resolve()
        start = hidden_dir if self._allow_hidden else config.SCRIPTS_DIR
        path = FileBrowserDialog.get_file(self, str(start), "Pick a script")
        if not path:
            return
        resolved = _Path(path).resolve()
        in_hidden = resolved == hidden_dir or hidden_dir in resolved.parents
        if in_hidden and not self._allow_hidden:
            # Vault-only scripts can't be attached to a normal (non-vault) key.
            QMessageBox.warning(
                self, "Scripts",
                "That's a vault-only script — add it to a hidden (vault) key.",
            )
            return
        try:
            # A script under the scripts dir is stored by relative name so it
            # stays valid across dev/packaged (RunScriptStep resolves it there).
            rel = resolved.relative_to(config.SCRIPTS_DIR.resolve())
            self._script_path.setText(str(rel))
        except ValueError:
            self._script_path.setText(path)

    def _browse_cwd(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pick a working folder")
        if path:
            self._shell_cwd.setText(path)

    def _browse_app(self) -> None:
        path = FileBrowserDialog.get_file(self, "", "Pick an app or file")
        if path:
            self._launch_target.setText(path)
            # Auto-set mode based on extension.
            from pathlib import Path as _Path
            ext = _Path(path).suffix.lower()
            self._launch_mode.setCurrentText("app" if ext in _APP_EXTENSIONS else "file")

    def _edit_branch(self, branch: str) -> None:
        steps = self._then if branch == "then" else self._else
        title = "Steps when it matches" if branch == "then" else "Steps when it doesn't"
        dialog = StepChainDialog(
            list(steps), self._macros, title, self._allow_hidden, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if branch == "then":
                self._then = dialog.steps()
            else:
                self._else = dialog.steps()
            self.changed.emit()

    # ---------------------------------------------------------- load/save
    def _select_type(self, step_type: str) -> None:
        index = self._type.findData(step_type)
        self._type.setCurrentIndex(max(0, index))
        self._stack.setCurrentIndex(max(0, index))

    def _load(self, step: Step) -> None:
        self._select_type(step.TYPE)
        if isinstance(step, RunScriptStep):
            self._script_path.setText(step.path or "")
            self._script_args.setText(" ".join(step.args))
        elif isinstance(step, KeyMacroStep):
            self._keys.setText(", ".join(step.keys))
        elif isinstance(step, DelayStep):
            self._delay_ms.setValue(step.ms)
        elif isinstance(step, RunMacroStep):
            index = self._macro.findData(step.macro_id)
            if index >= 0:
                self._macro.setCurrentIndex(index)
        elif isinstance(step, ShellStep):
            self._shell_cmd.setText(step.command)
            self._shell_cwd.setText(step.cwd or "")
            self._shell_timeout.setValue(step.timeout_ms)
        elif isinstance(step, LaunchStep):
            self._launch_target.setText(step.target)
            self._launch_args.setText(" ".join(step.args))
            self._launch_mode.setCurrentText(step.mode)
        elif isinstance(step, ConditionStep):
            self._then = list(step.then)
            self._else = list(step.orelse)

    def to_step(self) -> Step:
        step_type = self._type.currentData()
        if step_type == "run_script":
            return RunScriptStep(
                path=self._script_path.text().strip() or None,
                args=self._script_args.text().split(),
            )
        if step_type == "key_macro":
            keys = [k.strip() for k in self._keys.text().split(",") if k.strip()]
            return KeyMacroStep(keys=keys)
        if step_type == "delay":
            return DelayStep(ms=self._delay_ms.value())
        if step_type == "run_macro":
            return RunMacroStep(macro_id=self._macro.currentData() or "")
        if step_type == "shell":
            return ShellStep(
                command=self._shell_cmd.text().strip(),
                cwd=self._shell_cwd.text().strip() or None,
                timeout_ms=self._shell_timeout.value(),
            )
        if step_type == "launch":
            return LaunchStep(
                target=self._launch_target.text().strip(),
                mode=self._launch_mode.currentText(),
                args=self._launch_args.text().split(),
            )
        return ConditionStep(
            cond=self._cond_form.condition(),
            then=self._then,
            orelse=self._else,
        )


class StepChainEditor(QWidget):
    """The reusable step list: scrollable rows + 'Add a step'."""

    def __init__(self, steps: list[Step], macros: list[tuple[str, str]],
                 allow_hidden_scripts: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._macros = macros
        self._allow_hidden = allow_hidden_scripts
        self._rows: list[StepRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)

        self._empty = QLabel(EMPTY_STEPS_COPY)
        self._empty.setProperty("role", "dim")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(theme.CONTROL_PADDING)
        self._list.addStretch(1)
        self._scroll.setWidget(host)
        layout.addWidget(self._scroll, 1)

        add = QPushButton("Add a step")
        add.clicked.connect(self._show_add_menu)
        self._add_button = add
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        for step in steps:
            self._append_row(step)
        self._refresh_empty()

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        for step_type, label in STEP_CHOICES:
            menu.addAction(label, lambda t=step_type: self._add_step(t))
        menu.exec(self._add_button.mapToGlobal(self._add_button.rect().bottomLeft()))

    def _add_step(self, step_type: str) -> None:
        defaults: dict[str, Step] = {
            "run_script": RunScriptStep(),
            "key_macro": KeyMacroStep(),
            "delay": DelayStep(ms=500),
            "run_macro": RunMacroStep(),
            "shell": ShellStep(),
            "launch": LaunchStep(),
            "condition": ConditionStep(cond=WindowTitleCondition()),
        }
        # Auto-insert an adjustable wait between consecutive steps (unless the
        # previous step is already a wait, or this new step is itself a wait).
        if (
            self._rows
            and step_type != "delay"
            and not isinstance(self._rows[-1].to_step(), DelayStep)
        ):
            self._append_row(DelayStep(ms=_AUTO_GAP_MS))
        row = self._append_row(defaults[step_type])
        self._refresh_empty()
        # Bring the freshly added row into view so you don't have to hunt for it.
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(row))

    def _append_row(self, step: Step) -> StepRow:
        row = StepRow(step, self._macros, self._allow_hidden)
        row.remove_me.connect(self._remove_row)
        row.move_me.connect(self._move_row)
        self._rows.append(row)
        self._list.insertWidget(self._list.count() - 1, row)
        return row

    def _remove_row(self, row: StepRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._list.removeWidget(row)
            row.deleteLater()
        self._refresh_empty()

    def _move_row(self, row: StepRow, direction: int) -> None:
        index = self._rows.index(row)
        target = index + direction
        if not 0 <= target < len(self._rows):
            return
        self._rows.insert(target, self._rows.pop(index))
        self._list.removeWidget(row)
        self._list.insertWidget(target, row)

    def _refresh_empty(self) -> None:
        self._empty.setVisible(not self._rows)

    def steps(self) -> list[Step]:
        return [row.to_step() for row in self._rows]


class StepChainDialog(QDialog):
    """A nested chain (condition then/else branches)."""

    def __init__(self, steps: list[Step], macros: list[tuple[str, str]],
                 title: str, allow_hidden_scripts: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(theme.AI_PANEL_WIDTH * 2)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)
        self._editor = StepChainEditor(steps, macros, allow_hidden_scripts, self)
        layout.addWidget(self._editor, 1)
        layout.addLayout(_save_cancel_row(self))

    def steps(self) -> list[Step]:
        return self._editor.steps()


class ActionEditor(QDialog):
    """Edit one Action: its name and its step chain."""

    def __init__(self, action: Action, macros: list[tuple[str, str]],
                 allow_hidden_scripts: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action = action
        self._allow_hidden = allow_hidden_scripts
        self.setWindowTitle("Edit the action")
        # Wide enough that a pixel-color condition row breathes.
        self.setMinimumWidth(theme.AI_PANEL_WIDTH * 2 + theme.BUTTON_SIZE_DEFAULT * 2)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.CONTROL_PADDING * 2)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        self._name = QLineEdit(action.name)
        name_row.addWidget(self._name, 1)
        layout.addLayout(name_row)

        self._editor = StepChainEditor(
            list(action.steps), macros, self._allow_hidden, self
        )
        layout.addWidget(self._editor, 1)
        layout.addLayout(_save_cancel_row(self))

    def result_action(self) -> Action:
        self._action.name = self._name.text().strip() or self._action.name
        self._action.steps = self._editor.steps()
        return self._action


def _save_cancel_row(dialog: QDialog) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dialog.reject)
    save = QPushButton("Save")
    save.setProperty("variant", "primary")
    save.clicked.connect(dialog.accept)
    row.addWidget(cancel)
    row.addWidget(save)
    return row
