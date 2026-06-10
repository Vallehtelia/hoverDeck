"""Step ABC: every step is a dataclass with execute(ctx).

Concrete steps register themselves in the type registry (see
``hoverdeck.core.steps``) so models can (de)serialize them by their
``"type"`` discriminator.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar

from hoverdeck.core.context import ExecutionContext


class StepError(RuntimeError):
    """A step failed. The message is user-facing: say what happened + what to do."""


@dataclass
class Step(ABC):
    """One unit of work in an action's step chain."""

    TYPE: ClassVar[str] = ""

    @abstractmethod
    def execute(self, ctx: ExecutionContext) -> None:
        """Run this step. Raise StepError with a user-facing message on failure."""

    def describe(self) -> str:
        """Short human description, used in logs and (later) the action editor."""
        return self.TYPE.replace("_", " ")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.TYPE, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        """Build a concrete step from its dict (``"type"`` key already matched)."""
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)
