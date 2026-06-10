"""launch step: open a URL in the browser, run an app, or open a file."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError

MODES = ("auto", "url", "app", "file")

# Extensions whose auto-mode resolves to "app" (executed, not opened with handler).
_APP_EXTENSIONS = {".exe", ".bat", ".cmd", ".ps1", ".py", ".sh"}


def _launch_app(target: str) -> None:
    ext = Path(target).suffix.lower()
    if ext == ".ps1":
        subprocess.Popen(  # noqa: S603
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif ext == ".py":
        subprocess.Popen(  # noqa: S603
            [sys.executable, target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(  # noqa: S603
            [target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def _open_file(target: str) -> None:
    """Open a file with its default system handler."""
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606
        return
    if _is_wsl():
        # On WSL2, xdg-open delegates to the Linux desktop (often Chrome running
        # as root, which refuses without --no-sandbox).  Convert to a Windows UNC
        # path and let the Windows shell open it with the correct app instead.
        try:
            r = subprocess.run(  # noqa: S603
                ["wslpath", "-w", target],
                capture_output=True, text=True, check=True,
            )
            subprocess.Popen(  # noqa: S603
                ["explorer.exe", r.stdout.strip()],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass  # fall through to xdg-open
    subprocess.Popen(  # noqa: S603
        ["xdg-open", target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@dataclass
class LaunchStep(Step):
    TYPE = "launch"

    target: str = ""
    mode: str = "auto"  # auto | url | app | file

    def describe(self) -> str:
        return "Open an app, file, or address"

    def resolved_mode(self) -> str:
        """Determine the effective launch mode from explicit mode + target extension."""
        if self.mode in ("url", "app", "file"):
            return self.mode
        target_lower = self.target.lower()
        if target_lower.startswith(("http://", "https://")):
            return "url"
        ext = Path(target_lower).suffix
        if ext in _APP_EXTENSIONS:
            return "app"
        return "file"

    def execute(self, ctx: ExecutionContext) -> None:
        if not self.target.strip():
            raise StepError("This step has no target — add an app path or URL in Edit.")
        try:
            mode = self.resolved_mode()
            if mode == "url":
                if not webbrowser.open(self.target):
                    raise OSError("no browser found")
            elif mode == "file":
                _open_file(self.target)
            else:  # app
                _launch_app(self.target)
        except OSError as exc:
            raise StepError(
                f"Could not open {self.target} — check the path or URL."
            ) from exc

    def to_dict(self) -> dict:
        return {"type": self.TYPE, "target": self.target, "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict) -> "LaunchStep":
        return cls(target=data.get("target", ""), mode=data.get("mode", "auto"))
