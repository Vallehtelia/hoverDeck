# HoverDeck — Distribution Plan (Phase 0: Research + Audit)

> **Status (updated 2026-06-30):** Phase 0 research done; **Phase 1 (key-at-rest) and Phase 2
> (release hygiene) implemented in the working tree and verified** (full repo byte-compiles; 24/24
> runnable pure tests pass, incl. crypto vault + new secret-store tests). **Stopped before the paid
> version** (no licensing/store work) per the owner. Uncommitted. See **§0. Readiness status**.
>
> **Date:** 2026-06-30 · **Audited at:** `main` @ `76663d5` · **App version:** `hoverdeck/__init__.__version__` = `0.4.0`
>
> **Scope honored:** respects the "Sähkökeskus" design system and the *rejected defaults* in
> `PLAN.md §4`. Nothing in this plan introduces a visual regression; every UI touch reuses
> existing `theme.py` tokens and existing dialogs.

---

## TL;DR for the owner

1. **Your API key is NOT bundled, hardcoded, shipped, or defaulted anywhere.** I grepped the
   whole tree for key patterns (`sk-…`, `sk-ant`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `api_key = "…"`) → **0 matches**. The app is **already BYO-key**: `AIBuilder` *requires* a key
   passed in, and the only source is the user's own `Settings.ai_api_key`. **This means the
   "critical, blocks distribution" scenario in the brief does not exist.** You will not be billed
   for users; nothing can get *your* provider account flagged.
2. **The one real (and much smaller) gap:** the user's *own* key is stored in **plaintext**
   `settings.json`. That's the user's key on the user's machine — annoying, not catastrophic, and
   `PLAN.md §8.C` explicitly logged it as an "accepted risk." Phase 1 = harden this (encrypt at
   rest + validate on entry). It is **polish, not a blocker.**
3. **Store — decided: Gumroad for v1** (full merchant-of-record since 2025 → VAT/tax is *their*
   legal problem, built-in license keys, $0 setup, **no fixed cost, no approval gate**, free file
   hosting) selling the **existing Inno Setup installer**, gated by an **offline signed license
   key** (zero server infra). **No fixed cost + free hosting + offline keys = you cannot be out of
   pocket** (§3.0). Reversible: store-agnostic keys let you switch to Lemon Squeezy (5% vs 10%)
   later without a rebuild. **Skip the Microsoft Store** — MSIX sandboxing collides head-on with
   HoverDeck's global input capture, shell steps, registry autostart, and arbitrary-script
   execution.
4. **Signing:** ship **unsigned** for v1 (SmartScreen "More info → Run anyway", which the README
   already documents) at **$0**; upgrade to **Azure Trusted Signing (~$10/mo)** as the cheapest
   real signing path once sales justify it.

---

## 0. Readiness status — "ready up to the paid gate" (2026-06-30)

**Done & verified (working tree, uncommitted):**
- **Phase 1 — key-at-rest:** AI key encrypted via Windows DPAPI (new `security/secret_store.py` + `utils/win.py` seam), never written to `settings.json`, legacy plaintext auto-migrated on load. New `tests/test_secret_store.py`.
- **Phase 2 — release hygiene:** global `sys.excepthook` (no more silent crashes in the windowed build); version single-source = `hoverdeck/__init__.__version__` (`pyproject` derives via `attr`); README **Privacy** section + encrypted-at-rest copy.
- **Verified here:** full repo byte-compiles; 24/24 runnable pure tests pass (incl. real `cryptography` vault tests + new secret-store tests). pytest/PyQt6 aren't installable on this Linux host → run `pytest` and a quick smoke test on **Windows** to confirm the DPAPI round-trip and the crash dialog.

**Prepared, awaiting your input (not fabricated):**
- `docs/handoff/EULA-template.md` — fill `<<SELLER_LEGAL_NAME>>`, `<<JURISDICTION>>`, etc., then legal-review; ship as `EULA.txt` + wire into the Inno wizard.
- Installer **publisher name** (`installer/hoverdeck.iss` `MyAppPublisher`) — needs your legal/seller name (also required for code signing).

