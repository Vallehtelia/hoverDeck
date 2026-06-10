"""Global hotkeys: fire actions by id without the overlay being focused.

Backed by the `keyboard` library (Windows). On systems where it is missing
or can't hook the keyboard, the manager degrades to a logged no-op so the
rest of the app keeps working. Hotkey strings use the key_macro format
("ctrl+alt+1").
"""
from __future__ import annotations

from typing import Any, Callable

from hoverdeck.utils.logging import get_logger

log = get_logger("hotkeys")


class HotkeyManager:
    """Registers global hotkeys; dispatches through ``fire(action_id)``.

    ``fire`` is called from the keyboard library's listener thread — the
    caller must marshal into its own event loop (the UI uses a queued Qt
    signal for this).
    """

    def __init__(self, fire: Callable[[str], None]) -> None:
        self._fire = fire
        self._bindings: dict[str, str] = {}   # hotkey -> action_id
        self._handles: dict[str, Any] = {}
        self._keyboard: Any = None
        self._started = False

    # ---------------------------------------------------------------- state
    def start(self) -> None:
        if self._started:
            return
        try:
            import keyboard  # lazy: hooks the OS input stack
        except Exception:
            log.warning("Global hotkeys are unavailable on this system.")
            return
        self._keyboard = keyboard
        self._started = True

    def stop(self) -> None:
        self.unregister_all()
        self._started = False
        self._keyboard = None

    # ------------------------------------------------------------- bindings
    def register(self, hotkey: str, action_id: str) -> bool:
        """Bind one hotkey. Conflicting re-binds are skipped with a warning."""
        if not self._started or self._keyboard is None:
            return False
        bound = self._bindings.get(hotkey)
        if bound is not None and bound != action_id:
            log.warning(
                'Hotkey "%s" is already bound to another action — skipped.', hotkey
            )
            return False
        try:
            handle = self._keyboard.add_hotkey(
                hotkey, self._fire, args=(action_id,), suppress=False
            )
        except Exception as exc:  # noqa: BLE001 - keep the app alive
            log.warning('Hotkey "%s" could not be registered: %s', hotkey, exc)
            return False
        self._bindings[hotkey] = action_id
        self._handles[hotkey] = handle
        return True

    def unregister_all(self) -> None:
        if self._keyboard is not None:
            for hotkey, handle in self._handles.items():
                try:
                    self._keyboard.remove_hotkey(handle)
                except (KeyError, ValueError):
                    log.debug('Hotkey "%s" was already gone.', hotkey)
        self._bindings.clear()
        self._handles.clear()

    def apply(self, bindings: dict[str, str]) -> None:
        """Replace all bindings (called at startup and after settings change)."""
        self.start()
        self.unregister_all()
        for hotkey, action_id in bindings.items():
            self.register(hotkey, action_id)
        if bindings and self._started:
            log.info("Registered %d global hotkey(s).", len(self._bindings))
