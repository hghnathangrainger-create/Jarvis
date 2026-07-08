# Jarvis — Phase 8 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 8 — Real External-Content Ingestion (Batches 1–3, complete)
**Date:** 2026-07-08

---

## Executive Summary

Phase 8 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_8_implementation_plan.md`: it is the first phase in which genuine external content — a real file's contents — is intentionally read and supplied to the advisory AI reasoning path, through the Phase 7 trusted/untrusted context boundary, completely unmodified.

Phase 8 is deliberately narrow. It does not build a general research or knowledge-ingestion system. It adds exactly one source — local file content, via the existing, already-hardened `FileReadTool` — and proves, with a real temporary file rather than a synthetic string, that the Phase 7 defence (typed trust, automatic injection scanning, audited detection, an audited unexpected-action policy) generalises correctly to genuine external content. No new AI authority, no new approval gate, and no change to any GREEN/YELLOW/RED classification were introduced anywhere in this phase.

Three batches delivered this:

- **Batch 1 — File Content Ingestion Foundation.** A new, narrow, file-specific module, `ai/file_ingestion.py`, that owns the one acquisition call needed to read a file and label it as untrusted AI context, establishing provenance by construction rather than by convention. A real defect found during Phase 8's own architecture review was fixed at its strongest boundary: `AIReasoningRequest` now carries a typed `context_block: AIContextBlock | None` instead of a raw string the reasoning engine had to guess a trust label for.
- **Batch 2 — Command and Orchestrator Wiring.** An explicit `summarise file <path>` / `summarize file <path>` command, recognised in `CommandRouter`, coordinated by one new, terminal `JarvisOrchestrator` method that reuses — never duplicates or bypasses — the existing Batch 4 unexpected-action evaluation and audit methods.
- **Batch 3 — End-to-End Security Verification and Documentation.** This report, a README update, and an extended consolidated integration test proving the complete real stack against genuine file content, including a real injection attempt.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and every test — including every new Phase 8 test — uses a fake provider. No live Claude API call is made anywhere in this codebase's test suite.

---

## Phase 8 Purpose

Phase 7 completed the Master Specification's prompt-injection defence while deliberately feeding it no real external content — every Phase 7 test proved the defence against synthetic untrusted strings. Phase 8 closes that gap for exactly one source: local file content, read at the user's explicit request. Its purpose is narrow and specific — prove the Phase 7 trust boundary holds under genuine content, and leave behind an ingestion pattern (acquire → label atomically → forward unchanged) that a future content source can reuse rather than reinvent, without building that shared framework prematurely.

---

## What Was Added

### Batch 1 — File Content Ingestion Foundation
- `ai/file_ingestion.py`: `ingest_file_for_ai(executor, path, *, session_id=None, max_chars=4000) -> FileIngestionResult`. This function is the sole caller of `ToolExecutor.execute("file_read", ...)` for this purpose — it never accepts a pre-existing `ToolResult`, never accepts file content and a source label as independently-supplied values, and never accepts a caller-supplied trust level. On success it returns `AIContextBlock.from_untrusted(text, source=f"file:{path}")`; on failure it returns the underlying `ToolResult.error` unchanged, never a raised exception.
- `FileIngestionResult` enforces, via `__post_init__`, that exactly one of `context`/`error` is ever set — a contradictory state (both, or neither) raises `ValueError` at construction, closing a gap between the type's own documented contract and what it originally enforced.
- `ai/reasoning_models.py`: `AIReasoningRequest.context: str = ""` replaced entirely with `context_block: AIContextBlock | None = None`.
- `ai/reasoning_engine.py`: `reason()` no longer constructs an `AIContextBlock` or hardcodes `source="conversation_history"` — it forwards `request.context_block` to `AIRouter.route()` completely unchanged.

### Batch 2 — Command and Orchestrator Wiring
- `core/command_router.py`: `match_file_summary(text) -> str | None`, recognising `"summarise file <path>"` / `"summarize file <path>"` and extracting the path — a distinct, narrow operation from `match()`/`build_input()`, since summarising a file is a multi-step AI-reasoning workflow, not a single tool execution.
- `core/orchestrator.py`: `handle_request()` checks `match_file_summary()` first; on a match, it dispatches to a new terminal method, `_handle_file_summary_request()`, which never reaches `_handle_request_core()` or `_attach_ai_suggestion()` — both remain completely unmodified. The new method reads the file via `ingest_file_for_ai()`, calls `AIReasoningEngine.reason()` with the returned `context_block`, and calls the **existing, unmodified** `_evaluate_unexpected_actions()`/`_audit_unexpected_action()` methods for every `AISuggestedAction` the AI produces.

### Batch 3 — End-to-End Security Verification and Documentation
- `tests/integration/test_file_summary_end_to_end.py` extended (from its own Batch 2 version, rather than duplicated into a second near-identical file) with: a real injection-bearing file proof; direct provenance verification (the exact `AIContextBlock.source` reaching `AIRouter.route()`); provider-failure and empty-response distinctness; an exactly-one-tool-call proof; and real-stack GREEN/YELLOW/RED unexpected-action coverage, including a multi-line summary producing multiple evaluated `AISuggestedAction` entries.
- This report and a README update. **No production code was added or modified in Batch 3.**

---

## Final Phase 8 Architecture

```
User request ("summarise file report.txt")
    │
    ▼
