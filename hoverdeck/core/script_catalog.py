"""Build a short, AI-friendly catalog of the user's scripts.

Each entry is "name — one-line purpose" taken from the script's module
docstring (or a leading ``#`` comment). The AI Builder gets this so it can
REUSE a ready-made script that fits instead of inventing a filename.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MAX_DESC = 240


def summarize(path: Path) -> str:
    """A one-line purpose for a script: its docstring, else a leading comment."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    doc = ""
    try:
        doc = ast.get_docstring(ast.parse(src)) or ""
    except (SyntaxError, ValueError):
        doc = ""
    if not doc:
        for line in src.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#!") or stripped.startswith("# -*-"):
                continue  # shebang / coding line
            if stripped.startswith("#"):
                doc = stripped.lstrip("#").strip()
            break  # only the very first meaningful line
    return " ".join(doc.split())[:_MAX_DESC]


def split_docstring(src: str) -> tuple[str, str]:
    """Separate a leading module docstring → (one-line description, body code).

    If there's no parseable module docstring, description is "" and body is the
    whole source — so editing is lossless for files without one.
    """
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return "", src
    doc = ast.get_docstring(tree, clean=True)
    if doc is None or not tree.body:
        return "", src
    end = getattr(tree.body[0], "end_lineno", None)
    if end is None:
        return " ".join(doc.split()), src
    body = "".join(src.splitlines(keepends=True)[end:]).lstrip("\n")
    return " ".join(doc.split()), body


def join_docstring(description: str, body: str) -> str:
    """Rebuild a script from an edited description + body."""
    description = " ".join(description.split())
    body = body.lstrip("\n")
    if not description:
        return body if body.endswith("\n") or not body else body + "\n"
    safe = description.replace('"""', "'''")     # keep the docstring well-formed
    head = f'"""{safe}"""\n'
    return head + (f"\n{body}" if body.strip() else "")


def _entry(name: str, path: Path) -> str:
    desc = summarize(path)
    return f"{name} — {desc}" if desc else name


def catalog(scripts_dir: Path, include_hidden: bool = False) -> list[str]:
    """['name — purpose', …] for scripts/*.py (+ hidden/*.py when unlocked)."""
    out: list[str] = []
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.glob("*.py"), key=lambda p: p.name.lower()):
            out.append(_entry(path.name, path))
    if include_hidden:
        hidden = scripts_dir / "hidden"
        if hidden.is_dir():
            for path in sorted(hidden.glob("*.py"), key=lambda p: p.name.lower()):
                out.append(_entry(f"hidden/{path.name}", path))
    return out