**Deliberately NOT started (this IS the "paid version"):**
- **Phase 3** — licensing/activation (offline Ed25519 keys + activate UI + gating policy).
- **Phase 4** — Gumroad product + license-key delivery + store copy.
- Code signing + in-app update check (Phase 5, optional).

**Single gate to selling:** Phase 3 (license gate) + Phase 4 (store) + dropping in the finalized EULA/publisher name. Everything *before* that gate is done.

---

## 1. AI / API-key handling  ← audited first, it's the headline risk

### 1.1 How auth works today (verified, file-by-file)

| Concern | Reality in the code |
|---|---|
| Where the key comes from | `Settings.ai_api_key` only. `core/models.py:251` (`ai_api_key: str = ""`). |
| How it reaches the network | `AIBuilder.__init__(provider, api_key, model)` (`core/ai_builder.py:304`). Used as `x-api-key` (Anthropic, `:397`) or `Authorization: Bearer` (OpenAI, `:410`). |
| Who constructs `AIBuilder` | `ui/ai_builder_panel.py:202` and `:303`, and the Settings "Test connection" worker `ui/dialogs/settings_dialog.py:77` — **all three pass `settings.ai_api_key`**. No other source. |
| Default / fallback / env-var key | **None.** No `os.environ[...]`, no embedded constant, no `.env`. If the key is empty → `AIBuilderError("No API key — add one in Settings.")` (`ai_builder.py` `NO_KEY_ERROR`, raised at `_call_api` `:392`). |
| Bundled into the binary? | **No.** `build.py` bundles only `assets/fonts` + `assets/icons`; it `--exclude-module`s tests. `settings.json` is **git-ignored** (`.gitignore`: `settings.json`, `data/`) and is **not** added to the PyInstaller bundle. The release CI (`.github/workflows/release.yml`) injects **no secrets** into the build. |
| Does the app *discourage* leaking keys? | Yes — the system prompt (`ai_builder.py SYSTEM_PROMPT` rule 4) instructs the model to **never ask for passwords or API keys**, and routes credential steps to a local `run_script` placeholder. |

**Verdict: the brief's worst case is not present.** There is no extractable, you-billing,
store-flaggable secret. Severity of what *remains* (below) is **LOW–MEDIUM**, not critical, and
**does not block selling**.

### 1.2 The actual gap — plaintext key at rest

- `storage/settings_store.py` writes `Settings.to_dict()` to `settings.json` as **plaintext JSON**.
  `ai_api_key` is included verbatim (`models.py:251`, `to_dict` at `:260`, `from_dict` at `:291`).
- Impact: anyone with read access to `%APPDATA%\HoverDeck\settings.json` (malware, a shared
  machine, a synced backup, a support screen-share) can lift the **user's** key. It bills the
  **user**, not you. The vault, decks, and macros are unaffected (the vault is separately
  encrypted).
- This is exactly what `PLAN.md §8.C` flagged as "accepted risk." For a **paid** product the bar
  is higher, so Phase 1 closes it.

### 1.3 BYO-key plan (this is hardening, not greenfield)

What already exists and **must be preserved** (no regressions):

- Settings → **AI Builder** tab: provider dropdown, model dropdown (recommended-tagged), masked
  key field (`QLineEdit.Password`), **"Get a key…"** button → provider console
  (`API_KEY_URL`), **"Test connection"** (off-thread ping via `_PingWorker`).
- Graceful **no-key state**: panel refuses to send and shows *"No API key — add one in Settings."*
  (`ai_builder_panel.py:324`); everything else in the app works without a key (README already
  says so).

What Phase 1 adds — **encrypt at rest + validate on entry + one-time migration**:

