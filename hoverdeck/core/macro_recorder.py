"""Record global keyboard/mouse input into MacroEvents (pynput)."""
from __future__ import annotations

import time
from typing import Any

from hoverdeck.core.models import MacroEvent
from hoverdeck.utils.logging import get_logger

log = get_logger("macro_recorder")

_MOVE_SAMPLE_MS = 20  # coalesce mouse moves so macros stay small


def _key_to_data(key: Any) -> dict[str, Any]:
    """Serialize a pynput key to a JSON-safe dict (see _key_from_data)."""
    char = getattr(key, "char", None)
    if char:
        return {"char": char}
    name = getattr(key, "name", None)
    if name:
        return {"key": name}
    vk = getattr(key, "vk", None)
    return {"vk": vk if vk is not None else 0}


class MacroRecorder:
    """start() arms global listeners; stop() returns the captured events.

    TODO (later polish): trim the trailing events that belong to the Stop
    click/hotkey itself.
    """

    def __init__(self) -> None:
        self._events: list[MacroEvent] = []
        self._t0: float = 0.0
        self._last_move_ms: int = -10_000
        self._kb_listener: Any = None
        self._mouse_listener: Any = None

    @property
    def recording(self) -> bool:
        return self._kb_listener is not None

    def _now_ms(self) -> int:
        return round((time.monotonic() - self._t0) * 1000)

    def start(self) -> None:
        if self.recording:
            return
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Recording is unavailable on this system — input capture could not start."
            ) from exc

        self._events = []
        self._t0 = time.monotonic()
        self._last_move_ms = -10_000

        def on_press(key: Any) -> None:
            self._events.append(MacroEvent("key", "press", _key_to_data(key), self._now_ms()))

        def on_release(key: Any) -> None:
            self._events.append(MacroEvent("key", "release", _key_to_data(key), self._now_ms()))

        def on_move(x: int, y: int) -> None:
            now = self._now_ms()
            if now - self._last_move_ms >= _MOVE_SAMPLE_MS:
                self._last_move_ms = now
                self._events.append(MacroEvent("mouse", "move", {"x": x, "y": y}, now))

        def on_click(x: int, y: int, button: Any, pressed: bool) -> None:
            self._events.append(MacroEvent(
                "mouse", "click",
                {"x": x, "y": y, "button": button.name, "pressed": pressed},
                self._now_ms(),
            ))

        def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
            self._events.append(MacroEvent(
                "mouse", "scroll", {"x": x, "y": y, "dx": dx, "dy": dy}, self._now_ms()
            ))

        self._kb_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse_listener = mouse.Listener(
            on_move=on_move, on_click=on_click, on_scroll=on_scroll
        )
        self._kb_listener.start()
        self._mouse_listener.start()
        log.info("Recording started.")

    def stop(self) -> list[MacroEvent]:
        if not self.recording:
            return []
        self._kb_listener.stop()
        self._mouse_listener.stop()
        self._kb_listener = None
        self._mouse_listener = None
        log.info("Recording stopped: %d events.", len(self._events))
        return list(self._events)
