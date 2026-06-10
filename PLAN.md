# HoverDeck — Project Plan

A frameless, always-on-top Windows overlay that floats on your desktop as a
customizable Stream Deck-style grid of rounded-square buttons. Each button runs
a Python script, a recorded macro, or a chained sequence of steps with conditional
logic. A PIN-locked hidden deck holds private buttons that are completely
invisible until you unlock them with a 4–6 digit code.

Working name: **HoverDeck** (rename freely).

---

## 1. Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | familiar, dataclasses, typing |
| UI | PyQt6 | frameless overlay, custom-painted rounded widgets, tray, threads |
| Macro record/playback | pynput | global keyboard + mouse capture with timing |
| Global hotkeys (optional) | keyboard | trigger actions without focusing the deck |
| Windows helpers | pywin32 | active window title, foreground checks (for conditions/profiles) |
| Screen/pixel checks | mss + Pillow | pixel-color conditions, fast screen grabs |
| Vault encryption | cryptography (Fernet + PBKDF2-HMAC-SHA256) | real encryption of the hidden deck, key derived from PIN |
| Packaging | PyInstaller | single .exe, tray app, optional autostart |
| Tests | pytest | core/storage/security are pure-logic, unit-testable |

---

## 2. Core idea — the "Action = chain of steps" model

This is what gives you "mikä vaan sekotus mahdollisilla ehdoilla". A button isn't
bound to one thing — it's bound to an **Action**, which is an ordered list of
**Steps**. Steps can branch on **Conditions**. So one button can:

> run script A → wait 500ms → IF active window is "Photoshop" THEN send
> Ctrl+Shift+S ELSE run macro B → launch URL

### Data model

```
Action
  id: str
  name: str
  icon: str            # glyph/emoji or path to png
  color: str           # hex, button tint
  steps: list[Step]

Step (discriminated by "type")
  - run_script   { path | inline_code, args, cwd }
  - run_macro    { macro_id }
  - key_macro    { keys: ["ctrl+shift+s", ...] }   # quick inline hotkey send
  - shell        { command }
  - launch       { target }                         # app path or url
  - delay        { ms }
  - condition    { cond: Condition, then: [Step], else: [Step] }

Condition (discriminated by "type")
  - window_title { mode: contains|equals|regex, value }
  - pixel_color  { x, y, color, tolerance }
  - file_exists  { path }
  - time_window  { start, end }

Macro
  id: str
  name: str
  events: [ { kind: key|mouse, action: press|release|move|click|scroll, data, t_ms } ]

Deck
  pages: list[Page]
Page
  id, name, rows, cols
  slots: { slot_index: action_id }

Settings
  grid_rows, grid_cols, button_size, opacity, theme,
  autostart, relock_timeout_s,
  secret_trigger { type: long_press, target: handle, hold_ms: 1500 },
  global_hotkeys: { "ctrl+alt+1": action_id, ... }
```

Everything serializes to JSON via `to_dict` / `from_dict`. The vault is the same
shape as a Page but stored as an encrypted blob (see §5).

---

## 3. Directory tree

