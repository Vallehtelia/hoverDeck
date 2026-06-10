"""Themed file browser dialog — fully on-brand replacement for QFileDialog.

Panel (#14171B) background, keycap-style bookmark buttons, breadcrumb bar
(Plex Mono), sorted file list (dirs first then files) with a custom delegate
that draws name + human-readable size + type chip (ink_dim), signal-amber
selection highlight, full keyboard navigation.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QModelIndex, QRect, QSize, Qt
from PyQt6.QtGui import QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.ui import theme

# ---------------------------------------------------------------------------
# Item data roles
# ---------------------------------------------------------------------------
_R_IS_DIR = Qt.ItemDataRole.UserRole + 0
_R_NAME   = Qt.ItemDataRole.UserRole + 1
_R_SIZE   = Qt.ItemDataRole.UserRole + 2   # human-readable string, "" for dirs
_R_EXT    = Qt.ItemDataRole.UserRole + 3   # uppercase extension, max 4 chars

# ---------------------------------------------------------------------------
# Layout constants (unscaled bases, multiplied by theme.SCALE at paint time)
# ---------------------------------------------------------------------------
_ROW_H_BASE   = 28
_PAD_BASE     = 8
_GLYPH_W_BASE = 20
_SIZE_W_BASE  = 68
_CHIP_W_BASE  = 38


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n} {unit}"
        n //= 1024
    return f"{n} TB"


def _ext_chip(name: str) -> str:
    suffix = Path(name).suffix.lstrip(".").upper()
    return suffix[:4] if suffix else ""


class _RowDelegate(QStyledItemDelegate):
    """Paints name + size + type chip on each list row."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        h = max(1, round(_ROW_H_BASE * theme.SCALE))
        return QSize(option.rect.width() or 400, h)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        r = option.rect

        is_dir  = bool(index.data(_R_IS_DIR))
        name    = str(index.data(_R_NAME) or "")
        size_s  = str(index.data(_R_SIZE) or "")
        ext     = str(index.data(_R_EXT) or "")

        selected  = bool(option.state & option.state.State_Selected)  # type: ignore[attr-defined]
        hovered   = bool(option.state & option.state.State_MouseOver)  # type: ignore[attr-defined]

        # --- background ---
        if selected:
            painter.fillRect(r, theme.qcolor(theme.SIGNAL, 26))  # ~10% opacity
            painter.setPen(QPen(theme.qcolor(theme.SIGNAL), 1))
            painter.drawRect(r.adjusted(0, 0, -1, -1))
        elif hovered:
            painter.fillRect(r, theme.qcolor(theme.KEYCAP))

        pad     = max(1, round(_PAD_BASE * theme.SCALE))
        glyph_w = max(1, round(_GLYPH_W_BASE * theme.SCALE))
        size_w  = max(1, round(_SIZE_W_BASE * theme.SCALE))
        chip_w  = max(1, round(_CHIP_W_BASE * theme.SCALE))

        # --- glyph (▶ dirs, · files) ---
        painter.setPen(theme.qcolor(theme.SIGNAL if is_dir else theme.INK_DIM))
        glyph_rect = QRect(r.left() + pad, r.top(), glyph_w, r.height())
        painter.drawText(glyph_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "▶" if is_dir else "·")

        # --- filename (ink, Plex Mono) ---
        painter.setPen(theme.qcolor(theme.INK))
        painter.setFont(theme.mono_font())
        right_reserve = size_w + chip_w + pad * 2
        name_rect = QRect(
            r.left() + pad + glyph_w,
            r.top(),
            r.width() - pad - glyph_w - right_reserve,
            r.height(),
        )
        fm = painter.fontMetrics()
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

        # --- file size (ink_dim, right-aligned) ---
        if not is_dir and size_s:
            painter.setPen(theme.qcolor(theme.INK_DIM))
            painter.setFont(theme.mono_font())
            size_rect = QRect(
                r.right() - right_reserve, r.top(), size_w, r.height()
            )
            painter.drawText(
                size_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                size_s,
            )

        # --- type chip (ink_dim, far right) ---
        if not is_dir and ext:
            painter.setPen(theme.qcolor(theme.INK_DIM))
            small = theme.mono_font(max(6, theme.MONO_POINT_SIZE - 1))
            painter.setFont(small)
            chip_rect = QRect(
                r.right() - chip_w - pad, r.top(), chip_w, r.height()
            )
            painter.drawText(
                chip_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                ext,
            )

        painter.restore()


