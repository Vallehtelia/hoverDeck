"""run_script step: run a Python file (or inline code) in a subprocess."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError


@dataclass
class RunScriptStep(Step):
    """Run a script with the same interpreter, isolated in a subprocess.

    Exactly one of ``path`` / ``inline_code`` should be set. ``path`` may be
    relative, in which case it resolves against the user's scripts dir.
    """

    TYPE = "run_script"

    path: str | None = None
    inline_code: str | None = None
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    timeout_s: float = 60.0

    def describe(self) -> str:
        if self.path:
            return f"Run a script ({Path(self.path).name})"
        return "Run a script (inline)"

    def _resolve_path(self, ctx: ExecutionContext) -> Path:
        assert self.path is not None
        script = Path(self.path).expanduser()
        if not script.is_absolute() and ctx.scripts_dir is not None:
            candidate = ctx.scripts_dir / script
            if candidate.exists():
                return candidate
        return script

    def execute(self, ctx: ExecutionContext) -> None:
        if self.path:
            script = self._resolve_path(ctx)
            if not script.exists():
                raise StepError("Script not found — check the path in Edit.")
            cmd = [sys.executable, str(script), *self.args]
        elif self.inline_code:
            cmd = [sys.executable, "-c", self.inline_code, *self.args]
        else:
            raise StepError("This step has no script — add a path or code in Edit.")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.cwd or None,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise StepError(
                f"Script ran longer than {self.timeout_s:.0f}s and was stopped — "
                "raise the timeout in Edit or check the script."
            ) from exc
        except OSError as exc:
            raise StepError(f"Script could not start — {exc.strerror or exc}.") from exc

        ctx.last_output = result.stdout
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            tail = detail[-1] if detail else f"exit code {result.returncode}"
            raise StepError(f"Script failed ({tail}) — check the script's output in the log.")