```
hoverdeck/
├── pyproject.toml
├── requirements.txt
├── README.md
├── PLAN.md                      # this file
├── main.py                      # entry point
├── hoverdeck/
│   ├── __init__.py
│   ├── app.py                   # QApplication, tray, lifecycle
│   ├── config.py                # app paths (%APPDATA%/HoverDeck, ./data dev fallback)
│   │
│   ├── core/                    # PURE LOGIC — no PyQt imports
│   │   ├── __init__.py
│   │   ├── models.py            # Action, Step, Macro, Deck, Page dataclasses + (de)serialize
│   │   ├── context.py           # execution context passed between steps
│   │   ├── action_runner.py     # executes a step chain (on a worker thread)
│   │   ├── macro_recorder.py    # pynput capture -> Macro
│   │   ├── macro_player.py      # replay Macro events with timing
│   │   ├── ai_builder.py        # AI chat agent that builds Actions (httpx, async, no Qt)
│   │   ├── steps/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # Step ABC: execute(ctx)
│   │   │   ├── run_script.py
│   │   │   ├── run_macro.py
│   │   │   ├── key_macro.py
│   │   │   ├── shell.py
│   │   │   ├── launch.py
│   │   │   ├── delay.py
│   │   │   └── condition.py     # if/else branching
│   │   └── conditions/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── window_title.py
│   │       ├── pixel_color.py
│   │       ├── file_exists.py
│   │       └── time_window.py
│   │
│   ├── storage/                 # JSON persistence, no PyQt
│   │   ├── __init__.py
│   │   ├── deck_store.py
│   │   ├── macro_store.py
│   │   └── settings_store.py
│   │
│   ├── security/                # vault crypto, no PyQt
│   │   ├── __init__.py
│   │   ├── pin.py               # PIN -> key derivation, verify
│   │   └── vault.py             # encrypt/decrypt hidden deck (Fernet)
│   │
│   ├── ui/                      # ALL Qt lives here
│   │   ├── __init__.py
│   │   ├── overlay_window.py    # frameless, on-top, draggable shell + peek/tuck + resize grip
│   │   ├── deck_grid.py         # rows×cols grid widget
│   │   ├── deck_button.py       # single rounded-square button
│   │   ├── ai_builder_panel.py  # chat panel for the AI macro builder
│   │   ├── pin_pad.py           # hidden-section PIN entry overlay
│   │   ├── edit_mode.py         # add / rearrange / edit controls
│   │   ├── tray.py              # system tray menu
│   │   ├── theme.py             # colors, radii, sizes, SCALE, qss (the rounded look)
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── rounded_frame.py
│   │   │   ├── peek_button.py   # half-circle edge button shown while tucked
│   │   │   └── icon_picker.py
│   │   └── dialogs/
│   │       ├── __init__.py
│   │       ├── action_editor.py # build the step chain + conditions
│   │       ├── macro_editor.py  # record / edit a macro
│   │       ├── button_editor.py # icon, label, color, bind action
│   │       └── settings_dialog.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── hotkeys.py           # global hotkey registration
│       ├── win.py               # active window etc. (pywin32)
│       └── logging.py
│
├── assets/
│   ├── icons/
│   └── fonts/
│
├── scripts/                     # YOUR python scripts live here (gitignored)
│   └── .gitkeep
│
├── data/                        # runtime data (gitignored) — or use %APPDATA%
│   ├── decks/
│   ├── macros/
│   ├── vault/                   # vault.enc + salt
│   └── settings.json
│
└── tests/
    ├── __init__.py
    ├── test_action_runner.py
    ├── test_vault.py
    └── test_macro.py
```

**Rule that keeps it sane:** `core/`, `storage/`, `security/` never import PyQt.
That makes them unit-testable and keeps the UI swappable.

---

## 4. Design direction — "Sähkökeskus" (industrial switchboard)

> **Design process note:** the design was planned brief-first (subject → tokens →
> signature → self-critique), per studio practice. Do not drift back to generic
> dark-mode defaults during implementation.

### 4.1 The brief, grounded in the subject

Subject: a physical-feeling macro deck floating on a desktop. Audience: one
power user (an ex-electrician turned developer). The single job: press a key,
something happens — instantly legible, tactile, trustworthy.

The distinctive direction comes from the subject's own world: electrical
switchboards and control panels. Backlit keycaps, engraved label plates, indicator
LEDs, brushed dark steel. Not "dark mode with a neon accent" — an instrument panel
you'd mount in a cabinet. Every visual decision below derives from that metaphor.

**Rejected defaults (do not regress to these):** near-black + acid-green accent;
cream + serif + terracotta; generic glassmorphism/blur cards. These are AI-design
templates, not choices for this brief.

### 4.2 Token system (`ui/theme.py` — single source of truth)

**Color** (named tokens, hex):

