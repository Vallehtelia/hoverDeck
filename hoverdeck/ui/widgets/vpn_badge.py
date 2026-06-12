"""A small VPN status pill for the deck: a colored lamp + 'VPN' label.

Green = a VPN interface is up, red = none, dim = status unknown. Shown only
when Settings.vpn_overlay is on; it's click-through so it never blocks the deck.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from hoverdeck.ui import theme

_LABEL = "VPN"


class VpnBadge(QWidget):
    """Tiny status pill; call :meth:`set_state` with True / False / None."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: bool | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fit()

    def _fit(self) -> None:
        fm = self.fontMetrics()
        pad = theme.CONTROL_PADDING
        self._dot = theme.LED_DIAMETER + 1
        text_w = self._font_metrics_width()
        self.setFixedHeight(fm.height() + pad)
        self.setFixedWidth(pad + self._dot + pad // 2 + text_w + pad)

    def _font_metrics_width(self) -> int:
        from PyQt6.QtGui import QFontMetrics
        return QFontMetrics(theme.label_font(theme.LABEL_POINT_SIZE)).horizontalAdvance(
            _LABEL
        )

    def set_state(self, state: bool | None) -> None:
        if state != self._state:
            self._state = state
            self.setToolTip(
                "VPN connected" if state is True
                else "VPN not connected" if state is False
                else "VPN status unknown"
            )
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2

        painter.setBrush(theme.qcolor(theme.PANEL))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, radius, radius)

        lamp = (
            theme.LIVE if self._state is True
            else theme.FAULT if self._state is False
            else theme.INK_DIM
        )
        pad = theme.CONTROL_PADDING
        d = self._dot
        cy = rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        # soft halo + lamp
        painter.setBrush(theme.qcolor(lamp, theme.LED_GLOW_ALPHA))
        painter.drawEllipse(QRectF(rect.left() + pad - 1, cy - d / 2 - 1, d + 2, d + 2))
        painter.setBrush(theme.qcolor(lamp))
        painter.drawEllipse(QRectF(rect.left() + pad, cy - d / 2, d, d))

        painter.setFont(theme.label_font(theme.LABEL_POINT_SIZE))
        painter.setPen(theme.qcolor(theme.INK_DIM))
        text_rect = rect.adjusted(pad + d + pad / 2, 0, -pad / 2, 0)
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, _LABEL
        )