| File | Change |
|---|---|
| **NEW** `hoverdeck/security/secret_store.py` | Tiny pure-logic interface: `store_secret(name, value)` / `load_secret(name)` / `clear_secret(name)`. Delegates the actual OS crypto to the `utils/win.py` seam (keeps `security/` Qt-free, per the architecture rule). |
| `hoverdeck/utils/win.py` | Add **Windows DPAPI** calls (`win32crypt.CryptProtectData` / `CryptUnprotectData` — **pywin32 is already a dependency**, zero new deps). Per-user, transparent, no PIN. Non-Windows dev fallback: obfuscated-but-documented local file so tests run on Linux. |
| `hoverdeck/storage/settings_store.py` | On **save**: pop `ai_api_key` out of the JSON dict, write it via `secret_store`; persist only a marker (e.g. `"ai_api_key": ""`). On **load**: hydrate `Settings.ai_api_key` from `secret_store`. **One-time migration:** if a legacy plaintext key is found in `settings.json`, move it to `secret_store` and blank the JSON field. |
| `hoverdeck/ui/dialogs/settings_dialog.py` | Change the field tooltip/hint copy from *"Stored in settings.json"* → *"Stored encrypted on this machine; sent only to the provider."* (sentence case, `PLAN.md §4.4`). Optionally trigger **validate-on-save** by reusing the existing `_PingWorker`. **No layout/visual change.** |
| `hoverdeck/ui/ai_builder_panel.py` | No logic change — it already reads `settings.ai_api_key`, now hydrated from the secret store. |
| **NEW** `tests/test_secret_store.py` | Round-trip + missing-key + migration tests (pure Python, runs in CI on Linux via the fallback). |

**Design decision needed from you (do not proceed without confirming).** The brief says *"stored
in the existing encrypted vault."* I recommend **against** literally using the PIN vault, and here's why:

| Option | What it means | Trade-off | Rec |
|---|---|---|---|
| **A. OS secret store (DPAPI / `keyring`)** | Encrypt the key with the user's Windows login secret. No PIN, transparent. | Real at-rest encryption, zero new UX, zero new deps (pywin32 already present). Satisfies the **intent** of the brief. | ✅ **Recommended** |
| **B. App-level Fernet key** | Derive a key from a machine/user value, Fernet-encrypt. | Weaker (the wrapping key has to live somewhere); reinvents DPAPI. | ➖ |
| **C. Literal PIN vault (`VaultStore`)** | Put the AI key inside `vault.enc`. | **Couples a normal feature to the secret vault** — the user would have to *set up a PIN and unlock the vault every session* just to use the AI builder, breaking "everything else works without it." The vault may not even be set up. | ❌ Not for the default |

Option A delivers what you actually want ("not plaintext on disk") without the UX cost of C.
I'll implement A unless you prefer C's literal reading of the spec.

---

## 2. Packaging & signing

### 2.1 Current state (already in good shape)

- **`build.py`** — PyInstaller. `--onefile` → portable `dist/HoverDeck.exe`; `onedir` arg →
  `dist/HoverDeck/` (feeds the installer). `--windowed`, bundles fonts + icons, excludes
  tests/pytest, custom multi-size `.ico`.
- **`installer/hoverdeck.iss`** — Inno Setup, and it's **well done**: **per-user install**
  (`PrivilegesRequired=lowest`, `{autopf}` → `%LOCALAPPDATA%\Programs`, **no UAC/admin**), a
  **stable `AppId` GUID** (clean in-place upgrades + uninstall), optional desktop shortcut,
  uninstaller, modern wizard.
- **`.github/workflows/release.yml`** — on a `v*` tag: builds portable + one-dir, installs Inno
  via Choco, builds the installer with the tag-derived version, uploads artifacts, and publishes a
  GitHub Release (manual runs upload artifacts only — no release). **Injects no secrets.**
- Data lives in `%APPDATA%\HoverDeck` (untouched by uninstall). Clean.

### 2.2 What a clean Windows install needs (mostly already true)

- ✅ Per-user, no admin. ✅ Stable upgrade identity. ✅ Start-menu + uninstaller. ✅ Bundled fonts
  (no system dependency). ✅ Data survives uninstall.
