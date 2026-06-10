"""Verify the generated .ico has the expected sizes."""
from __future__ import annotations

from pathlib import Path

import pytest

ICO_PATH = Path(__file__).parent.parent / "assets" / "icons" / "hoverdeck.ico"


@pytest.mark.skipif(not ICO_PATH.exists(), reason="hoverdeck.ico not generated yet")
def test_ico_exists():
    assert ICO_PATH.is_file()
    assert ICO_PATH.stat().st_size > 0


@pytest.mark.skipif(not ICO_PATH.exists(), reason="hoverdeck.ico not generated yet")
def test_ico_has_correct_sizes():
    from PIL import Image

    with Image.open(ICO_PATH) as img:
        sizes = img.info.get("sizes", set())

    expected = {(16, 16), (32, 32), (48, 48), (256, 256)}
    assert expected.issubset(sizes), f"Missing sizes: {expected - sizes}"