CommandRouter.match_file_summary()        (Batch 2: recognises the command,
    │                                       extracts the path only)
    ▼
JarvisOrchestrator._handle_file_summary_request()   (Batch 2: terminal path,
    │                                                 never reaches
    │                                                 _handle_request_core or
    │                                                 _attach_ai_suggestion)
    │
    ├── Planner.create_plan()             (unchanged: normal Plan generation,
    │                                       giving the unexpected-action
    │                                       policy a real expected scope)
    │
    ├── ai.file_ingestion.ingest_file_for_ai()        (Batch 1: the only new
    │       │                                          acquisition component)
    │       └── ToolExecutor.execute("file_read", ...)  (unchanged: GREEN,
    │               └── FileReadTool                     classify-then-run,
    │                                                     audited)
    │       → AIContextBlock.from_untrusted(text, source=f"file:{path}")
    │
    ├── AIReasoningRequest(context_block=<the block above>)   (Batch 1: typed,
    │                                                           not a string)
    │
    ├── AIReasoningEngine.reason()  →  AIRouter.route()  →  PromptBuilder.build()
    │       │                                                   ├── AIContextBlock (UNTRUSTED, unconditionally)
    │       │                                                   ├── SecurityManager.scan_for_injection()  (Batch 3, unchanged)
    │       │                                                   └── audit_suspicious_injection()  (Batch 5A, unchanged)
    │       forwards context_block unchanged - never reconstructs it
    │
    └── _evaluate_unexpected_actions() / _audit_unexpected_action()
            (Batch 4, reused unchanged - not duplicated, not bypassed)
                → EventLogger.emit(...)   (FLAGGED / PENDING / BLOCKED)
