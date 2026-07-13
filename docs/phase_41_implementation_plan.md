# Jarvis — Phase 41 Implementation Plan

**Phase title:** Voice Interface Planning + Voice Output/Input Foundation
**Classification:** Very risky — planning + 3+ batches
**Baseline:** branch `phase-4-ai-reasoning-and-write-actions`, HEAD `984edfc`, full suite 3323 passed / 3 skipped / 0 failed
**Status:** planning complete; Nathan has recorded temporary selected defaults for several of the decisions below (see the section immediately following this header) — these are explicitly changeable, before or during implementation, and do not close off any option. **Batch 1 (TTS foundation) is complete. Batch 2 (opt-in CLI voice-output wiring + config) is complete. Batch 3 (STT foundation) is complete. Batch 4 (fake-provider-only CLI voice input routing + adversarial approval-bypass proof, no microphone, no real push-to-talk) is complete. Batch 5 (push-to-talk trigger design review — no code, no audio, review only) is now also complete** — see Section 12 for exactly what was delivered in each and what remains for later batches, and Section 14 for the Batch 5 design review itself. Phase 41 has not closed yet - no completion report exists, and real push-to-talk implementation/audio-capture-shape decisions remain future work.

---

## Nathan's Temporary Selected Defaults (recorded, changeable later)

Nathan has made the following **temporary** decisions to unblock planning and give the eventual implementation batches a concrete starting point. Every one of these can still be changed later — before implementation begins, during any batch, or after seeing/hearing a real result — exactly like any other decision in this project. Nothing below is final or irreversible; recording a temporary default is not the same as closing the underlying decision in Section 3, which remains there in full for future reference if any of these change.

| # | Decision | Nathan's temporary default | Changeable? |
|---|---|---|---|
| 1 | Voice gender/style | **Female voice.** | Yes — at any time. |
| 2 | Voice personality/style | **Calm, smart, clean Jarvis-style assistant voice.** Not too robotic. Not overly emotional. Not comedy/cartoon style. | Yes — this is a feel/character description, not a locked engine choice. |
| 3 | Cost/provider preference | **Try free/local options first.** Paid/cloud options may be considered later, only if local/free quality turns out to be poor. | Yes — this is an ordering preference (try free first), not a permanent ban on paid/cloud. |
| 4 | First implementation direction | **Voice output only first.** Jarvis should be able to speak responses before any microphone input exists. | Yes. |
| 5 | Speak mode | **Opt-in first.** Do not speak every response by default. A future setting or command will control when Jarvis speaks. | Yes. |
| 6 | Microphone (Batch 1) | **No microphone in Batch 1. No speech-to-text in Batch 1. No listening behavior yet.** | Yes — this is a Batch 1 scope boundary, not a permanent rule against microphone input later. |
| 7 | Future input mode | **Push-to-talk should be the first speech-to-text input mode**, once STT work begins in a later batch. | Yes. |
| 8 | Always-listening / wake word | **Explicitly deferred.** Will not be built in any Phase 41 implementation batch. | Yes — only in the sense that it remains eligible for its own separate future review; it is not being built now regardless. |
| 9 | Scope | **CLI only first.** No dashboard voice controls. No phone integration. No Core service. | Yes. |

These nine temporary defaults are consistent with, and now confirm, nearly all of this plan's own safest-recommendation guidance in Section 3 and its overall recommended path in Section 4 — see the per-item updates below for exactly how each one maps onto the original decision checklist.

**What remains genuinely open** (not yet given even a temporary default by Nathan): whether voice settings should be persisted in `.env`/config the same way every other Jarvis setting is today (Section 3.11), and the specific engine/provider actually chosen once Section 6/7's research happens at implementation time. See the updated Section 13 for the current, shorter list of open questions.

---

## 1. Purpose

Voice is being considered now for one reason: Nathan has explicitly asked for it, for the first time in this project's history. Every other candidate direction evaluated in the last several architectural reviews (scheduler schema work, Inbox integration for webpage summaries, empty-trash, dashboard write actions, a health-check tool) remains exactly as speculative or blocked as before, with no new evidence. Voice is different — it has a genuine, fresh forcing function: Nathan's own stated interest, plus a clear list of decisions he wants to make himself before anything is built.

This phase is planning-only because voice would be the first entirely new interaction modality Jarvis has ever had. Every capability built across the previous 40 phases started from an explicit, typed, text request; voice introduces a live microphone, a wake/trigger question, a new class of third-party dependency, and — critically — a new question about how much trust to extend to text that arrived via a transcription step rather than a keyboard. None of that should be decided by assumption. This document exists to lay out the real options, their tradeoffs, and this project's own safety reasoning, so Nathan can make each of the decisions in Section 3 deliberately, the same way every other phase boundary in this project has been decided by explicit, informed choice rather than default.

Nothing in this document is a commitment. No dependency has been installed, no code has been written, and no final choice has been made on Nathan's behalf anywhere in this plan.

---

## 2. Current Repository State

Verified directly against the repository at commit `984edfc` before writing this plan:

- **No voice code exists anywhere.** A repository-wide search for `voice`, `speech`, `microphone`, `whisper`, `tts`, `stt` (case-insensitive, `.py` files only) returns exactly three hits, all of them explicit *non-goal* statements in docstrings:
  - `core/orchestrator.py`: "Does NOT: ... Implement autonomous behaviour, voice, phone, or UI."
  - `main.py`: "...add voice or phone support" (listed as something this module does not do).
  - `ui/cli.py`: "Does NOT: Call the Claude API, add voice, or add phone support."
  There is no scaffolding, no stub module, no partially-built voice code of any kind.
