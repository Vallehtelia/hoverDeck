"""Pick a glyph for a key: a curated switchboard palette + free emoji entry."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.ui import theme
from hoverdeck.ui.dialogs.file_browser import FileBrowserDialog

# Switchboard-friendly glyphs that render in the bundled/system fonts.
GLYPHS = [
    "▶", "‖", "⟳", "↻", "⚠", "⚡", "⌂", "✉",
    "⌨", "♪", "☼", "✂", "≡", "↑", "↓", "✓",
]
_PALETTE_COLS = 8


class IconPicker(QWidget):
    """Emits icon_changed(str) — a glyph from the palette or typed emoji."""

    icon_changed = pyqtSignal(str)

    def __init__(self, current: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.CONTROL_PADDING)

        palette = QGridLayout()
        palette.setSpacing(theme.CONTROL_PADDING // 2)
        side = theme.CONTROL_PADDING * 5
        for i, glyph in enumerate(GLYPHS):
            button = QPushButton(glyph)
            button.setProperty("variant", "glyph")
            button.setFixedSize(side, side)
            button.clicked.connect(lambda _=False, g=glyph: self._pick(g))
            palette.addWidget(button, i // _PALETTE_COLS, i % _PALETTE_COLS)
        layout.addLayout(palette)

        field_row = QHBoxLayout()
        field_row.setSpacing(theme.CONTROL_PADDING)
        self._field = QLineEdit(current)
        self._field.setPlaceholderText("A glyph/emoji, or an image path")
        self._field.textChanged.connect(self.icon_changed)
        image_btn = QPushButton("Image…")
        image_btn.clicked.connect(self._pick_image)
        field_row.addWidget(self._field, 1)
        field_row.addWidget(image_btn)
        layout.addLayout(field_row)

    def _pick(self, glyph: str) -> None:
        self._field.setText(glyph)  # textChanged re-emits icon_changed

    def _pick_image(self) -> None:
        path = FileBrowserDialog.get_file(self, "", "Pick an image for this key")
        if path:
            self._field.setText(path)

    def icon(self) -> str:
        return self._field.text().strip()
