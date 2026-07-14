# Jarvis — Deferred Decisions

**Purpose:** This document consolidates the "Remaining Future Choices" repeated, unchanged, across Phases 40 and 44–52's own completion reports into one current, de-duplicated list. **It organizes these decisions; it does not make any of them.** Each item below remains exactly as undecided as it was when first named — nothing here is a recommendation, a plan, or a commitment to any direction. When Nathan is ready to act on one of these, it becomes its own explicitly-approved phase, following this project's own established review-then-implement discipline.

**Created:** Phase 53 (2026-07-14), as a documentation-only consolidation. See `docs/phase_53_completion_report.md` for how this document was assembled.

**How to keep this current:** When a future phase resolves one of these items, update its "Current status" row here in the same phase that resolves it — do not let this document itself become a second place that drifts out of sync with reality.

---

## 1. Wire `LOG_LEVEL` into real console logging

- **Origin:** First named as inert in Phase 46; formally investigated in Phase 47's planning-only stage; repeated in Phases 48–52.
- **Current status:** **Implemented, Phase 54.** Phase 47 confirmed, by direct live testing, that console logging did not actually work for INFO-level events (independent of `LOG_LEVEL` entirely) and compared two remediation paths — Option A (wire a real handler using `settings.log_level`) and Option B (leave behavior as-is, correct the docstring). Phase 48 implemented Option B first, as the safer interim step. Nathan then explicitly approved Option A: Phase 54, Batch 1 added `observability/logging_setup.py`'s `configure_console_logging()` (idempotent - attaches at most one console handler to the `"jarvis"` app logger, level set from the already-validated `settings.log_level`) and wired it into `main.py`'s `main()`; Batch 2 wired the same helper into `scheduler.py`'s `main()`. Neither `main.build_orchestrator()` nor `scheduler.build_components()` were touched, so the wide existing test suite that constructs these directly is unaffected. `dashboard.py` was not touched - it has no logging calls of any kind.
- **Resulting behavior:** Console output now genuinely reflects `LOG_LEVEL` for both the CLI (`main.py`) and the scheduler (`scheduler.py`) processes - GREEN/successful (INFO-level) events now appear on the console by default, a real, disclosed increase in default console verbosity Nathan explicitly accepted before implementation began.
- **Fuller source:** `docs/phase_47_logging_console_visibility_plan.md` (Section 4's six implementation risks, all respected in the actual implementation); `docs/phase_54_completion_report.md` for the full closure write-up.

## 2. Fate of `IntentType`, `ActionType`, `OnFailure`, and `MemoryType`

- **Origin:** Phase 50.
- **Current status:** Deferred. Their docstrings were corrected to honestly state they are defined but not consumed by any production code (each represents Master Specification-era architectural vocabulary — an Intent Classifier, step-level retry policy, multi-backend memory storage — that this project has never built). Whether to eventually remove them, wire them into a genuinely new architecture, or leave them exactly as-is indefinitely was deliberately left open.
- **Why it remains deferred:** No evidence yet that removal is safer/more useful than keeping them as documented future vocabulary, and no forcing function to build the architecture they represent.
- **Fuller source:** `docs/phase_50_completion_report.md`.

## 3. Real push-to-talk/microphone capture, or a real local/free TTS/STT provider

- **Origin:** Phase 41 (the voice interface foundation), repeated in Phases 44 and 46–52.
- **Current status:** Deferred. Phase 41 delivered a complete, disabled-by-default, fake-provider-only voice foundation and a push-to-talk trigger design comparison; no real audio, microphone, or engine selection exists.
- **Why it remains deferred:** Real microphone access is a new privacy and dependency boundary this project has never crossed; Nathan has not yet chosen a trigger mechanism, capture boundary, or a specific TTS/STT engine.
- **Fuller source:** `docs/phase_41_completion_report.md`; `docs/phase_41_implementation_plan.md` (Section 14, the trigger-mechanism comparison awaiting Nathan's choice).

## 4. Empty-trash/permanent delete for quarantine

- **Origin:** Standing since at least Phase 40's own completion report (sourced from README's "Next Phase" section); repeated through Phase 52.
- **Current status:** Deferred, unselected.
- **Why it remains deferred:** Would require its own RED classification and a dedicated safety-design review before being considered at all.
- **Fuller source:** README.md's "Next Phase" section.

## 5. A cleanup/retention policy for `.jarvis_trash/`

- **Origin:** Standing since at least Phase 40's own completion report; repeated through Phase 52.
- **Current status:** Deferred, unselected.
- **Why it remains deferred:** Premature without real usage evidence that it's actually needed.
- **Fuller source:** README.md's "Next Phase" section.

## 6. A scheduler schema/type foundation

- **Origin:** Standing since at least Phase 40's own completion report; repeated through Phase 52.
- **Current status:** Deferred, unselected. Currently blocks scheduled webpage summaries and any additional scheduled action type, since `ScheduleEntry` has no `action_type`/`kind` column.
- **Why it remains deferred:** Still unjustified without a concrete second use case beyond the existing web-search-summary schedule type.
- **Fuller source:** README.md's "Next Phase" section.

## 7. Inbox integration for webpage summaries

- **Origin:** Standing since at least Phase 40's own completion report; repeated through Phase 52.
- **Current status:** Deferred, unselected.
- **Why it remains deferred:** An unresolved producer-policy decision (whether an approval-gated summary should also auto-save to the Inbox) — not an implementation gap.
- **Fuller source:** README.md's "Next Phase" section.

## 8. Dashboard write actions of any kind

- **Origin:** Standing since Phase 19 (the dashboard's own creation as strictly read-only); repeated through Phase 52.
- **Current status:** Deferred, unselected. The dashboard remains strictly read-only.
- **Why it remains deferred:** No review has changed the dashboard's read-only architecture; nothing has surfaced a concrete need.
- **Fuller source:** README.md's "Next Phase" section.

## 9. A Research Agent or autonomous browsing foundation

- **Origin:** Standing since at least Phase 40's own completion report; repeated through Phase 52.
- **Current status:** Deferred, unselected — a standing non-goal unless explicitly selected through its own dedicated review.
- **Why it remains deferred:** No forcing function has emerged; autonomous behavior remains an explicit standing non-goal project-wide.
- **Fuller source:** README.md's "Next Phase" section.

## 10. A Project/Repo Health Check Tool

- **Origin:** Standing since at least Phase 40's own completion report; repeated through Phase 52.
- **Current status:** Deferred, unselected — evaluated in an earlier architectural review and found speculative.
- **Why it remains deferred:** No expressed need exists yet.
- **Fuller source:** README.md's "Next Phase" section.
