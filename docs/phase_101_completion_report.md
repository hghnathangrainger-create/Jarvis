# Phase 101 Completion Report — Missing/Invalid Required-Argument Guidance V1

## Commits

| Stage | Commit |
|---|---|
| Planning gate | `dee26fc` |
| Batch 1 (dormant foundation) | `c2e7b25` |
| Batch 2 / closure (live integration) | *(recorded at commit time — see `git log`)* |

## What Phase 101 closes

Jarvis can now turn a specific, narrow class of ambiguous "ask jarvis to:" request — a clearly-identified action missing (or malformed) its one required argument — into a precise, deterministic retry instruction, instead of a generic refusal, for five capabilities: `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`, `SCHEDULE_SHOW_ENABLED_STATE`, `MEMORY_SEARCH`, `PROJECT_STATE_UPDATE_PHASE`.

## Architecture

`intelligence/actionable_decision_issue.py` (Batch 1, hardened before Batch 2):

- `ActionableIssueKind` (`MISSING_REQUIRED_ARGUMENT`, `INVALID_ARGUMENT_FORMAT`), `ActionableDecisionIssue`, a fixed five-capability guidance specification, and `format_actionable_decision_issue()`.
- Three classifiers, all reusing the real, **completely unmodified** `intelligence.grounding.ground_decision()` as sole authority — never a new grounding call's logic, never a second independent evidence path:
  - `classify_actionable_issue_from_ungrounded_selection()` reuses a live `ground_decision()` call's own already-computed evidence directly.
  - `classify_actionable_issue_from_invalid_output()` gates on the new, stable `ToolSelectionParseErrorKind` (never the human-readable `.reason` string), peeks the model's claimed capability id, then re-confirms it via a fresh `ground_decision()` probe with a fixed sentinel argument.
  - `classify_actionable_issue_from_unsupported()` has no model capability id to start from and relies entirely on request text, probing each allowlisted capability the same way.

`intelligence/structured_output.py` (hardening step before Batch 2):

- New `ToolSelectionParseErrorKind` enum (`MISSING_REQUIRED_ARGUMENT`, `INVALID_ARGUMENT_TYPE`, `EMPTY_STRING_ARGUMENT`, `OTHER`).
- `ToolSelectionParseError` gained one new optional keyword field, `kind`, defaulting to `OTHER`. Only the three raise sites describing the required argument itself being absent/invalid set a non-default kind; every other raise site, and every existing `.reason`-only caller, is unchanged.

`intelligence/planning.py`: `PlanningOutcome` gained one new optional field, `actionable_issue`, populated at the three existing failure branches inside `select_tool()`.

`core/orchestrator.py`: `_handle_ask_jarvis_to_request()`'s three relevant branches (`INVALID_OUTPUT`, `UNSUPPORTED`, `UNGROUNDED_SELECTION`) each gained one check: render `format_actionable_decision_issue(outcome.actionable_issue)` when set, otherwise the exact, unchanged, pre-existing generic message.

## Live integration point

`core/orchestrator.py::_handle_ask_jarvis_to_request()` — the single existing function already producing every `ask jarvis to:` response. No new call site, no second AI call, no change to `PlanningOutcomeKind`, `outcome.plan`, or any `EXECUTABLE*`/compound branch.

## Live messages (all five capabilities)

| Capability | Missing | Invalid |
|---|---|---|
| `SCHEDULE_ENABLE` | "I need the schedule ID before I can prepare this action. Try: ask jarvis to: enable schedule \<schedule id\>. Enabling a schedule will still require approval." | "The schedule ID must be a whole number. Try: ...same retry/approval clause..." |
| `SCHEDULE_DISABLE` | Same shape, "disable" | Same shape, "disable" |
| `SCHEDULE_SHOW_ENABLED_STATE` | "I need the schedule ID before I can prepare this action. Try: ask jarvis to: check the enabled state of schedule \<schedule id\>." (no approval clause) | Same shape, "must be a whole number" |
| `MEMORY_SEARCH` | "I need the search text before I can prepare this action. Try: ask jarvis to: search memories for \<search text\>." (no approval clause) | Not applicable in V1 (no concrete string-format violation beyond absence) |
| `PROJECT_STATE_UPDATE_PHASE` | "I need the phase value before I can prepare this action. Try: ask jarvis to: update my project phase to \<phase value\>. Updating the project phase will still require approval." | N/A (string argument) |

