# Jarvis — Phase 47 Planning Document

**Phase title:** Logging Console-Visibility Behavior
**Classification:** Small — planning only. No implementation batch is authorized by this document.
**Baseline:** branch `phase-4-ai-reasoning-and-write-actions`, HEAD `022f24fd1ea2a23d5fd7ebd2d6808f92d555cc4a`, full suite 3545 passed / 3 skipped / 0 failed.
**Status:** planning only. No production code, test, or dependency was changed to produce this document. No implementation batch is authorized — a future phase must get its own explicit "proceed" instruction before any of the options below is built.

---

## 1. Purpose

Phase 46 validated `LOG_LEVEL` against `config.constants.LogLevel` but deliberately left the setting otherwise inert — it is read, validated, and displayed, but nothing in the codebase applies it to real logging verbosity. During the Phase 47 proposal review, direct, live inspection revealed that this inertness sits on top of a second, more fundamental and previously-undiscovered gap: **console logging does not actually work as documented today, independent of `LOG_LEVEL` entirely.** This document exists to record that evidence precisely, compare two legitimate remediation paths, and let Nathan choose a direction — deliberately, the same way every other implementation decision in this project has been made — before any code is written.

---

## 2. Current-State Evidence (Confirmed Directly, Not Assumed)

### 2.1 The documented claim

`observability/logger.py`'s module docstring states:

> "Emit events to two destinations: the console (for live visibility) and the append-only audit log (for the permanent record)."

`EventLogger.log()` implements this by calling `self._logger.log(self._level_for(event.outcome), event.to_console_line())`, where `self._logger = logging.getLogger(APP_NAME)` — a standard-library logger with no further configuration anywhere. `_level_for()` maps outcomes to standard levels: `FAILURE` → `ERROR`, `BLOCKED`/`TIMEOUT` → `WARNING`, everything else (the overwhelming majority of events — every successful GREEN action, every completed tool call) → `INFO`.

### 2.2 No production logging configuration exists anywhere

A repository-wide search (`grep -rn "basicConfig\|addHandler\|StreamHandler\|logging.config\|setLevel"` across all production `.py` files, excluding tests) returns **zero results**. No entry point (`main.py`, `scheduler.py`, `dashboard.py`) ever configures a handler or a level for any logger.

### 2.3 Live-verified behavior

Run directly against this repository's real code (not a hypothetical):

```
root logger effective level:        30 (WARNING)
"jarvis" (APP_NAME) logger level:   0 (NOTSET) - inherits from root
"jarvis" logger handlers:           [] (none)
"jarvis" logger propagate:          True
isEnabledFor(logging.INFO):         False
isEnabledFor(logging.WARNING):      True
```

Logging an actual `INFO`-level message through `EventLogger`'s own code path produces **no console output at all** — confirmed by capturing stderr around a real `.log(logging.INFO, ...)` call. Logging a `WARNING`-level message **does** produce output, via Python's `logging.lastResort` fallback handler (a `_StderrHandler` hardcoded to level `WARNING`, which Python attaches automatically only because no other handler exists anywhere in the logger hierarchy).

**Conclusion**: every `BLOCKED`/`TIMEOUT`/`FAILURE` event is visible on the console today, by accident of Python's own fallback behavior — but every `GREEN`/successful event (the majority of everything Jarvis does) is silently swallowed before it ever reaches a console. This has evidently been true since `EventLogger` was first written; `LOG_LEVEL`'s own inertness (Phase 46) is a symptom of the same underlying gap, not its cause.

### 2.4 The durable record is unaffected

None of this touches `security/audit_log.py`'s `AuditLog.record()` call, which persists every event to SQLite regardless of console visibility. `show approval history`, `show workflow history`, and the dashboard's read-only tabs all read from these durable, unaffected records. **No information is lost** — only the live, in-terminal, real-time visibility of routine (GREEN/successful) events is currently absent.

### 2.5 Naive "wiring" is insufficient — confirmed directly

A natural first instinct — "just call `logging.getLogger(APP_NAME).setLevel(logging.INFO)` based on `settings.log_level`" — was tested directly and confirmed **not sufficient on its own**: `logging.lastResort` filters at its own fixed `WARNING` threshold regardless of the logger's own effective level, since `lastResort` is only consulted when no real handler exists anywhere in the chain. An actual `logging.Handler` (e.g. `logging.StreamHandler()`) must be attached before `INFO`-level messages can appear at all, confirmed by direct before/after comparison.

### 2.6 Entry-point scope

Only `main.py` and `scheduler.py` construct an `EventLogger(AuditLog(...))` (confirmed by grep). `dashboard.py` does not use `logging`/`EventLogger` at all — it is read-only and has no events to emit. Any future implementation of Option A below would therefore only need to touch `main.py` and `scheduler.py`, not `dashboard.py`.

---

## 3. Options Compared

### Option A — Configure real console logging behavior using `settings.log_level`

Wire an actual `logging.Handler` (e.g. a `StreamHandler`) into the `"jarvis"` logger, with its level set from the already-validated `settings.log_level`, at startup in `main.py` and `scheduler.py`.

**Pros**: makes `logger.py`'s own docstring claim true; restores the "live visibility" the project's own documentation has always promised; gives `LOG_LEVEL` (validated since Phase 46) a genuine functional purpose for the first time; a natural, small, well-precedented piece of work (a single new helper function, called once per entry point).

**Cons / open design questions** (see Section 4 for the full risk list): requires a genuine implementation decision about *where* the configuration lives (a new small function in `observability/logger.py`? a new tiny module? inline in each entry point?); requires careful idempotency handling so repeated calls (especially in the test suite, where `main.build_orchestrator()` is called dozens of times across `test_main_*_wiring.py` files) never accumulate duplicate handlers; changes real, user-visible behavior — Jarvis's console output volume would increase noticeably (every GREEN action would now print a line), which is a genuine UX change Nathan should explicitly want, not one this project should assume by default.

