"""condition step: IF cond THEN [steps] ELSE [steps].

Phase 2 ships window_title conditions; the other condition types exist but
their evaluate() raises until Phase 3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hoverdeck.core.conditions.base import Condition, ConditionError
from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError


@dataclass
class ConditionStep(Step):
    TYPE = "condition"

    cond: Condition | None = None
    then: list[Step] = field(default_factory=list)
    orelse: list[Step] = field(default_factory=list)  # serialized as "else"

    def describe(self) -> str:
        if self.cond is None:
            return "If … then …"
        return f"If {self.cond.describe()}"

    def execute(self, ctx: ExecutionContext) -> None:
        if self.cond is None:
            raise StepError("This if-step has no condition — set one in Edit.")
        try:
            branch = self.then if self.cond.evaluate(ctx) else self.orelse
        except ConditionError as exc:
            raise StepError(str(exc)) from exc
        for step in branch:
            if ctx.cancelled:
                return
            step.execute(ctx)

    # Nested steps/conditions need their "type" discriminators preserved,
    # so this overrides the plain-asdict default.
    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.TYPE,
            "cond": self.cond.to_dict() if self.cond else None,
            "then": [s.to_dict() for s in self.then],
            "else": [s.to_dict() for s in self.orelse],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConditionStep":
        # Late imports: the registries import this module.
        from hoverdeck.core.conditions import condition_from_dict
        from hoverdeck.core.steps import step_from_dict

        cond_data = data.get("cond")
        return cls(
            cond=condition_from_dict(cond_data) if cond_data else None,
            then=[step_from_dict(s) for s in data.get("then", [])],
            orelse=[step_from_dict(s) for s in data.get("else", [])],
        )
