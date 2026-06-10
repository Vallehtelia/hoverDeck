# HoverDeck — Codebase Index

Frameless, always-on-top desktop macro deck (Stream Deck-style). PyQt6 + Python 3.11+. Industrial "Sähkökeskus" design. Phases 1–3 complete; Phase 4 (packaging, active-window profiles) remaining.

## Run & Test

```bash
python main.py                # entry point
pytest                        # tests/  (pure-logic modules only, no Qt)
```

Data lives in `./data/` (dev) or `%APPDATA%/HoverDeck` (packaged). `hoverdeck/config.py` picks the path.

## Architecture rule

`core/` `storage/` `security/` — **zero Qt imports**. Pure Python, unit-testable.
All Qt lives in `ui/`. The action runner executes on a QThread and emits signals; the overlay never blocks.

## Key files

| File | Role |
|------|------|
| `main.py` | Entry: calls `hoverdeck.app.run()` |
| `hoverdeck/app.py` | `HoverDeckApp`: QApplication, tray, hotkey bridge, lifecycle |
| `hoverdeck/config.py` | Data-dir resolution (APPDATA vs `./data`) |
| `hoverdeck/core/models.py` | **All data models** — Action, Macro, Page, Deck, Settings, SecretTrigger. All JSON round-trippable via `to_dict`/`from_dict`. Central import hotspot (20 reverse deps). |
| `hoverdeck/core/context.py` | `ExecutionContext` — cancellable + sleepable; passed down every step chain |
| `hoverdeck/core/action_runner.py` | Runs a step chain on a QThread; emits `started`/`step_done`/`finished`/`error` |
| `hoverdeck/core/ai_builder.py` | Async AI chat agent (httpx, streaming); Anthropic + OpenAI backends; zero Qt |
| `hoverdeck/core/macro_recorder.py` | pynput global capture → `Macro` |
| `hoverdeck/core/macro_player.py` | Replays `Macro` events with original timing |
| `hoverdeck/core/steps/__init__.py` | `STEP_REGISTRY` + `step_from_dict()` — add new step types here |
| `hoverdeck/core/steps/base.py` | `Step` ABC: `execute(ctx: ExecutionContext)` |
| `hoverdeck/core/conditions/base.py` | `Condition` ABC |
| `hoverdeck/storage/deck_store.py` | Load/save `deck.json` |
| `hoverdeck/storage/macro_store.py` | One JSON file per macro |
| `hoverdeck/storage/settings_store.py` | Load/save `settings.json` |
| `hoverdeck/security/pin.py` | PBKDF2-HMAC-SHA256 (300k iters) key derivation + verify token |
| `hoverdeck/security/vault.py` | `VaultStore`: Fernet-encrypt the hidden deck; wrong PIN → `None`, never raises |
| `hoverdeck/ui/theme.py` | **Single source of truth** for all colors, sizes, fonts, QSS. `SCALE` token drives everything; `set_scale()` recomputes all size globals. |
| `hoverdeck/ui/overlay_window.py` | `OverlayWindow` (housing), `DragHandle` (notched strip + secret long-press), `PageDots`, `ResizeGrip` — 947 lines, the main UI hub |
| `hoverdeck/ui/deck_grid.py` | `DeckGrid` (rows×cols grid) + `ActionDispatcher` |
| `hoverdeck/ui/deck_button.py` | Single rounded-square keycap with indicator LED |
| `hoverdeck/ui/ai_builder_panel.py` | Chat panel (slide-in or floating) |
| `hoverdeck/ui/pin_pad.py` | Hidden PIN entry overlay (numpad, shake on wrong code) |
| `hoverdeck/ui/tray.py` | System tray icon + menu |
| `hoverdeck/ui/widgets/peek_button.py` | Half-circle amber lamp shown when deck is tucked to screen edge |
| `hoverdeck/ui/dialogs/action_editor.py` | Step-chain builder UI |
| `hoverdeck/ui/dialogs/button_editor.py` | Icon / label / color / action binding |
| `hoverdeck/ui/dialogs/macro_editor.py` | Record / playback / save macros |
| `hoverdeck/ui/dialogs/settings_dialog.py` | General, AI Builder, Hotkeys, About tabs |
| `hoverdeck/utils/hotkeys.py` | `HotkeyManager` — global hotkey registration (`keyboard` lib) |
| `hoverdeck/utils/win.py` | pywin32 helpers (active window title, autostart registry key) |
| `hoverdeck/utils/logging.py` | `get_logger(name)` |

## Step types (all in `hoverdeck/core/steps/`)

| Type key | Class | What it does |
|----------|-------|--------------|
| `run_script` | `RunScriptStep` | Run a Python file or inline code |
| `run_macro` | `RunMacroStep` | Replay a recorded macro |
| `key_macro` | `KeyMacroStep` | Send a key combo (`ctrl+shift+s` etc.) |
| `shell` | `ShellStep` | `cmd.exe /c` (Windows), captured output |
| `launch` | `LaunchStep` | Open a URL or app |
| `delay` | `DelayStep` | Wait N ms (cancellable via context) |
| `condition` | `ConditionStep` | if/then/else branching |

Add a step: create `hoverdeck/core/steps/<name>.py`, subclass `Step`, register in `steps/__init__.py` `STEP_REGISTRY`.

## Condition types (all in `hoverdeck/core/conditions/`)

`window_title`, `pixel_color` (mss 1×1 grab), `file_exists`, `time_window` (supports overnight ranges).

## Data models quick-ref

```
Deck        pages: list[Page]  +  actions: dict[id, Action]
Page        id, name, rows, cols, slots: dict[slot_index, action_id]
Action      id, name, icon, color, steps: list[Step]
Macro       id, name, events: list[MacroEvent]
Settings    grid_rows/cols, button_size, opacity, scale, theme, autostart,
            relock_timeout_s, peek_*, ai_provider, ai_api_key, ai_panel_mode,
            secret_trigger, global_hotkeys
```

Vault stores a one-page `Deck` (never touches `deck.json`).

## Design tokens (theme.py)

All colors, sizes, fonts, and durations are module-level constants in `theme.py`. **Never hardcode hex/fonts/sizes elsewhere.**

Key colors: `PANEL` `KEYCAP` `SEAM` `SIGNAL` (amber — the only accent) `LIVE` (green) `FAULT` (red) `INK` `VAULT_TINT`.

Fonts: Chakra Petch (labels), IBM Plex Sans (body), IBM Plex Mono (data/PIN). Bundled in `assets/fonts/`.

Scale: `theme.set_scale(s)` recomputes all size globals and must be followed by `app.setStyleSheet(theme.app_qss())` and a widget rebuild.

## Vault security

- PIN → PBKDF2-HMAC-SHA256(300k) → 32-byte key → Fernet encrypt
- Files: `vault.enc` (blob), `salt.bin`, `verify.tok` (encrypted known value for PIN check)
- Wrong PIN → `VaultStore.load()` returns `None`; PIN and key are never logged or persisted
- Auto-relock: on hide, on tuck, or after `settings.relock_timeout_s`
- Secret trigger: ~1.5s long-press on the drag handle (no UI hint)

## OS-specific seams

- `hoverdeck/utils/win.py` — all pywin32 calls (active window, autostart registry)
- `hoverdeck/core/steps/shell.py` — `cmd.exe /c` on Windows
- `pyproject.toml` — `pywin32` and `keyboard` are Windows-only deps

## Tests

`tests/` covers `core/`, `storage/`, `security/` (pure Python, no Qt required):
- `test_action_runner.py`, `test_ai_builder.py`, `test_macro.py`, `test_steps_conditions.py`, `test_vault.py`