class FileBrowserDialog(QDialog):
    """Themed file picker — call ``get_file()`` for a one-shot result."""

    # Dialog dimensions at scale 1.0.
    _W_BASE = 680
    _H_BASE = 480

    def __init__(
        self,
        start_dir: str,
        title: str = "Open file",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        w = max(400, round(self._W_BASE * theme.SCALE))
        h = max(300, round(self._H_BASE * theme.SCALE))
        self.resize(w, h)

        self._current: Path = Path(start_dir) if start_dir else Path.home()
        if not self._current.is_dir():
            self._current = Path.home()
        self._selected: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.OVERLAY_PADDING, theme.OVERLAY_PADDING,
            theme.OVERLAY_PADDING, theme.OVERLAY_PADDING,
        )
        layout.setSpacing(theme.CONTROL_PADDING)

        layout.addLayout(self._build_header())

        self._list = QListWidget()
        self._list.setItemDelegate(_RowDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._list.itemActivated.connect(self._on_activate)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.installEventFilter(self)
        layout.addWidget(self._list, 1)

        layout.addLayout(self._build_footer())

        self._populate(self._current)

    # ---------------------------------------------------------------- header
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.CONTROL_PADDING)

        for label, path in [
            ("Home", Path.home()),
            ("Desktop", Path.home() / "Desktop"),
            ("Downloads", Path.home() / "Downloads"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(max(1, round(22 * theme.SCALE)))
            btn.clicked.connect(lambda _=False, p=path: self._navigate(p))
            row.addWidget(btn)

        row.addSpacing(theme.CONTROL_PADDING)

        self._breadcrumb = QLabel()
        self._breadcrumb.setFont(theme.mono_font())
        self._breadcrumb.setProperty("role", "dim")
        self._breadcrumb.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self._breadcrumb, 1)
        return row

    # ---------------------------------------------------------------- footer
    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.CONTROL_PADDING)

        self._path_label = QLabel()
        self._path_label.setFont(theme.mono_font())
        self._path_label.setProperty("role", "dim")
        self._path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self._path_label, 1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        self._open_btn = QPushButton("OPEN")
        self._open_btn.setFont(theme.label_font())
        self._open_btn.setProperty("variant", "primary")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._confirm)
        row.addWidget(self._open_btn)

        return row

    # -------------------------------------------------------------- populate
    def _populate(self, path: Path) -> None:
        self._current = path
        self._list.clear()
        self._selected = None
        self._open_btn.setEnabled(False)
        self._update_breadcrumb()
        self._path_label.setText("")

        try:
            entries = list(path.iterdir())
        except PermissionError:
            return

        dirs  = sorted((e for e in entries if e.is_dir()),  key=lambda e: e.name.lower())
        files = sorted((e for e in entries if e.is_file()), key=lambda e: e.name.lower())

        for entry in dirs:
            item = QListWidgetItem()
            item.setData(_R_IS_DIR, True)
            item.setData(_R_NAME, entry.name)
            item.setData(_R_SIZE, "")
            item.setData(_R_EXT, "")
            self._list.addItem(item)

        for entry in files:
            try:
                size_bytes = entry.stat().st_size
            except OSError:
                size_bytes = 0
            item = QListWidgetItem()
            item.setData(_R_IS_DIR, False)
            item.setData(_R_NAME, entry.name)
            item.setData(_R_SIZE, _human_size(size_bytes))
            item.setData(_R_EXT, _ext_chip(entry.name))
            self._list.addItem(item)

    def _navigate(self, path: Path) -> None:
        if path.is_dir():
            self._populate(path)

    def _update_breadcrumb(self) -> None:
        try:
            home = Path.home()
            rel = self._current.relative_to(home)
            text = "~/" + str(rel).replace("\\", "/")
        except ValueError:
            text = str(self._current).replace("\\", "/")
        self._breadcrumb.setText(text)

    # ----------------------------------------------------------- interactions
    def _on_activate(self, item: QListWidgetItem) -> None:
        if item.data(_R_IS_DIR):
            self._navigate(self._current / item.data(_R_NAME))
        else:
            self._confirm()

    def _on_selection_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if current is None or current.data(_R_IS_DIR):
            self._selected = None
            self._open_btn.setEnabled(False)
            self._path_label.setText("")
        else:
            self._selected = self._current / current.data(_R_NAME)
            self._open_btn.setEnabled(True)
            # Left-elide so the filename end is always visible.
            fm = self._path_label.fontMetrics()
            elided = fm.elidedText(
                str(self._selected),
                Qt.TextElideMode.ElideLeft,
                self._path_label.width() or 400,
            )
            self._path_label.setText(elided)

    def eventFilter(self, obj: object, event: object) -> bool:
        if obj is self._list and isinstance(event, QKeyEvent):
            key = event.key()
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                item = self._list.currentItem()
                if item is not None:
                    self._on_activate(item)
                return True
            if key == Qt.Key.Key_Backspace:
                parent = self._current.parent
                if parent != self._current:
                    self._navigate(parent)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def _confirm(self) -> None:
        if self._selected is not None and self._selected.is_file():
            self.accept()

    # ----------------------------------------------------------- public API
    @property
    def selected_path(self) -> Path | None:
        return self._selected

    @staticmethod
    def get_file(
        parent: QWidget | None,
        start_dir: str,
        title: str = "Open file",
    ) -> str | None:
        """Show the dialog and return the selected path, or None on cancel."""
        dlg = FileBrowserDialog(start_dir, title, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_path:
            return str(dlg.selected_path)
        return None
