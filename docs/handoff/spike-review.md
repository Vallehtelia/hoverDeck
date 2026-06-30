# HoverDeck — Full Spike (Review + UI + Features)

> Point-in-time deep-read of the codebase. **Date:** 2026-06-30 · **At:** `main` @ `76663d5`
> + the uncommitted Phase 1/2 readiness work. Read-only investigation; producing this
> document changed no source. Companion to `distribution-plan.md`.

## Snapshot
- **What it is:** PyQt6 frameless, always-on-top "Sähkökeskus" macro deck. ~76 files,
  `__version__ = 0.4.0`. CLAUDE.md says "Phases 1–3 done, Phase 4 remaining," but the code
  shows **Phase 4 features present** (active-window profiles, file browser, packaging) — the
  index lags reality.
- **Architecture rule holds:** `core/`, `storage/`, `security/` import **zero Qt** — every one
  of those ~22 files is stdlib + internal only. `pynput`/`mss`/`psutil`/`ctypes`/`win32*` are
  **lazy-imported inside methods** with friendly fallbacks, so the pure layers stay
  headless-importable.
- **Design-system rule (almost) holds:** `theme.py` is a genuine single source of truth; **no
  hardcoded hex anywhere outside it**. The only styling leaks are *geometry* constants in two
  files (below).
- **Threading boundary is clean:** `core` runs on a worker thread; results cross back as
  **queued Qt signals** via a long-lived `ActionDispatcher`, so the overlay never blocks and
  in-flight runs survive widget rebuilds.

---

# PART 1 — REVIEW REPORT

## 1.1 Readiness work already in the tree
- **Phase 1 (key-at-rest):** `security/secret_store.py` + DPAPI in `utils/win.py`;
  `settings_store.py` routes `ai_api_key` to the encrypted store, blanks it in `settings.json`,
  migrates legacy plaintext. Verified.
- **Phase 2 (release hygiene):** global `sys.excepthook` in `app.py`; version single-source
  (`__init__.__version__`, pyproject `attr`); README Privacy section.
- **Verification:** full repo byte-compiles; **24/24 runnable pure tests pass** (incl. real
  `cryptography` vault tests + new secret-store tests). pytest/PyQt6 aren't installable on the
  Linux dev host → the DPAPI round-trip and crash dialog still need a **Windows smoke test**.

## 1.2 Consolidated issue ledger (severity-ranked)

| # | Sev | Area | Finding | Where |
|---|-----|------|---------|-------|
| 1 | **High (inherent)** | Vault crypto | A 4–6 digit PIN = 10⁴–10⁶ combos. `salt.bin` + `verify.tok` sit on disk next to `vault.enc`, so an attacker with file access can **brute-force the PIN offline**. 300k PBKDF2 iters slow it but can't rescue that little entropy. The vault deters casual snooping, *not* a forensic attacker — set buyer expectations (or allow longer alphanumeric codes). | `security/pin.py` |
| 2 | **Med** | Secret store | DPAPI is called with **no extra entropy** → any process running as the same Windows user can decrypt `secrets.json` and lift the API key. Hardening: pass app-specific entropy to `CryptProtectData`/`CryptUnprotectData`. | `utils/win.py:91` |
| 3 | **Med (bug)** | Packaging | `core/vpn.py` imports `psutil`, declared in `pyproject` + `requirements-windows.txt`, **but missing from `requirements.txt`** → a source install via that file crashes when the VPN feature runs. | `requirements.txt` |
| 4 | **Med (UX bug)** | Macros | `MacroRecorder` records the **Stop click/hotkey itself**, so playback replays the stop gesture (acknowledged TODO). | `core/macro_recorder.py:30` |
| 5 | **Med (bug)** | Macros | `MacroEditor` plays back on a raw `threading.Thread` and **silently swallows playback errors**; the "surfaced by the status below" comment is stale — nothing is shown on failure. | `ui/dialogs/macro_editor.py:156` |
| 6 | **Low–Med** | Vault | `VaultStore.setup()` has **no `exists()` guard** — calling it on an existing vault overwrites salt/token/blob and irrecoverably destroys it. Relies on callers checking first. | `security/vault.py:51` |
| 7 | **Low** | Robustness | `pixel_color` (off-screen coord) and `macro_player` (unknown `Key` name) can raise **uncaught** exceptions that bubble to the runner's generic handler instead of a friendly error. | `conditions/pixel_color.py`, `core/macro_player.py` |
| 8 | **Low** | Engine | `run_script` and `shell` are **not cancel-aware** — they block until subprocess timeout, so a second-press / cancel can't interrupt a long script. (`delay`, `key_macro`, `run_macro`, `condition` are cancel-aware.) | `core/steps/run_script.py`, `shell.py` |
| 9 | **Low** | Crash handler | The `sys.excepthook` won't catch exceptions **on worker QThreads** or ones swallowed inside Qt slots. Consider a per-thread hook. | `app.py:47` |
| 10 | **Low** | Consistency | Regex errors handled two ways: `WindowProfile.matches` swallows `re.error`→False; `WindowTitleCondition` raises `ConditionError`. | `models.py:181` vs `conditions/window_title.py:22` |
| 11 | **Low** | Storage | `MacroStore` uses `macro_id` directly as a filename, unsanitized (ids are app-generated today). | `storage/macro_store.py:14` |
| 12 | **Low (smell)** | Design system | `file_browser.py` carries hardcoded **geometry** constants (`_ROW_H_BASE=28`, `_W_BASE=680`, selection alpha `26`, etc.) outside `theme.py` (they ×SCALE but bypass the token system). | `ui/dialogs/file_browser.py` |
| 13 | **Low (smell)** | Design system | `peek_button.py` hardcodes `lighter(126)/darker(122)`/`alpha 90`/`margin 16` instead of theme factors. | `ui/widgets/peek_button.py` |
| 14 | **Low** | Engine perf | Vault `load`/`save` run **PBKDF2 twice** per call (`verify_pin` + `derive_key`). | `security/vault.py:69,85` |
| 15 | **Trivia** | Cleanup | `condition.py` docstring stale (claims non-title conditions raise until Phase 3); `theme.TOP_HIGHLIGHT_ALPHA` dead token; `settings_dialog.py:546` unused `_QPoint` import; `settings_dialog` `_SLIDER_MIN/MAX` duplicate `theme.SCALE_MIN/MAX` (drift risk); `vpn._last_detail` module global (not thread-safe); `ChatBubble.set_text` complexity hotspot. | various |

