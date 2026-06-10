"""Condition ABC: evaluate(ctx) -> bool, plus dict round-tripping."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar

from hoverdeck.core.context import ExecutionContext


class ConditionError(RuntimeError):
    """A condition could not be evaluated. Message is user-facing."""


@dataclass
class Condition(ABC):
    """A boolean check a condition step can branch on."""

    TYPE: ClassVar[str] = ""

    @abstractmethod
    def evaluate(self, ctx: ExecutionContext) -> bool:
        """Return True if the condition currently holds."""

    def describe(self) -> str:
        return self.TYPE.replace("_", " ")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.TYPE, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Condition":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
