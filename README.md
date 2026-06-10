# HoverDeck

A frameless, always-on-top desktop overlay: a Stream Deck-style grid of
rounded-square keycaps. Each key fires an **Action** — an ordered chain of steps
(run a script, send keys, wait, branch on conditions). A PIN-locked hidden deck
keeps private keys invisible and encrypted until unlocked.

Design direction: **"Sähkökeskus"** — an industrial electrical control panel.
Gunmetal housing, raised backlit keycaps, engraved label plates, and one
signature element: a tiny indicator LED on every key that shows run state
(amber pulse = running, green blink = done, red = fault). See `PLAN.md` §4.

## Status

**Phases 1–3 are done.** Keys fire full step chains on worker threads with
LED feedback: scripts, key combos, waits, recorded macros, shell commands,
app/URL launches, and if/then/else branches on window title, pixel color,
file existence, or time of day.

- **Edit mode** (tray or right-click): pencil badges, drag-to-rearrange,
  button/action editors, macro recorder & player.
- **Multi-page decks**: click the page dots or swipe the grid; add/delete/
  rename pages in edit mode.
- **Adjustable size**: drag the 3-dot grip in the bottom-right corner, or use
  the Size slider in Settings (60–200%, live preview).
- **Peek mode**: the chevron on the drag handle (or tray → "Pin to edge")
  tucks the deck to the nearest screen edge behind an amber half-circle lamp;
  click it to slide the deck back.
- **AI Builder**: a chat panel (Anthropic or OpenAI — set a key in Settings)
  that asks questions, builds an action, and adds it to the deck.
- **Hidden vault**: long-press the drag handle (~1.5s); the first PIN you
  enter becomes the code. The vault page and its keys live in an encrypted
  blob (PBKDF2 + Fernet) — never in deck.json — and auto-relock on hide,
  tuck, or timeout.
- **Global hotkeys** (Windows): bind combos to keys in Settings → Hotkeys.
  **Autostart** toggle in Settings → General (Windows only).

Remaining (Phase 4, see `PLAN.md` §6): PyInstaller packaging, active-window
profiles, final polish.

## Run it

```bash
python3 -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
python3 main.py
```

First run creates `./data/` (dev) or `%APPDATA%/HoverDeck` (packaged) with a
sample deck of three demo keys: a hello script, a slow job (watch the amber
LED pulse), and a fault demo (red LED holds until you click it).

- **Drag** the machined strip at the top to move the deck.
- **Arrow keys** move focus, **Enter** fires the focused key.
- **Tray icon**: show/hide the deck, quit.
- Deck JSON is hand-editable: `data/decks/deck.json`.

Optional: drop the fonts listed in `assets/fonts/FONTS.md` into `assets/fonts/`
for the full engraved-label look (the app falls back to system fonts otherwise).

## Tests

```bash
pip install pytest
pytest
```

`core/`, `storage/`, and `security/` are pure Python (zero Qt imports) and
unit-testable.

## Layout

See `PLAN.md` §3 for the full tree. The short version:

```
hoverdeck/core/      pure logic: models, steps, action runner
hoverdeck/storage/   JSON persistence
hoverdeck/security/  vault crypto (Phase 4)
hoverdeck/ui/        all Qt: theme tokens, keycaps, overlay, tray
scripts/             your own Python scripts (gitignored)
data/                runtime data in dev (gitignored)
```

## License

Private project. Bundled fonts are under the SIL Open Font License 1.1
(see `assets/fonts/FONTS.md`).