```

Every arrow below "Planner.create_plan()" in this diagram is either a Phase 8 addition (the two Batch 1/2 boxes) or unmodified Phase 7 code. No new subsystem, no generic ingestion framework, and no second content source exist anywhere in this diagram.

---

## File Ingestion Provenance Model

- **Phase 8 introduces file content only** — not a general external-content ingestion capability. `ingest_file_for_ai()` is deliberately file-specific, not source-agnostic; a future source (stored memory, a webpage) gets its own equally narrow module, following the same pattern, not a shared abstraction built ahead of a second real example.
- **Provenance is established by construction.** `ingest_file_for_ai()` is the sole caller of `ToolExecutor.execute("file_read", ...)` for this purpose. It does not accept a pre-existing `ToolResult`, arbitrary content, a caller-supplied trust level, or a caller-supplied source label — the label (`source=f"file:{path}"`) is derived from the exact `path` argument used for the one acquisition call the function makes itself, so a label can never describe content it did not actually produce. This is directly proven by `test_context_source_reflects_the_exact_requested_path` (Batch 3), which inspects the exact `AIContextBlock` reaching `AIRouter.route()`.
- **`FileIngestionResult` cannot represent a contradictory outcome.** Exactly one of `context` (success) or `error` (failure) is ever present, enforced at construction, not merely by convention.
- File content always becomes `AIContextBlock.from_untrusted(...)` — never `from_system()` or `from_live_user_input()`. The Batch 2 (Phase 7) provenance guard (`_TRUSTED_ORIGIN_KEY` sentinel-identity check) makes it structurally impossible for this or any future path to claim `JARVIS_TRUSTED` status for file content, unchanged.

---

## Typed AI Context Flow

- **`AIReasoningRequest` carries a typed `context_block: AIContextBlock | None`**, not a raw string. Trust and provenance travel together, already bound, in the one object Phase 7 Batch 2 hardened — there is no loose string field left for anything downstream to mislabel or reconstruct.
- **`AIReasoningEngine.reason()` forwards `request.context_block` unchanged.** It no longer constructs, reconstructs, or relabels an `AIContextBlock` at all; the engine holds no reference to `AIContextBlock`'s constructors whatsoever.
- **The old hardcoded `source="conversation_history"` defect is removed, not merely parameterised.** Phase 8's own architecture review rejected an initial proposal to add a second, independent `context_source: str` field alongside the existing raw string — that would have recreated the identical class of defect (two loose values that can drift apart) the review was checking for. The corrected fix replaces the raw string field entirely.

---

## File Summary Workflow

- **Command parsing stays in `CommandRouter`.** `match_file_summary()` recognises the command and extracts the path only; it is not a tool name, since summarising a file is a multi-step workflow, not a single tool execution.
- **`JarvisOrchestrator` coordinates the workflow; it does not absorb its business logic.** `_handle_file_summary_request()` calls `ingest_file_for_ai()`, `AIReasoningEngine.reason()`, and the existing `_evaluate_unexpected_actions()` — it never reads a file itself, never constructs an `AIContextBlock`, and never re-derives trust or provenance. This mirrors the same Core-coordination boundary Phase 7 Batch 1 established when command-matching was first extracted out of the orchestrator.
- **The response is a new, distinct shape, not a shoehorned reuse of `_attach_ai_suggestion`.** For this request, the AI's own output *is* the point of the request, not an annotation appended to an already-decided response — so a new terminal method was added instead of forcing this shape through `_attach_ai_suggestion`'s "annotate an already-decided response" logic. `_attach_ai_suggestion` itself was not modified, and its own pre-existing tests pass unchanged.
- **Reading GREEN file content and supplying it to advisory AI adds no new approval gate.** The file read is already GREEN and unchanged; consulting advisory AI about already-permitted content creates no new side effect, consistent with the standing rule that approval is tied to actions with real consequences, not to advisory reasoning inputs.

---

## Security Model

Safety is enforced by the **Security Manager** and applied at a single gate — the **Tool Executor** — that the rest of the system cannot bypass. Phase 8 changed none of this.

- **GREEN — safe.** The file read underlying every file-summary request is GREEN, unchanged, and still fully classified and audited by `ToolExecutor`.
- **YELLOW/RED — unchanged.** No file-summary path can create, approve, or unlock a YELLOW or RED action; the unexpected-action verdicts it produces remain policy/audit observations only.
- **AI remains advisory in every configuration, without exception.** The file-summary response is clearly labelled `"[AI file summary - advisory only]"`, distinct from `_attach_ai_suggestion`'s own `"[AI suggestion - advisory only]"` label, since the two represent different response shapes but the same authority boundary: neither can execute, approve, or reclassify anything.
- **No GREEN/YELLOW/RED classification changed for any existing action string across all of Phase 8.**

---

## Phase 7 Guarantees Inherited

Every one of these held for synthetic content in Phase 7 and is now proven, unchanged, for genuine file content in Phase 8:

- File content is always `UNTRUSTED`; never `JARVIS_TRUSTED`; never a `SecurityTier` override; never Nathan approval.
- File content always passes through `PromptBuilder`'s automatic injection scan before reaching a provider, because it travels through the same, completely unmodified `AIContextBlock`/`PromptBuilder` path.
- A suspicious detection in file content is audited through the existing `audit_suspicious_injection()` reporter (Batch 5A), with the same "never log the raw matched text" property.
- The Batch 4 unexpected-action policy applies to file-derived AI output exactly as it does everywhere else, via the same, unmodified `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods.
- A failing audit logger cannot break an already-authoritative response (inherited, untouched).
- AI output remains advisory: it cannot execute, approve, reclassify, or modify a Plan.

---

## Injection Defence Verification

`tests/integration/test_file_summary_end_to_end.py::test_injection_bearing_file_remains_untrusted_and_is_audited` writes a real temporary file containing ordinary benign text followed by a known instruction-like pattern ("ignore all previous instructions..."), then exercises it through `summarise file <real path>` end to end, proving:

