# Jarvis — Phase 61 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 61 — Explicit Webpage Summary Inbox Save Command (medium: 2 batches, complete)
**Date:** 2026-07-15

---

## Executive Summary

Phase 60's planning review found a real inconsistency: `summarise web search for <query>` (Phase 20) always auto-saves its successful summary to the Inbox, but `summarise webpage <url>` (Phase 34) never saved anywhere at all. Nathan reviewed three options (always auto-save, an explicit opt-in command, or deferring the decision) and chose **Option C — an explicit opt-in command**, reasoning that approving a webpage *fetch* should not be read as automatic consent to durably *store* its summary — a distinct decision he should make each time, via its own command. Batch 1 implemented the new grammar, approval-metadata threading, and the Inbox-save mechanics. Batch 2 (this closing batch) documents the command (HelpTool, README, user guide), updates `docs/deferred_decisions.md` item 7, and adds a dashboard smoke check confirming no dashboard code change was needed.

## Baseline

```
Branch:                       phase-4-ai-reasoning-and-write-actions
Phase 61 Batch 1 commit:      fcceededb97e972cb77fab713c1e827c3e8cc09f
Full suite before Batch 2:    3689 passed, 3 skipped, 0 failed
```

## Files Changed (Batch 2)

- **`tools/builtin/help_tool.py`** — the existing webpage-summary help line clarified ("does not save to the Inbox"), and a new line added documenting the explicit `... and save to inbox` variant.
- **`tests/unit/test_help_tool.py`** — `"and save to inbox"` added to the existing documented-command-family parametrized list; new `test_output_documents_the_explicit_webpage_save_command_and_its_distinction` test.
- **`tests/unit/test_help_output_routing_consistency.py`** — new representative phrase, `("Web: summarize webpage and save to inbox", "summarize webpage https://example.com and save to inbox")`, proving the new command routes correctly through the real orchestrator end-to-end.
- **`tests/unit/test_dashboard_read_model.py`** — new `test_webpage_summary_source_type_renders_like_any_other_entry` smoke check.
- **`README.md`** — Phase 34 section's two stale claims corrected (durable wording, referencing Phase 61 rather than claiming the summary is never saved); new "## Phase 61 —" section added.
- **`docs/user_guide.md`** — §6's webpage-summary command table extended with the new row and clarified wording; §7's Inbox section updated from "two things write to it" to three, with the new `webpage_summary` source_type named; §8's Inbox tab row description updated; §11 and §13 updated to reflect the new command and resolved deferred item.
- **`docs/deferred_decisions.md`** — item 7 updated to "Implemented, Phase 61."
- **`docs/phase_61_completion_report.md`** (this file, new).

No other file was touched. `CommandRouter`, `SecurityManager`, `WebpageReadTool`, `main.py`, and the Batch 1 grammar/orchestrator logic were re-confirmed unchanged and were not modified, per the approved non-goals.

## Exact Help-Output Changes

Before:
```
  summarize webpage <url> / summarise webpage <url> - fetches and AI-summarizes a
  webpage (approval required)
```

After:
```
  summarize webpage <url> / summarise webpage <url> - fetches and AI-summarizes a
  webpage (approval required); does not save to the Inbox
  summarize webpage <url> and save to inbox / summarise webpage <url> and save to
  inbox - same as above, and also saves the summary to the Inbox on success
  (approval required)
```

## Exact Documentation Updates

- **README.md, Phase 34 section**: "The summary is never saved anywhere: no Inbox entry, no file, no database row." → "By itself, this exact command's summary is never saved anywhere: no Inbox entry, no file, no database row. An explicit, separate opt-in command was added later to save it on request instead — see Phase 61 below." The "What is deliberately NOT included" line was similarly updated to describe the distinction (no *automatic* save for the plain command) rather than falsely claiming no Inbox integration exists at all.
- **README.md**: new "## Phase 61 — Explicit Webpage Summary Inbox Save Command (complete)" section (mirroring the Phase 34/57 section style), describing the policy rationale, the new command, and Batch 1's exact safety guarantees.
- **docs/user_guide.md §6**: webpage-summary command table now has two rows (plain, and `... and save to inbox`), with prose clarifying the plain command's Inbox-free guarantee is unchanged and the new variant's save-only-on-real-success behavior.
- **docs/user_guide.md §7**: "Two things write to it" → "Three things write to it," naming the new `webpage_summary` source_type and its exact save semantics; the "search-result snippets and metadata only" claim was corrected to note the webpage-summary producer stores the AI's summary of real fetched text (never raw content) instead.
- **docs/user_guide.md §8**: Inbox tab row updated to mention all three producer kinds.
- **docs/user_guide.md §11/§13**: updated to describe the resolved decision (explicit opt-in, not automatic) rather than listing it as still-undecided.
- **docs/deferred_decisions.md item 7**: "Deferred, unselected" → "Implemented, Phase 61," with a summary of both batches and the policy rationale.