**Note on the old "plaintext API key" finding:** `Settings.to_dict()` still *includes* `ai_api_key`
in memory, but Phase 1's `settings_store.save()` **scrubs it to `""` before writing disk**, so it
no longer lands in `settings.json`. Residual is only theoretical (a future serializer of
`Settings`). Low.

---

# PART 2 — FULL UI SPIKE

## 2.1 Design system — `ui/theme.py`
Single source of truth. **Colors:** `PANEL #14171B`, `KEYCAP #1F242B`, `KEYCAP_HOVER`,
`SEAM #2C333D`, **`SIGNAL #F5A623` (the one accent)**, `LIVE #5BD66A`, `FAULT #E05547`,
`INK #E8E6E1`, `INK_DIM`, `VAULT_TINT #3A2430` (vault pages only). **Fonts:** Chakra Petch
(labels, uppercase +6% tracking), IBM Plex Sans (body), IBM Plex Mono (paths/PIN), each with
fallbacks. **SCALE:** one float (clamped 0.6–2.0); `set_scale()` materializes same-named module
globals from `_SIZE_BASES` so widgets read `theme.OVERLAY_RADIUS` directly — hairlines
(`SEAM_WIDTH=1`, `FOCUS_RING_WIDTH=1`) stay 1px at every scale on purpose. **Motion tokens** (ms):
key depress 80, LED pulse 900, success blink/fade, PIN slide 160, peek slide 200, shake 300 —
consumers gate on `reduce_motion` themselves. **QSS:** `app_qss()` builds one stylesheet for all
stock widgets, rebuilt on every `set_scale`; buttons use a `variant` property
(`primary`/`live`/`danger`/`glyph`) and a `role` property (`dim`/`fault`/`live`/`mono`).

## 2.2 The overlay shell — `ui/overlay_window.py` (1,179 lines)
Frameless `Frameless | StaysOnTop | Tool` + translucent. Four classes:
- **`DragHandle`** — machined notched strip; drag moves the window; a `QTimer` (`hold_ms`≈1500)
  fires the **unhinted vault long-press** (`secret_held`); any movement cancels it; a right-end
  "tuck zone" click emits `tuck_requested`.
- **`PageDots`** — one dot per page (active = amber), a `+` dot in edit mode, and a **vault dot**
  that's barely-visible `SEAM@idle` until unlocked (a click on the locked vault dot is *silently
  swallowed* by design). Right-click → delete page; double-click → inline rename.
