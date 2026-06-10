"""time_window condition: true between start and end times of day.

Handles overnight ranges (start > end), e.g. 22:00–06:00.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from hoverdeck.core.conditions.base import Condition, ConditionError
from hoverdeck.core.context import ExecutionContext


def parse_hhmm(value: str) -> dt.time:
    hours, _, minutes = value.strip().partition(":")
    return dt.time(int(hours), int(minutes))


def in_window(now: dt.time, start: dt.time, end: dt.time) -> bool:
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # crosses midnight


@dataclass
class TimeWindowCondition(Condition):
    TYPE = "time_window"

    start: str = "00:00"
    end: str = "23:59"

    def describe(self) -> str:
        return f"time is {self.start}–{self.end}"

    def evaluate(self, ctx: ExecutionContext) -> bool:
        try:
            start = parse_hhmm(self.start)
            end = parse_hhmm(self.end)
        except ValueError as exc:
            raise ConditionError(
                "The time window is not valid — use HH:MM in Edit."
            ) from exc
        return in_window(dt.datetime.now().time(), start, end)