```
panel        #14171B — gunmetal housing; overlay body
keycap       #1F242B — raised key surface (default button fill)
keycap_hover #262C35 — key under finger
seam         #2C333D — 1px seams/borders between machined parts
signal       #F5A623 — amber indicator lamp; THE accent: run-state LED, focus ring, active page dot
live         #5BD66A — green "OK" lamp; success flash after a run
fault        #E05547 — fault lamp; error flash, destructive actions
ink          #E8E6E1 — primary text (warm off-white, not pure white)
ink_dim      #8A919C — labels, secondary text
vault_tint   #3A2430 — deep ember wash used ONLY on vault pages (see 4.4)
```

One accent (signal amber) carries the identity. live/fault are status lamps,
never decoration.

**Type** (bundle in `assets/fonts/`, load via QFontDatabase):

- Display/labels: **Chakra Petch** (squared, technical — reads like engraved panel
  lettering). Button labels: Chakra Petch Medium, UPPERCASE, +0.06em letterspacing,
  small size — like label plates.
- Body/dialogs: **IBM Plex Sans** — neutral, engineered companion.
- Data/mono: **IBM Plex Mono** — step lists, paths, PIN digits, timings.

**Shape & layout:**

- Buttons: soft-rounded squares, border-radius ≈ 20% of button size (≈14px @ 72px).
  Never circles, never sharp rectangles.
- Keycap construction: 1px seam border + a subtle top-edge highlight and bottom-edge
  shade (2-stop vertical gradient) so keys read as raised. Press = the key visually
  depresses (shift down 1px, gradient flattens). No drop-shadow blur spam.
- Grid gutter 10px; overlay padding 12px; drag handle is a 14px machined strip on top
  with three engraved notches (also the secret trigger target).
- Overlay corner radius 16px; thin seam outline so it sits on any wallpaper.

**Signature element** (the one memorable thing): every keycap has a tiny indicator
LED — a 5px dot in the top-right corner. Idle: off (barely-visible seam dot).
Action running: glows signal amber with a soft pulse. Finished OK: blinks live
green once and fades. Failed: holds fault red until clicked. The deck reads like a
live control panel — you can see at a glance what's running, what succeeded, what
faulted. This doubles as the async-feedback channel for the threaded action runner.
Spend boldness only here. Everything else stays quiet and disciplined.

### 4.3 Motion & quality floor

- Motion is restrained and mechanical: key depress (≈80ms), LED pulse (≈900ms ease),
  PIN pad slides up (≈160ms). Nothing bounces, nothing floats. A global
  `reduce_motion` setting disables animations (status LEDs switch states instantly).
- Keyboard reachable: arrow keys move focus on the grid, Enter fires; focus ring =
  1px signal outline. Esc closes dialogs/PIN pad.
- All text from theme tokens — no hardcoded hex or font names outside theme.py.

### 4.4 UI copy (words are design material)

- Plain verbs, sentence case in dialogs; button names are the user's own.
- Name by what the user controls: "Run a script", "Record a macro", "Add a step" —
  never internals like "execute step chain".
- An action keeps its name through the flow: "Save" button → "Saved" toast.
- Errors say what happened + what to do: *Script not found — check the path in Edit.*
  No apologies, no vague "Something went wrong".