- **`ResizeGrip`** — bottom-right 3-dot grille; drag → live `scale_preview`, release →
  `scale_committed`.
- **`OverlayWindow`** — the hub. `_page_index` is a *combined* index (pages, then vault when
  unlocked). Rebuilds its whole column (handle+grid+dots) on every state change; the
  `ActionDispatcher` + worker threads deliberately **outlive** rebuilds.
  - **Secret→PIN→vault flow:** `secret_held` → `_open_pin_pad` → `PinPad` → `_on_pin`: first-ever
    PIN calls `vault_store.setup()` (that PIN becomes the code); else `vault_store.load(pin)`.
    Wrong PIN → escalating lockout (`_wrong_pin_lock_s`: first 2 free, then 5/10/20… doubling,
    capped 300s). Success → ember `VAULT_TINT` wash + switch to vault page.
  - **Auto-relock:** single-shot timer reset on activity; `hideEvent` *always* relocks (covers
    tuck/hide); drops the decrypted deck + PIN from memory.
  - **Peek/tuck:** `tuck()` **fades opacity to 0 in place** (never slides across monitors), hides,
    then shows a `PeekButton`; `untuck()` recomputes home pos and fades back in. Peek state persists.
  - **Multi-page:** swipe (`±1`), dots, add/delete/rename; delete GCs orphaned actions.
  - **AI panel:** `toggle_ai_builder()` lazily builds `AIBuilderPanel`, floating or docked; passes
    macro names, free slots, and the script catalog (hidden scripts only when vault unlocked).
  - **VPN badge:** polls `core.vpn` every 4s, drives a badge + the peek lamp ring.
  - **Right-click menu:** Edit deck / AI Builder / Macros / Scripts / (vault-only items) / Pin to
    edge / Settings / Quit.

## 2.3 Keycap + grid + the LED loop
- **`deck_grid.py`** — `ActionThread(QThread)` runs one action; `ActionDispatcher(QObject)` emits
  `started/step_done/finished/cancelled/error` as queued signals and routes them by action-id to
  the right keycap. Keyboard arrow-nav, horizontal swipe (cancels the press, emits `swiped`), and
  move-via-menu swaps. The `is_vault_action` callback gates `allow_hidden_scripts` overlay →
  dispatcher → context.
- **`deck_button.py`** — the raised rounded-square keycap with the **signature 5px LED**. State
  machine: IDLE (faint seam dot) → RUNNING (amber pulse) → SUCCESS (green blink→fade) → ERROR
  (**holds red until clicked**, error message in tooltip). Painting: 2-stop keycap gradient or
  cover-scaled image face, moving diagonal glass specular streak on hover, optional user tint
  (restricted to lamp tokens), pencil edit badge, drag-drop rearrange with amber drop-hover. Focus
  ring shows for keyboard focus only (not mouse).
- **`pin_pad.py`** — numpad that slides up from the housing; keycap-style keys (no LED); 4–6 amber
  fill dots that shake + flash fault on wrong code ("Wrong code.") and live-green on unlock;
  per-second lockout countdown; Esc dismisses; auto-fits keys to the housing.

## 2.4 Supporting widgets
- **`tray.py`** — paints a keycap-with-lit-lamp icon; menu mirrors the right-click menu;
  single-click toggles visibility.
- **`edit_mode.py`** — drag mime payload + the "lifted key" drag pixmap + the key context menu.
- **`screens.py`** — multi-monitor geometry (resolve `QScreen.name()`, taskbar-excluded area,
  human labels).
- **`widgets/peek_button.py`** — the half-circle edge lamp: domed radial gradient, glass sheen,
  optional VPN arc, inward chevron; drag along the edge re-places + persists offset.
- **`widgets/icon_picker.py`** — 16-glyph switchboard palette + free emoji/path field + "Image…".
- **`widgets/no_scroll.py`** — wheel-ignoring `QComboBox/QSpinBox/QTimeEdit` so scrolling a form
  never silently changes a value.

## 2.5 Dialogs
- **`action_editor.py`** — the step-chain builder: one card per step, reorder/add/delete,
  **auto-inserts a 300ms delay between consecutive non-delay steps**. `ConditionForm` covers all 4
  condition types incl. a "Pick pixel" screen-grab helper; conditions get nested Then/Else editors.
  run_script browse enforces the **vault-only-script rejection** and stores paths relative to
  `scripts/` for portability.
- **`button_editor.py`** — label / icon / tint / "repeat until stopped" / bound action, with a
  **live WYSIWYG preview using a real `DeckButton`**. Can bind a new key to an existing action.