- ⚠️ **Python dependency for `run_script`:** scripts (and AI-written scripts) need a Python
  interpreter on the user's machine (README documents this; `Settings.script_python` points at it).
  Non-script features work without it. Acceptable — just make it loud in first-run/store copy.
- ⚠️ **AV false positives:** PyInstaller `--onefile` exes are unpacked to a temp dir at launch and
  frequently trip SmartScreen/AV heuristics. **Prefer the one-dir installer as the primary
  download**; offer the one-file exe as the secondary "portable" option (the README already frames
  it that way).

### 2.3 Signing — cheap path vs polished path

| Path | Cost (approx — verify at purchase) | UX | Notes |
|---|---|---|---|
| **Unsigned (cheap)** | **$0** | SmartScreen *"Windows protected your PC"* → **More info → Run anyway**. AV false-positive risk. | README already explains the click-through. Reputation accrues slowly with downloads. **Fine for v1.** |
| **Azure Trusted Signing** | **~$10/mo** | Cloud signing, no hardware token. Builds Microsoft reputation; SmartScreen clears as reputation accrues. | **Cheapest real signing.** Requires an eligible identity (individual validation now offered; org needs ~3yr history). Integrates into the CI signing step. **Recommended upgrade.** |
| **OV certificate** | ~$200–400/yr | Must be stored on a **hardware token / cloud HSM** (CA/B rule since 2023). Does **not** instantly clear SmartScreen — reputation still accrues. | Middling value. |
| **EV certificate** | ~$300–600+/yr | Hardware token. **Instant SmartScreen reputation** from first download. | Best UX, highest cost/friction. Only worth it at volume. |

**Recommendation:** unsigned for the first paid release → Azure Trusted Signing once revenue
justifies it. Don't buy EV on day one.

---

## 3. Store / channel options (researched June 2026; ranked: reliability + lowest cost-to-you)

> **Your stated goal:** the *most reliable* way to actually collect earnings with the *lowest
> chance of being out of pocket* ("so I don't lose money"). The analysis below is built around
> that, not around squeezing the last % of margin.

### 3.0 Why, structured right, you literally cannot lose money

The fear is "what if it costs me to run this." Here's why it won't:

- **No fixed/monthly cost on any option below.** Every platform here is **pay-per-sale only** — a
  % of money you actually received. **Zero sales → zero cost.** You are never out of pocket.
- **File hosting is free.** Gumroad / Lemon Squeezy / Paddle / itch.io all **host your installer
  download** — no S3, no bandwidth bill. (GitHub Releases is also free if you ever self-host.)
- **License infra is free.** The Phase 3 plan uses **offline signed keys** (§4) — **no server**,
  no database, no uptime to pay for.
