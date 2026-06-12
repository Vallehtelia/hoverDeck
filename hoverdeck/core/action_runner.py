"""Executes an action's step chain, reporting progress through callbacks.

This module is pure Python (no Qt). The UI wraps it in a QThread and routes
the callbacks into Qt signals (see hoverdeck.ui.deck_grid) so the overlay
never freezes; tests drive it synchronously or with run_async().
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.models import Action
from hoverdeck.core.steps.base import StepError
from hoverdeck.utils.logging import get_logger

log = get_logger("runner")


def _noop(*_args: object) -> None:
    return None


@dataclass
class RunnerCallbacks:
    """Progress hooks, signature-compatible with the UI's Qt signals.

    All callbacks fire on the worker thread.
    """

    on_started: Callable[[str], None] = _noop            # (action_id)
    on_step_done: Callable[[str, int, str], None] = _noop  # (action_id, index, description)
    on_finished: Callable[[str], None] = _noop           # (action_id)
    on_cancelled: Callable[[str], None] = _noop          # (action_id) — repeat loop stopped
    on_error: Callable[[str, int, str], None] = _noop    # (action_id, index, message)


class ActionRunner:
    """Runs step chains; tracks which actions are in flight."""

    def __init__(self, scripts_dir: Path | None = None, macro_store: object = None,
                 python_exe: str | None = None) -> None:
        self._scripts_dir = scripts_dir
        self._macro_store = macro_store
        self._python_exe = python_exe
        self._running: set[str] = set()
        self._contexts: dict[str, ExecutionContext] = {}
        self._lock = threading.Lock()

    def set_python_exe(self, python_exe: str | None) -> None:
        """Set the interpreter future runs use for 'Run a script' steps."""
        self._python_exe = python_exe

    def make_context(self, allow_hidden_scripts: bool = False) -> ExecutionContext:
        """Build a fresh run context carrying the runner's shared settings."""
        return ExecutionContext(
            scripts_dir=self._scripts_dir,
            macro_store=self._macro_store,
            python_exe=self._python_exe,
            allow_hidden_scripts=allow_hidden_scripts,
        )

    def is_running(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._running

    def cancel(self, action_id: str) -> None:
        """Cancel a running action (no-op if it isn't running)."""
        with self._lock:
            ctx = self._contexts.get(action_id)
        if ctx is not None:
            ctx.cancel()

    def run(
        self,
        action: Action,
        callbacks: RunnerCallbacks | None = None,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionContext:
        """Execute the chain synchronously on the calling thread.

        Emits on_started, then on_step_done per step, then exactly one of
        on_finished / on_cancelled / on_error.  If action.repeat is True the
        step chain loops until ctx is cancelled (second button press).
        A second run of a non-repeat action that is still in flight is ignored.
        """
        cb = callbacks or RunnerCallbacks()
        ctx = ctx or self.make_context()

        with self._lock:
            if action.id in self._running:
                log.info("Action %r is already running — ignored.", action.name)
                return ctx
            self._running.add(action.id)
            self._contexts[action.id] = ctx

        index = -1
        try:
            cb.on_started(action.id)
            log.info("Run %r (%d steps, repeat=%s)", action.name, len(action.steps), action.repeat)
            while True:
                for index, step in enumerate(action.steps):
                    if ctx.cancelled:
                        log.info("Run %r cancelled at step %d.", action.name, index)
                        break
                    step.execute(ctx)
                    cb.on_step_done(action.id, index, step.describe())
                if ctx.cancelled or not action.repeat:
                    break
            if ctx.cancelled:
                cb.on_cancelled(action.id)
            else:
                cb.on_finished(action.id)
        except StepError as exc:
            log.warning("Step %d of %r failed: %s", index, action.name, exc)
            cb.on_error(action.id, index, str(exc))
        except NotImplementedError as exc:
            cb.on_error(action.id, index, str(exc))
        except Exception:  # noqa: BLE001 - the overlay must never crash
            log.exception("Step %d of %r crashed", index, action.name)
            cb.on_error(
                action.id, index,
                "The step crashed — see the log for details (data/hoverdeck.log).",
            )
        finally:
            with self._lock:
                self._running.discard(action.id)
                self._contexts.pop(action.id, None)
        return ctx

    def run_async(
        self,
        action: Action,
        callbacks: RunnerCallbacks | None = None,
        ctx: ExecutionContext | None = None,
    ) -> threading.Thread:
        """Run on a plain daemon thread (for non-Qt callers and tests)."""
        thread = threading.Thread(
            target=self.run,
            args=(action, callbacks, ctx),
            name=f"action-{action.id}",
            daemon=True,
        )
        thread.start()
        return thread