- **No TTS/STT/audio dependency exists.** `pyproject.toml`'s full dependency list is: `anthropic`, `sqlalchemy`, `pydantic`, `python-dotenv`, `duckduckgo-search`, `httpx` (plus `pytest`/`black`/`ruff` as dev dependencies). Nothing audio-related is present, directly or transitively.
- **Current CLI entry point**: `main.py` builds the orchestrator and hands control to `JarvisCLI` (`ui/cli.py`), a thin, synchronous, text-in/text-out read-eval-print loop. It reads one line of typed input at a time, calls `JarvisOrchestrator.handle_request()`, prints the formatted result, and (for YELLOW actions) prompts for an approve/decline decision via `ui/approval_prompt.py`. It is explicitly documented as not calling any AI provider, voice, or phone support itself — all risk decisions are made by the Security Manager and Approval Manager, never the CLI layer.
- **Current dashboard state**: `dashboard.py` is a separate local process (tkinter/ttk, via `ui/dashboard_app.py`) that shares only the SQLite database file with the CLI process — no IPC, no socket, no shared Python objects. It is strictly read-only across all seven tabs (Overview, Memories, Approval History, Workflow History, Inbox, Schedules, Quarantine); the only interactive control in the entire window is a single "Refresh now" button, confirmed structurally by an existing test that counts every `ttk.Button` in the window and asserts there is exactly one.
- **Current SecurityManager/approval model**: `SecurityManager.classify_action()` is a single, ordered, keyword-substring matcher over a fixed rule table (currently 63 rules) that classifies any action string into GREEN (runs immediately), YELLOW (requires an explicit approve/decline decision via `ApprovalManager` before `ToolExecutor` will run it), or RED (blocked outright, no approval can override it). This classification is completely input-modality-agnostic today — it operates on a plain Python string produced by `CommandRouter`/`Planner`, with no concept of whether that string arrived by keyboard, file, or (in the future) transcription. This matters directly for voice: nothing about this model needs to change to support voice-originated commands, provided transcribed text is fed into exactly the same string-in path typed text already uses (see Section 8).
- **Current non-goals around voice/phone/Core service/autonomous behavior**: repeated verbatim across nearly every phase's instructions and multiple module docstrings throughout the project's history (`core/orchestrator.py`, `main.py`, `ui/cli.py`, and the standing rules given at the start of every recent phase). No phase has ever built toward any of these; this plan does not change that.
- **A prior, more ambitious vision exists in `docs/JARVIS_PROJECT_MASTER_SPECIFICATION_V2_1.md`, Chapter 14 ("Voice & Communication System").** This is a historical, aspirational specification document, not a record of decisions already made about *this* incremental build — the actual Jarvis codebase has consistently implemented a much narrower, more conservative subset of that specification's larger vision (no Android client, no Core-as-a-service, no computer-control system, no plugin architecture exist today either). That said, it contains genuinely useful prior notes worth carrying into this plan, and Nathan's instruction was explicit: if prior notes mention a female-voice preference, record it as a *known preference*, not a decision made for him. The specification states:
  - **Design philosophy**: "The voice system translates. The brain decides." — voice input/output is meant to sit alongside the decision-making core, never replace or bypass it. This is fully consistent with, and does not require any change to, the current `CommandRouter → SecurityManager → ApprovalManager → ToolExecutor` pipeline.
  - **Wake word (Phase 1 candidate)**: OpenWakeWord (free, local, Python), with Porcupine (Picovoice) named as a possible more-accurate upgrade with a free tier.
  - **STT (Phase 1 candidate)**: faster-whisper with the `medium.en` model (free, local, offline), with Deepgram or AssemblyAI named as possible cloud upgrades for noisy-environment accuracy.
  - **TTS (Phase 1 candidate)**: Kokoro-82M, described as a "natural-sounding **female voice**" (free, local, offline), with ElevenLabs or Azure Neural TTS named as possible premium/cloud upgrades.
  - **Stated voice requirements**: female voice with natural cadence; offline/local support; replaceable STT/TTS providers; low latency (target under 2 seconds from speech end to response start); interruptible responses (live speech cancels in-progress TTS output).
  - **Already-considered failure modes**: a missed wake word simply continues listening silently (no error); an STT failure asks the user to repeat and falls back to text input; a TTS failure returns the response as text only, logs the failure, and continues without voice; high background noise lowering STT confidence should trigger a confirmation request before acting on the transcription, rather than acting on a guess.

  **This is recorded here as a known, previously-documented preference and a source of genuinely useful prior design thinking — not as a decision.** Nathan still chooses the final voice, provider, and every other item in Section 3. Where this plan's own recommendations differ from the specification's original vision (most notably: starting with push-to-talk rather than an always-on wake word — see Section 4), that difference is called out explicitly and explained, not silently overridden.

---

## 3. Nathan Decision Checklist

For each item: the real options, their tradeoffs, this plan's safest recommendation, and what Nathan must actually decide. **No item below is marked as a final choice** — each is an open question until Nathan answers it.

