"""Conditions for branching steps, plus the type registry."""
from __future__ import annotations

from typing import Any

from hoverdeck.core.conditions.base import Condition, ConditionError
from hoverdeck.core.conditions.file_exists import FileExistsCondition
from hoverdeck.core.conditions.pixel_color import PixelColorCondition
from hoverdeck.core.conditions.time_window import TimeWindowCondition
from hoverdeck.core.conditions.window_title import WindowTitleCondition

CONDITION_REGISTRY: dict[str, type[Condition]] = {
    cls.TYPE: cls
    for cls in (
        WindowTitleCondition,
        PixelColorCondition,
        FileExistsCondition,
        TimeWindowCondition,
    )
}


def condition_from_dict(data: dict[str, Any]) -> Condition:
    cond_type = data.get("type", "")
    cls = CONDITION_REGISTRY.get(cond_type)
    if cls is None:
        raise ValueError(f"Unknown condition type: {cond_type!r}")
    return cls.from_dict(data)


__all__ = [
    "Condition",
    "ConditionError",
    "CONDITION_REGISTRY",
    "condition_from_dict",
    "WindowTitleCondition",
    "PixelColorCondition",
    "FileExistsCondition",
    "TimeWindowCondition",
]