- **The one thing that *could* actually cost you money is tax compliance** (EU VAT registration,
  US sales-tax nexus, fines for getting it wrong). A **Merchant-of-Record (MoR)** platform makes
  that *their* legal problem, not yours. **So: only use an MoR option** (all the recommended ones
  are). Avoid anything where *you* are the seller of record (raw Stripe self-host, itch's "Direct
  to you" mode) for v1.

Net: pick an MoR platform with no fixed fee → your only outflow is a slice of revenue you've
already banked. **Out-of-pocket risk ≈ $0.**

### 3.1 Direct-sale platforms (verified 2026 figures)

| Platform | Fee (2026) | MoR / tax handled? | License keys | Payout | Approval gate | Reliability note |
|---|---|---|---|---|---|---|
| **Gumroad** ✅ | **10% + $0.50** | **Yes — full MoR since Jan 2025** (VAT/GST/US tax remitted for you) | **Built-in** + verify API (`/v2/licenses/verify`) | Weekly (Fri), **$10 min**, free US bank | **None — sign up & sell today** | Established since 2011; simplest, most "just works" for a brand-new solo product. Highest fee is the price of that simplicity. |
| **Lemon Squeezy** | **5% + $0.50** (+1.5% intl) | Yes — MoR, full tax compliance | **Best-in-class** for desktop apps | **~13-day hold** then bank | None (still open) | ⚠️ **Continuity risk:** acquired by Stripe (2024); in 2026 LS + "Stripe Managed Payments" coexist with Stripe steering merchants to **migrate**. Great tooling, uncertain long-term home. |
| **Paddle** | 5% + 50¢ (+FX margin on intl) | Yes — MoR, software-focused | Integrate yourself | Bank | ⚠️ **Manual seller vetting** (KYC/business review) — friction/possible rejection for a tiny new product | Solid but enterprise/subscription-shaped; heavier than v1 needs. |
| **itch.io** | Open share (default 10%) | Only in **"Collected by itch.io"** mode (EU VAT) | Weak/none | Bank/PayPal | None | Indie-friendly but game-oriented; **US devs' note: 30% US withholding unless a tax-treaty form (W-8BEN) is filed**. Fine as a free *secondary mirror*, not the primary store. |

### 3.2 Microsoft Store (MSIX) — not for v1

| Concern | Reality for HoverDeck |
|---|---|
| Dev account | One-time **~$19 individual / ~$99 company** (approx). |
| Packaging | Must convert to **MSIX**. Store-signed → SmartScreen solved automatically. |
| **Policy / sandbox conflicts** | **The dealbreaker.** MSIX runs in a restricted container, and HoverDeck's core behaviors fight it: **global keyboard/mouse capture** (`pynput`), **global hotkeys** (`keyboard`, low-level hooks), **`shell` steps** (`cmd.exe`), **registry autostart** (`HKCU\…\Run`), and **running arbitrary user Python**. Exactly what Store review scrutinizes and AppContainer restricts → high chance of **rejection or broken features**. |
| Effort | High (repackage + sandbox adaptation + review). |

### 3.3 The concrete money comparison (a $15 sale)

Under MoR, the buyer's VAT is added *on top* for the buyer — it doesn't come out of your cut.

| Platform | Fee on $15 | **You keep** |
|---|---|---|
| Gumroad | $1.50 + $0.50 = $2.00 | **~$13.00** |
| Lemon Squeezy | $0.75 + $0.50 = $1.25 (US) | **~$13.75** |

≈ **$0.75/sale** difference. At first-launch volumes, Gumroad's reliability + zero approval gate
outweighs it. The kicker: because Phase 3's keys are **offline-verified and store-agnostic**
(§4), **switching to Lemon Squeezy later to reclaim that 5% is a config change, not a rebuild** —
the store just emails a key string; HoverDeck validates it itself.

### 3.4 Recommendation — **Gumroad for v1**

Most reliable, zero fixed cost, **no approval gate**, full MoR (tax is their problem),
free file hosting, built-in keys, weekly $10-min payouts — and the store choice is **reversible**
thanks to store-agnostic offline keys. Accept the 10% as the cost of "it just works on day one."
**Add/switch to Lemon Squeezy later** if volume makes the 5% worth the continuity risk. Use
**itch.io only as a free secondary mirror** if you want extra discovery. **Skip the Microsoft
Store** until/unless the risky capabilities are sandboxed behind opt-ins.

---

## 4. Licensing / activation (minimal, near-zero infra)

**Recommended: offline signed license keys.**

- You hold an **Ed25519** (or RSA) private key offline. A license key = a short signed token
  (e.g. buyer email/order id + issue date). The app embeds the **public key** and verifies the
  signature **locally, offline** — no server, no phone-home, works on air-gapped machines, and
  **can't be key-genned** without your private key.
- **Issuance:** either (a) generate keys yourself per sale, or (b) let **Gumroad generate the key**
  (verified: built-in per-product license keys + `POST /v2/licenses/verify`) and optionally call
  that endpoint once on activation, then cache a local token. **(a) is zero-infra and the
  recommended default.** Gumroad's *own* online check is easily bypassed (it just returns a JSON
  `success`), which is the very reason the **offline signed-key** design is stronger **and**
  **store-agnostic** — the store only needs to deliver a key string; HoverDeck verifies it itself,
  so you're never locked to one platform.
