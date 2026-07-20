# Phase 93 — Safe Read-Only Intelligence Expansion V2 — Planning Gate

**Status: Planning gate only. No production or test code has been implemented.**

---

## 1. Current Baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD at the start of this planning gate: `04fa06c` (Phase 92 Batch 2 and closure).
- Verified baseline: **4760 passed, 3 skipped, 0 failed**.
- Phase 90 — Jarvis Intelligence Core V1: closed.
- Phase 91 — Safe Intelligence Capability Expansion: closed.
- Phase 92 — Intelligence Decision Grounding and Reliability V1: formally closed (`04fa06c`); the follow-up Ruff-scope verification pass confirmed all 8 changed Python files pass with zero findings, with no code changes.
- Manual Anthropic API acceptance remains postponed (insufficient account credits) — an external limitation, not a code defect; see §19.

---

## 2. Production and Test Architecture Inspected

**Intelligence Core (read, no changes made):**
- `intelligence/capability_catalog.py` — `CapabilityId`, `ExecutionStrategy`, `CapabilityArgumentSpec`, `CapabilityAdapter`, `CAPABILITY_CATALOG` (7 entries: 6 model-selectable + 1 internal-only `PROJECT_STATE_VERIFY_FOCUS`), `_FIXED_ARGUMENTS_BY_CAPABILITY`, `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`, `build_tool_input()`.
- `intelligence/planning.py` — `select_tool()`'s exact execution order (structured parsing → argument validation → `ground_decision()` → `_preflight_capability()` → execution-strategy branch), `PlanningOutcomeKind` (including Phase 92's `UNGROUNDED_SELECTION`), `_TRUSTED_PLANNING_INSTRUCTION` (currently documents exactly six model-selectable capabilities).
- `intelligence/grounding.py` — `ground_decision()`, `UngroundedReason` (7 bounded values), `_IntentSignature` (action tokens, domain tokens/phrases, qualifier tokens — every dimension required independently), the six existing signatures, the negation/conflict gate, the two existing argument-span extractors.
- `intelligence/structured_output.py` — the strict three-key JSON schema, per-capability argument validation (`_validate_string_argument`), rejection of unknown/extra/wrongly-typed arguments.
- `core/orchestrator.py` — `_handle_ask_jarvis_to_request()`'s exact outcome-kind branching (`PROVIDER_UNAVAILABLE`/`PROVIDER_FAILED`/`INVALID_OUTPUT`/`UNSUPPORTED`/`EXECUTABLE_WORKFLOW`/`UNGROUNDED_SELECTION`/`EXECUTABLE` fallthrough), the two Phase 92 public refusal messages.
- `core/command_router.py` — existing deterministic grammar for `approval_history` (line ~793), `workflow_history` (line ~808), `quarantine_list` (line ~888), and `info` (line ~1043, via `_INFO_KEYWORDS`).
- `security/security_manager.py` — the generic `"list"`/`"show"` GREEN rules (lines 256–257) that already classify every candidate tool's `action_for()` string.

**Candidate tools inspected (production, unmodified):**
- `tools/builtin/quarantine_list_tool.py` (`QuarantineListTool`, registered as `"quarantine_list"`).
- `tools/builtin/workflow_history_tool.py` (`WorkflowHistoryTool`, registered as `"workflow_history"`).
- `tools/builtin/approval_history_tool.py` (`ApprovalHistoryTool`, registered as `"approval_history"`).
- `tools/builtin/info_tool.py` (`InfoTool`, registered as `"info"`).
- `workflow/workflow_history_store.py` (`WorkflowHistoryRecord`, `WorkflowHistoryStore`, `KNOWN_WORKFLOW_STATUSES`).
- `approval/approval_history_store.py` (`ApprovalHistoryRecord`, `ApprovalHistoryStore`, `KNOWN_APPROVAL_STATUSES`).
- `quarantine/quarantine_store.py` (`QuarantineStore`, `get_by_quarantine_path()`).
- `config/constants.py` (`APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION` — the exact static values `InfoTool` returns).
- `main.py` (production wiring — confirmed all four candidate tools are already registered and live: `InfoTool()` at line 191, `QuarantineListTool(quarantine_store)` at line 211, `ApprovalHistoryTool(approval_history)` at line 227, `WorkflowHistoryTool(workflow_history)` at line 236).

