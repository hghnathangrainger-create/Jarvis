# Phase 99 Completion Report — Second Bounded Compound Template (Schedule Enable/Show)

## Commits

| Stage | Commit |
|---|---|
| Planning gate | `fa2f983` |
| Batch 1 (dormant foundation) | `f7b956f` |
| Batch 2 (dormant lifecycle) | `e019ba8` |
| Batch 3 / closure (live activation) | *(recorded at commit time — see `git log`)* |

## Exact live grammar

Standalone GREEN read: `ask jarvis to: check the enabled state of schedule <id>`

Compound: `ask jarvis to: enable schedule <id> and then check the enabled state of schedule <same id>`

The schedule id must be identical in both clauses; a mismatch, a malformed id, a missing id, negation, `schedule_disable` substitution, or `schedule_list` substitution are all refused before any plan, approval, or execution exists.

## Exact trusted plan

1. `SCHEDULE_ENABLE(schedule_id)` — YELLOW, requires approval
2. `SCHEDULE_VERIFY_ENABLED_STATE(schedule_id)` — GREEN, internal-only, `verification_field_name="enabled_str"`, `verification_expected_value="true"`
3. `SCHEDULE_SHOW_ENABLED_STATE(schedule_id)` — GREEN, real user-facing capability, gated on Step 2's verified outcome

## Atomic activation flow