- The command is recognised by the real `CommandRouter`.
- The real file is acquired through the real `ToolExecutor`/`FileReadTool`.
- The acquired content becomes `ContentTrust.UNTRUSTED` (confirmed directly by `test_context_source_reflects_the_exact_requested_path`, which also confirms the source label is exactly `f"file:{path}"`).
- The content enters `PromptBuilder` as untrusted context, and the prompt reaching the fake provider contains the `BEGIN CONTEXT`/data-only-directive framing, never the trusted markers.
- The injection scanner actually runs, and the suspicious detection is audited through the real, production-wired `audit_suspicious_injection()` reporter — `source="prompt_builder"`, `outcome=EventOutcome.FLAGGED`, `detail` naming the matched pattern.
- The raw suspicious file content is never embedded in the audit detail.
- The file content never becomes `JARVIS_TRUSTED`, Nathan approval, system authority, a `SecurityTier` override, or an execution instruction — the response remains a plain advisory summary, with `blocked=False`, `requires_confirmation=False`, `approval_request=None`.

---

## Unexpected AI Action Verification

`test_unexpected_green_suggestion_is_flagged_end_to_end`, `..._yellow_suggestion_is_escalated_end_to_end`, and `..._red_suggestion_is_blocked_end_to_end` prove, through the real stack, that an AI-suggested action outside the request's own expected scope is evaluated and audited exactly as Phase 7 Batch 4 already proved for the rule-based path: GREEN → `FLAGGED`, YELLOW → `PENDING`, RED → `BLOCKED`. `test_multi_line_summary_produces_multiple_evaluated_suggestions_end_to_end` proves a realistic multi-line AI summary produces multiple `AISuggestedAction` entries (an unavoidable consequence of `AIReasoningEngine._parse()`'s existing, unchanged behaviour) and that every one of them is evaluated, not just the first. In every case: the verdict is a policy/audit observation only — no suggestion becomes a `ToolRequest`, executes a tool (`test_exactly_one_tool_call_for_a_successful_summary` and the RED test both confirm exactly one real `tool_call` event, never a second for the suggested action), grants approval, changes a `SecurityTier`, or modifies the Plan. Existing RED/YELLOW execution controls remain fully authoritative throughout.

---

## Failure Model

Every ingestion and reasoning failure is represented as data, never a raised exception:

- **File not found, is a directory, permission denied, binary content:** represented as a failed `ToolResult` by the unmodified `FileReadTool`, forwarded as `FileIngestionResult.error`, and returned as an honest `JarvisResponse(success=False, message=<that error>)` — never presented as a summary, and the AI provider is never even called (`provider.received_requests == []`, proven directly).
- **AI reasoning not configured:** a distinct message ("AI reasoning is not enabled...").
- **AI reasoning configured but inactive, unavailable, or the provider fails or returns an empty/invalid response:** `AIReasoningEngine.reason()` returns `None` for all of these (by its own existing, unchanged design, which does not distinguish the reason), and the file-summary workflow reports a second, distinct honest message — proven separately for the unavailable, provider-failure, and empty-response cases, so as not to conflate "not configured" with "configured but produced nothing."
- **No failure/error text is ever supplied to the AI as file context** — every failure path returns before an `AIReasoningRequest` is ever constructed.

---

## Tests and Verification

**New/extended in Batch 3:** `tests/integration/test_file_summary_end_to_end.py` — 14 tests (5 from Batch 2, 9 added in Batch 3: real-injection audit provenance, exact source-label verification, provider-failure and empty-response distinctness, exactly-one-tool-call, and GREEN/YELLOW/RED/multi-line unexpected-action coverage through the real stack).

**Full Phase 8 test inventory, run directly in the development environment** (`poetry run pytest -v`, Python 3.14.6, pytest 9.1.1):

```
800 passed
0 failed
0 skipped
0 errored
```

This is every test from Phases 1–7 plus all of Phase 8's batches. No live Claude API call is made anywhere in the suite.

Batch-by-batch test files:
- **Batch 1:** `tests/unit/test_file_ingestion.py` (22 tests); `tests/unit/test_ai_reasoning_models.py` and `tests/unit/test_ai_reasoning_engine.py` extended; 4 pre-existing call sites in `tests/integration/test_ai_injection_defence_end_to_end.py` updated to the new `context_block` field.
- **Batch 2:** `tests/unit/test_command_router.py` extended (8 new tests); `tests/unit/test_file_summary_workflow.py` (18 tests, new); `tests/integration/test_file_summary_end_to_end.py` (5 tests, new).
- **Batch 3:** `tests/integration/test_file_summary_end_to_end.py` extended to 14 tests; this report; the README update.