- Empty slot in edit mode says: *+ Add a key*. Empty deck: *No keys yet — right-click to start.*
- Vault PIN pad placeholder: `••••` (mono); wrong PIN shakes once, lamp flashes
  fault, text: *Wrong code.* Nothing more (no hints, no lockout messaging that
  reveals the vault's importance).

### 4.5 Structure & behavior

- Frameless QWidget: `FramelessWindowHint | WindowStaysOnTopHint | Tool`
  (Tool keeps it off the taskbar). Translucent background for the rounded housing.
  Drag the whole window by the machined handle strip (also the secret long-press target).
- Edit mode toggle: keys get a small edit badge, drag to rearrange, click an empty
  slot to add, right-click to edit/delete. Normal mode: a click only fires the action.
- Multi-page decks — page dots under the grid; active dot is signal amber.
- Vault pages are visually distinguished to you only: the panel gets a barely-
  perceptible vault_tint ember wash and the page dot turns ember. Subtle enough that
  a bystander glancing at it sees nothing — you always know where you are.
- System tray: show/hide overlay, quit, open settings.

---

## 5. Hidden vault — the private section

Goal: a section only you know exists, invisible in normal use, behind a 4–6 digit code.
And it's **actually encrypted**, not just hidden in the UI.

**Crypto:**

- PIN (4–6 digits) → PBKDF2-HMAC-SHA256(pin, salt, iters=300k) → 32-byte key.
- Random salt generated on first setup, stored next to the blob.
- Hidden deck JSON encrypted with Fernet using that key → `vault.enc`.
- A small verification token (encrypted known value) lets you check "is this PIN right?"
  without decrypting the whole thing. Wrong PIN → can't decrypt, period.

**Access (invisible by design):**

- Default secret trigger = long-press (~1.5s) on the drag handle / a chosen corner.
  Nothing on screen hints at it.
- Long-press → `pin_pad.py` slides up → correct PIN → swap to the hidden page.
- Auto-relock on hide, on overlay blur, or after `relock_timeout_s`.
- Configurable trigger in settings (long-press / triple-click logo / secret slot).

---

## 6. Build phases

- **Phase 0 — Scaffold:** full tree, deps, main.py, stubbed modules with docstrings + TODOs, theme tokens.
- **Phase 1 — Runnable deck (MVP):** frameless draggable overlay + tray, rounded-square
  grid, load a sample deck from JSON, buttons fire run_script / key_macro / delay
  step chains on a worker thread. You can actually use it after this. **(done)**
- **Phase 2 — Editors, size & peek, AI builder:** three feature areas, full spec in §8.
  **(done)**
  - **A. Edit mode + editors:** edit badges, drag-to-rearrange, button_editor,
    action_editor (step chain UI incl. run_macro + a window_title-only condition step),
    macro_editor with live pynput recorder/player.
  - **B. Adjustable size + peek button:** one `SCALE` token in theme.py drives every
    size; resize grip on the overlay; settings slider with live preview; "pin to edge"
    tucks the deck away behind a half-circle signal-amber peek button.
  - **C. AI macro builder:** in-app chat panel (Anthropic/OpenAI via httpx, streaming);
    the agent asks clarifying questions, emits an action JSON block, and "Add to deck"
    binds it to the first empty slot.
- **Phase 3 — Steps, conditions, vault, pages, hotkeys:** **(done)**
  - **Bug fixes first:** tucking hides the overlay *before* the peek lamp is placed;
    the peek lamp anchors flush to the nearest edge (from `availableGeometry()`,
    relative to the overlay's position at tuck time) and only slides along it;
    untucking recomputes the overlay position deterministically from edge +
    along-edge offset (never stale geometry); the offset persists on every drag move.
  - **A. Remaining step types:** `shell` (cmd.exe /c on Windows, captured output,
    *Command failed (exit {code}) — {stderr_tail}*) and `launch` (url | app | auto,
    *Could not open {target} — check the path or URL.*); both editable in
    action_editor.
  - **B. Full condition types:** pixel_color (mss 1×1 grab, per-channel tolerance,
    "Pick pixel" helper in the editor), file_exists, time_window (overnight ranges);
    all four selectable on a condition row.
  - **C. Encrypted PIN vault:** PBKDF2-HMAC-SHA256(300k) key from a 4–6 digit PIN,
    Fernet blob + salt + verify token under data/vault/ (wrong PIN → None, never an
    exception). The vault stores its own page *and* its actions (a one-page Deck) so
    hidden keys never touch deck.json. PinPad slides up on a ~1.5s handle long-press:
    keycap-style numpad, amber fill dots, shake + *Wrong code.* on rejection, ember
    vault_tint wash while unlocked, auto-relock on hide/tuck/timeout.
  - **D. Multi-page decks:** clickable page dots (active = amber), horizontal swipe
    on the grid, add/delete/rename pages in edit mode, vault dot stays a
    barely-visible seam dot until unlocked.
  - **E. Global hotkeys + autostart:** HotkeyManager on the `keyboard` lib
    (conflict-safe, settings-driven, Hotkeys tab with press-to-capture cells);
    Windows autostart via HKCU\\…\\Run registry key, toggle in Settings > General.
- **Phase 4 — Packaging & polish:** **(done)**
  - **A. Launch step upgrades:** "file" mode opens any file with `os.startfile` (Windows)
    / `xdg-open` (other); `.ps1` launches via `powershell -ExecutionPolicy Bypass -File`;
    `.py` launches via `sys.executable`; `auto` mode now maps `.exe/.bat/.cmd/.ps1/.py/.sh`
    → app, everything else → file.
  - **B. FileBrowserDialog** (`ui/dialogs/file_browser.py`): fully themed replacement
    for `QFileDialog` — panel background, keycap-style bookmark shortcuts (Home/Desktop/
    Downloads), breadcrumb path bar (Plex Mono), sorted file list (dirs first then files)
    with a custom delegate drawing name + human-readable size + type chip (ink_dim),
    signal-amber selection border, keyboard navigation (↑↓ Enter Backspace Esc),
    footer path (Plex Mono, left-elided) + Cancel/OPEN keycap buttons. 680×480 at
    scale 1.0. Last visited directory persisted as `settings.last_browse_dir`.
  - **C. Active-window profiles** (`core/models.py` `WindowProfile`, `app.py` 500ms
    poll timer, Profiles tab in settings dialog): auto-switch the active page when the
    foreground app matches a pattern (contains/equals/regex); first match wins; fall
    back to page 0 on no match; manual override clears when the matched window loses
    focus.
  - **D. PyInstaller packaging** (`build.py` + `assets/icons/make_icon.py`): single-exe,
    windowed, bundles fonts/icons, excludes tests/data/scripts; icon = gunmetal rounded
    square with signal-amber LED dot (16/32/48/256 px multi-size .ico).
  - **E. Settings dialog polish:** General tab adds relock timeout spinbox + last_browse_dir
    display; new Profiles tab (table with inline-editable Name/Pattern/Match/Page +
    per-row Capture button); About tab with version from VERSION file.

---

## 7. Conventions

- Type hints everywhere; dataclasses for models.
- `core/` `storage/` `security/` = zero Qt, pure + testable.
- Action runner executes on a QThread; emits `started` / `step_done` / `finished` /
  `error` signals so the overlay never freezes.
- All persistence is JSON (hand-editable) except the encrypted vault blob.
- App data under `%APPDATA%/HoverDeck` in prod, `./data` fallback in dev.
- Windows-first; keep `utils/win.py` as the only OS-specific seam.
- **Design discipline:** every color, radius, font, and duration comes from
  `ui/theme.py` tokens (§4.2) — zero hardcoded styling elsewhere. Fonts (Chakra Petch,
  IBM Plex Sans, IBM Plex Mono) are bundled in `assets/fonts/` and registered via
  QFontDatabase at startup. The keycap LED is the only "loud" element; if a new UI
  idea competes with it, cut the new idea.

---

## 8. Phase 2 spec

### 8.A Edit mode + editors

- Toggle from the tray menu or right-click on the overlay. In edit mode every bound
  key shows a small seam-colored pencil badge (top-left); empty sockets invite with
  *+ Add a key*. Click an empty socket → button_editor (new key); click a bound key →
  button_editor pre-populated; right-click a bound key → Edit / Delete / Move.
- Drag-to-rearrange: the dragged key lifts (opacity 0.7, slight scale-up); the slot
  under the cursor highlights with a signal-amber border; drop swaps the slots.
  Normal mode stays pure — a click only fires the action.
- `ui/dialogs/button_editor.py`: icon (glyph palette or free emoji via
  `widgets/icon_picker.py`), label, disciplined color tint, bind/edit the Action.
- `ui/dialogs/action_editor.py`: the step chain builder. One row per step: type
  selector + type-specific fields; rows reorder/add/delete. Available types:
  run_script (file picker + args), key_macro (hotkey field), delay (ms spinbox),
  run_macro (pick a saved macro), condition (if/then/else with **window_title only**;
  other condition types stay Phase 3 stubs). Empty list copy: *No steps yet — add one
  below.*
- `ui/dialogs/macro_editor.py`: Record (pynput capture) / Stop, playback preview,
  name + save, list of saved macros, delete. `storage/macro_store.py` persists one
  JSON file per macro.

### 8.B Adjustable size + peek button

- **Scale:** `theme.SCALE` (1.0 = default, clamp 0.6–2.0) is THE size token; every
  px and pt in theme.py is `base * SCALE` (`theme.set_scale()` recomputes them, the
  QSS is rebuilt, the overlay rebuilds its widgets). Persisted as `settings.scale`.
  Hairlines (seams, focus ring) stay 1px — machined seams don't get thicker.
- **Resize grip:** bottom-right corner of the housing; a subtle 3-dot machined
  texture (speaker-grille style, gunmetal). Dragging scales the whole deck
  proportionally, live; "Size" slider in settings (60–200%, step 5%, live preview).
- **Peek button:** the tuck control on the drag handle (or tray "Pin to edge")
  slides the overlay to the nearest screen edge and tucks it away, leaving a
  half-circle signal-amber peek button protruding from the edge — an indicator lamp
  mounted on a wall, not a floating action button. Chevron points inward; hover
  brightens it; drag slides it along the edge; click slides the deck back in
  (200ms ease-out, instant under reduce_motion). Peek state (`peek_enabled`,
  `peek_edge`, `peek_offset`) persists in settings.json and is restored on launch.
  `ui/widgets/peek_button.py` owns the widget; `ui/overlay_window.py` owns the logic.

### 8.C AI macro builder

- A chat panel where the user describes an automation in plain language; the agent
  asks ONE clarifying question at a time, then produces an action JSON block, and
  the user confirms before anything is saved. Conversational and iterative.
- **Core (`core/ai_builder.py`, zero Qt, pure async):**
  - `BuilderContext`: partial action, existing macro names, deck slot count, plus
    `pasted_urls` / `pasted_info` captured from the chat via a simple URL regex.
  - `BuilderResponse`: `{ reply, partial_action: Action | None, ready_to_save,
    clarifying_questions }`.
  - `AIBuilder.send(user_message, context)` (async; optional `on_chunk` for
    streaming). Hardcoded system prompt: macro-building assistant, one question at
    a time, emit one fenced ```json block when ready, confirm before saving, never
    ask for passwords — login flows become a `run_script` step with a placeholder
    path like `scripts/login_site.py` that the user fills in locally.
  - Providers behind `_call_api(messages)`: Anthropic (`claude-sonnet-4-20250514`,
    `/v1/messages`) and OpenAI (`gpt-4o`, `/v1/chat/completions`), both via httpx,
    both streaming.
  - The fenced JSON is extracted with `str.split` (no regex), parsed through
    `core.models.action_from_dict_safe(d) -> Action | None` (returns None + logs on
    schema errors), and post-processed: `PASTE_URL_HERE`-style placeholders are
    replaced with the first pasted URL (logged).
- **Panel (`ui/ai_builder_panel.py`):** slides in from the overlay's right side
  (pushing the grid left) or floats next to it — user choice in settings. Header
  "AI Builder" (Chakra Petch, signal-amber) + close. Chat bubbles: user = right,
  keycap fill; agent = left, panel fill + seam border (panel readouts, Plex Mono for
  JSON/code). Multi-line input (max 3 lines) + amber Send. URL paste shows an inline
  chip: *URL captured — will be inserted into action*. Streaming token-by-token with
  a seam-colored three-dot typing indicator. When `ready_to_save`: a live-green
  "ADD TO DECK" lamp-button saves the Action into the first empty slot (the new key
  gets the standard LED). Errors per §4.4: *No API key — add one in Settings.* /
  *Connection failed — check your key and network.* / *Could not parse action JSON —
  ask the agent to try again.*
- **Settings:** `ai_provider` ("anthropic" | "openai"), `ai_api_key` (stored in
  settings.json — accepted risk, sent only to the chosen provider), `ai_panel_mode`
  ("slide" | "floating"). settings_dialog gets an "AI Builder" tab (provider,
  masked key, "Test connection" → *Connected ✓* or the error in fault-red, panel
  mode) alongside General (size slider, reduce_motion, autostart), Hotkeys (stubs),
  About.