### 3.1 Voice style
- **Options**: a natural/conversational cadence; a more formal/assistant-like cadence; an accent/character preference (e.g. the specification's own historical "Jarvis-style" framing); no strong preference (default to whatever the chosen engine sounds like out of the box).
- **Tradeoffs**: a distinctive style may require a specific engine/provider (narrowing later options); no preference keeps every provider option open longest.
- **Safest recommendation**: decide this loosely for now (a general feel, not a specific engine), and finalize the exact voice only after Section 6's research narrows which engines can actually deliver it.
- **What Nathan must choose**: whether he has a specific style/character in mind, or wants to hear a few real samples before deciding.
- **Nathan's temporary selection (changeable later)**: a calm, smart, clean Jarvis-style assistant voice — explicitly **not** too robotic, **not** overly emotional, and **not** comedy/cartoon style. This is a feel/character description to guide engine selection at implementation time, not a locked-in specific engine — the exact voice is still chosen only after hearing real samples against this description.

### 3.2 Male / female voice
- **Options**: female, male, either (no preference), or "decide after hearing samples."
- **Tradeoffs**: none technically — essentially every TTS option researched in Section 6 offers both. This is purely a preference question.
- **Known prior note**: the Master Specification (Chapter 14, "Voice Requirements") explicitly states "Female voice with natural cadence" and names Kokoro-82M specifically for its female voice. This is recorded as Nathan's own previously-documented preference, not assumed as final.
- **Safest recommendation**: none needed — this is a pure preference call.
- **What Nathan must choose**: confirm whether the female-voice preference above still stands, or has changed.
- **Nathan's temporary selection (changeable later)**: **female voice** — confirming the prior documented preference noted above. Still changeable at any time, including after hearing real candidate voices.

### 3.3 Local vs. cloud TTS
- **Options**: fully local/offline (no network call, no per-use cost, audio never leaves the machine); cloud API (typically higher quality, costs money or has a free tier, requires network and an API key, sends response text to a third party).
- **Tradeoffs**: local keeps everything private and free but is more work to set up and generally sounds less natural; cloud sounds better with less engineering effort but means Jarvis's spoken responses (which may include memory content, file paths, or other personal information) leave the machine.
- **Safest recommendation**: start local/offline for the first working version — it has zero privacy exposure and zero recurring cost, and proves the TTS integration path (Section 5) works before deciding whether the quality tradeoff is worth a cloud dependency.
- **What Nathan must choose**: whether privacy/cost (favoring local) or voice quality (favoring cloud) matters more to him for the first version.
- **Nathan's temporary selection (changeable later)**: **try free/local options first.** Paid/cloud TTS may be considered later, but only if local/free quality turns out to be poor — this is an ordering preference, not a permanent ban on cloud TTS.

### 3.4 Free vs. paid TTS
- **Options**: fully free (local model or a free-tier cloud API); paid (a premium cloud voice API, ongoing per-character or per-minute cost).
- **Tradeoffs**: free options exist and are usable (see Section 6); paid options generally sound more natural and offer more voice choices, at a real recurring cost tied to usage.
- **Safest recommendation**: prove the feature works and is actually used before paying for anything.
- **What Nathan must choose**: whether he's willing to pay for TTS quality now, or wants to validate the feature free first.
- **Nathan's temporary selection (changeable later)**: **free/local first**, same as 3.3 — paid only considered later if free/local quality proves poor.

### 3.5 Local vs. cloud STT
- **Options**: fully local/offline transcription (private, free, requires more setup and a capable-enough machine); cloud API (typically more accurate, especially in noisy conditions, sends recorded audio to a third party, costs money or has a free tier).
- **Tradeoffs**: local keeps Nathan's spoken words (which could include anything he says near the microphone) off the network entirely; cloud is generally more accurate but means raw audio recordings leave the machine.
- **Safest recommendation**: local/offline first, for the same privacy-first reasoning as TTS — and because STT only matters once push-to-talk input is actually being built (a later batch), not for this planning phase.
- **What Nathan must choose**: same privacy-vs-accuracy tradeoff as 3.3, specifically for audio leaving the machine (a more sensitive case than text).
- **Nathan's temporary selection (changeable later)**: **free/local first**, matching the same overall preference as TTS above — applies once STT work actually begins in a later batch (not Batch 1).

### 3.6 Free vs. paid STT
- **Options**: free (local model or free-tier cloud API); paid (a premium cloud STT API with better accuracy, especially in noisy environments).
- **Tradeoffs**: same shape as 3.4 — paid usually means better accuracy, at a real ongoing cost.
- **Safest recommendation**: free first, matching 3.4's reasoning.
- **What Nathan must choose**: same as 3.4, for STT specifically.
- **Nathan's temporary selection (changeable later)**: **free/local first**, same reasoning as 3.4, deferred until STT work begins.

### 3.7 Voice output only vs. input + output
- **Options**: (a) Jarvis can speak its responses, but Nathan still types everything (no microphone at all); (b) full two-way — Jarvis speaks, and Nathan can also speak commands.
- **Tradeoffs**: output-only has zero microphone/privacy exposure and is far simpler to build and test (see Section 4); input adds real complexity — recording, transcription accuracy, and the trust-model questions in Section 8.
- **Safest recommendation**: output only for the first implementation batch. This lets Jarvis's voice be evaluated and enjoyed immediately, while the harder and more sensitive microphone question is deferred to its own later, separately-considered batch.
- **What Nathan must choose**: confirm output-only is an acceptable and useful first version on its own, before microphone input is ever built.
- **Nathan's temporary selection (changeable later)**: **(a) voice output only first.** Jarvis should be able to speak responses before any microphone input exists. No microphone and no speech-to-text in Batch 1 — confirmed explicitly.

### 3.8 Typed-command-triggered speech vs. push-to-talk vs. always-listening
- **Options**: (a) typed-command-triggered — Nathan types a normal command, and Jarvis's *response* is spoken (this only concerns output, not input); (b) push-to-talk — Nathan explicitly triggers a recording window (e.g. a hotkey or a typed "listen" command), speaks, and that transcription is treated as a single request, exactly like a typed one; (c) always-listening/wake-word — Jarvis continuously monitors the microphone in the background for a wake phrase, with no explicit per-use trigger.
- **Tradeoffs**: (a) has no privacy exposure at all since there is no microphone involved. (b) is bounded and explicit — the microphone is only ever active for a short, Nathan-initiated window, consistent with how every other Jarvis action has always started from an explicit request. (c) is a fundamentally different commitment: a continuously-active microphone, running indefinitely in the background, is a categorically larger privacy and trust surface than anything this project has built, and arguably sits in tension with this project's own repeated "no autonomous behavior" discipline, since a system perpetually listening for a trigger is itself operating autonomously in the background even before any command is spoken.
- **Safest recommendation**: (a) first (output only, no microphone), then (b) push-to-talk as the *only* input mode built initially. (c) always-listening/wake-word should be explicitly deferred, and only reconsidered later with its own dedicated safety review — not folded into this phase's implementation batches. See Section 4 for the full reasoning.
- **What Nathan must choose**: confirm push-to-talk (not always-listening) as the first — and, for now, only — input trigger mode.
- **Nathan's temporary selection (changeable later)**: **(a) first, then (b).** Voice output (no trigger needed beyond opt-in, per 3.9/3.10) comes first with no microphone at all. **Push-to-talk is confirmed as the first speech-to-text input mode**, once STT work begins in a later batch. **(c) always-listening/wake-word is explicitly deferred** — it will not be built in any Phase 41 implementation batch, and remains eligible only for its own separate future review.

### 3.9 Speak every response, or only selected responses
- **Options**: (a) every response is spoken automatically once voice output is enabled; (b) only responses to certain kinds of requests are spoken (e.g. only GREEN/read-only responses, never YELLOW approval prompts or sensitive content); (c) speech is opt-in per request (e.g. a distinct command form, or a toggle Nathan flips on/off as needed).
- **Tradeoffs**: (a) is simplest to build but could end up reading long file contents, memory dumps, or other bulky/sensitive text aloud without Nathan wanting that. (b)/(c) require a rule for what counts as "speakable," adding a small amount of design complexity but giving Nathan control over what's actually spoken.
- **Safest recommendation**: make it Nathan's explicit choice per session (a simple on/off setting, defaulting off — see 3.10) rather than silently deciding which responses "deserve" to be spoken; keep the speak/don't-speak decision itself dumb and uniform (whatever is enabled, speak it) rather than inventing a new classification system alongside `SecurityManager`.
- **What Nathan must choose**: whether he wants an all-or-nothing toggle, or finer-grained control over which responses get spoken.
- **Nathan's temporary selection (changeable later)**: **opt-in, not every response by default.** A future setting or command will control when Jarvis actually speaks — the exact shape of that control (all-or-nothing toggle vs. finer-grained) is still open and can be decided at implementation time.

### 3.10 Enabled by default, or opt-in
- **Options**: (a) voice output is on by default once built; (b) off by default, Nathan turns it on explicitly (a setting or a session flag).
- **Tradeoffs**: default-on could surprise or annoy Nathan (or anyone else in the room) the first time it's run after an update; opt-in requires one extra step but means voice never activates unless Nathan asks for it.
- **Safest recommendation**: opt-in, off by default — consistent with `AI_REASONING_ENABLED` already defaulting to `False` in this exact codebase (Jarvis runs in a fully safe, minimal mode until a capability is explicitly turned on).
- **What Nathan must choose**: confirm opt-in/off-by-default, or state a preference for on-by-default.
- **Nathan's temporary selection (changeable later)**: **(b) opt-in, off by default** — confirmed, matching this plan's own safest recommendation and this codebase's existing `AI_REASONING_ENABLED` precedent.

### 3.11 Should voice settings be saved in config
- **Options**: (a) yes, persisted the same way every other setting is today, via `.env`/`config/settings.py`'s `Settings` dataclass (e.g. `VOICE_ENABLED`, `VOICE_TTS_PROVIDER`, `VOICE_STT_PROVIDER`, `VOICE_SPEAK_MODE`); (b) session-only, reset every time Jarvis restarts; (c) some mix (e.g. provider choice persisted, on/off toggle session-only).
- **Tradeoffs**: (a) matches this codebase's own established pattern exactly (`Settings` is a frozen dataclass loaded once at startup from environment variables, validated and typed, with `ConfigTool` already able to report a setting's status — never its secret value — without exposing anything sensitive); (b) is simpler but means Nathan re-enables voice every session.
- **Safest recommendation**: persist provider/style choices in config (matching every other setting in this project), but keep the strongest safety-relevant behavior (whether voice is *active* right now) an explicit, visible state Nathan can always see — e.g. via an extended `show config` output — never a hidden background flag.
- **What Nathan must choose**: confirm config-file persistence is wanted, and whether `ConfigTool`/`show config` should be the place voice settings show up (see Section 9).
- **Nathan's temporary selection**: **not yet decided.** This remains the one genuinely open item from the original checklist — Nathan has not yet given even a temporary default here. See Section 13.

