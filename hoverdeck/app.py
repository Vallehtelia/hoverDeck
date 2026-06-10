"""QApplication lifecycle: wiring stores, runner, overlay, tray, and hotkeys."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from hoverdeck import config
from hoverdeck.core.action_runner import ActionRunner
from hoverdeck.core.models import WindowProfile
from hoverdeck.security.vault import VaultStore
from hoverdeck.storage.deck_store import DeckStore
from hoverdeck.storage.macro_store import MacroStore
from hoverdeck.storage.settings_store import SettingsStore
from hoverdeck.ui import theme
from hoverdeck.ui.overlay_window import OverlayWindow
from hoverdeck.ui.tray import Tray
from hoverdeck.utils.hotkeys import HotkeyManager
from hoverdeck.utils.logging import get_logger, setup_logging
from hoverdeck.utils.win import get_foreground_title


class _HotkeyBridge(QObject):
    """Marshals hotkey callbacks from the keyboard listener thread into Qt."""

    fired = pyqtSignal(str)  # action_id


class HoverDeckApp:
    """Owns the QApplication and the long-lived objects."""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.qapp = QApplication(argv if argv is not None else sys.argv)
        self.qapp.setApplicationName(config.APP_NAME)
        self.qapp.setQuitOnLastWindowClosed(False)  # we live in the tray

        config.ensure_dirs()
        setup_logging(config.LOG_FILE)
        self._log = get_logger("app")

        loaded = theme.load_fonts(config.FONTS_DIR)
        if loaded:
            self._log.info("Fonts loaded: %s", ", ".join(sorted(set(loaded))))
        else:
            self._log.warning(
                "No bundled fonts found in %s — using system fallbacks "
                "(see assets/fonts/FONTS.md).", config.FONTS_DIR,
            )

        self.settings_store = SettingsStore(config.SETTINGS_FILE)
        self.settings = self.settings_store.load()
        theme.set_scale(self.settings.scale)
        self.qapp.setStyleSheet(theme.app_qss())

        self.deck_store = DeckStore(config.DECKS_DIR)
        self.deck = self.deck_store.load()
        self.macro_store = MacroStore(config.MACROS_DIR)
        self.vault_store = VaultStore(config.VAULT_DIR)
        self.runner = ActionRunner(
            scripts_dir=config.SCRIPTS_DIR, macro_store=self.macro_store
        )

        # Global hotkeys: the keyboard lib fires on its own thread; the queued
        # Qt signal hands the action id to the UI thread safely.
        self._hotkey_bridge = _HotkeyBridge()
        self.hotkeys = HotkeyManager(self._hotkey_bridge.fired.emit)

        self.overlay = OverlayWindow(
            self.deck,
            self.settings,
            self.runner,
            self.deck_store,
            self.settings_store,
            self.macro_store,
            vault_store=self.vault_store,
            hotkeys=self.hotkeys,
        )
        self._hotkey_bridge.fired.connect(self.overlay.run_action_by_id)
        self.hotkeys.apply(self.settings.global_hotkeys)

        # Active-window profile switcher (§Phase 4.C).
        self._profile_override = False
        self._override_profile_id: str | None = None
        self.overlay.page_manually_switched.connect(self._on_user_page_switch)
        self._profile_timer = QTimer()
        self._profile_timer.setInterval(500)
        self._profile_timer.timeout.connect(self._on_profile_tick)
        self._profile_timer.start()

        self.tray: Tray | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self.overlay)
            self.tray.show()
        else:
            self._log.warning("No system tray available — close via the log/console.")

        self.qapp.aboutToQuit.connect(self.hotkeys.stop)

    # --------------------------------------------------------- profile logic
    def _find_matching_profile(self, title: str) -> WindowProfile | None:
        for profile in self.settings.profiles:
            if profile.matches(title):
                return profile
        return None

    def _on_user_page_switch(self) -> None:
        """Record a manual override so the auto-switcher doesn't fight the user."""
        title = get_foreground_title()
        matched = self._find_matching_profile(title)
        self._profile_override = True
        self._override_profile_id = matched.id if matched else None

    def _on_profile_tick(self) -> None:
        if not self.settings.profiles:
            return
        title = get_foreground_title()
        matched = self._find_matching_profile(title)

        if self._profile_override:
            # Clear the override once the previously-matched window loses focus.
            current_id = matched.id if matched else None
            if current_id != self._override_profile_id:
                self._profile_override = False
                self._override_profile_id = None
            return  # don't auto-switch while override is active

        if matched:
            self.overlay.switch_to_page_id(matched.page_id)
        elif self.overlay.page_index != 0:
            self.overlay.switch_page(0)

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        self.overlay.show_or_peek()
        self._log.info("HoverDeck is up. Data dir: %s", config.DATA_DIR)
        return self.qapp.exec()


def run(argv: list[str] | None = None) -> int:
    """Entry point used by main.py."""
    return HoverDeckApp(argv).run()
