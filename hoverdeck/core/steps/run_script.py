"""run_script step: run a Python file (or inline code) in a subprocess."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError


def resolve_interpreter(configured: str | None = None) -> str:
    """The Python that runs scripts: the configured one, else a sane default.

    When frozen (packaged exe) ``sys.executable`` is HoverDeck.exe — not a
    Python — so fall back to a ``python`` on PATH. Settings can override this
    to point at an environment that has the scripts' dependencies installed.
    """
    if configured:
        return configured
    if getattr(sys, "frozen", False):
        return shutil.which("python") or shutil.which("python3") or "python"
    return sys.executable


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

    @staticmethod
    def _guard_hidden(ctx: ExecutionContext, script: Path) -> None:
        """Hidden (vault-only) scripts may run only from a vault action."""
        if ctx.scripts_dir is None or ctx.allow_hidden_scripts:
            return
        hidden = (ctx.scripts_dir / "hidden").resolve()
        try:
            script.resolve().relative_to(hidden)
        except ValueError:
            return  # not a hidden script
        raise StepError("This is a vault-only script — add it to a hidden key.")

    def execute(self, ctx: ExecutionContext) -> None:
        interp = resolve_interpreter(ctx.python_exe)
        if self.path:
            script = self._resolve_path(ctx)
            if not script.exists():
                raise StepError("Script not found — check the path in Edit.")
            self._guard_hidden(ctx, script)
            cmd = [interp, str(script), *self.args]
        elif self.inline_code:
            cmd = [interp, "-c", self.inline_code, *self.args]
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