## Behaviour across the three model-dependent outcomes

Proven directly, live, end-to-end: for `"enable schedule"` (no id), a model that omits the argument (`INVALID_OUTPUT`), one that hallucinates a value grounding independently rejects (`UNGROUNDED_SELECTION`), and one that returns `"unsupported"` all produce **byte-identical** guidance text. Repeated for `"search memories for"` (a string-argument capability).

## Independent current-request evidence

Confirmed live: a vague request ("do something with my schedules"), a negated request, a conflicting request, an ambiguous multi-signature request, a model/request disagreement (model claims `schedule_enable`, request text names `memory_search`'s own action instead), and a non-allowlisted capability all retain their exact pre-existing generic message — never guidance.

## Missing vs. invalid

Both classifications come from a fresh, independent `ground_decision()` probe against the real request text — word numbers ("twelve"), decimals ("4.5"), negative numbers ("-5"), and unrelated trailing prose all classify as `INVALID_ARGUMENT_FORMAT`; a marker with nothing after it classifies as `MISSING_REQUIRED_ARGUMENT`. No new argument-format rule was invented; no coercion of any kind occurs.

## Stateless retry, proven live

A first incomplete request returns guidance and creates zero durable rows. A later, independent request of a bare `"12"` is never bound to it — no schedule is enabled, no approval exists, the response never mentions "enable." A later, complete, valid request reaches the exact, unchanged, pre-existing approval-gated or immediate-execution pipeline.

## Verified Action Context isolation, proven live

With real historical evidence seeded (a verified schedule 12, a verified ProjectState phase value) through a genuinely wired `VerifiedActionContextBuilder`, a current incomplete request still renders the fixed placeholder (`<schedule id>`, `<phase value>`) — the historical value never appears anywhere in the response.

## Zero side effects

For every actionable-guidance response across all five capabilities and both missing/invalid cases: zero `PendingApprovalStore` rows, zero `PausedWorkflowStore` rows, zero `CompoundWorkflowProgressStore`/`ScheduleCompoundWorkflowProgressStore` rows, and zero `tool_call` log events.

## Valid-request and compound regression, proven live

All five capabilities' valid requests reach their existing, correct behaviour unchanged (GREEN reads execute immediately; YELLOW writes reach the existing "Confirmation required..." approval-gated response). Both existing compound grammars (ProjectState phase-update-and-show, schedule enable-and-check) remain fully unchanged, including the genuinely-different-clause-ids case, which still receives its existing generic compound message — `CLAUSE_ARGUMENT_MISMATCH` remains untouched and un-reclassified, exactly as deferred.

## Test results

- New Batch 2 live integration file: 47/47 passing.
- Batch 1 file (revised for the stable-discriminator signature change and the one now-legitimate live call site): 74/74 passing.
- `structured_output` full suite (proving the additive `kind` field changes nothing existing): 257/257 passing.
- Regression (`-k "phase101 or intelligence_planning or grounding or structured_output or compound or phase98 or phase99 or phase100 or approval or orchestrator"`): see validation section of the delivered report.
- Full suite, all three environments (normal / `AI_REASONING_ENABLED=false` / `PYTHON_DOTENV_DISABLED=1`): see validation section.

## Explicit non-goals (confirmed at closure)

No stateful clarification or pending-intent persistence. No new table or migration. No compound correction guidance — `CLAUSE_ARGUMENT_MISMATCH` and every other compound-only reason remain generic, deferred. No capability-collision guidance (deferred). No typed verification. No third compound workflow. No second AI call anywhere in the classification or rendering path. No Prompt Studio change. No CommandRouter grammar change. No capability catalogue expansion. `dashboard_test.txt` never touched.

Phase 101 is formally closed. Phase 102, typed verification, and a third compound workflow were not started.
