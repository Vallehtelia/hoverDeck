"""run_macro step: replay a saved macro by id."""
from __future__ import annotations

from dataclasses import dataclass

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.base import Step, StepError


@dataclass
class RunMacroStep(Step):
    TYPE = "run_macro"

    macro_id: str = ""

    def describe(self) -> str:
        return "Run a macro"

    def execute(self, ctx: ExecutionContext) -> None:
        if not self.macro_id:
            raise StepError("No macro picked — choose one in Edit.")
        if ctx.macro_store is None:
            raise StepError("Macros are unavailable — restart HoverDeck and try again.")
        macro = ctx.macro_store.load(self.macro_id)
        if macro is None:
            raise StepError("Macro not found — pick another in Edit.")

        from hoverdeck.core.macro_player import MacroPlayer

        MacroPlayer().play(macro, ctx)
