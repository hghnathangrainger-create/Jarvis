# Jarvis — Phase 31 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 31 — Configuration Inspection Tool (small whole-phase, complete)
**Date:** 2026-07-12

---

## Executive Summary

Phase 31 adds one small, GREEN, read-only tool — `show config`/`show settings` — that reports Jarvis's current configuration status directly from the already-loaded `Settings` object, without ever exposing the Anthropic API key's value in any form. It directly answers a real, already-documented troubleshooting pain point (`docs/user_guide.md` §12) that previously had no remedy beyond manually reading `.env` yourself.

## Baseline

```
Branch:        phase-4-ai-reasoning-and-write-actions
Phase 30 final commit: 288c2c6
Full suite before Phase 31: 2814 passed, 0 failed
```

## Files Changed

- `tools/builtin/config_tool.py` (new) — `ConfigTool`.
- `tools/builtin/__init__.py` — import, docstring entry, `__all__` entry.
- `core/command_router.py` — new `_CONFIG_EXACT_COMMANDS` frozenset and a `match()` branch.
- `main.py` — `ConfigTool` import and registration (constructed from the already-loaded `settings` object).
- `security/security_manager.py` — one new explicit GREEN rule, `"show configuration"`, matching the Phase 24/25 precedent of naming a rule explicitly even when an existing generic rule (`"show"`) already covers it.
- `tests/unit/test_config_tool.py` (new, 15 tests).
- `tests/unit/test_command_router.py` (extended, 11 new tests; `_ALL_TOOL_NAMES` gained `"config"`).
- `tests/unit/test_main_config_wiring.py` (new, 8 tests).
- `README.md` — new `## Phase 31` section.
- `docs/user_guide.md` — new command-reference row and a new Troubleshooting row.
- `docs/phase_31_completion_report.md` — this report, new.

---

## Final Command Grammar

```
show config
show settings
```

Both are exact-phrase matches (mirroring `_APPROVAL_HISTORY_EXACT`/`_WORKFLOW_HISTORY_EXACT`'s own established pattern) routing to the same `config` tool — two names for the same fixed, no-argument request, never two different operations. Collision-checked directly by test against `show memories`, `show approval history`, `show workflow history`, and `list files`; confirmed neither phrase appears as a substring anywhere else in `core/command_router.py`. Unlike file/web-search commands, this is deliberately **not** a prefix match — `"show config please"` and `"show configuration"` are both confirmed non-matches, since there is no trailing argument to capture and no reason to accept variations of a fixed, no-argument command.

## Final Tool Behavior

`ConfigTool` is constructed with the application's already-loaded `Settings` object (passed in once, at `main.py`'s own composition time) and never calls `load_settings()` again, never reads `.env`/`os.environ` directly. Its `action_for()` returns the fixed string `"show configuration"` regardless of input (proven directly with an adversarial-looking `input_data` payload), so classification can never vary with user input.

Output reports, in full: `ai_model`, `ai_max_tokens`, `ai_reasoning_enabled`, `database_path`, `log_level`, `approval_timeout_seconds`, `debug`. None of these are secret.

## Final Secret-Redaction Behavior

The one secret field, `anthropic_api_key`, is reported only as `"set"` or `"not set"` (`"not set"` when empty or whitespace-only). Proven directly, with a realistic-looking fake key value, that the output never contains: the full key, its first 8 characters, its last 8 characters, its exact length as a string, or any mention of "hash"/"checksum"/"fingerprint"/"sha"/"md5". The "not set" branch was tested by constructing `Settings` directly (bypassing `load_settings()`, whose own required-field validation means this state can never actually occur via the real startup path) — a defensive, disclosed proof of correctness for an unreachable-in-production branch, matching this project's own established testing convention for such cases.

## Final Security Classification

`ConfigTool.action_for()` returns `"show configuration"`, classified `GREEN` by the real `SecurityManager` (proven directly, not assumed) — both via the pre-existing generic `"show"` rule and the new, explicit `"show configuration"` rule added for UX-consistent reason text, matching the Phase 24 (`"search files"`) and Phase 25 (`"copy file"`) precedent of adding an explicit rule even when a generic one already covers the same classification.

## Tests Added/Updated

- 15 new tests in `tests/unit/test_config_tool.py`.
- 11 new tests in `tests/unit/test_command_router.py` (plus `_ALL_TOOL_NAMES` fixture update).
- 8 new tests in `tests/unit/test_main_config_wiring.py`.

## Final Verification

```
Focused (config tool, command router, security classification, main wiring): all passing
poetry run pytest -q: 2848 passed, 0 failed (run 3x, stable; +34 since Phase 30's 2814)
poetry run ruff check (all touched files): zero findings
git diff --check: clean
```

## Non-Goals Confirmed

Confirmed absent, by direct inspection and by structural AST-based tests: no `subprocess` import anywhere in `tools/builtin/config_tool.py`; no git/repo-health reporting; no test-running; no configuration mutation (`Settings` remains a frozen dataclass, read-only); no `.env` editing; no new dependency (`pyproject.toml` unchanged); no secret display in any form; no dashboard, scheduler, or Inbox change; no Core service; no goals/projects/tasks; no new workflow template; no automated summary-saving; no notifications; no phone/voice features; no DB tamper/integrity work.

---

## Status Statement

**Phase 31 complete for its defined scope: one small, GREEN, read-only configuration-status tool, exposing every non-secret setting in full and the API key's presence only, with zero new architectural precedent (no subprocess, no new dependency, no new durable state).** Implemented in a single pass, exactly matching its approved "small whole-phase" classification.
