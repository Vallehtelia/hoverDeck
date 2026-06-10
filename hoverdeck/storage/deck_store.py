"""Load/save the deck as hand-editable JSON; ships a sample deck on first run."""
from __future__ import annotations

import json
from pathlib import Path

from hoverdeck.core.models import Action, Deck, Page
from hoverdeck.core.steps import DelayStep, RunScriptStep
from hoverdeck.utils.logging import get_logger

log = get_logger("deck_store")

DECK_FILENAME = "deck.json"


def sample_deck() -> Deck:
    """Three demo keys that exercise the runner and all three LED states."""
    hello = Action(
        id="hello",
        name="Hello",
        icon="▶",
        steps=[
            RunScriptStep(inline_code='print("Hello from HoverDeck")'),
        ],
    )
    slow_job = Action(
        id="slow-job",
        name="Slow job",
        icon="⟳",
        steps=[
            DelayStep(ms=900),
            RunScriptStep(inline_code='print("halfway")'),
            DelayStep(ms=900),
            RunScriptStep(inline_code='print("done")'),
        ],
    )
    fault_demo = Action(
        id="fault-demo",
        name="Fault demo",
        icon="⚠",
        steps=[
            RunScriptStep(inline_code='import sys; sys.exit(2)'),
        ],
    )
    page = Page(
        id="main",
        name="Main",
        rows=2,
        cols=3,
        slots={0: hello.id, 1: slow_job.id, 2: fault_demo.id},
    )
    return Deck(
        pages=[page],
        actions={a.id: a for a in (hello, slow_job, fault_demo)},
    )


class DeckStore:
    """Persists the visible deck under <decks_dir>/deck.json."""

    def __init__(self, decks_dir: Path) -> None:
        self._path = decks_dir / DECK_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Deck:
        """Load the deck; create and persist the sample deck if none exists."""
        if not self._path.exists():
            log.info("No deck found — writing the sample deck to %s", self._path)
            deck = sample_deck()
            self.save(deck)
            return deck
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return Deck.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # Never destroy a hand-edited file; run with the sample instead.
            log.error("Deck file is unreadable (%s) — using the sample deck. "
                      "Fix or delete %s.", exc, self._path)
            return sample_deck()

    def save(self, deck: Deck) -> None:
        """Atomic write so a crash mid-save can't corrupt the deck."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(deck.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)
