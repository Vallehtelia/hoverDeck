"""Edit-mode helpers: drag payloads, the lifted-key visual, the key menu.

The grid and buttons own the behavior; this module keeps the shared pieces
(mime type, drag pixmap, context menu) in one place.
"""
from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, Qt
from PyQt6.QtGui import QDrag, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QWidget

from hoverdeck.ui import theme

SLOT_MIME = "application/x-hoverdeck-slot"


def make_drag_pixmap(widget: QWidget) -> QPixmap:
    """The dragged key lifts: opacity 0.7, slight scale-up (§8.A)."""
    grabbed = widget.grab()
    size = grabbed.size() * theme.DRAG_LIFT_SCALE
    lifted = QPixmap(size)
    lifted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(lifted)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(theme.DRAG_LIFT_OPACITY)
    painter.drawPixmap(lifted.rect(), grabbed)
    painter.end()
    return lifted


def start_slot_drag(button: QWidget, slot_index: int) -> None:
    """Begin a drag carrying the source slot index."""
    mime = QMimeData()
    mime.setData(SLOT_MIME, str(slot_index).encode("ascii"))
    drag = QDrag(button)
    drag.setMimeData(mime)
    pixmap = make_drag_pixmap(button)
    drag.setPixmap(pixmap)
    drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
    drag.exec(Qt.DropAction.MoveAction)


def slot_from_mime(mime: QMimeData) -> int | None:
    if not mime.hasFormat(SLOT_MIME):
        return None
    try:
        return int(bytes(mime.data(SLOT_MIME)).decode("ascii"))
    except ValueError:
        return None


def show_key_menu(parent: QWidget, global_pos: QPoint) -> str | None:
    """Right-click menu for a bound key in edit mode: Edit / Delete / Move."""
    menu = QMenu(parent)
    edit = menu.addAction("Edit")
    move = menu.addAction("Move")
    delete = menu.addAction("Delete")
    chosen = menu.exec(global_pos)
    if chosen is edit:
        return "edit"
    if chosen is move:
        return "move"
    if chosen is delete:
        return "delete"
    return None
