"""shell step: run an arbitrary shell command, capturing its output."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError

_STDERR_TAIL = 200


def _safe_cwd(explicit: str | None) -> str | None:
    """A working directory cmd.exe can actually run from.

    On Windows, cmd.exe refuses a UNC current directory (``\\\\server\\share``)
    — which is exactly what HoverDeck inherits when run from a ``\\\\wsl.localhost``
    path — and ``start`` then fails looking for ``\\\\``. When the step doesn't
    specify a cwd, fall back to the user's home so commands run from a normal
    local drive.
    """
    if explicit:
        return explicit
    if sys.platform == "win32":
        return os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return None


@dataclass
class ShellStep(Step):
    TYPE = "shell"

    command: str = ""
    cwd: str | None = None
    timeout_ms: int = 10_000

    def describe(self) -> str:
        return "Run a command"

    def execute(self, ctx: ExecutionContext) -> None:
        if not self.command.strip():
            raise StepError("This step has no command — type one in Edit.")

        kwargs: dict[str, object] = {
            "cwd": _safe_cwd(self.cwd),
            "capture_output": True,
            "text": True,
            "timeout": self.timeout_ms / 1000.0,
        }
        try:
            if sys.platform == "win32":
                result = subprocess.run(["cmd.exe", "/c", self.command], **kwargs)
            else:
                result = subprocess.run(self.command, shell=True, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise StepError(
                f"Command ran longer than {self.timeout_ms} ms and was stopped — "
                "raise the timeout in Edit or check the command."
            ) from exc
        except OSError as exc:
            raise StepError(f"Command could not start — {exc.strerror or exc}.") from exc

        ctx.last_output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip()[-_STDERR_TAIL:]
            raise StepError(
                f"Command failed (exit {result.returncode}) — {tail or 'no output'}"
            )
