"""Macro model tests. Recorder/player tests arrive with Phase 2."""
from __future__ import annotations

import pytest

from hoverdeck.core.models import Macro, MacroEvent


def test_macro_serialization_round_trip() -> None:
    macro = Macro(
        id="m1",
        name="Open project",
        events=[
            MacroEvent(kind="key", action="press", data={"key": "ctrl"}, t_ms=0),
            MacroEvent(kind="key", action="press", data={"key": "o"}, t_ms=35),
            MacroEvent(kind="key", action="release", data={"key": "o"}, t_ms=80),
            MacroEvent(kind="key", action="release", data={"key": "ctrl"}, t_ms=120),
            MacroEvent(kind="mouse", action="click",
                       data={"x": 100, "y": 240, "button": "left"}, t_ms=600),
        ],
    )
    restored = Macro.from_dict(macro.to_dict())
    assert restored == macro
    assert restored.events[-1].data["button"] == "left"


@pytest.mark.skip(reason="Needs a real display + input stack (manual test on Windows).")
def test_recorder_captures_timing() -> None:
    ...


@pytest.mark.skip(reason="Needs a real display + input stack (manual test on Windows).")
def test_player_replays_with_timing() -> None:
    ...
