"""pixel_color condition: check a screen pixel against a color (± tolerance)."""
from __future__ import annotations

from dataclasses import dataclass

from hoverdeck.core.conditions.base import Condition, ConditionError
from hoverdeck.core.context import ExecutionContext


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """'#RRGGBB' (or 'RRGGBB') -> (r, g, b). Raises ValueError on junk."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"not a hex color: {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def within_tolerance(
    a: tuple[int, int, int], b: tuple[int, int, int], tolerance: int
) -> bool:
    """True if every RGB channel differs by at most ``tolerance``."""
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


@dataclass
class PixelColorCondition(Condition):
    TYPE = "pixel_color"

    x: int = 0
    y: int = 0
    color: str = "#000000"
    tolerance: int = 10

    def describe(self) -> str:
        return f"pixel ({self.x}, {self.y}) is {self.color}"

    def evaluate(self, ctx: ExecutionContext) -> bool:
        try:
            expected = parse_hex_color(self.color)
        except ValueError as exc:
            raise ConditionError(
                f"The pixel color {self.color!r} is not valid — use #RRGGBB in Edit."
            ) from exc

        try:
            import mss  # lazy: touches the display server
        except Exception as exc:  # pragma: no cover - environment dependent
            raise ConditionError(
                "Pixel checks are unavailable on this system."
            ) from exc

        with mss.mss() as sct:
            region = {"left": self.x, "top": self.y, "width": 1, "height": 1}
            shot = sct.grab(region)
            actual = shot.pixel(0, 0)  # (r, g, b)
        return within_tolerance(actual, expected, self.tolerance)
