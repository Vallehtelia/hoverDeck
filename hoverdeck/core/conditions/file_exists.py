"""file_exists condition."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hoverdeck.core.conditions.base import Condition
from hoverdeck.core.context import ExecutionContext


@dataclass
class FileExistsCondition(Condition):
    TYPE = "file_exists"

    path: str = ""

    def describe(self) -> str:
        return f"{Path(self.path).name or 'file'} exists"

    def evaluate(self, ctx: ExecutionContext) -> bool:
        return bool(self.path) and Path(self.path).expanduser().exists()