### Option B — Leave console behavior as-is; correct `observability/logger.py`'s documentation

Leave `EventLogger`'s runtime behavior completely unchanged (console remains WARNING+/fallback-only) and instead correct the module's own docstring so it no longer overclaims full console visibility — mirroring the exact remediation Phase 46 itself chose when a similar docstring-vs-behavior mismatch was found for `LogLevel` in `config/constants.py` (there, though, the resolution was to make the docstring true by wiring validation in; here, the two precedents diverge specifically because of Section 2.5's finding — the "just wire it in" version is more involved than a validation check, since it changes visible runtime output, not just startup validation).

**Pros**: zero runtime behavior change of any kind; zero test-suite risk; the audit log already provides the complete, durable, queryable record every existing CLI command (`show approval history`, `show workflow history`) and the dashboard already rely on — arguably nothing was actually "missing" for Jarvis's actual users (Nathan, via CLI/dashboard), only for someone tailing raw console/stderr output live, which isn't how this project has ever been operated day-to-day.

**Cons**: does not restore the originally-intended "live visibility" capability; leaves `LOG_LEVEL` permanently inert (Phase 46 validates it but nothing consumes it) unless a future phase revisits this decision.

### A third option was considered and rejected as out of scope for this document

A "hybrid" — wiring console logging in only for GREEN/INFO events optionally, gated behind a new setting — was considered but rejected as premature to even outline in detail: it would introduce a *new* configuration surface beyond what Phase 46 already validates, which is exactly the kind of scope-widening this planning document exists to prevent. If Option A is chosen, `settings.log_level` (already validated, already the established mechanism) is sufficient on its own — no new setting is needed.

---

## 4. Option A Implementation Risks (Documented Now So a Future Batch Doesn't Rediscover Them)

1. **Handler idempotency.** `logging.getLogger(APP_NAME)` returns the same process-wide singleton every time. If a future `configure_logging()`-style function is called once per `main.build_orchestrator()`/`scheduler.py` startup without guarding against repeat calls, every test that constructs an orchestrator (dozens of files, e.g. every `test_main_*_wiring.py`) would attach a new handler each time, causing later log calls in the same test process to print multiple times. A future implementation must check `if not logger.handlers:` (or explicitly clear/replace) before attaching, and this must itself be tested.
2. **Repeated `build_orchestrator()` calls in tests.** Directly related to (1) — this project's own test suite calls `main.build_orchestrator()` very frequently (confirmed: `test_main_config_wiring.py`, `test_main_help_wiring.py`, `test_main_voice_wiring.py`, `test_main_voice_input_wiring.py`, and others each construct a fresh orchestrator per test). Any logging setup added to `build_orchestrator()` itself (as opposed to only `main.py`'s `main()` entry function) would run this same risk far more often than a human ever would in real usage. A future implementation should strongly consider configuring logging only in `main()`/`scheduler.py`'s actual process entry point, never inside `build_orchestrator()` itself, so the test suite's frequent orchestrator construction is never affected at all.
3. **Avoiding duplicate handlers across `main.py` and `scheduler.py`.** Both are separate OS processes, but if a shared helper function is used by both, it must be written so that calling it doesn't assume it's the first/only caller in a given process — the guard in (1) covers this too, but it's worth naming explicitly since two independent entry points will share whatever helper is written.
4. **Which entry points configure logging.** Confirmed (Section 2.6): only `main.py` and `scheduler.py` need to; `dashboard.py` has no logging calls today and should not gain any as part of this work (that would be new scope, not a fix to existing behavior).
5. **Preserving dashboard read-only behavior.** `dashboard.py` must not be touched by a future Option A implementation at all — it remains exactly as read-only and log-free as it is today. This is named explicitly so a future batch doesn't assume "all three entry points" symmetrically without checking first, as this document already has.
6. **Console output volume as a genuine UX decision, not an engineering default.** Turning on INFO-level console output means every single GREEN/successful action will now print a line during ordinary CLI use — a real, user-visible change to what a running session looks like. This should be something Nathan explicitly wants, confirmed at the time Option A is actually approved, not something assumed as an obviously-correct restoration of "intended" behavior.

---

## 5. Recommendation

**This document does not pick a side between Option A and Option B — that choice belongs to Nathan.** Both are legitimate, safe, small, well-scoped next steps; they simply serve different values (restoring documented live visibility vs. minimizing behavior change and risk). What this document does establish:

- The mismatch is real and directly confirmed, not speculative.
- If Nathan wants live console visibility restored, Option A is buildable safely as its own small phase, provided the six risks in Section 4 are respected — most importantly, configuring logging only at the real process entry points (`main()`, `scheduler.py`'s startup), never inside `build_orchestrator()` itself, so the test suite is never affected.
- If Nathan is content with the audit log as the sole durable record (which every existing read command and the dashboard already rely on) and console output as it already behaves (WARNING+ visible, INFO silent), Option B is a trivial, same-day docstring correction with zero risk.

**What Nathan must decide before any implementation phase begins**: Option A or Option B. If Option A, a follow-up phase should be scoped narrowly to exactly what Section 4 describes — nothing more.

---

## 6. Explicit Confirmation: No Runtime Behavior Changes in Phase 47

Phase 47 is planning only. No production file, test file, `.env.example`, `README.md`, `docs/user_guide.md`, or dependency was changed to produce this document. `observability/logger.py`, `main.py`, and `scheduler.py` remain byte-for-byte unchanged. The current console-logging behavior described in Section 2 remains exactly as it was before this document was written.