### Test commands

```powershell
# The full test suite
poetry run pytest -v

# Phase 8 file ingestion and workflow
poetry run pytest tests/unit/test_file_ingestion.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_file_summary_workflow.py -v
poetry run pytest tests/unit/test_ai_reasoning_models.py tests/unit/test_ai_reasoning_engine.py -v

# Consolidated end-to-end security verification (Batch 3)
poetry run pytest tests/integration/test_file_summary_end_to_end.py -v

# All integration tests
poetry run pytest tests/integration -v
```

---

## Security Implications

- **No new attack surface beyond what Phase 7 already defended against.** File content is subject to the identical trust/scan/audit pipeline synthetic strings already exercised; Phase 8 proves that pipeline generalises to genuine content rather than introducing a new one.
- **The AI's authority is unchanged and unchangeable by its own output**, proven directly for file-derived reasoning: no suggestion can execute, approve, or change a tier, regardless of what the AI returns about real file content.
- **Provenance is now a structural guarantee, proven directly**, not merely documented: `ingest_file_for_ai()`'s narrow signature has no seam for a caller to supply mismatched content and labels, and `test_context_source_reflects_the_exact_requested_path` proves the exact label reaching the AI request matches the exact path requested.
- **A real design defect was found and corrected before it shipped**, not after: the original plan for the `AIReasoningEngine` source-label fix (a parallel `context_source: str` field) was rejected during architecture review because it would have reintroduced the same class of drift risk the ingestion boundary was designed to avoid. This is disclosed here in the same spirit Phase 7 disclosed its own mid-stream findings.

---

## Known Limitations

These are understood and disclosed; none is a defect in what has shipped.

- **`max_chars=4000` relies on `ingest_file_for_ai`'s own default**, matching `FileReadTool`'s existing default, rather than a value derived from `Settings.ai_max_tokens`. Character limiting is a simple, deterministic character count — it is **not token-aware model budgeting**, and no provider-specific tokenizer dependency was introduced, preserving provider independence.
- **No web ingestion exists.** No HTTP client dependency, no `web_search`/`browser_navigate` tool.
- **No memory-to-AI ingestion exists.** `MemoryManager`'s content is never supplied to `AIReasoningEngine` in this phase.
- **No generic, multi-source ingestion framework exists.** `ingest_file_for_ai()` is intentionally file-specific; a second source gets its own equally narrow module.
- **`AIReasoningEngine.reason()` still cannot distinguish *why* it returned `None`** (disabled, unavailable, provider failure, or empty response) — the file-summary workflow reports two honest categories (not configured vs. configured-but-produced-nothing), not four, because the underlying engine does not expose finer detail, by its own existing design.

---

## Deferred Work

Explicitly out of scope for Phase 8, unchanged from `docs/phase_8_implementation_plan.md §20`:

1. Stored-memory ingestion — the natural second content source, reusing this phase's ingestion pattern.
2. Web/browser/research-content ingestion — requires a new dependency and new tool.
3. A plugin/manifest-based Tool Manager — the current code-based `ToolRegistry` remains sufficient.
4. Any expansion of AI execution authority, or any path from an `AISuggestedAction` to a `ToolRequest`.
5. Persistent storage of ingested content, or a content cache of any kind.
6. Token-aware, provider-specific size limiting.

---

## Status Statement

**Phase 8 complete for its defined scope: real file-content ingestion into the advisory AI reasoning path, through the completely unmodified Phase 7 trust and injection-defence pipeline, with full Phase 4 unexpected-action policy coverage for the new AI output path.**

No architectural or security defect was found during Batch 3's end-to-end verification. The one real defect found during Phase 8's own architecture review (the `AIReasoningEngine` source-label design) was corrected before any batch was committed, not discovered afterward — disclosed here for the same honesty this project's completion reports have consistently required of themselves.

---

## Exact Recommended Next Action

Per `docs/phase_8_implementation_plan.md §21`: begin planning **stored-memory ingestion** as the second content source, reusing the ingestion pattern this phase establishes (a narrow, source-specific module that owns its own acquisition call and establishes provenance by construction), following the same batch discipline applied here. Web/browser ingestion should follow only after that second proof point, once a dependency and tool-safety design for outbound network access has been separately scoped and reviewed. Neither is started here.