### 3.12 CLI only first, or also dashboard/other surfaces
- **Options**: (a) CLI only for the first version; (b) also wire into the dashboard somehow; (c) also wire into some future surface (phone, etc.).
- **Tradeoffs**: (b) and (c) are both explicit standing non-goals today (dashboard write actions and phone integration are both out of scope, repeatedly, across many phases) and would require their own separate review even if voice itself is approved.
- **Safest recommendation**: CLI only. The dashboard remains strictly read-only (Section 5); voice output/input has no reason to touch it, and doing so would conflate two separately-scoped decisions.
- **What Nathan must choose**: confirm CLI-only is the intended first scope (this plan assumes yes unless told otherwise).
- **Nathan's temporary selection (changeable later)**: **(a) CLI only first — confirmed.** No dashboard voice controls, no phone integration, no Core service.

---

## 4. Recommended Safe Implementation Path

**Planning first** (this document) → **Batch 1: TTS output only** → **Batch 2: opt-in speak setting/config** → **Batch 3: push-to-talk STT input** → **always-listening/wake-word explicitly deferred to a separate future review.**

**This path is now confirmed by Nathan's own temporary decisions** (see the summary section near the top of this document): voice output only first, no microphone/STT in Batch 1, opt-in speak mode, push-to-talk as the first future input mode, and always-listening/wake-word explicitly deferred — all match this plan's own safest-recommendation reasoning below exactly. The reasoning is retained in full for future reference (e.g. if any temporary decision changes before implementation).

**Why TTS before STT:** text-to-speech only ever *consumes* text Jarvis already produced and already fully trusts — it introduces no new input source, no new trust question, and no microphone. It can be built, tested, and even disabled entirely (falling back to text-only output) with zero risk to the security/approval model. Speech-to-text is the opposite: it's a new *input* channel whose output — a transcribed string — must be decided how much to trust before a single line of code routes it toward `CommandRouter`. Building output first proves the simpler half of the pipeline (provider integration, config, graceful failure) works, before tackling the harder, more sensitive half.

**Why push-to-talk before always-listening:** push-to-talk is bounded and explicit — the microphone is active only for a short window Nathan personally starts, exactly mirroring how every single existing Jarvis command already starts from an explicit, typed request. It requires no new background process and no continuous audio capture. Always-listening requires a perpetually-running microphone listener — a fundamentally different privacy commitment (audio is being captured continuously, not just when asked for) and a fundamentally different reliability question (a wake-word detector can misfire, or fail to catch a real wake attempt, in ways a single bounded recording window never has to handle).

**Why always-listening/wake-word should be deferred, not just sequenced later:** it is not simply "the next increment" after push-to-talk — it changes the shape of the problem. It requires a new, continuously-running background component (something this project has never built for any capability, including scheduling, which only runs as a distinct opt-in process Nathan starts himself); it raises the standing "no autonomous behavior" non-goal directly, since a system that is always listening is, in a real sense, always doing something in the background without being asked; and it deserves its own dedicated safety review once push-to-talk voice has actually been used and evaluated — not a decision folded into this plan's batch sequence by default.

---

## 5. Architecture Options