`intelligence.planning.select_tool()`'s discriminator peek → `_select_compound_tool_sequence()`'s two-template dispatch (ProjectState template tried first via `ground_compound_decision()`; only a `TEMPLATE_NOT_ALLOWED` result triggers a second attempt via `ground_schedule_compound_decision()`, since the two templates' declared capability pairs are structurally disjoint) → `_build_schedule_compound_outcome()` builds the trusted three-step Plan via the (already-existing, Batch 1) `_build_schedule_enable_verify_show_workflow_plan()` → `JarvisOrchestrator._start_schedule_enable_and_show_workflow()` runs the Plan through the real, unmodified `WorkflowEngine`, then calls `establish_schedule_compound_progress_or_isolate()` **before** returning the actionable approval → one honest approval → `JarvisOrchestrator._claim_and_resume_workflow()` claims via the existing, generic `ApprovalManager.claim_for_resume()`, recognizes the template via `_compound_step_observer_for()`, attaches `ScheduleCompoundStepObserver` only when recognized → `WorkflowEngine.resume()` executes with the observer attached, `CompoundCheckpointError` caught before any generic exception handler → `translate_schedule_compound_workflow_result()`'s six bounded outcomes → `main.reconcile_claimed_handoffs()`'s schedule-compound-first startup recovery ordering.

This entire path was wired in one commit; there was never an intermediate committed state with only part of it live.

## Approval/progress ordering proof

`establish_schedule_compound_progress_or_isolate()` is called, and must succeed, before `_start_schedule_enable_and_show_workflow()` ever returns the actionable `JarvisResponse` carrying the approval request. If it fails, the pending approval and paused workflow are terminally isolated by that function itself, using only existing bounded APIs (`ApprovalManager.invalidate_pending()`, `PausedWorkflowStore.delete()`) — the approval is never shown. Proven directly in `TestApprovalAndProgressOrdering::test_progress_exists_before_approval_is_returned`.

## Observer attachment boundary

`ScheduleCompoundStepObserver` is attached only inside `_compound_step_observer_for()`, called only from `_claim_and_resume_workflow()`, itself reached only after `ApprovalManager.claim_for_resume()` has already succeeded. A decline never attaches it at all — `_terminalize_declined_schedule_compound_progress()` runs instead, and the generic `WorkflowEngine` decline contract (zero `before_step()` calls, zero tool/verifier/read calls) is completely unaffected, identical to the ProjectState template's own proven contract.

## Checkpoint pause semantics

`workflow.engine.CompoundCheckpointError` and the `_CompoundStepObserver` Protocol are both fully generic (confirmed by direct source inspection before reuse) and were reused as-is — never duplicated. `_claim_and_resume_workflow()` catches `CompoundCheckpointError` before its generic `except Exception:` handler, for both templates identically: the handoff is left exactly `CLAIMED`, no synthetic terminal workflow history is written, and durable/in-memory paused state is preserved for a later, exclusive startup reconciliation pass to resolve.

## Six-outcome mapping (schedule template)

| Outcome | Condition | User-facing claim |
|---|---|---|
| `FULL_SUCCESS` | Enable completed, verified `"true"`, exact read completed | States the schedule id and that it is enabled |
| `ENABLE_FAILURE` | Step 1 did not complete | "did not complete" — never claims verification or read occurred |
| `VERIFICATION_MISMATCH` | Verifier ran, `enabled_str != "true"` | States the enable may have run but persisted state disagrees; never runs/claims Step 3 |
| `VERIFICATION_UNAVAILABLE` | Verifier did not produce a usable result | "could not be completed" — never fabricates enabled/disabled |
| `FINAL_SHOW_FAILURE` | Verified `"true"`, but Step 3 failed | Acknowledges enable+verification succeeded, never collapsed into `ENABLE_FAILURE` |
| `INTERRUPTED` | No `WorkflowResult` (checkpoint interruption) | Paused/recoverable — never presented as success or ordinary failure |

Declined/expired pristine work is a separate, seventh case handled entirely outside this translator: `NOT_EXECUTED`, never routed through it.

## Decline and expiry semantics

Decline: `ApprovalManager.decline()` → `_claim_and_resume_workflow()` recognizes the template, calls `_terminalize_declined_schedule_compound_progress()` (idempotent, CAS-backed `mark_not_executed_before_start()`), never attaches the observer, handoff remains `DECLINED`.

Expiry: no live hook exists (mirrors ProjectState); `main.reconcile_claimed_handoffs()`'s startup repair pass (`terminalize_declined_or_expired_schedule_compound_progress()`) is the sole mechanism, terminalizing only pristine rows, never overwriting started work, handoff remains `EXPIRED` until consumed.

## Startup recovery ordering

`main.reconcile_claimed_handoffs()`: approval-history repair → ProjectState pristine-progress repair → schedule pristine-progress repair → ProjectState claimed reconciliation → schedule claimed reconciliation → ProjectState terminalize-pristine-declined/expired → schedule terminalize-pristine-declined/expired → existing, unchanged generic `CLAIMED` fallback (only ever sees rows neither compound-specific pass resolved). The two compound reconcilers never act on the same handoff — their trusted fingerprints are structurally disjoint.

The Batch 2 ambiguous-execution safety rule is preserved unmodified: if a schedule was already enabled before an interrupted Step 1 and remains enabled after, `reconcile_schedule_enable()` reports `POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED`, never falsely concluding the write executed — the row is flagged `NEEDS_RECONCILIATION` and left `CLAIM_INTERRUPTED`, proven in `test_ambiguous_pre_execution_interruption_is_not_falsely_confirmed`.

## Interlock

No second locking system was introduced. Claim-before-resume uses the existing, unmodified `ApprovalManager.claim_for_resume()`/CAS primitives; a failed claim (already claimed/consumed) executes zero tools, proven directly. The observer is constructed only after a successful claim. The OS `ExecutionProcessLock` and its DB-path-derived boundary are untouched.

## Tests and validation

**New/updated test files:** `tests/unit/test_phase99_batch3_live_schedule_compound_activation.py` (30 tests: decision activation/grounding/mutual non-collision, approval/progress ordering, successful execution, six-outcome translation, checkpoint handling, decline/expiry, interlock, restart/crash recovery); revisions to `tests/unit/test_phase99_batch1_isolation.py`, `tests/unit/test_phase99_batch2_dormant_isolation.py`, `tests/unit/test_compound_isolation.py`, `tests/unit/test_phase98_batch1_isolation.py`, `tests/unit/test_production_approval_wiring.py` (confinement sets widened to the exact new named call sites the live activation legitimately introduced — never weakened, never blanket-relaxed).

**Focused:** all new/updated files pass in isolation.

**Regression** (`-k "compound or schedule or phase98 or phase99 or approval or workflow or orchestrator or planning or grounding"`): 2651 passed.

**Full suite**, all three environments (normal / `AI_REASONING_ENABLED=false` / `PYTHON_DOTENV_DISABLED=1`): **5962 passed, 3 skipped, 0 failed**, identical (up from 5933 at Batch 2 — 29 net new tests, all passing).

**Ruff:** Batch 3 scope (9 files) and complete Phase 99 range (35 files): all checks passed, both scopes.

**`git diff --check`:** clean over both the Batch 3 range and the complete Phase 99 range.

**`git status`:** only `?? dashboard_test.txt` — confirmed untouched and untracked throughout Phase 99.

## Explicit non-goals (confirmed at closure)

- No third compound template exists or was started.
- No generic compound registry, discovery mechanism, or generalized multi-step/arbitrary-chain planner was introduced anywhere.
- `SCHEDULE_LIST`'s ordering, limit, and output are untouched.
- The verification engine's string-only `verification_expected_value` contract was never generalized.
- Phase 98's own ProjectState compound — recognizer, progress store, observer, translator, recovery — is byte-for-byte unchanged in behavior.
- `dashboard_test.txt` was never touched.

Phase 99 is formally closed. Phase 100 has not been started.
