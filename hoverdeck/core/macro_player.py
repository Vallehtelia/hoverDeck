"""Replay a Macro's events with their original timing (cancel-aware)."""
from __future__ import annotations

from typing import Any

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.models import Macro
from hoverdeck.utils.logging import get_logger

log = get_logger("macro_player")


def _key_from_data(keyboard_mod: Any, data: dict[str, Any]) -> Any:
    """Inverse of macro_recorder._key_to_data."""
    if "char" in data:
        return data["char"]
    if "key" in data:
        return getattr(keyboard_mod.Key, data["key"])
    return keyboard_mod.KeyCode.from_vk(data.get("vk", 0))


class MacroPlayer:
    """Replays events through pynput controllers."""

    def play(self, macro: Macro, ctx: ExecutionContext | None = None) -> None:
        ctx = ctx or ExecutionContext()
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Playback is unavailable on this system — input control could not start."
            ) from exc

        kb = keyboard.Controller()
        ms = mouse.Controller()
        log.info("Play %r (%d events)", macro.name, len(macro.events))

        t_prev = 0
        for event in macro.events:
            if ctx.cancelled:
                log.info("Playback of %r cancelled.", macro.name)
                return
            if not ctx.sleep(event.t_ms - t_prev):
                return
            t_prev = event.t_ms
            data = event.data

            if event.kind == "key":
                key = _key_from_data(keyboard, data)
                if event.action == "press":
                    kb.press(key)
                elif event.action == "release":
                    kb.release(key)
            elif event.kind == "mouse":
                if event.action == "move":
                    ms.position = (data["x"], data["y"])
                elif event.action == "click":
                    ms.position = (data["x"], data["y"])
                    button = getattr(mouse.Button, data.get("button", "left"))
                    if data.get("pressed", True):
                        ms.press(button)
                    else:
                        ms.release(button)
                elif event.action == "scroll":
                    ms.scroll(data.get("dx", 0), data.get("dy", 0))
