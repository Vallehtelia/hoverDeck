"""A rounded, seam-bordered panel — the housing material, for dialog sections."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QFrame, QWidget

from hoverdeck.ui import theme


class RoundedFrame(QFrame):
    """Paints a panel-colored rounded rect with a 1px seam outline."""

    def __init__(self, parent: QWidget | None = None,
                 fill_token: str | None = None) -> None:
        super().__init__(parent)
        self._fill = fill_token or theme.PANEL
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(theme.qcolor(self._fill))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
