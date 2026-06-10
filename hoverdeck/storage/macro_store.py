"""Persist recorded macros, one hand-editable JSON file per macro."""
from __future__ import annotations

import json
from pathlib import Path

from hoverdeck.core.models import Macro
from hoverdeck.utils.logging import get_logger

log = get_logger("macro_store")


class MacroStore:
    def __init__(self, macros_dir: Path) -> None:
        self._dir = macros_dir

    def _path(self, macro_id: str) -> Path:
        return self._dir / f"{macro_id}.json"

    def load(self, macro_id: str) -> Macro | None:
        path = self._path(macro_id)
        if not path.exists():
            return None
        try:
            return Macro.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.error("Macro file %s is unreadable (%s).", path, exc)
            return None

    def load_all(self) -> list[Macro]:
        macros: list[Macro] = []
        if not self._dir.is_dir():
            return macros
        for path in sorted(self._dir.glob("*.json")):
            macro = self.load(path.stem)
            if macro is not None:
                macros.append(macro)
        return macros

    def save(self, macro: Macro) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(macro.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(macro.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    def delete(self, macro_id: str) -> None:
        self._path(macro_id).unlink(missing_ok=True)