**Existing tests inspected (unmodified):**
`tests/unit/test_quarantine_list_tool.py`, `tests/unit/test_main_quarantine_list_wiring.py`, `tests/unit/test_workflow_history_tool.py`, `tests/unit/test_workflow_history_store.py`, `tests/unit/test_cli_workflow_history.py`, `tests/unit/test_approval_history_tool.py`, `tests/unit/test_approval_history_store.py`. No test file exists for `InfoTool` (confirmed via directory listing — `tests/unit/` contains no `test_info_tool.py` or equivalent).

---

## 3. Candidate Inventory

Per the task's own instruction, the planning labels (`QUARANTINE_LIST`, `WORKFLOW_HISTORY`, `APPROVAL_HISTORY`, `INFO`) were not assumed to be existing enums. Inspection confirms the real, corresponding production tools are `quarantine_list`, `workflow_history`, `approval_history`, and `info` respectively — all four already registered, already GREEN-classified, already deterministically reachable, and already individually tested (except `info`, which has no test file).

---

## 4. Per-Candidate Input and Output Contracts

### `quarantine_list` (`QuarantineListTool`)
- Input: none recognised (`run()` reads no `input_data` keys at all).
- Output: iterates **every** entry in `.jarvis_trash/` with no limit, no pagination, and no truncation of any kind. Each file line reports: filename, size in bytes, a modified/quarantined timestamp, and — when a `QuarantineStore` record exists — the file's **recorded original filesystem path** (or an honest `"unknown (quarantined before metadata tracking)"` fallback). Unsupported (non-file) directory entries are also named.
- Real tool: unmodified since Phase 72, Batch 2.

### `workflow_history` (`WorkflowHistoryTool`)
- Input: `operation` (`"history"` default, `"recent"`, or `"get"`); `workflow_id` (required only for `"get"`).
- Output: `"history"` calls `WorkflowHistoryStore.list_recent(limit=20)`; `"recent"` calls it with `limit=10`; `"get"` calls `list_for_workflow(workflow_id)` (unbounded — a real, single workflow's full transition count is used, never a synthetic cap, but bounded in practice by that workflow's own step count, which the deterministic two-step or single-tool execution strategies keep small). Every list operation's header reports a real, honest, recent-activity-scoped status breakdown (Phase 73, Batch 2).
- Fields per record: `workflow_id`, `status`, `step_number`/`step_total`, `created_at` (UTC timestamp), `tool_name`, `approval_request_id`, `detail` (documented, and confirmed by inspecting every real `record_transition()` call site in `workflow/engine.py`, as **content-free** — fixed strings like `f"workflow_id={workflow_id} steps={len(plan.steps)}"`, `f"steps_completed={len(outcomes)}"`, or a generic `tool_result.error`/`"Awaiting your confirmation."` fallback; never a raw model-supplied argument value).