| Option | Description | Verdict for v1 |
|---|---|---|
| **CLI-side local voice feature** | TTS/STT logic lives inside (or alongside) `ui/cli.py`, called synchronously from the existing read-eval-print loop — speak a response after printing it; for push-to-talk, record/transcribe audio to produce the string that's handed to `handle_request()` exactly like typed input is today. No new process, no IPC. | **Recommended.** Matches this project's entire architecture: `JarvisCLI` already is the presentation layer that turns input into an `orchestrator.handle_request()` call and turns a response into printed output; voice is simply a second way to produce/consume that same text. |
| **Separate local voice module** | A dedicated `voice/` package (mirroring `web/`'s own precedent as a self-contained, structurally-isolated foundation) holding the TTS/STT provider abstractions, imported by `ui/cli.py` but with no dependency in the other direction. | **Compatible with, and likely combined with, the option above.** This is really a packaging/isolation choice, not a competing architecture — `web/`'s own structural-import tests (proving it imports nothing from `ai/`, `core/`, `tools/`, etc.) are a good precedent for a future `voice/` package to follow. |
| **Core service / multi-client architecture** | A standalone, always-running background process serving the CLI, dashboard, and any future client (phone, etc.) over some IPC/network boundary, with voice as one channel into it. | **Not needed for v1, and not recommended.** This is the master specification's "Jarvis Core" concept realized as an actual network service — a much larger, separately-scoped architectural change this project has repeatedly deferred (it would need its own dedicated review of authentication, process lifecycle, and failure isolation, none of which voice specifically requires). Note: the master specification's own "Jarvis Core" is conceptually already implemented today as `core/orchestrator.py`'s in-process `JarvisOrchestrator` — voice input/output can plug into that exactly the way typed CLI input already does, with no new service required. |
| **Dashboard voice integration** | Wiring voice controls (speak button, listen button, etc.) into `ui/dashboard_app.py`. | **Explicitly rejected for v1.** The dashboard has been strictly read-only since Phase 19, verified structurally by a test asserting exactly one button exists in the entire window. Adding any voice control there is a dashboard write action — a separate standing non-goal, unrelated to whether voice itself is approved. |

**Why v1 should avoid a Core service and dashboard integration**: both would conflate two independent decisions — "should Jarvis have voice" and "should Jarvis's architecture change to a multi-client service" / "should the dashboard stop being read-only." Neither of those larger questions has any new evidence or forcing function today; voice can be fully realized as a CLI-side feature without either.

---

## 6. TTS Options to Evaluate Later

*Nothing below has been installed, tested, or verified against current pricing/licensing/availability — these are categories and illustrative examples to research fresh at implementation time, not commitments.*

| Category | Example(s) (to verify at build time) | Quality | Cost | Privacy | Setup complexity | Windows compatibility | Testability |
|---|---|---|---|---|---|---|---|
| **Local offline TTS** | Kokoro-82M (named in the Master Specification, female voice) | Good for a local model; generally below top cloud quality | Free | Best — audio never leaves the machine | Higher — requires downloading/running a local model, likely a GPU/CPU trade-off to research | To verify — local ML model tooling on Windows can require extra setup (Python environment, model weights, possibly `torch` or an ONNX runtime) | Easy to fake/mock in tests since it's just a Python call; real-engine tests would need to run only where the model is actually installed |
| **OS-provided TTS** | Windows SAPI5 (accessible from Python via packages such as `pyttsx3` or direct COM access) | Adequate, dated-sounding compared to modern neural voices | Free (built into Windows) | Best — fully local, no network, no model download | Lowest — already present on the target Windows machine | Native — this is a Windows-first project already | Easy to fake in tests; real calls only meaningful on Windows with SAPI voices installed |
| **Cloud TTS API** | Azure Neural TTS (named in the Master Specification) or a comparable provider | High — modern neural cloud voices | Free tier + paid usage beyond it | Response text leaves the machine to a third party | Low-to-moderate — an API key and a network call | Fine — any HTTP client works cross-platform | Must be faked in tests (no real network calls in the test suite, matching this project's own standing testing discipline) |
| **Paid premium voice API** | ElevenLabs (named in the Master Specification) or a comparable premium provider | Highest — most natural-sounding premium voices, widest voice selection | Paid, usage-based, no meaningful free tier for extended use | Same as cloud TTS above | Low-to-moderate | Fine | Same as cloud TTS above |

---

## 7. STT Options to Evaluate Later

*Same caveat as Section 6 — categories and illustrative examples only, nothing installed or verified yet.*

| Category | Example(s) (to verify at build time) | Accuracy | Cost | Privacy | Latency | Microphone requirements | Windows compatibility | Testability |
|---|---|---|---|---|---|---|---|---|
| **Local offline STT** | faster-whisper, `medium.en` model (named in the Master Specification) | Good-to-strong for English | Free | Best — audio never leaves the machine | Depends on CPU/GPU; a `medium` model is heavier than `small`/`base` | Standard microphone input via a Python audio library (e.g. `sounddevice`/`pyaudio`) | To verify — works on Windows, but the audio-capture library choice matters | Easy to fake with a pre-recorded/fixed transcription result; real-engine tests need real audio fixtures |
| **OS-provided speech recognition** | Windows Speech Recognition / the Windows Speech API | Adequate, but historically less accurate than modern neural STT | Free (built into Windows) | Best — fully local | Generally fast | Needs a working microphone and Windows's own speech recognition set up | Native to Windows | Same as above |
| **Cloud STT API** | Deepgram or AssemblyAI (both named in the Master Specification) | High, often noticeably better in noisy environments | Free tier + paid usage beyond it | Recorded audio leaves the machine to a third party — the most privacy-sensitive option here, since it's raw audio, not just text | Network-dependent | Same local microphone capture, then an upload step | Fine, cross-platform | Must be faked in tests; no real network/audio in the suite |
| **Paid premium STT API** | A premium tier of the above, or a comparable provider | Highest available accuracy | Paid, usage-based | Same as cloud STT above | Network-dependent | Same as above | Fine | Same as above |

---

## 8. Security and Trust Model

**Update: the core claim below - that a transcription is classified and approval-gated identically to typed text, with no voice-specific bypass - is no longer just a design intention. It is now proven by Batch 4's adversarial test suite** (`tests/unit/test_cli.py`): a real `FileCreateTool` + real `ApprovalManager` registered, a fake transcription of a YELLOW-shaped command requiring approval, creating no file until a decision is made, a denied/timed-out decision leaving no file, an approved decision executing normally, and the same command text producing an identical `security_tier` whether typed or transcribed. `voice/input.py` is structurally re-confirmed to import none of `ToolExecutor`/`ApprovalManager`/`CommandRouter` directly.

- **Microphone privacy risk**: any input mode involving a live microphone is a materially different privacy commitment than anything Jarvis has done before — a keyboard only sends Jarvis what Nathan chooses to type, but a microphone (even push-to-talk) could capture ambient sound, other voices in the room, or a slip of the tongue before Nathan can stop the recording. Push-to-talk bounds this to a short, explicit, Nathan-initiated window; always-listening does not bound it at all, which is the central reason it's deferred (Section 4).
- **Should audio capture itself be classified GREEN/YELLOW/RED?** This is an open design question for the implementation batch, not resolved here — but this plan's recommendation is that *starting* a bounded, push-to-talk recording is a low-risk, Nathan-initiated action (arguably GREEN, similar to `read file` — it doesn't change any state), while what happens *after* transcription (i.e., whatever command the transcribed text resolves to) is classified exactly the same way it already would be if typed — a transcribed `"delete file notes.txt"` must still hit the exact same YELLOW `SecurityManager` rule a typed one does. The recording action and the resulting command's classification are two separate questions; only the second one matters for approval-gating, and it already works correctly today for any string, regardless of its origin.
- **Should transcribed speech be treated exactly like typed live input, or tracked separately?** This plan's recommendation: treated identically, for the purpose of executing commands — a transcribed string, once produced, should flow into `CommandRouter.match()`/`build_input()` exactly like a typed one, with no special-cased trust bump or penalty. The one place transcription *should* be visibly distinguished is in any audit/log trail (so a future review of approval history can tell "Nathan typed this" apart from "Nathan said this, transcribed as this"), matching this project's existing discipline of always being honest about where content came from (e.g. `AIContextBlock.from_untrusted(source=...)` always labels its origin). This is a recommendation for Nathan to confirm, not a decision made here.
- **How transcribed commands must flow through `CommandRouter`/`SecurityManager`/`ApprovalManager`**: identically to typed commands, with zero new code path. The transcription step's only job is to produce a plain string; everything after that point — matching a tool, classifying the action, gating YELLOW actions behind an explicit approve/decline decision, blocking RED actions outright — must be the exact same call sequence `JarvisCLI` already uses for typed input. No voice-specific bypass, shortcut, or auto-approval path should ever exist.
- **YELLOW/RED approvals must still work identically for voice-originated commands**: a voice-triggered YELLOW action must still produce a real `ApprovalRequest` and wait for an explicit decision before `ToolExecutor` runs it — the only open question (for the implementation phase, not this plan) is *how* Nathan gives that decision when the trigger was spoken (e.g. does he type "yes"/"no" as today, or could a future version let him speak the decision too — itself a separate, later, explicitly-reviewed choice, not assumed here). RED actions remain blocked outright regardless of how the request arrived, exactly as today.
- **Why voice must never bypass approvals**: the entire safety model of this project rests on the Security Manager and Approval Manager being the *only* gate a state-changing action passes through, regardless of what tool or interface produced the request string. Voice is just one more producer of a request string. Any implementation that let a spoken command skip approval — even "just for low-risk-sounding" commands — would silently reopen every risk this project has spent 40 phases carefully gating.
- **Why a bad transcription must not create hidden write actions**: a mis-heard word could turn an intended read into something that sounds like a write command, or garble a filename. Because the transcribed string is never trusted more than typed text, and because `SecurityManager`'s classification and `ApprovalManager`'s approval gate apply uniformly regardless of origin, a garbled transcription that happens to match a YELLOW/RED action still gets stopped for approval/blocked exactly as it would if Nathan had mistyped the same words — it is never silently executed just because it arrived via speech. The Master Specification's own prior design note is a useful, compatible idea worth carrying forward for the implementation batch: when STT confidence is low (e.g. due to background noise), request confirmation before acting on the transcription at all, rather than guessing.
- **Why always-listening is higher risk**: beyond the privacy exposure already discussed, a continuously-active listener means the system is always in a state where *something* could be captured and acted on without a clear, single, Nathan-initiated moment marking "this recording was intentional" — every other trust boundary in this project (approval, YELLOW/RED classification, even the CLI's own read-eval-print loop) relies on there being a clear, discrete, user-initiated request to reason about. Always-listening blurs exactly that boundary, which is why it needs its own dedicated review rather than being treated as "push-to-talk, but automatic."

---

## 9. Configuration Design Questions

**Update: the first three items below were answered and implemented in Batch 2** (see Section 12) — `voice_enabled`, `voice_speak_mode`, and `voice_provider` now exist in `config/settings.py`, following the exact established pattern described below, and `ConfigTool`/`show config` now reports all three in full. The remaining items are still future work, for a later batch, not implemented now.

For reference, `config/settings.py` today is a frozen `Settings` dataclass populated once at startup from environment variables (via `.env`), with typed helpers (`_get_required`, `_get_optional`, `_get_int`, `_get_bool`, and now `_get_choice` for a fixed set of accepted string values) and full validation at load time; `ConfigTool` reports a redacted view of the loaded settings (e.g. the API key is reported only as "set"/"not set", never its value) via the existing `show config`/`show settings` command.

- ~~A `VOICE_ENABLED` (or similarly named) boolean flag, defaulting to `False` (opt-in, per Section 3.10).~~ **Done (Batch 2)**: `voice_enabled: bool = False`.
- A selected voice/style identifier, once Nathan has chosen one (Section 3.1/3.2) — still future work.
- A selected TTS provider identifier (local/OS/cloud/premium — Section 3.3/3.4/3.6 above) — still future work; `voice_provider` today only distinguishes `"none"`/`"fake"`, not any real engine.
- A selected STT provider identifier, once input is being built (Section 3.5/3.6) — still future work.
- ~~A "speak mode" flag/enum (Section 3.9 — e.g. all responses vs. none).~~ **Done (Batch 2)**: `voice_speak_mode: str = "off"` (`"off"`/`"all"`).
- A push-to-talk trigger setting (e.g. which key/typed command starts a recording), once STT is being built — still future work.
- Rate/speed/volume settings for TTS output, if the chosen provider supports tuning them — still future work.
- ~~Whether `ConfigTool`/`show config` should be extended to report voice settings' status~~ **Done (Batch 2)**: yes, all three fields are shown in full - none is a secret.

---

## 10. Testing Strategy

Planned for future batches only — no tests are added by this planning document.

- **Fake/mock TTS provider**: a test double implementing whatever provider interface is eventually designed, so `speak()`-shaped behavior can be tested without any real audio output or third-party dependency — mirroring this project's own established pattern (e.g. `WebSearchProvider`'s abstraction plus a concrete adapter, or `QuarantineStore`'s own fakeable interface used throughout the quarantine-family tests).
- **Fake/mock STT provider**: a test double that returns a fixed, pre-programmed transcription string for a given input, so command-routing/approval behavior can be tested deterministically without any real microphone or audio file.
- **No real microphone in tests, ever** — matching this project's existing "no real database/network/AI call in the test suite" discipline (e.g. `pytest.importorskip` patterns, fake clocks, fake loggers used throughout the existing suite).
- **No real network calls in tests, ever** — any cloud TTS/STT option, if ever selected, must be exercised only through a fake/mocked HTTP layer in tests, exactly like this project already handles `httpx`/`SafeWebFetcher` in the webpage-fetch test suite.
- **Approval-flow tests for voice-transcribed commands**: an end-to-end test (mirroring `tests/integration/test_write_approval_end_to_end.py`'s existing pattern) proving that a fake-transcribed YELLOW-classified command still produces a real `ApprovalRequest`, is not executed until approved, and is fully blocked/declined exactly like its typed equivalent.
- **Tests proving spoken/transcribed commands cannot bypass `SecurityManager`**: a structural or parametrized test confirming there is no code path from a transcription result to `ToolExecutor.execute()` that skips classification — the transcription step must always terminate in a plain string handed to the exact same `CommandRouter`/`SecurityManager` entry point typed input already uses.
- **Tests proving TTS failure does not break normal text output**: if the TTS provider raises, times out, or is unavailable, the existing text response must still print exactly as it does today (matching the Master Specification's own documented TTS-failure behavior — text-only, log the failure, continue).
- **Tests proving voice can be disabled**: with `VOICE_ENABLED` (or equivalent) off, no TTS/STT code path should be reachable at all, and Jarvis's behavior must be provably identical to today's — the safest possible default.

---

## 11. Non-Goals

Explicitly, for this planning phase:

- No implementation of any kind — no production code, no tests.
- No microphone access of any kind.
- No dependency installed; `pyproject.toml` is unchanged.
- No always-listening or wake-word behavior.
- No phone integration.
- No Core service (in the multi-client/network sense).
- No dashboard voice controls.
- No autonomous behavior.
- No AI workflow steps.
- No approval bypass of any kind, for any reason, ever.
- No hidden command execution — every command, regardless of how it was produced, must remain visible and subject to the same classification and approval rules already in force.

---

## 12. Proposed Future Batch Sequence

Presented for Nathan's review. Each batch below needs its own explicit "proceed" instruction, exactly like every other phase in this project.

- **Batch 1 — COMPLETE. TTS provider interface + fake provider + voice output service, foundation only, no CLI wiring.** No microphone. Delivered: `voice/tts.py` (`TextToSpeechProvider` abstract interface, `SpeechResult`, `FakeTextToSpeechProvider`, mirroring `WebSearchProvider`'s own precedent) and `voice/output.py` (`VoiceOutputService`, wrapping a provider, opt-in/disabled by default, matching `AIReasoningEngine`'s own established `enabled` pattern). **Narrower than originally sketched here**: no "speak this response" behavior was wired into `ui/cli.py` in Batch 1 after all — repository inspection during Batch 1 confirmed the safest, smallest first slice was the internal foundation alone (provider abstraction, fake provider, service), fully testable in isolation, with zero default-runtime-behavior change. `main.py` and `ui/cli.py` do not import or construct anything from the `voice` package yet (confirmed structurally by tests). CLI wiring is now planned for a later batch instead (see Batch 2 below, renumbered accordingly).
- **Batch 2 — COMPLETE. CLI opt-in voice-output wiring + config.** Delivered exactly three new `Settings` fields (`config/settings.py`): `voice_enabled: bool = False` (the master switch), `voice_speak_mode: str = "off"` (`"off"`/`"all"` — a second, independent gate on top of `voice_enabled`, so turning voice "on" and choosing to actually hear every response are two separate, both-required opt-ins, matching Nathan's own "opt-in first" + "not every response by default" as two distinct decisions), and `voice_provider: str = "none"` (`"none"`/`"fake"` — no real engine value exists yet). `VOICE_MAX_CHARS` was deliberately **not** added: Batch 1's existing hardcoded 2000-character guard in `voice/output.py` had no reported issue, and making it configurable would have meant an unjustified constructor change for no proven need - deferred until a real reason appears. `ConfigTool`/`show config` now reports all three new fields in full (none is a secret - no API key or credential exists for a fake, local-only provider). `main.py` gained `build_voice_output_service()`, mirroring `build_startup_notice()`'s own established "second, independent, best-effort, never-blocks-startup" pattern exactly: it loads `Settings` a second time, constructs `FakeTextToSpeechProvider()` only when `voice_provider == "fake"` (never a real engine - none exists), and returns `(VoiceOutputService, speak_responses)` for `main()` to hand to `JarvisCLI`. `ui/cli.py`'s `JarvisCLI` gained two new optional constructor parameters, `voice_output: VoiceOutputService | None = None` and `speak_responses: bool = False` (both default to the exact prior behaviour), and one new call site: `self._speak_if_enabled(response.message)`, invoked once per request, strictly after the text response is already fully decided and printed - never before, never influencing it. No user-facing voice command was added (repository inspection found no need for one in Batch 2 - speaking is driven entirely by config, not a per-request command yet).
- **Batch 3 — COMPLETE. Speech-to-text foundation only, still no microphone, still no push-to-talk.** Delivered: `voice/stt.py` (`SpeechToTextProvider` abstract interface, `TranscriptionResult`, `FakeSpeechToTextProvider`, mirroring `voice/tts.py`'s own established provider-abstraction pattern) and `voice/input.py` (`VoiceInputService`, wrapping a provider, opt-in/disabled by default, matching `VoiceOutputService`'s own precedent). **Narrower than originally sketched here**: no push-to-talk trigger was wired into `ui/cli.py` in Batch 3 after all — repository inspection during Batch 3 confirmed the same lesson Batch 1 already taught for voice output: the safest, smallest first slice is the internal foundation alone (provider abstraction, fake provider, service), fully testable in isolation, with zero default-runtime-behavior change. `SpeechToTextProvider.transcribe()` deliberately takes no audio-input parameter yet - no recording/capture mechanism has been chosen, so committing to an audio shape (bytes, a file path, a stream) now would be guessing. `main.py`/`ui/cli.py` do not import or construct `VoiceInputService`/`FakeSpeechToTextProvider` yet (confirmed structurally by tests) - real push-to-talk wiring, and the audio-capture-shape decision it requires, is now planned for a later batch instead (see Batch 4 below, renumbered accordingly). **Trust/origin boundary (see voice/input.py's own module docstring for the full text)**: a transcription produced by `VoiceInputService` is inert - nothing in `voice/stt.py` or `voice/input.py` routes it to `CommandRouter`, `ToolExecutor`, `ApprovalManager`, or any AI component (confirmed structurally). Whenever a future batch does wire transcribed text toward execution, it must flow through the exact same `CommandRouter -> SecurityManager -> ApprovalManager -> ToolExecutor` path typed text already uses, with identical YELLOW/RED classification and approval requirements regardless of origin - a bad transcription must never become a hidden write action. Voice-originated commands may need explicit origin tracking (e.g. in audit/history display) in whatever future batch first makes them executable; no such tracking exists yet, and none was needed for Batch 3, since nothing downstream of `VoiceInputService` reads its output yet. No new `AIContextBlock` trust level was added or needed - this service does not construct one at all. No new configuration setting was added in Batch 3 (unlike Batch 2's TTS settings): `VoiceInputService`'s own `enabled` constructor flag already sufficed for every Batch 3 test, mirroring exactly how Batch 1 needed no config either.
- **Batch 4 — COMPLETE. Fake-provider-only CLI voice input routing + adversarial approval-bypass proof.** No microphone, no real push-to-talk hardware capture, no real STT, no always-listening/wake-word. Delivered: `JarvisCLI` gained `voice_input: VoiceInputService | None = None`; the interactive loop's per-request handling was extracted into a new shared method, `_handle_text_request(text)`, so the typed-input loop and the new `_handle_voice_input_once()` call the *exact same* code - not a parallel or shortened path. `_handle_voice_input_once()` (a private method, reachable only from tests/future wiring - **not** from the interactive typed-input loop, and **no new typed command was added**, since repository inspection found no proven need for one yet) transcribes once via `_voice_input` and, on success, forwards the text to `_handle_text_request()`. Two new config fields (`voice_input_enabled: bool = False`, `voice_input_provider: str = "none"`/`"fake"`), independent of the Batch 2 output settings, plus `main.py`'s `build_voice_input_service()` mirroring `build_voice_output_service()`'s own pattern exactly. `ConfigTool`/`show config` reports both new fields. **Adversarial proof (`tests/unit/test_cli.py`, 20 new tests)**: a GREEN fake transcription routes and succeeds normally; a YELLOW fake transcription (using a real `FileCreateTool` + real `ApprovalManager`) requires approval and creates no file before a decision; a declined approval leaves no file; a timed-out approval (proven via the same direct-`handle_request()`-plus-fake-clock technique `test_write_approval_end_to_end.py` already established, since a synchronous approval prompt cannot itself time out mid-call) leaves no file; an approved voice-originated command *does* execute normally (a positive control, proving the gate isn't just "always refuse"); the exact same command text produces identical `security_tier` whether typed or transcribed; a RED-classified transcription is blocked outright with no approval step at all; and command-shaped/injection-shaped transcriptions are proven to receive only the ordinary approval-gated treatment, never a silent bypass or silent execution. Structurally, `voice/input.py` is re-confirmed to import none of `ToolExecutor`/`ApprovalManager`/`CommandRouter` directly - only `JarvisCLI`, via the orchestrator, ever reaches them, identically for typed and voice-originated text.
- **Batch 5 — COMPLETE. Push-to-talk trigger design review only — no code behavior change, no audio, no dependency.** Repository-grounded review of how a *future* real push-to-talk batch should be shaped, done deliberately before writing any capture code (see Section 14 for the full design comparison). Confirmed `pyproject.toml` still has zero audio/hotkey dependencies. Delivered: Section 14 (trigger-mechanism comparison, the still-open capture-boundary decision, per-option dependency implications, and the adversarial tests a future real-capture batch will need); a documentation-accuracy fix to `voice/input.py`'s module docstring (it previously still said "nothing in main.py/ui/cli.py constructs this yet," which Batch 4 had already made false — corrected to describe the actual opt-in, disabled-by-default wiring); one new structural test locking the dependency boundary itself (`pyproject.toml` contains no audio-capture/hotkey package, not just "no such import" as the existing tests already checked). **Why review-only, not a tiny trigger-shape implementation**: the capture-boundary question (press-to-release vs. fixed-duration vs. silence-detection) is still open, and every trigger-mechanism option implies a different dependency and a different interface shape — building an abstraction now would mean guessing at a shape real hotkey/audio libraries would likely force to change anyway, repeating the exact lesson Batches 1 and 3 already taught ("the safest first slice is foundation/design, not a guessed-at shape"). No new interface, class, or config field was added in Batch 5.
- **Batch 6 (or later) — real push-to-talk trigger/audio-capture shape.** Once Nathan picks a trigger mechanism and capture boundary from Section 14, decide and implement the actual recording trigger and the audio-capture shape `SpeechToTextProvider.transcribe()` deliberately left unspecified through Batch 3/4/5, and call `_handle_voice_input_once()` (or an equivalent) from it. This is the batch that will need a `pyproject.toml` edit and Nathan's explicit approval of a specific new dependency. A real STT provider is only added once Nathan has explicitly chosen one from Section 7's research.
- **Batch 7 (or later) — closure, remaining adversarial safety tests, and documentation.** Any tests from Section 10 not already covered, plus README/user_guide updates and a completion report — mirroring how every prior phase in this project has closed. Phase 41 has not closed yet; real push-to-talk implementation (Batch 6) and this closure batch both remain outstanding.
- **Always-listening/wake-word: explicitly deferred**, not scheduled as any numbered batch above. It would require its own separate future architectural review, on its own merits, once push-to-talk voice has actually been used and evaluated.

---

## 13. Open Questions for Nathan

**Update: Nathan has now recorded temporary defaults for most of these** (see the summary section near the top of this document). They are listed below with their status — answered items remain open to change at any time; this is simply the current state, not a closed decision.

**Answered (temporary defaults recorded, still changeable at any time):**

1. ~~Do you want a female voice?~~ **Answered: yes, female voice** (temporary).
2. ~~Do you want free/local TTS and STT options tried first, or are paid/cloud options acceptable from the start?~~ **Answered: try free/local first; paid/cloud considered later only if quality is poor** (temporary).
3. ~~Should Jarvis speak every response once voice output is on, or only some?~~ **Answered: opt-in, not every response by default** (temporary).
4. ~~Should the first implementation batch be voice output only, with no microphone at all?~~ **Answered: yes** (temporary).
5. ~~Should microphone input wait until after TTS output is working?~~ **Answered: yes — no microphone/STT in Batch 1** (temporary).
6. ~~Should push-to-talk be the first voice input mode?~~ **Answered: yes** (temporary).
7. ~~Should always-listening/wake-word remain deferred?~~ **Answered: yes, explicitly deferred from all Phase 41 implementation batches** (temporary).
8. ~~Should voice be off by default (opt-in)?~~ **Answered: yes, opt-in** (temporary).
10. ~~Is CLI-only the right scope for the first version?~~ **Answered: yes — CLI only, no dashboard, no phone, no Core service** (temporary).

**Still genuinely open — no default given yet:**

9. Should voice settings be saved in `.env`/config the same way every other setting is today (Section 3.11), or would Nathan prefer some other persistence approach (or none, for now)?

**New, practical follow-up questions arising from the temporary defaults above** (not required before Batch 1, but worth answering before engine research narrows in Section 6/7):

11. For the "calm, smart, clean, not robotic/emotional/cartoon" voice personality — would Nathan like to hear a short list of real candidate samples once free/local options are researched, before any is wired in even provisionally?
12. What would count as "poor quality" for the free/local-first TTS/STT preference (item 3) — a specific, concrete bar (e.g. "hard to understand," "sounds too robotic despite trying"), or simply Nathan's own subjective judgment once he's heard it?

---

## 14. Push-to-Talk Trigger Design (Batch 5 Review)

This section exists so a future real-capture batch (Batch 6) starts from a concrete, compared set of options, instead of guessing. **Nothing in this section is implemented. No option below has been chosen yet — that choice belongs to Nathan, before Batch 6 begins.**

### 14.1 Trigger-mechanism candidates

| Option | How it would work | New dependency needed | Notes |
|---|---|---|---|
| (a) Global hotkey | A system-wide key (e.g. holding a chosen key) starts capture on press, stops on release, even when the terminal isn't focused. | A hotkey/input-hook library (e.g. `keyboard` or `pynput`). | Most literal reading of "push-to-talk." On some OS configurations, global key hooks can require elevated/accessibility permissions — a real, separate trust surface beyond just "a new pip package," worth flagging to Nathan explicitly when this is chosen. |
| (b) Terminal-local keypress | A key is read only while the Jarvis terminal window has focus (e.g. via the stdlib `msvcrt` module on Windows) to start/stop capture — no system-wide hook. | None for the trigger itself (stdlib-only on Windows). | Narrower privacy surface than (a): the key only does anything while Jarvis is the focused window. Platform-specific (would need a different approach on macOS/Linux). |
| (c) Existing typed-command trigger + fixed duration | Nathan types an explicit command; Jarvis records for a fixed, bounded window (e.g. 5 seconds) and stops automatically — no key-up/key-down semantics at all. | None for the trigger itself. | Simplest to implement and to reason about safety-wise (bounded by construction, no missed-release edge case) but the least literal "push-to-talk" — closer to "record on demand." |

**Note that all three options still require a separate, real audio-capture dependency** (e.g. `sounddevice` or `pyaudio`) to actually read microphone input — the trigger mechanism and the audio-capture mechanism are two independent dependency decisions. Today, zero dependencies exist for either.

### 14.2 Capture-boundary decision (still open)

Independent of which trigger is chosen, the capture window itself must have a defined end condition:

1. **Press-to-release** — capture runs exactly as long as the key is held. Requires reliable key-up detection (only really available with options (a) or (b) above); a missed release event needs a hard-cap fallback so capture can never run unbounded.
2. **Fixed duration** — capture always runs for a preset number of seconds, then stops automatically regardless of trigger mechanism. Simplest and safest to bound, but caps how long a single voice command can be.
3. **Silence detection** — capture stops automatically after detecting a pause in speech. Most natural to use, but requires real-time audio analysis during capture, the most implementation complexity of the three, and its own failure mode (never detecting silence) that would also need a hard cap.

**Whichever is chosen, a hard maximum capture duration must exist regardless** — this is a non-negotiable safety property for Batch 6, not an open question: unbounded capture is indistinguishable from always-listening, which remains explicitly deferred.

### 14.3 Adversarial tests a future real-capture batch (Batch 6) will need

Recorded now so Batch 6 does not have to rediscover them:

- Prove a hard maximum capture duration is enforced even if a key-release/stop signal is never received.
- Prove a cancelled, failed, or timed-out capture never reaches `_handle_text_request()` with partial or garbage audio — mirroring how Batch 4 already proved a failed/empty fake transcription produces no request.
- Prove capture only ever starts synchronously, in direct response to an explicit trigger already in progress in the current call stack — never on a timer, and never on a background thread that outlives the call that started it — to keep the "no always-listening" boundary structural, not just conventional.
- Re-run the full Batch 4 routing/security/approval adversarial suite (GREEN/YELLOW/RED, denied, timed-out, approved) with a real-but-test-double capture backend, to confirm the trust/origin guarantees still hold once real audio is in the loop.
- A dependency-boundary canary test confirming exactly one new, explicitly-approved dependency was added to `pyproject.toml` for Batch 6 — not more than what Nathan approved.

### 14.4 What Batch 5 deliberately did not decide

No trigger mechanism, no capture boundary, and no audio-capture library were chosen in this review — all three remain Nathan's decision, to be made explicitly before Batch 6 begins, exactly like every other implementation choice in this project.
