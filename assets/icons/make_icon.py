"""Generate hoverdeck.ico — run once, commit the output.

Produces a multi-size .ico:
  • Gunmetal (#14171B) rounded-square background
  • Signal-amber (#F5A623) filled circle in the top-right corner (the LED motif)
  Sizes: 16, 32, 48, 256 px
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_PANEL  = (20, 23, 27)     # #14171B
_SIGNAL = (245, 166, 35)   # #F5A623
_SIZES  = (16, 32, 48, 256)
_OUT    = Path(__file__).parent / "hoverdeck.ico"


def _make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = max(2, round(size * 0.18))
    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=radius,
        fill=_PANEL + (255,),
    )

    led_d = max(2, round(size * 0.25))
    led_x = size - led_d - max(1, round(size * 0.08))
    led_y = max(1, round(size * 0.08))
    draw.ellipse(
        [(led_x, led_y), (led_x + led_d, led_y + led_d)],
        fill=_SIGNAL + (255,),
    )

    return img


def main() -> None:
    # Draw at the largest size; Pillow resizes down to each target size when saving.
    large = _make_frame(256)
    large.save(
        _OUT,
        format="ICO",
        sizes=[(s, s) for s in _SIZES],
    )
    print(f"Wrote {_OUT}")


if __name__ == "__main__":
    main()