### `approval_history` (`ApprovalHistoryTool`)
- Input: `operation` (`"history"` default, `"recent"`, `"approved"`, `"declined"`, or `"get"`); `request_id` (required only for `"get"`).
- Output: `"history"` calls `list_recent(limit=20)` with an all-time per-status breakdown header; `"recent"` uses `limit=10`; `"approved"`/`"declined"` call `list_by_status(status, limit=20)` with an honest `"[showing N of M ...]"` truncation footer when more exist.
- Fields per record: `request_id`, `status`, `action` (confirmed, by inspecting `ProjectStateUpdateTool.action_for()` and every other candidate tool's `action_for()`, to always be a **fixed, generic string** such as `"update jarvis project state"` — never the actual field/value being changed), `reason` (a fixed, rule-level `SecurityManager` explanation string, e.g. from `_Rule(...)`'s own `reason` field — never free text tied to a specific argument value), `security_tier`, `created_at`, `decided_at`/`decided_by` (when decided), `decision_reason` (an optional, user-supplied free-text note attached to the decision itself — in this single-user system this is Nathan's own prior note being read back to him, not a third-party privacy exposure, and it is never a captured tool argument).

### `info` (`InfoTool`)
- Input: none.
- Output: exactly three fixed lines — `APP_NAME` (`"Jarvis"`), `APP_VERSION` (`"0.1.0"`), `APP_DESCRIPTION` (`"Jarvis AI Operating System"`) — all static `Final` constants from `config/constants.py`. No configuration values, no environment variables, no paths, no model names, no per-instance state of any kind.

---

## 5. Data-Exposure Assessment

| Candidate | Filesystem paths | Filenames | Record IDs | Timestamps | Free-text/argument risk | Overall |
|---|---|---|---|---|---|---|
| `quarantine_list` | **Yes — real original paths** | Yes | No | Yes | Low (metadata only, but paths are exactly the kind of filesystem structure the task's default-deferral policy targets) | **High exposure, unbounded** |
| `workflow_history` | No | No | Yes (`workflow_id`, `approval_request_id`) | Yes | Low (`detail` confirmed content-free by real call-site inspection) | Low |
| `approval_history` | No | No | Yes (`request_id`) | Yes | Low (`action`/`reason` confirmed fixed strings; `decision_reason` is Nathan's own note, not a captured argument) | Low |
| `info` | No | No | No | No | None (fully static) | None |

**`quarantine_list` exposes real, original filesystem paths and has no result limit whatsoever** (confirmed: `run()` calls `sorted(quarantine_dir.iterdir(), ...)` with no slicing, and no existing test exercises or asserts any bound). This is exactly the filesystem-facing, unbounded shape the task's default-deferral policy is written for. **Recommendation: defer, not select, for Phase 93** — not merely because it is GREEN, but because (a) it discloses real original paths that could reveal directory/filesystem structure never otherwise exposed through the Intelligence Core, and (b) it has no deterministic bound, violating the result-bounding requirement outright. A narrower, bounded, path-redacting summary adapter is a plausible future direction but does not exist today and is out of scope for this phase (see §8).

---

## 6. Security Classifications

All four candidates classify **GREEN** via the existing, unmodified generic rules in `security/security_manager.py`:
- `quarantine_list` → `action_for()` returns `"list quarantine"` → GREEN via the generic `"list"` rule (line 256).
- `workflow_history` → `"show workflow history"` / `"show recent workflows"` / `"show workflow details"` → GREEN via the generic `"show"` rule (line 257).
- `approval_history` → `"show approval history"` / `"show recent approvals"` / `"show approved actions"` / `"show declined actions"` / `"show approval details"` → GREEN via the same rule.
- `info` → `"show system information"` → GREEN via the same rule.

**No new `SecurityManager` rule is required for any candidate.**

---

## 7. Grounding Feasibility and Collision Analysis

Both viable candidates (`workflow_history`, `approval_history`) fit the existing Phase 92 `_IntentSignature` shape (action tokens + domain tokens + optional qualifier tokens) with no broadening of the grounding mechanism itself:

- **`APPROVAL_HISTORY`**: action tokens `"show"`/`"list"`; domain tokens `"approval"`/`"approvals"`; qualifier token `"history"` (mandatory, mirroring `MEMORY_LIST_RECENT`'s existing action+domain+qualifier shape exactly). Real, existing phrasing: `"show approval history"` (deterministic command grammar already accepts this exact phrase — `core/command_router.py` line ~793).
- **`WORKFLOW_HISTORY`**: action tokens `"show"`/`"list"`; domain tokens `"workflow"`/`"workflows"`; qualifier token `"history"`. Real, existing phrasing: `"show workflow history"` (command grammar already accepts this — line ~808).

**Collision check against all 6 existing signatures**: neither `"approval"` nor `"workflow"` appears as an action, domain, or qualifier token in any of `PROJECT_STATE_SHOW`, `PROJECT_STATE_UPDATE_FOCUS`, `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT`, or `MEMORY_SEARCH`'s signatures — zero overlap. `"history"` as a qualifier is entirely new and appears in neither existing signature, so it cannot be satisfied by any current phrasing.

**Collision check between the two new signatures**: `APPROVAL_HISTORY` and `WORKFLOW_HISTORY` share the qualifier token `"history"` and the action tokens, but their domain tokens (`"approval"`/`"approvals"` vs. `"workflow"`/`"workflows"`) are disjoint — a request can only supply one domain's tokens genuinely, so the catalogue-wide uniqueness rule (§20.3 of the Phase 92 plan) continues to produce exactly one match for any real, direct request. A request naming both domains at once (e.g. "show my approval and workflow history") would correctly match both signatures and be refused as `multiple_signatures_matched` — the same, already-proven Phase 92 behavior, not a new failure mode.

**No broad natural-language parsing, semantic similarity, additional AI call, probabilistic confidence, or large synonym table is required for either signature.** Both reuse the exact token/phrase/qualifier mechanism already shipped in `intelligence/grounding.py`.

`quarantine_list` and `info` are not assigned grounding signatures in this plan since neither is selected (§10).

---

## 8. Result-Bounding Analysis

| Candidate | Default op | Bound | Ordering | Truncation wording | Exact vs. partial | IDs/timestamps/paths safe? |
|---|---|---|---|---|---|---|
| `workflow_history` | `"history"` | **20** (`_DEFAULT_LIMIT`, hard-coded) | most-recent-first (store's own `list_recent()`) | none needed at exactly 20 (the header's status breakdown is itself an honest, separately-computed real count, not a truncation claim) | the 20 shown are exact rows; the breakdown counts are real, separately queried totals | Yes — `workflow_id`/`approval_request_id` are internal correlation ids, no filesystem paths, `detail` confirmed content-free |
| `approval_history` | `"history"` | **20** (`_DEFAULT_LIMIT`) | most-recent-first | the "approved"/"declined" filtered views append an honest `"[showing N of M ...]"` footer when truncated (Phase 76); the default `"history"` view's per-status breakdown is a real, separate all-time count, never implied to be the shown-row count | shown rows are exact; breakdown/footer totals are real, separately queried | Yes — `request_id` is an internal id, `action`/`reason` confirmed fixed strings |
| `quarantine_list` | (only op) | **none** | filename-sorted | none exists | N/A — not bounded at all | No — real original paths |
| `info` | (only op) | N/A (exactly 3 fixed lines) | fixed | N/A | exact | Yes — fully static |

**Only `workflow_history`'s and `approval_history`'s default `"history"` operation is proposed for Phase 93.** Both already have a deterministic, hard-coded 20-record bound built into the real, existing tool — no new limit-enforcement code is needed. The `"recent"`, `"approved"`, `"declined"`, and `"get"` operations are deliberately **not** exposed in Phase 93 (see §13) to keep both new capabilities zero-argument, per the task's explicit preference and the "do not expose optional filters merely because the underlying tool supports them" instruction.

---

## 9. Verification-Framework Reassessment

The task requires reassessing whether Phase 93 should instead introduce a second verified write capability or generalize verification, but only if the repository already contains a genuinely useful existing write action, a real approval path, a clear deterministic postcondition, **and** a narrow verifier that can already prove success.

Inspection of `intelligence/capability_catalog.py` confirms `verification_strategy_id` is `None` for every capability except `PROJECT_STATE_UPDATE_FOCUS` (`"project_state_focus_exact_match"`), and `intelligence/verification.py` implements exactly one verification function, `verify_focus_update()`, with no second strategy anywhere in the module. Other real write-capable tools exist outside the Intelligence Core catalog (e.g. memory update/move/forget, schedule enable/disable, quarantined-file restore) and each already requires YELLOW approval through the deterministic command path, but **none has an existing, narrow, already-built verifier** analogous to `verify_focus_update()` — building one from scratch would itself be new architecture, not reuse, and is explicitly discouraged ("do not create a write capability merely to justify verifier expansion").

**Conclusion: verification generalization remains premature.** No second write capability is proposed. Phase 93 remains a read-only expansion, consistent with the task's own default framing.

---

## 10. Selected Milestone

**Phase 93 — Safe Read-Only Audit History Expansion.**

Add exactly two new model-selectable, zero-argument, GREEN, `SINGLE_TOOL` capabilities to `CAPABILITY_CATALOG`, each a thin wrapper around an already-registered, already-tested tool's existing default (`"history"`) operation — the same proven shape Phase 91, Batch 1 already used for `HEALTH_CHECK`/`SCHEDULE_LIST`/`MEMORY_LIST_RECENT`:

- **`APPROVAL_HISTORY`** → wraps `approval_history`'s default `"history"` operation.
- **`WORKFLOW_HISTORY`** → wraps `workflow_history`'s default `"history"` operation.

**Deferred**: `quarantine_list` (real original-path exposure, no result bound — §5/§8). **Deferred**: `info` (safe but marginal daily value, no existing test coverage, and does not meaningfully add operational intelligence beyond what `HEALTH_CHECK`/`PROJECT_STATE_SHOW` already provide). **Rejected as premature**: a second write capability or verification generalization (§9).

**Rationale against the task's five priorities**: (1) daily usefulness — Nathan actively approves/declines YELLOW actions and benefits from asking "what have I approved recently" or "what happened in that workflow" in natural language, more so than static branding info; (2) low information-exposure risk — both confirmed to expose no filesystem paths and only fixed/content-free text fields; (3) simple deterministic grounding — both reuse the exact existing three-dimension signature shape with zero collision; (4) reuse of existing production tools — both tools are already registered, live, and independently tested; (5) bounded outputs — both already have a hard-coded 20-record limit built into the real tool, requiring no new bounding logic; (6) minimal new architecture — no new `SecurityManager` rule, no new store method, no new execution strategy, no new verifier.

---

## 11. Exact Capability Schemas

### `APPROVAL_HISTORY`
- `tool_name`: `"approval_history"`.
- `arguments`: `()` — exactly zero. The model is never asked for, and can never supply, an `operation` or `request_id`.
- `allowed_strategy`: `ExecutionStrategy.SINGLE_TOOL`.
- `max_execution_tier`: `SecurityTier.GREEN`.
- `verification_strategy_id`: `None`.
- `internal_only`: `False`.
- Real tool input (via `_FIXED_ARGUMENTS_BY_CAPABILITY`, a new entry): `{"operation": "history"}` — a fixed literal, never model-supplied, mirroring `memory_list_recent`'s existing `{"operation": "list"}` pattern exactly.

### `WORKFLOW_HISTORY`
- `tool_name`: `"workflow_history"`.
- `arguments`: `()` — exactly zero.
- `allowed_strategy`: `ExecutionStrategy.SINGLE_TOOL`.
- `max_execution_tier`: `SecurityTier.GREEN`.
- `verification_strategy_id`: `None`.
- `internal_only`: `False`.
- Real tool input (new `_FIXED_ARGUMENTS_BY_CAPABILITY` entry): `{"operation": "history"}`.

Both capabilities require **no** change to `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`, `CapabilityArgumentSpec`, `ExecutionStrategy`, or `build_tool_input()`'s own logic — only two new `CAPABILITY_CATALOG` entries and two new `_FIXED_ARGUMENTS_BY_CAPABILITY` entries, exactly the size and shape of Phase 91, Batch 1's own additions.

---

## 12. Exact Grounding Signatures

To be added to `intelligence/grounding.py`'s `_SIGNATURES` dict, in the same `_IntentSignature(action_tokens=..., domain_tokens=..., qualifier_tokens=...)` shape already used by `MEMORY_LIST_RECENT`:

```
CapabilityId.APPROVAL_HISTORY: _IntentSignature(
    action_tokens=("show", "list"),
    domain_tokens=("approval", "approvals"),
    qualifier_tokens=("history",),
),
CapabilityId.WORKFLOW_HISTORY: _IntentSignature(
    action_tokens=("show", "list"),
    domain_tokens=("workflow", "workflows"),
    qualifier_tokens=("history",),
),
```

- **Required action evidence**: `"show"` or `"list"` — identical vocabulary to `MEMORY_LIST_RECENT`/`SCHEDULE_LIST`, already proven safe and sufficient.
- **Required domain evidence**: `"approval"`/`"approvals"` for the first; `"workflow"`/`"workflows"` for the second — both traceable to the real, existing command-router grammar and each tool's own registered name.
- **Required qualifier**: `"history"` for both — mandatory, mirroring the corrected `MEMORY_LIST_RECENT` design (Phase 92, §20.1) where a qualifier is required *in addition to*, never instead of, genuine action evidence.
- **Likely collisions with current signatures**: none (§7) — no existing signature's action, domain, or qualifier tokens overlap with `"approval"`, `"workflow"`, or `"history"`.
- **Examples proven by existing commands/documentation**: `"show approval history"` and `"show workflow history"` are both already-accepted deterministic command phrasings (`core/command_router.py` lines ~793 and ~808 respectively) — the exact same "already a real, tested phrase" sourcing discipline Phase 92's own signature table required.

The complete, eight-signature catalogue still produces exactly one grounded match for any of these two new accepted phrasings, and the existing six signatures are completely unaffected (no existing signature is edited).

---

## 13. Exact Scope and Non-Goals

**In scope:**
- Two new `CapabilityId` members: `APPROVAL_HISTORY`, `WORKFLOW_HISTORY`.
- Two new `CAPABILITY_CATALOG` entries, each zero-argument, GREEN, `SINGLE_TOOL`, wrapping the real tool's existing default `"history"` operation only.
- Two new `_FIXED_ARGUMENTS_BY_CAPABILITY` entries (`{"operation": "history"}` each).
- Two new `_IntentSignature` entries in `intelligence/grounding.py`.
- Extending `_TRUSTED_PLANNING_INSTRUCTION` in `intelligence/planning.py` to describe eight capabilities instead of six.
- Documentation updates: `docs/user_guide.md`, `tools/builtin/help_tool.py` (only where necessary and truthful).
- Focused, regression, and full-suite tests for both new capabilities, following the exact Phase 91/92 test shape.

**Explicitly out of scope (non-goals):**
- `quarantine_list` (deferred — §5/§8/§10).
- `info` (deferred — §10).
- The `"recent"`, `"approved"`, `"declined"`, or `"get"` operations of either history tool (deferred — zero-argument-only scope, §8).
- Any new `SecurityManager` rule, security-tier change, or classification change.
- Any new write capability, approval path, or verifier.
- Arbitrary `ToolRegistry` exposure, multi-tool plans, retries, replanning, autonomous loops, automatic memory writes, conversation persistence, source-code self-modification, dashboard changes, voice, microphone, wake word, phone integration, browser control, or general computer control.
- Any broadening of the Phase 92 grounding mechanism itself (negation markers, punctuation policy, argument-span mechanism, uniqueness algorithm) — only new, additive signatures are proposed, using the existing mechanism unmodified.
- Any workaround for the manual Anthropic API credit limitation (§19).

---

## 14. Proposed Batch Breakdown

**Medium phase — two batches** (per Nathan's own milestone-sizing rule; both capabilities together are comparable in size/risk to Phase 91, Batch 1's own three-capability addition, but are split into two batches for clearer, separately-reviewable checkpoints):

- **Batch 1 — Capability implementation.** Add both `CapabilityId` members, both `CAPABILITY_CATALOG` entries, both `_FIXED_ARGUMENTS_BY_CAPABILITY` entries, both grounding signatures, extend `_TRUSTED_PLANNING_INSTRUCTION`. Add focused unit tests: catalog entries, grounding signatures (including collision/uniqueness proofs against all 8 signatures), structured-output validation (zero-argument rejection of any supplied argument), planning-layer `select_tool()` integration, and orchestrator-level end-to-end execution proofs (real `ApprovalHistoryTool`/`WorkflowHistoryTool`, real `ToolExecutor`, grounded response). Run focused + Phase 90/91/92 regression + full suite (normal, `AI_REASONING_ENABLED=false`, `PYTHON_DOTENV_DISABLED=1`) + Ruff + `git diff --check`. One commit.
- **Batch 2 — Documentation and closure.** Update `docs/user_guide.md` and `tools/builtin/help_tool.py` (only if truthful and necessary), create `docs/phase_93_completion_report.md`, re-run full verification, formally close Phase 93. One commit.

---

## 15. Test Strategy

Mirrors the exact, established Phase 91/92 pattern:
- **Catalog-level**: both new `CapabilityId` members exist, are non-`internal_only`, declare zero arguments, and produce the exact expected `build_tool_input()` output (`{"operation": "history"}`).
- **Grounding-level**: both new signatures match their own real, existing accepted phrasing exactly once against the full 8-signature catalogue; neither collides with any of the 6 existing signatures or each other's disjoint domain; adversarial/negated/ambiguous phrasing is refused exactly as Phase 92's existing mechanism already guarantees (no new grounding logic is introduced, so no new *mechanism* tests are needed — only new *fixture* tests proving the new signatures behave correctly within the unmodified mechanism).
- **Structured-output-level**: a model response supplying any argument (e.g. `operation`, `request_id`) for either new capability is rejected as an unknown argument, exactly like every other zero-argument capability today.
- **Planning-level**: `select_tool()` returns `EXECUTABLE` for both, with the correct one-step `StructuredPlan`.
- **Orchestrator-level, end-to-end**: real `ApprovalHistoryTool`/`WorkflowHistoryTool` (backed by real, in-memory SQLite `ApprovalHistoryStore`/`WorkflowHistoryStore`, never mocks) execute through the real `ToolExecutor`, produce a `[Jarvis tool result]`-labelled grounded response, and — mirroring Phase 92's own zero-side-effect discipline — a request that fails grounding for either capability causes zero preflight/execution.
- **Regression**: full Phase 90/91/92 focused suites re-run unmodified; advisory `ask jarvis:` and deterministic command paths re-confirmed unaffected.
- **Full suite**: normal environment, `AI_REASONING_ENABLED=false`, and `PYTHON_DOTENV_DISABLED=1` — zero failures required in all three, matching Phase 92 Batch 2's own verification bar.

---

## 16. Acceptance Criteria

Phase 93 may be closed only when:
- `APPROVAL_HISTORY` and `WORKFLOW_HISTORY` are both selectable, zero-argument, GREEN, execute through the real, unmodified `ToolExecutor`, and produce grounded, verbatim tool output.
- Both have a working, collision-free grounding signature verified against the complete 8-signature catalogue.
- All 6 existing capabilities, the advisory `ask jarvis:` path, and every deterministic command remain unchanged and passing.
- Focused, regression, and full-suite tests (all three environment configurations) pass with zero failures.
- Ruff is clean (or all findings are confirmed pre-existing and unrelated) on every file changed.
- `git diff --check` is clean.
- Documentation is truthful and updated only where necessary.
- No capability beyond the two named above was added; no new write action, security rule, or verifier was introduced.

---

## 17. Risks and Mitigations

- **Risk**: a future capability might need a genuinely different qualifier word that collides with `"history"`. **Mitigation**: none exists today; the catalogue-wide uniqueness rule would refuse any genuine future collision rather than silently misroute, exactly as Phase 92 already guarantees for the existing six.
- **Risk**: `approval_history`'s `decision_reason` field could, in an unusual case, contain a note that inadvertently mentions a sensitive value Nathan typed at decision time. **Mitigation**: this is Nathan's own prior free-text note in a single-user system, already visible via the existing deterministic `"show approval history"` command today — Phase 93 adds no new access path beyond an additional phrasing, and does not change what data is stored or shown.
- **Risk**: exposing `workflow_history`/`approval_history` through the AI path could be perceived as expanding audit-log exposure. **Mitigation**: both are already fully deterministic, already GREEN, already reachable via existing command grammar, and Phase 93 adds no new field, no new store query, and no new limit — only a second access phrasing through the already-safe grounded pipeline.
- **Risk**: scope creep toward also including `"recent"`/`"approved"`/`"declined"`/`"get"` operations. **Mitigation**: explicitly excluded in §13; only the zero-argument default operation is in scope for V1.

---

## 18. Stop Conditions

- Stop and report if implementation reveals `approval_history`'s or `workflow_history`'s default `"history"` operation is not, in fact, bounded at exactly 20 records by the real, current store implementation.
- Stop and report if any real, currently-accepted phrasing for `"show approval history"` or `"show workflow history"` fails to satisfy its own proposed signature exactly once against the full 8-signature catalogue.
- Stop and report if extending `_TRUSTED_PLANNING_INSTRUCTION` is found to require anything beyond a mechanical extension of the existing eight-capability description pattern.
- Stop and report, and propose a narrower design, if either capability is found to require any argument, filter, or synonym beyond what this plan specifies.
- Stop after Batch 2's closure report. Do not begin Phase 94 or any other unrelated work without Nathan's explicit approval.

---

## 19. Manual API Limitation

Live Anthropic manual acceptance remains **postponed** because the configured API account lacks sufficient credits. This is an external account limitation, not a Jarvis code failure. No production behavior will be changed to bypass it. Phase 93, like Phases 90–92 before it, must remain fully verifiable through deterministic, fake-provider, and full-suite tests — never through a claimed live-model acceptance run.
