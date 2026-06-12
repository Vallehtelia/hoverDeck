"""System tray: show/hide, edit mode, AI builder, pin to edge, settings, quit."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from hoverdeck.config import APP_NAME
from hoverdeck.ui import theme
from hoverdeck.ui.overlay_window import OverlayWindow


def _tray_icon() -> QIcon:
    """A tiny keycap with a lit amber lamp, painted from theme tokens."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rect = QRectF(4, 4, size - 8, size - 8)
    radius = theme.key_radius(size)
    painter.setBrush(theme.qcolor(theme.KEYCAP))
    painter.setPen(QPen(theme.qcolor(theme.SEAM), 3))
    painter.drawRoundedRect(rect, radius, radius)

    painter.setBrush(theme.qcolor(theme.SIGNAL))
    painter.setPen(Qt.PenStyle.NoPen)
    led = size * 0.14
    painter.drawEllipse(QRectF(rect.right() - led * 2.2, rect.top() + led * 1.2,
                               led, led))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, overlay: OverlayWindow, parent: QWidget | None = None) -> None:
        super().__init__(_tray_icon(), parent)
        self._overlay = overlay
        self.setToolTip(APP_NAME)

        menu = QMenu()
        self._toggle_action = QAction("Hide the deck", menu)
        self._toggle_action.triggered.connect(self._toggle)
        menu.addAction(self._toggle_action)

        self._edit_action = QAction("Edit the deck", menu)
        self._edit_action.setCheckable(True)
        self._edit_action.toggled.connect(overlay.set_edit_mode)
        menu.addAction(self._edit_action)

        ai_action = QAction("AI Builder", menu)
        ai_action.triggered.connect(overlay.toggle_ai_builder)
        menu.addAction(ai_action)

        macros_action = QAction("Macros…", menu)
        macros_action.triggered.connect(overlay.open_macros)
        menu.addAction(macros_action)

        scripts_action = QAction("Scripts…", menu)
        scripts_action.triggered.connect(overlay.open_scripts)
        menu.addAction(scripts_action)

        menu.addSeparator()
        pin_action = QAction("Pin to edge", menu)
        pin_action.triggered.connect(lambda: overlay.tuck(None))
        menu.addAction(pin_action)

        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(overlay.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self._menu = menu  # keep alive; the tray doesn't own it
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _toggle(self) -> None:
        self._overlay.toggle_visible()
        self._toggle_action.setText(
            "Hide the deck" if self._overlay.isVisible() else "Show the deck"
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle()
