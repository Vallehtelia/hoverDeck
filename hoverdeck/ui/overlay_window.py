"""The overlay: a frameless, always-on-top gunmetal housing.

Frameless | stays-on-top | Tool (off the taskbar), translucent background so
only the rounded housing shows. Dragged by the machined handle strip at the
top — a ~1.5s long-press on it is the (unhinted) vault trigger.

Phase 2 (§8): edit mode + deck persistence, the resize grip (SCALE),
tuck-to-edge peeking behind a PeekButton, the AI Builder panel.
Phase 3: multi-page decks with interactive page dots, the encrypted vault
page (ember wash + auto-relock), global hotkey dispatch.
"""
from __future__ import annotations

import uuid

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from hoverdeck.core.action_runner import ActionRunner
from hoverdeck.core.models import Action, Deck, Page, Settings
from hoverdeck.security.vault import VaultStore
from hoverdeck.storage.deck_store import DeckStore
from hoverdeck.storage.macro_store import MacroStore
from hoverdeck.storage.settings_store import SettingsStore
from hoverdeck.ui import screens, theme
from hoverdeck.ui.ai_builder_panel import AIBuilderPanel
from hoverdeck.ui.deck_grid import ActionDispatcher, DeckGrid
from hoverdeck.ui.dialogs.button_editor import ButtonEditor
from hoverdeck.ui.dialogs.macro_editor import MacroEditor
from hoverdeck.ui.dialogs.settings_dialog import SettingsDialog
from hoverdeck.core import vpn
from hoverdeck.ui.pin_pad import PinPad
from hoverdeck.ui.widgets.peek_button import PeekButton
from hoverdeck.ui.widgets.vpn_badge import VpnBadge
from hoverdeck.utils import win as winutil
from hoverdeck.utils.hotkeys import HotkeyManager
from hoverdeck.utils.logging import get_logger

log = get_logger("overlay")

NO_EMPTY_SLOT_COPY = "No empty slot — clear a key in Edit or enlarge the grid."


