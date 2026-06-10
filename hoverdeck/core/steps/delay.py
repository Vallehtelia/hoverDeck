"""delay step: wait a number of milliseconds (cancel-aware)."""
from __future__ import annotations

from dataclasses import dataclass

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step


@dataclass
class DelayStep(Step):
    TYPE = "delay"

    ms: int = 0

    def describe(self) -> str:
        return f"Wait {self.ms} ms"

    def execute(self, ctx: ExecutionContext) -> None:
        ctx.sleep(self.ms)
