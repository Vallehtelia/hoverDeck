"""key_macro step: send one or more hotkey combos ("ctrl+shift+s", ...)."""
from __future__ import annotations

from dataclasses import dataclass, field

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError

# Combo-token -> pynput Key attribute name (single characters pass through).
_SPECIAL_KEYS: dict[str, str] = {
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "win": "cmd", "cmd": "cmd", "super": "cmd", "meta": "cmd",
    "enter": "enter", "return": "enter",
    "esc": "esc", "escape": "esc",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete", "del": "delete",
    "insert": "insert",
    "home": "home", "end": "end",
    "pageup": "page_up", "pagedown": "page_down",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "capslock": "caps_lock",
    "printscreen": "print_screen",
    **{f"f{i}": f"f{i}" for i in range(1, 25)},
}


def parse_combo(combo: str) -> list[str]:
    """Normalize "Ctrl + Shift+S" -> ["ctrl", "shift", "s"] (validated tokens)."""
    tokens = [t.strip().lower() for t in combo.split("+") if t.strip()]
    if not tokens:
        raise StepError("A key combo is empty — type the keys in Edit (e.g. ctrl+shift+s).")
    for token in tokens:
        if len(token) != 1 and token not in _SPECIAL_KEYS:
            raise StepError(f'Unknown key "{token}" — check the combo in Edit.')
    return tokens


@dataclass
class KeyMacroStep(Step):
    """Press each combo in ``keys`` in order, with a short gap between combos."""

    TYPE = "key_macro"

    keys: list[str] = field(default_factory=list)
    interval_ms: int = 30

    def describe(self) -> str:
        return f"Send keys ({', '.join(self.keys)})" if self.keys else "Send keys"

    def execute(self, ctx: ExecutionContext) -> None:
        if not self.keys:
            raise StepError("No keys to send — add a combo in Edit (e.g. ctrl+shift+s).")
        combos = [parse_combo(c) for c in self.keys]

        # Lazy import: pynput touches the OS input stack, keep core importable
        # headless (tests, CI).
        try:
            from pynput.keyboard import Controller, Key
        except Exception as exc:  # pragma: no cover - environment dependent
            raise StepError("Keyboard output is unavailable on this system.") from exc

        keyboard = Controller()
        for tokens in combos:
            if ctx.cancelled:
                return
            resolved = [
                getattr(Key, _SPECIAL_KEYS[t]) if t in _SPECIAL_KEYS else t
                for t in tokens
            ]
            for key in resolved:
                keyboard.press(key)
            for key in reversed(resolved):
                keyboard.release(key)
            ctx.sleep(self.interval_ms)
