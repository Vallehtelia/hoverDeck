"""Execution context passed between steps of a running action."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecutionContext:
    """Mutable state shared by the steps of one action run.

    A fresh context is created per run. Steps may read/write ``variables``
    and ``last_output``; the runner (or the UI) may request cancellation,
    which interruptible steps honor via :meth:`sleep` / :attr:`cancelled`.
    """

    scripts_dir: Path | None = None
    python_exe: str | None = None   # interpreter for run_script ("" / None = auto)
    allow_hidden_scripts: bool = False  # may this run use scripts/hidden/* (vault only)?
    variables: dict[str, Any] = field(default_factory=dict)
    last_output: str = ""
    # MacroStore-compatible object (load(macro_id) -> Macro | None). Typed as
    # Any to keep core free of import cycles (models -> steps -> context).
    macro_store: Any = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        """Ask the running chain to stop at the next opportunity."""
        self._cancel.set()

    def sleep(self, ms: int) -> bool:
        """Wait ``ms`` milliseconds, waking early on cancel.

        Returns True if the full wait completed, False if cancelled.
        """
        if ms <= 0:
            return not self.cancelled
        return not self._cancel.wait(ms / 1000.0)
