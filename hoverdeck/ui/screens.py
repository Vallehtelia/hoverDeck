"""Multi-monitor helpers: resolve the user-chosen screen by name.

The deck and its peek lamp dock to the right wall of a single chosen monitor.
Everything that needs screen geometry routes through here so the deck never
jumps to the wrong display or computes off-screen positions on the wrong one.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication


def available_screens() -> list[QScreen]:
    """All connected screens (primary first is not guaranteed by Qt)."""
    return list(QApplication.screens())


def resolve_screen(name: str = "") -> QScreen | None:
    """Screen whose ``QScreen.name()`` matches ``name``; primary if unmatched."""
    if name:
        for screen in QApplication.screens():
            if screen.name() == name:
                return screen
    return QApplication.primaryScreen()


def screen_area(name: str = "") -> QRect:
    """Available geometry (taskbar-excluded) of the chosen screen."""
    screen = resolve_screen(name)
    return screen.availableGeometry() if screen is not None else QRect()


def describe(screen: QScreen, primary: bool) -> str:
    """Human label for a screen, e.g. ``\\\\.\\DISPLAY1 — 2560×1440 (primary)``."""
    geo = screen.geometry()
    tag = "  (primary)" if primary else ""
    return f"{screen.name()} — {geo.width()}×{geo.height()}{tag}"