- **Honest caveat:** any client-side check is ultimately crackable. For a small paid utility, an
  offline signed-key check is the right effort/value ratio — **don't over-invest** in DRM.

**Recommended gating model (was open decision #2):** **one-time purchase + a limited free trial**
(e.g. time-boxed, or AI-Builder-gated until activated), *not* a subscription. Rationale for "most
reliable earnings, lowest cost-to-you": no recurring-billing infra to run, no churn/dunning to
manage, lowest support burden, and a trial lifts conversion by letting buyers feel the deck before
paying. A subscription earns more per user but adds billing complexity and support load that don't
pay off for a single-purchase desktop utility at launch.

**Files this touches (Phase 3):**

| File | Role |
|---|---|
| **NEW** `hoverdeck/security/license.py` | Pure-logic verify (`verify_license(key) -> LicenseInfo | None`), embedded public key. Unit-testable, Qt-free. |
| **NEW** `hoverdeck/ui/dialogs/activate_dialog.py` (or a Settings tab) | Themed "Activate" entry reusing `theme.py` tokens; *Activated ✓* / fault-red on bad key, mirroring the existing Test-connection pattern. |
| `hoverdeck/app.py` | First-run gate: decide **what's gated** (recommend gating the **AI Builder** + a gentle nag, leaving the core deck usable as a trial — or gate the whole app; your call). |
| `tests/test_license.py` | Valid / tampered / expired key cases. |

**Decision needed:** gate the *whole app*, or gate only the *AI Builder* (freemium/trial)? This
shapes the first-run experience — flag it for a later follow-up.

---

## 5. Pre-ship checklist (must be true before selling)

| ✓/⚠️/❌ | Item | Finding & action |
|---|---|---|
| ✅ | **No bundled secrets** | Verified: 0 key matches; `settings.json` git-ignored; CI injects nothing. Keep a CI guard that fails the build if a key pattern appears. |
| ⚠️ | **Key at rest** | Plaintext in `settings.json` → **Phase 1** (encrypt at rest). |
| ✅ | **Global crash handling** | **DONE (Phase 2).** `app.py` installs a `sys.excepthook` that logs the full traceback (`critical`, `exc_info`) to `hoverdeck.log` and, on the GUI thread, shows a one-line `QMessageBox.critical` pointing at the log; `KeyboardInterrupt` passes through; the handler never re-raises. Needs a real on-Windows crash test to confirm the dialog path. |
| ✅ | **Version single-source** | **DONE (Phase 2).** `hoverdeck/__init__.__version__` (`0.4.0`, what the About tab reads, bundle-safe) is now canonical; `pyproject.toml` derives it via `[tool.setuptools.dynamic] version = {attr = "hoverdeck.__version__"}` so it can't drift. `VERSION` file matches. **Residual:** keep the git release tag == `__version__` (and mirror/retire `VERSION`); optional CI guard — not done (avoids touching packaging without sign-off). |
| ⚠️ | **EULA / license terms** | README + pyproject say *"Private project."* A paid product needs real **license terms / EULA** (and a refund policy on the store page). |
| ⚠️ | **Publisher identity** | `.iss` `MyAppPublisher = "HoverDeck"`. Set a real publisher/legal name (also required later for signing). |
| ✅ | **First-run experience** | Good: `settings_store` writes defaults on first run; empty deck with *+ Add a key*; AI degrades gracefully without a key. Vault note: *the first PIN entered becomes the code* — make sure store copy doesn't over-explain the hidden vault (by design, `PLAN.md §4.4`). |
| ⚠️ | **Update path** | Today: manual download from GitHub Releases; clean in-place upgrade thanks to the stable Inno `AppId`. **Cheap add:** an in-app "check for updates" that reads a static version JSON (or the GitHub Releases API) and links to the download — no auto-updater needed. Gumroad can also email buyers on new versions. |
| ⚠️ | **AV false positives** | PyInstaller one-file risk. Prefer the **installer** as primary; submit false-positive reports to Microsoft/vendors if flagged. |
| ✅ | **Privacy note** | **DONE (Phase 2).** Added a **Privacy** section to `README.md` (local-only data, no telemetry, BYO-key sent only to the chosen provider, run-only-what-you-trust note); the two inline AI-key mentions now say "encrypted on your machine." Still **TODO at sell time:** mirror this onto the store page. |

### Privacy note (draft — for store page + in-app About)

> HoverDeck stores everything locally in `%APPDATA%\HoverDeck`: your decks, recorded macros,
> settings, and the encrypted vault. **No telemetry, no analytics, no account.** The only data
> that leaves your machine is what you type into the **AI Builder**, which is sent **only to the
> AI provider you choose** (Anthropic or OpenAI) using **your own API key**. Recorded macros, the
> vault, and your scripts never leave your computer. Note: keys run **scripts and shell commands
> you create**, so only run automations you trust.

---

## 6. Phased roadmap (each phase = a vertical slice)

> Phase 1 is front-loaded per the brief. Reality check: it is **hardening**, not a blocker — the
> app is already BYO-key with no bundled secret — but it's the right first slice for a paid product.

### Phase 1 — BYO-key hardening — ✅ DONE *(implemented + verified on Linux; uncommitted)*
Encrypt the user's key at rest (DPAPI via the `utils/win.py` seam), validate on entry, migrate any
existing plaintext key, update copy. Files: §1.3.
**Done when:** the key is **never written in plaintext** to `settings.json`; a pre-existing
plaintext key is migrated and the JSON field blanked; "Test connection" still works; the no-key
state still degrades gracefully; `tests/test_secret_store.py` passes in CI; **no visual change** to
the AI Builder tab beyond copy.

### Phase 2 — Release hygiene & trust — ✅ DONE *(EULA text + publisher name pending your input)*
Add `sys.excepthook` → log + themed error; unify the version source; add EULA + publisher name;
add the in-app privacy line; document/mitigate AV false positives.
**Done when:** an unhandled exception lands in `hoverdeck.log` and shows a one-line themed message
instead of dying silently; `pyproject`, `VERSION`, installer, and About all report the **same**
version; EULA + publisher present; privacy note shipped.

### Phase 3 — Licensing / activation *(~1 day)*
`security/license.py` (offline Ed25519 verify, embedded public key) + a themed Activate flow +
the chosen gating policy. Files: §4.
**Done when:** an unactivated install shows the agreed gated state; a valid key activates and
persists; a tampered/expired key is rejected; activation works **offline**; `tests/test_license.py`
passes.

### Phase 4 — Sales channel live *(~0.5 day, mostly non-code)*
Create the Gumroad product, wire its license-key issuance to the Phase 3 verifier, upload the
installer (+ portable exe), write store copy + privacy note + refund policy, do a real test
purchase.
**Done when:** a test purchase yields a working license key and a downloadable installer that
activates end-to-end.

### Phase 5 — Polish (optional, post-launch)
Azure Trusted Signing in CI (kills SmartScreen friction); in-app update check; store-listing
screenshots/GIF (already have `docs/screenshots/`).
**Done when:** signed builds verify on Windows and/or the app surfaces "an update is available."

---

## 7. Decisions — resolved (2026-06-30)

1. **Key-at-rest mechanism:** ✅ **RESOLVED → Option A** (OS secret store / **Windows DPAPI** via
   the `utils/win.py` seam). *(Phase 1)*
2. **Gating model:** ✅ **RESOLVED via research → one-time purchase + limited free trial** (not a
   subscription); see §4. Sub-decision still open: trial is *time-boxed* vs *AI-Builder-gated* —
   pin down during Phase 3 first-run design.
3. **Store choice:** ✅ **RESOLVED via research → Gumroad for v1**, store-agnostic offline keys keep
   it reversible; Lemon Squeezy as the later fee-optimization, itch.io as an optional free mirror.
   See §3.4. *(Phase 4)*

**Next action:** all three decisions are settled — Phase 1 (DPAPI key-at-rest hardening) is
unblocked and ready to implement on your go.
