"""window_title condition: match the active window's title."""
from __future__ import annotations

import re
from dataclasses import dataclass

from hoverdeck.core.conditions.base import Condition, ConditionError
from hoverdeck.core.context import ExecutionContext
from hoverdeck.utils.win import get_active_window_title


@dataclass
class WindowTitleCondition(Condition):
    TYPE = "window_title"

    mode: str = "contains"  # contains | equals | regex
    value: str = ""

    def describe(self) -> str:
        return f'window title {self.mode} "{self.value}"'

    def evaluate(self, ctx: ExecutionContext) -> bool:
        title = get_active_window_title()
        if self.mode == "contains":
            return self.value.casefold() in title.casefold()
        if self.mode == "equals":
            return title.casefold() == self.value.casefold()
        if self.mode == "regex":
            try:
                return re.search(self.value, title) is not None
            except re.error as exc:
                raise ConditionError(
                    f"The window-title pattern is invalid ({exc.msg}) — fix it in Edit."
                ) from exc
        raise ConditionError(
            f'Unknown match mode "{self.mode}" — pick contains, equals, or regex in Edit.'
        )