## Dashboard Smoke-Check Result

`test_webpage_summary_source_type_renders_like_any_other_entry` (new, in `tests/unit/test_dashboard_read_model.py`) appends a real `InboxEntry` with `source_type="webpage_summary"` through a real `InboxStore` and confirms `DashboardReadModel.get_recent_inbox_entries()` returns a correctly-populated `InboxRow` (`source_query`, `full_body`, `id`, `created_at` all correct). **Result: passes with zero dashboard code changes** — confirmed directly by reading `dashboard/read_model.py`'s `InboxRow`/`get_recent_inbox_entries()`, which never reference `source_type` at all, so a new producer's entries flow through identically to any other. No dashboard code was touched.

## Confirmation: Base Command Unchanged and Inbox-Free

`summarise webpage <url>` (no trailing phrase) is untouched from Batch 1 — re-confirmed by the full Batch 1 test suite passing unmodified, plus the pre-existing `test_no_inbox_integration_exists_for_this_command` and `test_plain_command_never_creates_an_inbox_entry_even_when_store_configured` both still passing.

## Confirmation: No Auto-Save Added

Saving only ever happens through the explicit `... and save to inbox` grammar, matched by a distinct `CommandRouter` method checked before the base matcher. No code path saves a summary produced by the plain command.

## Confirmation: No Raw Webpage Content Saved

Unchanged from Batch 1 — the saved `body` is always `response.message` (the exact disclosure-labeled AI summary), never the raw extracted webpage text, proven by Batch 1's `test_saved_body_never_contains_raw_webpage_content_only_the_ai_summary`.

## Confirmation: Trust Boundaries Unchanged

Webpage content remains `UNTRUSTED` `AIContextBlock` content, scanned exactly as before — unchanged from Batch 1, re-confirmed by Batch 1's `test_ai_still_receives_untrusted_context_for_save_command` still passing.

## Confirmation: No Other Behavior Changed

No dashboard, scheduler, voice/audio, enum, dependency, empty-trash, permanent-delete, Research Agent, Core service, phone, autonomous, security, approval, or scheduler-schema behavior changed beyond the approved explicit save-command path established in Batch 1. `CommandRouter`'s grammar, `SecurityManager`'s rules, `WebpageReadTool`, and `main.py` were not touched in Batch 2. No new dependency; `pyproject.toml` unchanged.

## Tests Run and Results

```
Batch 2 focused: test_help_tool.py + test_help_output_routing_consistency.py +
  test_webpage_summary_approval_end_to_end.py + test_command_router.py +
  test_dashboard_read_model.py                                     — 547 passed

Full suite: poetry run pytest -q                                    — 3693 passed, 3 skipped, 0 failed
(3689 Batch-1 baseline + 4 net-new: 1 new parametrized phrase in
test_help_tool.py, 1 new focused help-distinction test, 1 new
representative phrase in test_help_output_routing_consistency.py, 1
new dashboard smoke-check test)
```

## Touched-File Ruff Result

```
poetry run ruff check tools/builtin/help_tool.py \
    tests/unit/test_help_tool.py \
    tests/unit/test_help_output_routing_consistency.py
All checks passed!
```

(`tests/unit/test_dashboard_read_model.py` carries 11 pre-existing `E402` warnings from an established `pytest.importorskip("sqlalchemy")`-before-imports pattern, confirmed via `git stash` to be identical before and after this phase's edit — not introduced by this change.)

## git diff --check Result

Clean.

## Final Git Status

```
 M README.md
 M docs/deferred_decisions.md
 M docs/user_guide.md
 M tests/unit/test_dashboard_read_model.py
 M tests/unit/test_help_output_routing_consistency.py
 M tests/unit/test_help_tool.py
 M tools/builtin/help_tool.py
?? dashboard_test.txt
?? docs/phase_61_completion_report.md
```

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout both batches.
- No security, approval, or trust-boundary behavior changed beyond what Batch 1 already established and this batch merely documented.

## Remaining Future Choices

Item 7 is now resolved. Unchanged, named descriptively in `docs/deferred_decisions.md`: the fate of `IntentType`/`ActionType`/`OnFailure`/`MemoryType`, real push-to-talk/voice planning, empty-trash/cleanup/retention policy, scheduler schema, dashboard write actions, and a Research Agent all remain exactly as deferred as before.

---

## Status Statement

**Phase 61 complete for its defined scope, across both batches: an explicit `summarise webpage <url> and save to inbox` command now saves a successful webpage summary to the Inbox as `source_type="webpage_summary"`, reusing the existing YELLOW approval gate, existing trust boundaries, and the existing Inbox-save-and-audit pattern — while the original `summarise webpage <url>` command remains completely unchanged and Inbox-free. Documentation (HelpTool, README, user guide, deferred decisions) is fully current, and a dashboard smoke check confirms no dashboard code change was needed.**