- **`macro_editor.py`** — record/play/delete with a live event counter. *(Defects #4–#5.)*
- **`settings_dialog.py`** — edits a **copy** of Settings (caller persists), live scale preview.
  Tabs: **General** (size slider 60–200%, monitor, grid rows/cols, reduce-motion, VPN overlay +
  hint, autostart, relock timeout, last-browse-dir, script interpreter); **AI Builder** (provider,
  fixed model list, masked key + "Get a key…", off-thread **Test connection**, panel mode/side);
  **Profiles** (table + per-row **Capture** that grabs the foreground title after 2s); **Hotkeys**
  (per-action click-then-press capture cells); **About** (`__version__`).
- **`file_browser.py`** — fully themed `QFileDialog` replacement (keycap bookmarks, mono
  breadcrumb, custom row delegate w/ size + type chip, amber selection, full keyboard nav).
  *(Smell #12.)*
- **`script_manager.py`** — manage the `.py` files steps reference: list/edit-in-place/new/delete/
  **drag-drop import**/**pip install** (off-thread `_PipWorker`). The **Description field is saved
  as the script's docstring** and is the seam that feeds the AI which scripts exist.
- **`script_review.py`** — human-in-the-loop gate for AI-written code: editable, warns scripts run
  with full permissions, **basename-only** save (no path traversal), normal vs hidden placement.

## 2.6 AI Builder panel — `ui/ai_builder_panel.py`
Chat column. `_SendWorker(QThread)` runs one turn via `asyncio.run(builder.send(..., on_chunk))`,
streaming tokens to a typing indicator → live bubble; renders ``` fences as mono. **One-turn-at-
a-time** guard; no-key short-circuit. **Suggestion chips**, **URL-captured chip**, **ADD TO DECK**
(green lamp → emits Action + target slot), **REVIEW SCRIPT** (opens review dialog, then tells the
agent where the script landed). A **tool-loop guard** (>6 auto-replies bails) and a deferred
`show_script` responder with a `relative_to()` path-traversal guard + vault gate.

## 2.7 UI architecture verdict
The **LED feedback loop is the most polished thing in the codebase**: worker QThread → queued
signals → dispatcher → per-keycap state machine, `reduce_motion` honored throughout, errors held
until acknowledged. Gesture set is rich and the vault's deliberate undiscoverability is coherent
and well-isolated. Main risks: **rebuild-heavy** column churn and the two **geometry-token leaks**
(file_browser, peek_button).

---

# PART 3 — FULL FEATURE SPIKE

## 3.1 Data model — `core/models.py`
`Action{id,name,icon,color,steps,repeat}`, `MacroEvent{kind,action,data,t_ms}`,
`Macro{id,name,events}`, `Page{id,name,rows,cols,slots}` (string↔int slot-key conversion handled),
`Deck{pages,actions}`, `WindowProfile{pattern,match_mode,page_id}` (`matches()` swallows bad
regex), `SecretTrigger{type,target,hold_ms=1500}`, `Settings` (tolerant `from_dict`).
`action_from_dict_safe()` is the **only** safe-wrapper — returns `None`+logs on bad/AI JSON; the
step/condition *registries* raise `ValueError` on unknown type, which that wrapper catches.

## 3.2 Execution engine
- **`ExecutionContext`** — cancellable + sleepable: `sleep(ms)` returns `True` if the full wait
  elapsed, `False` if cancel woke it early. Carries `scripts_dir`, `python_exe`,
  `allow_hidden_scripts`, `macro_store`, `variables`, `last_output`.
- **`ActionRunner`** — **pure `threading`, not QThread** (Qt-ness wrapped in the UI). `run_async()`
  spawns a daemon thread; 5 callbacks fire on the worker thread (UI marshals to signals). **Dedup
  guard** by `action.id` (second press ignored; `repeat=True` loops until `cancel()`). Three error
  tiers: `StepError`→friendly, `NotImplementedError`, bare `Exception`→logs traceback + generic.

## 3.3 Step types (7)
| Key | Behavior | Cancel-aware? |
|-----|----------|---------------|
| `run_script` | Python file or inline; resolves interpreter (handles frozen exe); **vault-only `hidden/` gate**; captures stdout→`ctx.last_output`; non-zero exit→StepError | ❌ (blocks to timeout) |
| `run_macro` | Validates + lazy-loads player; replays with timing | ✅ (via player) |
| `key_macro` | Sends key combos; rich token map; unknown token→StepError | ✅ (between combos) |
| `shell` | Windows `cmd.exe /c` (list) / non-Windows `shell=True`; UNC-cwd workaround; non-zero→StepError | ❌ |
| `launch` | url/app/file/auto; `.ps1`→powershell, `.py`→python; `os.startfile`; **WSL `explorer.exe` case** | ❌ (by design) |
| `delay` | `ctx.sleep(ms)` | ✅ |
| `condition` | if/then/else, recursive; serializes `orelse` as `"else"`; late imports avoid cycle | ✅ |

## 3.4 Condition types (4)
- `window_title` — contains/equals (casefold) / regex (raises on bad regex); reads the OS seam.
- `pixel_color` — `mss` 1×1 grab, per-channel ±tolerance (L∞); strict 6-hex parse.
- `file_exists` — `Path.expanduser().exists()`; empty path → False.
- `time_window` — inclusive range, **correct overnight handling** (e.g. 22:00–06:00); local time.

## 3.5 Macro record/playback
`MacroRecorder` — global pynput keyboard+mouse listeners; **mouse-move coalescing** (≥20ms);
JSON-safe key serialization; monotonic-clock timestamps. *(Records the stop gesture — #4.)*
`MacroPlayer` — replays inter-event deltas via `ctx.sleep`, fully cancel-aware; absolute screen
coords (no resolution scaling).

## 3.6 Security
- **`pin.py`** — PBKDF2-HMAC-SHA256, **300k iters**, 32-byte key → Fernet; verify token =
  encrypted known constant. PIN/key never logged or persisted. *(Entropy ceiling — #1.)*
- **`vault.py`** — stores a one-page `Deck` as a Fernet blob (`vault.enc`+`salt.bin`+`verify.tok`);
  **wrong PIN → `None`, never raises**; atomic writes. *(No setup() guard — #6; double PBKDF2 — #14.)*
- **`secret_store.py`** — `secrets.json` with `dpapi`|`plain` scheme; DPAPI on Windows, base64-only
  fallback elsewhere (logged, dev-only). *(No entropy — #2.)*

## 3.7 AI Builder (core — `core/ai_builder.py`)
Async httpx agent, Anthropic + OpenAI, streaming. Curated fixed model lists (recommended:
`claude-sonnet-4-6` / `gpt-5.4-mini`). System prompt: one question at a time, fenced ```json action
block, **never asks for secrets**, composes small reusable scripts, can request to read existing
scripts (`show_script`), targets specific slots. Extracts JSON via `str.split` →
`action_from_dict_safe`, substitutes `PASTE_URL_HERE` with pasted URLs. **BYO-key** (Phase 1
secured at-rest).

## 3.8 Scripts subsystem
`script_catalog.py` builds an AI-facing "name — purpose" list from each script's docstring/first
comment (hidden scripts only when unlocked); `split_/join_docstring` separate description from body.
Paired with the **vault-only run gate** in `run_script` and the human-review gate in
`script_review.py`. Scripts run with the user's full permissions (privacy/EULA note covers this).

## 3.9 Other features
- **Global hotkeys** (`utils/hotkeys.py`) — `keyboard` lib (Windows-only), lazy import,
  conflict-safe, graceful no-op elsewhere; fires onto the UI thread via a queued signal bridge.
- **Active-window profiles** — 500ms `QTimer` polls the foreground title and auto-switches pages
  (first match wins, fall back to page 0); manual override suppresses auto-switch until focus
  leaves. *(Off-Windows the title is always "" → keeps forcing page 0.)*
- **VPN overlay** (`core/vpn.py`) — **egress-route detection** (UDP connect to 8.8.8.8, no packets
  sent, read `getsockname()`) to defeat the "tunnel adapter stays up" trap; pure-ctypes
  `GetAdaptersAddresses` on Windows, psutil fallback; honest about split-tunnel.
- **Peek/tuck, live scaling, multi-monitor docking** — all persisted in settings.
- **Storage/config** — JSON, atomic writes, never destroys a bad file (falls back to defaults);
  `%APPDATA%/HoverDeck` (prod) vs `./data` (dev).
- **Packaging** — PyInstaller (onefile portable + onedir for installer, windowed, fonts/icons
  bundled, tests excluded); Inno Setup **per-user, no-admin**, stable AppId; CI builds + releases
  on `v*` tags, artifacts on manual runs; dynamic version from `__init__`.

---

*Generated as part of distribution-readiness work. This spike changed no source files.*