class DragHandle(QWidget):
    """The machined strip: drag to move the deck; three engraved notches.

    The chevron at the right end tucks the deck to the screen edge (§8.B).
    A quiet ~1.5s long-press anywhere on the strip summons the vault PIN pad —
    no tooltip, no cursor change, nothing on screen hints at it.
    """

    secret_held = pyqtSignal()
    tuck_requested = pyqtSignal()
    drag_finished = pyqtSignal()   # a move drag ended; re-snap to the wall

    def __init__(self, window: QWidget, hold_ms: int = 1500,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._drag_offset: QPoint | None = None
        self._dragged = False
        self.setFixedHeight(theme.HANDLE_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(hold_ms)
        self._hold.timeout.connect(self._on_held)
        self._held_fired = False

    def _tuck_zone(self) -> QRectF:
        side = float(theme.HANDLE_HEIGHT)
        return QRectF(self.width() - side * 1.6, 0, side * 1.6, side)

    def _on_held(self) -> None:
        self._held_fired = True
        self.secret_held.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
            self._dragged = False
            self._held_fired = False
            self._hold.start()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._dragged = True
            self._hold.stop()  # a drag is a drag, not a long-press
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._hold.stop()
        if self._dragged:
            self.drag_finished.emit()  # re-snap the deck to its wall
        elif (
            not self._held_fired
            and event.button() == Qt.MouseButton.LeftButton
            and self._tuck_zone().contains(event.position())
        ):
            self.tuck_requested.emit()
        self._drag_offset = None
        event.accept()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(theme.qcolor(theme.KEYCAP))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, theme.HANDLE_RADIUS, theme.HANDLE_RADIUS)

        # Three engraved notches: dark groove with a light glint below.
        notch_w = float(theme.HANDLE_NOTCH_WIDTH)
        gap = float(theme.HANDLE_NOTCH_GAP)
        total = theme.HANDLE_NOTCHES * notch_w + (theme.HANDLE_NOTCHES - 1) * gap
        x = rect.center().x() - total / 2
        y = rect.center().y()
        groove = QColor(theme.PANEL)
        groove.setAlpha(theme.NOTCH_SHADOW_ALPHA)
        glint = QColor(theme.INK)
        glint.setAlpha(theme.NOTCH_GLINT_ALPHA)
        for _ in range(theme.HANDLE_NOTCHES):
            painter.setPen(QPen(groove, 1))
            painter.drawLine(QRectF(x, y - 1, notch_w, 0).topLeft(),
                             QRectF(x, y - 1, notch_w, 0).topRight())
            painter.setPen(QPen(glint, 1))
            painter.drawLine(QRectF(x, y, notch_w, 0).topLeft(),
                             QRectF(x, y, notch_w, 0).topRight())
            x += notch_w + gap

        # Tuck chevron, right end: quiet seam metal, like the notches.
        zone = self._tuck_zone()
        pen = QPen(theme.qcolor(theme.SEAM).lighter(theme.EDIT_BADGE_LIGHTER), 1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        size = theme.HANDLE_HEIGHT * 0.22
        cx, cy = zone.center().x(), zone.center().y()
        for dx in (-size, size * 0.6):
            painter.drawLine(QRectF(cx + dx, cy - size, 0, 0).topLeft(),
                             QRectF(cx + dx + size, cy, 0, 0).topLeft())
            painter.drawLine(QRectF(cx + dx + size, cy, 0, 0).topLeft(),
                             QRectF(cx + dx, cy + size, 0, 0).topLeft())


class PageDots(QWidget):
    """Interactive page dots (§8.D) + the unhinted vault dot (§8.C).

    Normal pages: seam dots, the active one signal-amber. The vault dot sits
    last, barely visible (idle-lamp alpha) — it only turns amber while the
    vault is unlocked AND active. In edit mode a faint "+" dot adds a page,
    right-click deletes, double-click renames inline.
    """

    page_selected = pyqtSignal(int)            # combined index (vault = count)
    add_page_requested = pyqtSignal()
    delete_page_requested = pyqtSignal(int)
    rename_page_requested = pyqtSignal(int, str)

    def __init__(self, names: list[str], active: int, vault_unlocked: bool,
                 edit_mode: bool, vault_visible: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._names = names
        self._active = active
        self._vault_unlocked = vault_unlocked
        self._edit_mode = edit_mode
        self._vault_visible = vault_visible
        self._rename_index: int | None = None
        self.setFixedHeight(theme.PAGE_DOT_HIT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._rename_edit = QLineEdit(self)
        self._rename_edit.setFont(theme.mono_font(theme.LABEL_POINT_SIZE + 1))
        self._rename_edit.setProperty("role", "mono")
        self._rename_edit.hide()
        self._rename_edit.editingFinished.connect(self._finish_rename)

    # ----------------------------------------------------------- geometry
    def _dot_specs(self) -> list[tuple[str, int, QRectF]]:
        """[(kind, page_index, hit_rect)] — kind: page | add | vault."""
        d = theme.PAGE_DOT_DIAMETER
        hit = theme.PAGE_DOT_HIT
        gap = d * 2
        kinds: list[tuple[str, int]] = [("page", i) for i in range(len(self._names))]
        if self._edit_mode:
            kinds.append(("add", -1))
        if self._vault_visible:
            kinds.append(("vault", -1))

        total = len(kinds) * d + (len(kinds) - 1) * gap
        x = self.width() / 2 - total / 2
        specs: list[tuple[str, int, QRectF]] = []
        for kind, index in kinds:
            specs.append(
                (kind, index,
                 QRectF(x - (hit - d) / 2, 0, hit, hit))
            )
            x += d + gap
        return specs

    def _hit(self, pos: QPoint) -> tuple[str, int] | None:
        for kind, index, rect in self._dot_specs():
            if rect.contains(QRectF(pos.x(), pos.y(), 1, 1).center()):
                return kind, index
        return None

    # -------------------------------------------------------------- events
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        hit = self._hit(event.position().toPoint())
        if hit is None:
            return
        kind, index = hit
        if event.button() == Qt.MouseButton.LeftButton:
            if kind == "page":
                self.page_selected.emit(index)
            elif kind == "add":
                self.add_page_requested.emit()
            elif kind == "vault" and self._vault_unlocked:
                self.page_selected.emit(len(self._names))
            # A locked vault dot swallows the click: nothing happens, on purpose.
        elif event.button() == Qt.MouseButton.RightButton:
            if kind == "page" and self._edit_mode:
                menu = QMenu(self)
                delete = menu.addAction("Delete page")
                delete.setEnabled(len(self._names) > 1)
                if menu.exec(event.globalPosition().toPoint()) is delete:
                    self.delete_page_requested.emit(index)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        hit = self._hit(event.position().toPoint())
        if hit is None or not self._edit_mode or hit[0] != "page":
            return
        kind, index = hit
        self._rename_index = index
        specs = self._dot_specs()
        rect = specs[index][2]
        width = theme.PAGE_DOT_HIT * 6
        x = int(min(max(0, rect.center().x() - width / 2), self.width() - width))
        self._rename_edit.setGeometry(x, 0, width, self.height())
        self._rename_edit.setText(self._names[index])
        self._rename_edit.selectAll()
        self._rename_edit.show()
        self._rename_edit.setFocus()

    def _finish_rename(self) -> None:
        if self._rename_index is None:
            return
        index, self._rename_index = self._rename_index, None
        self._rename_edit.hide()
        name = self._rename_edit.text().strip()
        if name and name != self._names[index]:
            self.rename_page_requested.emit(index, name)

    # ------------------------------------------------------------ painting
    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = theme.PAGE_DOT_DIAMETER
        y = self.height() / 2 - d / 2

        for kind, index, hit_rect in self._dot_specs():
            cx = hit_rect.center().x()
            dot = QRectF(cx - d / 2, y, d, d)
            if kind == "page":
                token = theme.SIGNAL if index == self._active else theme.SEAM
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.qcolor(token))
                painter.drawEllipse(dot)
            elif kind == "add":
                painter.setPen(QPen(theme.qcolor(theme.INK_DIM), theme.SEAM_WIDTH))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(QRectF(cx - d / 2, y + d / 2, d, 0).topLeft(),
                                 QRectF(cx - d / 2, y + d / 2, d, 0).topRight())
                painter.drawLine(QRectF(cx, y, 0, d).topLeft(),
                                 QRectF(cx, y, 0, d).bottomLeft())
            else:  # vault: a barely-visible seam dot; amber only when active
                painter.setPen(Qt.PenStyle.NoPen)
                if self._vault_unlocked and self._active == len(self._names):
                    painter.setBrush(theme.qcolor(theme.SIGNAL))
                else:
                    painter.setBrush(theme.qcolor(theme.SEAM, theme.LED_IDLE_ALPHA))
                painter.drawEllipse(dot)


class ResizeGrip(QWidget):
    """Bottom-right corner: a 3-dot machined grille; drag to scale the deck."""

    scale_preview = pyqtSignal(float)   # while dragging
    scale_committed = pyqtSignal(float)  # on release

    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__(overlay)
        self._overlay = overlay
        self._press_global: QPoint | None = None
        self._start_scale = theme.SCALE
        self._start_width = 1
        self.setFixedSize(theme.GRIP_SIZE, theme.GRIP_SIZE)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_scale = theme.SCALE
            self._start_width = max(1, self._overlay.width())
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        factor = (self._start_width + delta.x()) / self._start_width
        self.scale_preview.emit(self._start_scale * factor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press_global is not None:
            self._press_global = None
            self.scale_committed.emit(theme.SCALE)
            event.accept()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(theme.SEAM))
        d = theme.GRIP_DOT
        gap = d * 2
        # Speaker-grille triangle hugging the corner.
        for i, j in ((2, 0), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2)):
            painter.drawEllipse(QRectF(i * gap, j * gap, d, d))


class OverlayWindow(QWidget):
    """The housing that everything is mounted in."""

    # Emitted when the user explicitly switches pages (click, swipe) — not when
    # the profile auto-switcher calls switch_page() programmatically.
    page_manually_switched = pyqtSignal()

    def __init__(
        self,
        deck: Deck,
        settings: Settings,
        runner: ActionRunner,
        deck_store: DeckStore,
        settings_store: SettingsStore,
        macro_store: MacroStore,
        vault_store: VaultStore | None = None,
        hotkeys: HotkeyManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._deck = deck
        self._settings = settings
        self._deck_store = deck_store
        self._settings_store = settings_store
        self._macro_store = macro_store
        self._vault_store = vault_store
        self._hotkeys = hotkeys

        self._edit_mode = False
        self._page_index = 0  # combined: 0..n-1 pages, n == vault (if unlocked)
        self._vault_deck: Deck | None = None
        self._vault_pin: str | None = None
        self._pin_pad: PinPad | None = None
        self._pin_attempts = 0  # consecutive wrong PINs → escalating lockout
        self._peek: PeekButton | None = None
        self._tucking = False
        self._panel: AIBuilderPanel | None = None
        self._slide: QPropertyAnimation | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keeps it off the taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(settings.opacity)

        self._runner = runner
        self._dispatcher = ActionDispatcher(
            runner, self, is_vault_action=self._is_vault_action_id
        )
        self._dispatcher.started.connect(lambda _aid: self._poke_relock())

        self._relock_timer = QTimer(self)
        self._relock_timer.setSingleShot(True)
        self._relock_timer.timeout.connect(self.relock)

        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(*([theme.OVERLAY_PADDING] * 4))
        self._root.setSpacing(theme.SECTION_SPACING)
        self._column: QWidget | None = None
        self._grid: DeckGrid | None = None
        self._build_column()

        self._grip = ResizeGrip(self)
        self._grip.scale_preview.connect(lambda s: self.apply_scale(s, persist=False))
        self._grip.scale_committed.connect(lambda s: self.apply_scale(s, persist=True))
        self._grip.raise_()

        # VPN status overlay (optional): a badge on the deck + a dot on the lamp.
        self._vpn_state: bool | None = None
        self._vpn_badge = VpnBadge(self)
        self._vpn_badge.hide()
        self._vpn_timer = QTimer(self)
        self._vpn_timer.setInterval(4000)
        self._vpn_timer.timeout.connect(self._refresh_vpn)

        self._fit()
        self._place_default()
        self._configure_vpn()

    # --------------------------------------------------------- page helpers
    def _vault_index(self) -> int:
        return len(self._deck.pages)

    def _is_vault_active(self) -> bool:
        return self._page_index == self._vault_index() and self._vault_deck is not None

    def _is_vault_action_id(self, action_id: str) -> bool:
        """True if the action belongs to the (unlocked) vault deck.

        Only these may run hidden (vault-only) scripts.
        """
        return self._vault_deck is not None and action_id in self._vault_deck.actions

    def _current_page(self) -> Page:
        if self._is_vault_active():
            assert self._vault_deck is not None
            return self._vault_deck.pages[0]
        return self._deck.pages[min(self._page_index, len(self._deck.pages) - 1)]

    def _current_actions(self) -> dict[str, Action]:
        if self._is_vault_active():
            assert self._vault_deck is not None
            return self._vault_deck.actions
        return self._deck.actions

    def _persist_current(self) -> None:
        if self._is_vault_active():
            assert self._vault_deck is not None and self._vault_pin is not None
            if self._vault_store is not None:
                self._vault_store.save(self._vault_pin, self._vault_deck)
        else:
            self._deck_store.save(self._deck)
        if self._grid is not None:
            self._grid.refresh()

    def switch_page(self, combined_index: int) -> None:
        top = self._vault_index() if self._vault_deck is not None \
            else self._vault_index() - 1
        combined_index = max(0, min(top, combined_index))
        if combined_index == self._page_index:
            return
        self._page_index = combined_index
        self._build_column()
        self._fit()
        self._poke_relock()
        self.update()  # vault wash on/off

    # ------------------------------------------------------------ building
    def _build_column(self) -> None:
        if self._column is not None:
            self._root.removeWidget(self._column)
            self._column.deleteLater()

        column = QWidget(self)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SECTION_SPACING)

        handle = DragHandle(self, self._settings.secret_trigger.hold_ms, column)
        handle.tuck_requested.connect(self.tuck)
        handle.secret_held.connect(self._open_pin_pad)
        handle.drag_finished.connect(self._snap_to_wall)

        grid = DeckGrid(self._current_page(), self._current_actions(),
                        self._settings, self._dispatcher, column)
        grid.edit_slot.connect(self._on_edit_slot)
        grid.delete_slot.connect(self._on_delete_slot)
        grid.swap_slots.connect(self._on_swap_slots)
        grid.swiped.connect(self._on_swipe)
        grid.set_edit_mode(self._edit_mode)

        dots = PageDots(
            [p.name for p in self._deck.pages],
            self._page_index,
            self._vault_deck is not None,
            self._edit_mode,
            self._settings.vault_visible,
            column,
        )
        dots.page_selected.connect(self._on_user_page_select)
        dots.add_page_requested.connect(self._add_page)
        dots.delete_page_requested.connect(self._delete_page)
        dots.rename_page_requested.connect(self._rename_page)

        layout.addWidget(handle)
        layout.addWidget(grid)
        layout.addWidget(dots)

        self._column = column
        self._grid = grid
        self._root.insertWidget(0, column)
        # Children added after the window is shown stay hidden (and are then
        # excluded from the layout's size hint) unless shown explicitly.
        column.show()

    def _fit(self) -> None:
        self.setFixedSize(self.sizeHint())
        self._position_grip()

    def _position_grip(self) -> None:
        if hasattr(self, "_grip"):
            margin = theme.SEAM_WIDTH * 3
            self._grip.move(
                self.width() - self._grip.width() - margin,
                self.height() - self._grip.height() - margin,
            )
            self._grip.raise_()
        if getattr(self, "_vpn_badge", None) is not None:
            pad = theme.OVERLAY_PADDING
            self._vpn_badge.move(
                pad + theme.SEAM_WIDTH * 2,
                self.height() - self._vpn_badge.height() - pad,
            )
            self._vpn_badge.raise_()

    def _configure_vpn(self) -> None:
        """Start/stop the VPN poll + show/hide the badge per the setting."""
        if self._settings.vpn_overlay:
            if not self._vpn_timer.isActive():
                self._vpn_timer.start()
            self._refresh_vpn()
        else:
            self._vpn_timer.stop()
            self._vpn_state = None
            self._vpn_badge.hide()
            if self._peek is not None:
                self._peek.set_vpn(False, None)

    def _refresh_vpn(self) -> None:
        if not self._settings.vpn_overlay:
            return
        state = vpn.vpn_status(self._settings.vpn_adapter_hint)
        if state != self._vpn_state:
            log.info("VPN status -> %s: %s", state, vpn.last_detail())
        self._vpn_state = state
        self._vpn_badge.set_state(self._vpn_state)
        self._vpn_badge.show()       # follows the deck; hidden with it when tucked
        self._position_grip()
        if self._peek is not None:
            self._peek.set_vpn(True, self._vpn_state)

    def resizeEvent(self, event: object) -> None:
        self._position_grip()
        super().resizeEvent(event)  # type: ignore[arg-type]

    def _home_pos(self) -> QPoint:
        """Anchored top-left, floating just off the chosen monitor's right wall.

        A ``gap`` of clear space is left between the painted housing and the
        wall/floor so the deck doesn't touch the screen edges. The vertical
        position is the persisted ``dock_y`` (default: near the bottom), so the
        deck always returns to the same place.
        """
        area = self._screen_area()
        pad = theme.OVERLAY_PADDING       # transparent margin inside the window
        gap = theme.OVERLAY_PADDING       # clear space between housing and edge
        x = area.right() - gap - self.width() + pad
        floor_y = area.bottom() - gap - self.height() + pad
        if self._settings.dock_y < 0:
            y = floor_y
        else:
            y = area.top() + self._settings.dock_y
        y = max(area.top(), min(floor_y, y))
        return QPoint(x, y)

    def _place_default(self) -> None:
        """Park flush against the right wall at the remembered height."""
        self.move(self._home_pos())

    def _snap_to_wall(self) -> None:
        """Re-glue the deck to the right wall after a free drag; keep the height."""
        area = self._screen_area()
        y = max(area.top(), min(area.bottom() - self.height() + 1, self.y()))
        self._settings.dock_y = max(0, y - area.top())
        self._settings_store.save(self._settings)
        home = self._home_pos()
        log.info("snap_to_wall: drag-end (%d,%d) -> home (%d,%d) on %s %s",
                 self.x(), self.y(), home.x(), home.y(),
                 self._settings.monitor or "primary", area)
        self.move(home)

    def redock(self) -> None:
        """Re-anchor to the (possibly newly chosen) monitor's right wall."""
        if self._peek is not None:
            self._peek.set_screen(self._settings.monitor)
            self._peek.place(self._settings.peek_offset)
        else:
            self.move(self._home_pos())

    def _apply_grid_size(self) -> None:
        """Resize every page to the configured rows×cols.

        Keys in slots beyond the new grid stay in the data (harmless) and
        reappear if the grid grows again — nothing is destroyed.
        """
        rows, cols = self._settings.grid_rows, self._settings.grid_cols
        for page in self._deck.pages:
            page.rows, page.cols = rows, cols
        self._deck_store.save(self._deck)
        if self._vault_deck is not None:
            for page in self._vault_deck.pages:
                page.rows, page.cols = rows, cols
            if self._vault_pin is not None and self._vault_store is not None:
                self._vault_store.save(self._vault_pin, self._vault_deck)

    # --------------------------------------------------------------- pages
    @property
    def page_index(self) -> int:
        return self._page_index

    def _on_user_page_select(self, index: int) -> None:
        self.switch_page(index)
        self.page_manually_switched.emit()

    def switch_to_page_id(self, page_id: str) -> bool:
        """Switch to the page with the given id. Returns False if not found."""
        for i, page in enumerate(self._deck.pages):
            if page.id == page_id:
                self.switch_page(i)
                return True
        return False

    def _on_swipe(self, direction: int) -> None:
        self.switch_page(self._page_index + direction)
        self.page_manually_switched.emit()

    def _add_page(self) -> None:
        self._deck.pages.append(Page(
            id=uuid.uuid4().hex[:8],
            name=f"Page {len(self._deck.pages) + 1}",
            rows=self._settings.grid_rows,
            cols=self._settings.grid_cols,
        ))
        self._deck_store.save(self._deck)
        self.switch_page(len(self._deck.pages) - 1)

    def _delete_page(self, index: int) -> None:
        if len(self._deck.pages) <= 1:
            return
        page = self._deck.pages.pop(index)
        for action_id in set(page.slots.values()):
            if not any(action_id in p.slots.values() for p in self._deck.pages):
                self._deck.actions.pop(action_id, None)
        self._deck_store.save(self._deck)
        self._page_index = min(self._page_index, len(self._deck.pages) - 1)
        self._build_column()
        self._fit()

    def _rename_page(self, index: int, name: str) -> None:
        self._deck.pages[index].name = name
        self._deck_store.save(self._deck)
        self._build_column()
        self._fit()

    # --------------------------------------------------------------- vault
    def _open_pin_pad(self) -> None:
        if self._vault_store is None:
            return
        if self._vault_deck is not None:  # already unlocked: just go there
            self.switch_page(self._vault_index())
            return
        if self._pin_pad is None:
            self._pin_pad = PinPad(self._settings.reduce_motion, self)
            self._pin_pad.pin_submitted.connect(self._on_pin)
        self._pin_pad.open()

    def _on_pin(self, pin: str) -> None:
        assert self._vault_store is not None and self._pin_pad is not None
        if not self._vault_store.exists():
            # First use: this PIN becomes the vault code.
            vault = self._vault_store.setup(
                pin, self._settings.grid_rows, self._settings.grid_cols
            )
        else:
            vault = self._vault_store.load(pin)
        if vault is None:
            self._pin_attempts += 1
            delay = self._wrong_pin_lock_s(self._pin_attempts)
            if delay > 0:
                self._pin_pad.lock_for(delay)
            else:
                self._pin_pad.reject_wrong_code()
            return
        self._pin_attempts = 0
        self._vault_deck = vault
        self._vault_pin = pin
        self._pin_pad.accept_unlock()
        delay = theme.PIN_FLASH_MS + theme.PIN_SLIDE_MS + 20
        QTimer.singleShot(delay, lambda: self.switch_page(self._vault_index()))

    @staticmethod
    def _wrong_pin_lock_s(attempts: int) -> int:
        """Lockout seconds after ``attempts`` consecutive wrong PINs.

        First two are free (a typo shouldn't punish); then 5s, 10s, 20s …
        doubling up to a 5-minute cap, to choke off brute-force attempts.
        """
        if attempts < 3:
            return 0
        return min(5 * (2 ** (attempts - 3)), 300)

    def relock(self) -> None:
        """Drop the vault from memory; nothing on screen mentions it."""
        if self._vault_pin is None:
            return
        self._vault_deck = None
        self._vault_pin = None
        self._relock_timer.stop()
        if self._page_index >= self._vault_index():
            self._page_index = 0
            self._build_column()
            self._fit()
        self.update()

    def _poke_relock(self) -> None:
        """Any activity while unlocked restarts the relock countdown."""
        if self._vault_pin is not None:
            self._relock_timer.start(self._settings.relock_timeout_s * 1000)

    def hideEvent(self, event: QHideEvent) -> None:
        self.relock()  # hiding (incl. tucking) always relocks
        super().hideEvent(event)

    # ----------------------------------------------------------- edit mode
    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, enabled: bool) -> None:
        if enabled == self._edit_mode:
            return
        self._edit_mode = enabled
        self._build_column()  # the dots row changes shape (the + dot)
        self._fit()

    def _macro_list(self) -> list[tuple[str, str]]:
        return [(m.id, m.name) for m in self._macro_store.load_all()]

    def _on_edit_slot(self, slot: int) -> None:
        page = self._current_page()
        actions = self._current_actions()
        action = actions.get(page.slots.get(slot, ""))
        deck_for_editor = self._vault_deck if self._is_vault_active() else self._deck
        assert deck_for_editor is not None
        editor = ButtonEditor(
            deck_for_editor, action, self._macro_list(), self,
            allow_hidden_scripts=self._is_vault_active(),
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            result = editor.result_action()
            actions[result.id] = result
            page.slots[slot] = result.id
            self._persist_current()
        self._poke_relock()

    def _on_delete_slot(self, slot: int) -> None:
        page = self._current_page()
        actions = self._current_actions()
        pages = (self._vault_deck.pages if self._is_vault_active() and self._vault_deck
                 else self._deck.pages)
        action_id = page.slots.pop(slot, "")
        if action_id and not any(action_id in p.slots.values() for p in pages):
            actions.pop(action_id, None)
        self._persist_current()
        self._poke_relock()

    def _on_swap_slots(self, source: int, target: int) -> None:
        slots = self._current_page().slots
        slots[source], slots[target] = slots.get(target, ""), slots.get(source, "")
        for index in (source, target):
            if not slots.get(index):
                slots.pop(index, None)
        self._persist_current()
        self._poke_relock()

    def open_macros(self) -> None:
        MacroEditor(self._macro_store, self).exec()

    def open_scripts(self) -> None:
        from hoverdeck import config
        from hoverdeck.ui.dialogs.script_manager import ScriptManager
        ScriptManager(
            config.SCRIPTS_DIR, self._settings.script_python,
            vault_unlocked=self._vault_deck is not None, parent=self,
        ).exec()

    def _set_vault_visible(self, visible: bool) -> None:
        """Toggle the vault page dot (vault-only setting; secret entry stays)."""
        self._settings.vault_visible = visible
        self._settings_store.save(self._settings)
        self._build_column()
        self._fit()

    # ------------------------------------------------------------- hotkeys
    def run_action_by_id(self, action_id: str) -> None:
        """Dispatch an action fired from a global hotkey (queued to UI thread)."""
        action = self._deck.actions.get(action_id)
        if action is None and self._vault_deck is not None:
            action = self._vault_deck.actions.get(action_id)
        if action is None:
            log.warning("Hotkey fired for an unknown action: %s", action_id)
            return
        self._dispatcher.run(action)

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        original_scale = self._settings.scale
        actions = [(a.id, a.name) for a in self._deck.actions.values()]
        pages = [(p.id, p.name) for p in self._deck.pages]
        dialog = SettingsDialog(
            self._settings,
            actions,
            pages=pages,
            on_scale_preview=lambda s: self.apply_scale(s, persist=False),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_to(self._settings)
            self._apply_grid_size()  # resize pages before the rebuild below
            self.apply_scale(self._settings.scale, persist=False)
            self._settings_store.save(self._settings)
            if self._panel is not None:
                self._panel.refresh_credentials()
            if self._hotkeys is not None:
                self._hotkeys.apply(self._settings.global_hotkeys)
            winutil.set_autostart(self._settings.autostart)
            self._runner.set_python_exe(self._settings.script_python or None)
            self._configure_vpn()  # VPN overlay may have been toggled
            self.redock()  # monitor may have changed — re-glue to the right wall
        else:
            self.apply_scale(original_scale, persist=False)

    # --------------------------------------------------------------- scale
    def apply_scale(self, scale: float, persist: bool) -> None:
        self._settings.scale = theme.set_scale(scale)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.app_qss())  # type: ignore[union-attr]
        self._build_column()
        if self._panel is not None:
            self._panel.setFixedWidth(theme.AI_PANEL_WIDTH)
        self._fit()
        if persist:
            self._settings_store.save(self._settings)

    # ----------------------------------------------------------- AI panel
    def toggle_ai_builder(self) -> None:
        if self._panel is not None and self._panel.isVisible():
            self._close_ai_builder()
            return
        if self._panel is None:
            from hoverdeck import config
            self._panel = AIBuilderPanel(
                self._settings,
                scripts_dir=config.SCRIPTS_DIR,
                vault_unlocked=lambda: self._vault_deck is not None,
            )
            self._panel.action_ready.connect(self._add_action_from_ai)
            self._panel.closed.connect(self._close_ai_builder)
        page = self._current_page()
        from hoverdeck import config as _config
        from hoverdeck.core.script_catalog import catalog
        scripts = catalog(
            _config.SCRIPTS_DIR, include_hidden=self._vault_deck is not None
        )
        self._panel.begin_session(
            [name for _, name in self._macro_list()],
            page.rows * page.cols,
            free_slots=[
                i for i in range(page.rows * page.cols) if not page.slots.get(i)
            ],
            scripts=scripts,
        )
        side = self._panel_side()
        if self._settings.ai_panel_mode == "floating":
            self._panel.setParent(None)
            self._panel.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self._panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            pad = theme.OVERLAY_PADDING
            self._panel.layout().setContentsMargins(pad, pad, pad, pad)
            self._panel.setFixedWidth(theme.AI_PANEL_WIDTH + pad * 2)
            self._panel.resize(self._panel.width(), self.height())
            if side == "right":
                x = self.x() + self.width() + pad
            else:
                x = self.x() - self._panel.width() - pad
            area = self._screen_area()
            x = max(area.left(), min(x, area.right() - self._panel.width() + 1))
            self._panel.move(x, self.y())
            self._panel.show()
        else:
            self._panel.setParent(self)
            self._panel.setWindowFlags(Qt.WindowType.Widget)
            self._panel.layout().setContentsMargins(0, 0, 0, 0)
            self._panel.setFixedWidth(theme.AI_PANEL_WIDTH)
            if side == "right":
                self._root.addWidget(self._panel)
            else:
                self._root.insertWidget(0, self._panel)
            self._panel.show()
            self._fit()
            self.redock()  # widened housing: keep it glued inside the wall

    def _panel_side(self) -> str:
        """Where the AI panel opens, relative to the deck.

        "auto" picks the side with room: a deck on the right half of the
        screen opens the panel to the LEFT (never past the wall / onto the
        next monitor), and vice versa.
        """
        side = self._settings.ai_panel_side
        if side in ("left", "right"):
            return side
        area = self._screen_area()
        on_right_half = self.frameGeometry().center().x() >= area.center().x()
        return "left" if on_right_half else "right"

    def _close_ai_builder(self) -> None:
        if self._panel is None:
            return
        if self._panel.parent() is self:
            self._root.removeWidget(self._panel)
        self._panel.hide()
        self._fit()
        self.redock()  # housing narrowed again — back flush to the wall

    def _add_action_from_ai(self, payload: object) -> None:
        # payload: (Action, slot|None) — slot is the user's requested position.
        if isinstance(payload, tuple):
            action, wanted = payload
        else:                       # plain Action (older callers)
            action, wanted = payload, None
        page = self._current_page()
        actions = self._current_actions()
        slot_count = page.rows * page.cols
        empty = None
        if isinstance(wanted, int) and 0 <= wanted < slot_count \
                and not page.slots.get(wanted):
            empty = wanted
        else:
            empty = next(
                (i for i in range(slot_count) if not page.slots.get(i)), None
            )
        if empty is None:
            if self._panel is not None:
                self._panel.show_error(NO_EMPTY_SLOT_COPY)
            return
        actions[action.id] = action
        page.slots[empty] = action.id
        self._persist_current()
        log.info("AI builder added %r to slot %d.", action.name, empty)
        if self._panel is not None:
            self._panel.confirm_added(action.name)

    # ---------------------------------------------------------------- peek
    def _screen_area(self) -> QRect:
        """Available geometry of the user-chosen monitor (primary by default)."""
        return screens.screen_area(self._settings.monitor)

    def tuck(self, edge: str | None = None) -> None:
        """Hide the deck behind a peek lamp on the chosen monitor's right wall.

        Tucking always docks to the right wall so the deck and its lamp stay
        glued there (never jumping across monitors). The deck's height is
        remembered as ``dock_y`` so untuck restores it exactly; the lamp is
        placed only AFTER the overlay hides so its own frame can't interfere.
        """
        if self._peek is not None or self._tucking:
            return
        self._tucking = True
        area = self._screen_area()
        edge = edge or "right"
        center = self.frameGeometry().center()

        # Remember where the deck sat so we can put it back unchanged.
        self._settings.dock_y = max(0, self.y() - area.top())

        # Peek lamp centered on the overlay's position along the edge axis.
        if edge in ("left", "right"):
            offset = center.y() - area.top() - theme.PEEK_RADIUS
        else:
            offset = center.x() - area.left() - theme.PEEK_RADIUS

        self._settings.peek_enabled = True
        self._settings.peek_edge = edge
        self._settings.peek_offset = max(0, offset)
        self._settings_store.save(self._settings)

        log.info("tuck: edge=%s area=%s deck@(%d,%d) -> dock_y=%d peek_offset=%d "
                 "reduce_motion=%s", edge, area, self.x(), self.y(),
                 self._settings.dock_y, self._settings.peek_offset,
                 self._settings.reduce_motion)

        def finish() -> None:
            self.hide()  # hide FIRST, then place the lamp
            self.setWindowOpacity(self._settings.opacity)  # reset for the next show
            self._show_peek(edge, self._settings.peek_offset)
            log.info("tuck.finish: deck visible=%s peek@(%d,%d)", self.isVisible(),
                     self._peek.x() if self._peek else -1,
                     self._peek.y() if self._peek else -1)
            self._tucking = False

        if self._settings.reduce_motion:
            finish()
        else:
            # Fade out in place — never slides onto a neighbouring monitor.
            self._fade(self._settings.opacity, 0.0, finish)

    def untuck(self) -> None:
        """Bring the deck back to its home spot on the chosen monitor's wall.

        The target is the persisted right-wall home position, recomputed every
        time — never stale pre-hide geometry — so open/close is repeatable.
        """
        if self._peek is None:
            return
        edge = self._settings.peek_edge
        self._settings.peek_offset = self._peek.offset()
        self._peek.close()
        self._peek.deleteLater()
        self._peek = None
        self._settings.peek_enabled = False
        self._settings_store.save(self._settings)

        target = self._home_pos()
        log.info("untuck: edge=%s -> home (%d,%d) reduce_motion=%s",
                 edge, target.x(), target.y(), self._settings.reduce_motion)
        if self._settings.reduce_motion:
            self.move(target)
            self.setWindowOpacity(self._settings.opacity)
            self.show()
            self.raise_()
            return
        # Appear at home and fade in — no positional travel across monitors.
        self.move(target)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade(0.0, self._settings.opacity, None)

    def _show_peek(self, edge: str, offset: int) -> None:
        self._peek = PeekButton(edge, self._settings.monitor)
        self._peek.invoked.connect(self.untuck)
        self._peek.edge_moved.connect(self._on_peek_moved)
        self._peek.quit_requested.connect(self._quit)
        self._peek.set_vpn(self._settings.vpn_overlay, self._vpn_state)
        self._peek.place(offset)   # pre-position so no flash at (0,0)
        self._peek.show()
        self._peek.place(offset)   # re-enforce after show; some WMs reposition on map

    def _on_peek_moved(self, offset: int) -> None:
        self._settings.peek_offset = offset
        # Keep the deck's docked height aligned with the lamp it returns to.
        if self._settings.peek_edge in ("left", "right"):
            self._settings.dock_y = max(
                0, offset + theme.PEEK_RADIUS - self.height() // 2
            )
        self._settings_store.save(self._settings)

    def _fade(self, start: float, end: float, on_finish: object) -> None:
        """Animate window opacity in place (no movement → no monitor-hopping)."""
        self.setWindowOpacity(start)
        self._slide = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide.setDuration(theme.PEEK_SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._slide.setStartValue(start)
        self._slide.setEndValue(end)
        if callable(on_finish):
            self._slide.finished.connect(on_finish)
        self._slide.start()

    def show_or_peek(self) -> None:
        """Startup entry: restore peek mode if the deck was left tucked."""
        log.info("show_or_peek: peek_enabled=%s monitor=%s area=%s deck_pos=(%d,%d)",
                 self._settings.peek_enabled, self._settings.monitor or "primary",
                 self._screen_area(), self.x(), self.y())
        if self._settings.peek_enabled:
            self._show_peek(self._settings.peek_edge, self._settings.peek_offset)
        else:
            self.show()

    def toggle_visible(self) -> None:
        if self._peek is not None:
            self.untuck()
            return
        self.setVisible(not self.isVisible())

    # ---------------------------------------------------------------- menu
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        edit = menu.addAction("Edit the deck")
        edit.setCheckable(True)
        edit.setChecked(self._edit_mode)
        edit.toggled.connect(self.set_edit_mode)
        menu.addAction("AI Builder", self.toggle_ai_builder)
        menu.addAction("Macros…", self.open_macros)
        menu.addAction("Scripts…", self.open_scripts)
        # Vault-only: shows only while unlocked, so a bystander never sees it.
        if self._vault_deck is not None:
            dot = menu.addAction("Show vault dot")
            dot.setCheckable(True)
            dot.setChecked(self._settings.vault_visible)
            dot.toggled.connect(self._set_vault_visible)
            menu.addAction("Lock vault now", self.relock)
        menu.addSeparator()
        menu.addAction("Pin to edge", lambda: self.tuck(None))
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit HoverDeck", self._quit)
        menu.exec(event.globalPos())

    def _quit(self) -> None:
        """Clean shutdown — relock the vault, then drop the app."""
        self.relock()
        if self._peek is not None:
            self._peek.close()
        log.info("Quit requested from the overlay menu.")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ------------------------------------------------------------ painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(theme.qcolor(theme.PANEL))
        painter.setPen(QPen(theme.qcolor(theme.SEAM), theme.SEAM_WIDTH))
        painter.drawRoundedRect(rect, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)
        if self._is_vault_active():
            # Barely-perceptible ember wash: you know, a bystander doesn't.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(theme.VAULT_TINT, theme.VAULT_WASH_ALPHA))
            painter.drawRoundedRect(rect, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)
