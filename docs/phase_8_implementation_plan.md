# Jarvis Phase 8 Implementation Plan

**Version:** Phase 8 — Real External-Content Ingestion
**Builds on:** `62a2f70` (Phase 7 complete: Core Simplification and AI Safety Hardening, Batches 1–5 + 5A)
**Date:** 2026-07-08

---

## 1. Purpose

Phase 7 completed the Master Specification's prompt-injection defence — trusted-vs-untrusted AI context, automatic injection scanning, an audited unexpected-action policy — while deliberately feeding it no real external content. Every Phase 7 test proves the defence against *synthetic* untrusted text; nothing in the running application has ever supplied genuine external content (a file, a webpage, stored memory) to an AI prompt.

Phase 8 closes that gap for exactly one source. It is **not** a capability sprint across every content type the Master Specification eventually envisions. It is the first, smallest, most conservative real exercise of the Phase 7 trust boundary — proving the defence holds under genuine (not synthetic) untrusted content, and establishing the ingestion pattern the next content type will reuse rather than reinvent.

---

## 2. Scope

**In scope:** reading a single local text file, at the user's explicit request, and supplying its contents to the advisory AI reasoning path as `UNTRUSTED` context — through the existing, unmodified Phase 7 trust and injection-defence pipeline.

**Out of scope:** every other content type named in the Master Specification's Memory Engine, Knowledge Library, or Tool Manager chapters (stored memory, web/browser content, project files, research agents), a plugin/manifest tool system, a Workflow Engine, and any new AI execution authority.

---

## 3. Success Criteria

- A user can ask Jarvis to have the AI reason about a specific local file's contents, and receive an advisory, clearly-labelled AI response derived from that file.
- The file's content is provably `UNTRUSTED` at every step: never `JARVIS_TRUSTED`, always scanned for injection patterns, always subject to the same audit trail Phase 7 already built.
- A synthetic injection pattern embedded in a real file is detected and audited exactly as Phase 7's synthetic-string tests predicted, proving the defence generalises to genuine file content.
- No existing Phase 1–7 test's assertions change.
- No new approval gate is introduced for reading a file or for supplying its content to AI — both remain exactly as permissive (or not) as they already are today.
- Full test suite passes throughout, count only growing.

---

## 4. Explicit Non-Goals

- No stored-memory ingestion, no web/browser ingestion, no multi-source ingestion abstraction beyond what one source requires.
- No plugin/manifest-based Tool Manager (Master Specification Ch. 11's future architecture) — the existing code-based `ToolRegistry`/`tools/builtin/` pattern is retained unchanged.
- No new AI execution authority: the AI still cannot execute, approve, or reclassify anything, and still cannot trigger a file read on its own initiative.
- No persistence of ingested content.
- No token-aware or provider-specific size limiting; no new external dependency of any kind.
- No change to `SecurityManager.classify_action`, `scan_for_injection`, `evaluate_unexpected_action`, or any GREEN/YELLOW/RED classification.
- No change to `ai/context_models.py`'s trust-provenance guard, `ai/prompt_builder.py`'s scanning/reporting behaviour, or `core/orchestrator.py`'s existing `_attach_ai_suggestion` advisory-suggestion path.
- No Master Specification, README, or test changes in this planning document — those are implementation-batch deliverables, not part of this plan itself.

---

## 5. Architectural Constraints

Carried forward from Phase 7's own development discipline, since nothing about Phase 8's problem shape invalidates it:

1. Narrow interfaces and dependency injection over broad ones.
2. No new subsystem, no new distributed/async mechanism.
3. Every audit-relevant event emits through the existing `EventLogger`/`EventOutcome` machinery — reuse before adding a new outcome value, and only add one with the same evidence-based rigor Batch 5A used for `FLAGGED`.
4. A batch is not complete until its own tests pass **and** the full suite, including every pre-existing test, passes unchanged.
5. `classify_action` remains the sole tier authority; nothing in Phase 8 introduces a second classification path.
6. AI remains advisory in every batch, in every configuration, without exception.
7. One batch per short-lived branch; a batch is not committed without an explicit, per-batch approval, matching Phase 7's practice exactly.
8. No real network call anywhere, in any test — trivially true for a file-only source, and stated here so it is not silently relaxed if a later phase reopens this document as a template.
9. **Provenance is established by construction, never by an independently caller-supplied label.** A component that labels content with its origin (a path, a memory id, a URL) must itself be the thing that acquired that exact content — never a function accepting a pre-existing result object and a separately-supplied label that could drift apart from it. This generalises the same lesson Batch 2 already applied to `AIContextBlock`'s trust field, to provenance metadata as well (§10).

---

## 6. Current-State Assessment

Confirmed by direct inspection, not assumption:

- **`tools/builtin/file_read_tool.py`'s `FileReadTool` already exists, is GREEN, and is already hardened**: it refuses binary files (NUL-byte sniff), enforces a bounded, deterministic character limit (`_DEFAULT_MAX_CHARS = 4000`, `_MAX_ALLOWED_CHARS = 100_000`) with an explicit truncation notice, and represents every failure (missing path, not found, is a directory, permission denied, OS error) as a failed `ToolResult` — it never raises. This is already the exact acquisition-and-size-limiting logic Phase 8 needs; nothing about it needs to be reimplemented.
- **`ai/context_models.py`'s `AIContextBlock.from_untrusted(text, source=...)` already accepts arbitrary source strings** and is already unconditionally scanned (Batch 3) and audited when suspicious (Batch 5A) by `ai/prompt_builder.py`. No change needed here for a single new source.
- **A real, concrete defect found during this assessment**: `ai/reasoning_engine.py`'s `AIReasoningEngine.reason()` hardcodes `source="conversation_history"` for *any* non-empty `AIReasoningRequest.context`:
  ```python
  if request.context:
      context_block = AIContextBlock.from_untrusted(
          request.context, source="conversation_history"
      )
  ```
  This was harmless while nothing populated `context`, but it is now **inaccurate** the moment a second, real source (a file) needs to flow through the same field — an audit record for a file-derived injection detection would falsely read `source="conversation_history"`. Worse, a fix that merely adds a second, independent string field (e.g. `context_source`) would recreate the exact same class of defect this plan's architecture review identified for file ingestion itself: two loose values (`context` and its label) that nothing stops from drifting apart. The correct fix is stronger than a parallel string; see §11, item 6.
- **`core/orchestrator.py`'s `_attach_ai_suggestion` never populates `AIReasoningRequest.context` today** — it is a dead field in production, exercised only by tests. Phase 8 is the first phase that populates it for real.
- **No web/browser tool of any kind exists** (`tools/builtin/` has no `web_search`, `browser_navigate`, or equivalent). The Master Specification's Tool Manager chapter (Ch. 11) names these as a manifest-based plugin system that also does not exist yet — building web ingestion first would require inventing both a new tool *and* a new network dependency simultaneously, with no existing scaffolding to lean on.
- **`memory/memory_manager.py`'s `MemoryManager` already exists** (`save`, `list_recent`, `list_by_category`, `search`, `get`, `update_content`, `move_category`, `forget`) and is a plausible second ingestion source, but the Master Specification's Memory Engine chapter (Ch. 8) describes four memory types (Session, Working, Long-Term, Project) of which only a single flat, categorised long-term store is implemented — building the first real ingestion pathway on top of a still-partial subsystem is less clean than building it on `FileReadTool`, which is complete and stable.
- **No command today lets a user ask Jarvis to reason about a specific file's contents.** `CommandRouter` matches `file_read`-style requests to display content directly to the user; it has no path that also forwards that content into `AIReasoningEngine`.

---

## 7. Chosen First Ingestion Source, and Why

**File content, via the existing `FileReadTool`, is the first Phase 8 ingestion source.**

Evaluated against the three candidates named in this plan's brief:

| Criterion | File content | Stored memory | Web/research content |
|---|---|---|---|
| Existing production support | `FileReadTool` complete, GREEN, hardened (binary rejection, deterministic truncation, failure-as-data) | `MemoryManager` complete for a single memory type; three of four spec'd memory types (Ch. 8) do not exist | None — no tool, no HTTP client dependency anywhere in the codebase |
| Required new dependencies | None | None | A new HTTP client (and likely an HTML-to-text step) — a real new dependency and new sandboxing surface (SSRF, arbitrary URLs, rate limits) |
| Security/injection exposure | Identical in kind to the Master Specification's own worked injection example (hidden instructions in read content); fully mediated by the unmodified Phase 7 pipeline | Same untrusted-by-default treatment already documented in Phase 7's Trust-Boundary Rules; adds a new question of *which* memories to select and how many, before any injection concern | Highest exposure: network-supplied content, larger attack surface, plus infrastructure-level risks (SSRF) outside the injection-defence model entirely |
| Approval implications | None — reading is already GREEN, unchanged | None — searching/reading memory is already GREEN, unchanged | Undetermined — outbound network access has no existing tier precedent in this codebase |
| Observability requirements | Reuses existing `tool_call` audit for the read; needs one new, narrowly-scoped ingestion-outcome event (§12) | Same shape, plus a new "which memories were selected" audit question | Same shape, plus new provider/rate-limit/failure observability with no precedent |
| Testing complexity | Lowest — real files via `tmp_path`, no mocking of anything external | Low — real in-memory SQLite, matching existing memory tests | Highest — every test must fake an HTTP layer that does not exist yet |
| Reusable abstraction vs. one-off | A thin, narrowly file-specific adapter (§9) establishes a *pattern* — acquire-and-label atomically, in one function, per source — that a future memory or web adapter repeats on its own terms, without sharing code prematurely | Same pattern would apply, but entangled with the still-evolving memory-type model | Same pattern would apply, but entangled with a dependency and tool that do not exist yet |
| Master Specification consistency | `file_read` is explicitly named GREEN in Ch. 11's Built-In Tools table; the ingestion pattern matches Ch. 12's worked injection example directly | Consistent with Ch. 8, but Ch. 8 itself is only partially built | Consistent with Ch. 11's aspirational `web_search`, but that tool does not exist |
| Correct next architectural layer | A thin adapter over an already-complete tool — no new subsystem | Would pull forward Memory Engine (extended) work (Ch. 18) ahead of its own phase | Would pull forward Tool Manager's plugin system (Ch. 11) and a new dependency ahead of its own phase |

File content wins on every axis except novelty of demo — which this plan explicitly rejects as a selection criterion, per instruction. It is the only candidate requiring **zero new dependencies, zero new tools, and zero new subsystems** — only a thin adapter connecting two already-complete, already-tested pieces (`FileReadTool` and the Phase 7 trust pipeline), plus the one real defect found in §6.

---

## 8. Rejected Alternatives, and Why They Are Deferred

- **Stored memory → AI context.** Deferred, not rejected outright: it is the natural second source once the ingestion adapter pattern exists, and reuses it almost unchanged. Deferred because (a) three of the Memory Engine's four documented memory types do not exist yet, so "which memory content is relevant" is itself an underspecified design question this plan should not answer under Phase 8's file-only scope, and (b) it is safer to prove the ingestion pattern once, on the simplest source, before adding memory-selection logic on top of it.
- **Web/research content → AI context.** Deferred: it requires a new external dependency (an HTTP client), a new tool, and a new class of risk (SSRF, arbitrary-URL fetching, rate limiting) with no existing precedent in this codebase to build on. Building it first would conflate "prove the Phase 7 trust pipeline generalises to real content" with "design a safe web-fetching tool from scratch" — two different, separable problems. It is the natural third source, after memory.

---

## 9. Final Proposed Ingestion Architecture

Revised by explicit architecture review (2026-07-08) — see the design notes after the diagram for what changed and why.

```
User request ("summarise file report.txt")
    │
    ▼
CommandRouter.match()  →  a new, explicit command (Batch 2)
    │  extracts only the requested path; the orchestrator never sees a
    │  pre-existing ToolResult from anywhere else
    ▼
JarvisOrchestrator's new handler calls:
    ingest_file_for_ai(executor: ToolExecutor, path: str, *, session_id)
        (new, narrow, file-specific, Batch 1 — the only new component)
    │
    │  This function OWNS the acquisition call - it is the sole caller of
    │  ToolExecutor.execute("file_read", {"path": path, ...}, session_id=...)
    │  for this purpose. It never accepts a pre-existing ToolResult from an
    │  external caller, and never accepts path and content as two
    │  independently-supplied values - both come from the one call this
    │  function makes itself, so a label can never drift from the content
    │  it describes (Architectural Constraint 9).
    │
    │  - on tool failure: returns a represented failure, never raises
    │  - on success: applies the ingestion-specific size decision (§13),
    │    audits the outcome (§12), and returns an
    │    AIContextBlock.from_untrusted(text, source=f"file:{path}")
    ▼
AIReasoningRequest(user_input=..., context_block=<the AIContextBlock above>)
    │   (context_block replaces the old context: str field entirely -
    │    see §11, item 6, for why a second parallel string was rejected)
    ▼
AIReasoningEngine.reason()  →  AIRouter.route()  →  PromptBuilder.build()
    │                                                   ├── AIContextBlock (UNTRUSTED, unconditionally)
    │                                                   ├── scan_for_injection()      (unchanged, Batch 3)
    │                                                   └── audit_suspicious_injection() (unchanged, Batch 5A)
    ▼
Advisory AIReasoningResult
    │
    ├──▶ self._evaluate_unexpected_actions(response, result, session_id)
    │        (Batch 4's existing private method, called directly and
    │        unchanged - see §11, item 7: this is REQUIRED, not bypassed,
    │        because AIReasoningEngine._parse() can produce
    │        AISuggestedAction entries from any multi-line AI response,
    │        including a file summary)
    │
    └──▶ returned as the response's primary message, clearly labelled
         advisory. This is a new, terminal response-building method on
         JarvisOrchestrator - it does not reuse _attach_ai_suggestion's
         suggestion-formatting logic (that method's "annotate an
         already-decided response" shape does not fit "the AI's output
         IS what was asked for"), but it DOES reuse the same Batch 4
         evaluation/audit methods _attach_ai_suggestion itself calls.
         _attach_ai_suggestion is otherwise untouched.
```

The only genuinely new production components are: the narrow, file-specific `ingest_file_for_ai`-style function; the `AIReasoningRequest.context_block` field (replacing `context`); and one new orchestrator method that reuses Batch 4's existing evaluation methods rather than duplicating or bypassing them. Everything below the `AIContextBlock` line, and the unexpected-action evaluation itself, is Phase 7 code, completely unmodified.

---

## 10. Trust Model

Unchanged from Phase 7, extended to name file content explicitly:

- File content read via `FileReadTool` is **always** `UNTRUSTED`. It is constructed only via `AIContextBlock.from_untrusted(text, source=f"file:{path}")` — never `from_system()` or `from_live_user_input()`, and the Batch 2 provenance guard (`_TRUSTED_ORIGIN_KEY` sentinel) makes it structurally impossible for any caller to claim otherwise, unchanged.
- If a convenience constructor is added for file-sourced context (optional, implementation-level detail), it must internally delegate to `from_untrusted(...)` and must not become a third trusted-capable factory.
- The user's own live request text (e.g., "summarise file report.txt") remains `JARVIS_TRUSTED` via `from_live_user_input()`, exactly as it always has been — it is never conflated with the file's own content.

---

## 11. Security Invariants

Explicit Phase 8 restatement of the Phase 7 guarantees that must hold for real file content, plus the one required fix:

1. File content is always `UNTRUSTED`; never `JARVIS_TRUSTED`; never a `SecurityTier` override; never Nathan approval (§10).
2. File content always passes through `PromptBuilder`'s automatic injection scan before reaching a provider — because it is delivered via the same, unmodified `AIContextBlock`/`PromptBuilder` path, not a new one.
3. A suspicious detection in file content is audited through the existing `audit_suspicious_injection()` reporter, inherited for free, with the same "never log the raw matched text" property Batch 5A already established.
4. AI output derived from file content remains advisory: it cannot execute, approve, reclassify, or modify a Plan — proven directly, not asserted, mirroring `test_ai_core_safety.py`'s existing style.
5. The AI cannot trigger its own file read. Every read remains user-initiated, through the same `ToolExecutor` gate as every other GREEN tool call; nothing in Phase 8 lets an `AISuggestedAction` cause a new tool execution.
6. **Required fix, revised by architecture review:** a new field alone (`context_source: str`, independent of `context: str`) was this plan's original proposal and is **rejected** — two loose, independently-settable strings can drift apart exactly as an adapter accepting an arbitrary `ToolResult` plus a separately-supplied path could (Architectural Constraint 9). The corrected fix: `AIReasoningRequest` gains a new field carrying an already-constructed `AIContextBlock | None` (e.g. `context_block`), replacing the raw `context: str` field's role entirely. `AIReasoningEngine.reason()` no longer constructs an `AIContextBlock` itself at all — it forwards whatever block it was given, unmodified, to `AIRouter.route(context=...)`. Trust *and* provenance travel together, already bound, in the one object Batch 2 already hardened — there is no string left to hardcode or drift. Since no production caller populates the old field today (§6), this is a clean, non-breaking replacement in practice, chosen for the strength of the boundary, not the size of the diff, per explicit instruction.
7. **The Batch 4 unexpected-action policy applies to file-derived AI output, and must not be bypassed.** `AIReasoningEngine._parse()` mechanically treats every non-first line of any AI response as a suggested action, with no awareness of *why* the AI was consulted — a multi-line file summary can and will produce `AISuggestedAction` entries under today's unchanged parsing. The new Batch 2 response path must call `JarvisOrchestrator`'s existing `_evaluate_unexpected_actions`/`_audit_unexpected_action` directly (the same private methods `_attach_ai_suggestion` already uses), so an unexpected action surfaced while reasoning about untrusted file content is flagged/escalated/blocked and audited exactly as it would be anywhere else. Omitting this would be an accidental policy-coverage gap in precisely the path most likely to face adversarial content, not an intentional non-goal.

---

## 12. Observability Requirements

Reusing the existing `EventLogger`/`EventOutcome` machinery only — no new logging subsystem, matching Development Rule 3:

- **Content acquired (file read succeeded):** already covered by `ToolExecutor`'s existing `tool_call`/`SUCCESS` event for `file_read` — no new event required.
- **Content rejected (file read failed, or ingestion itself refuses e.g. empty file):** the existing `tool_call`/`FAILURE` event already covers a failed read. If the ingestion layer itself rejects an otherwise-successful read (for a reason `FileReadTool` cannot express, if any), a new, narrowly-scoped ingestion `action_type` with `FAILURE` is warranted — decided during Batch 1 with the same rigor Batch 5A applied.
- **Content truncated:** `FileReadTool` already signals truncation in its own output text. Whether this also warrants a distinct audit event (and, if so, which `EventOutcome` truthfully fits — likely `SUCCESS` with a `detail` noting truncation, since truncation is an expected size-policy outcome, not an anomaly, unlike `FLAGGED`) is an explicit open question for Batch 1 to resolve with evidence, not to be decided by default.
- **Content passed to AI:** the existing `ai_call` event (Phase 1, `AIRouter.route()`) already fires for this. Batch 1 must decide whether a distinct "content ingested" event adds real value beyond this, or would be redundant — do not add vocabulary without evidence it is needed.
- **Injection detected:** fully inherited from Batch 5A. Zero new work.

No audit event, in any case, may embed the raw file content itself — only identifying, non-sensitive detail (path, size, truncation flag, matched pattern labels), matching the precedent already set for `audit_suspicious_injection()`.

---

## 13. Failure Model

Every ingestion failure is represented as data, never as a raised exception into `AIReasoningEngine` or `JarvisOrchestrator` — matching `ToolResult`'s existing error-as-data convention and `AIReasoningEngine.reason()`'s own "never raise into the caller" precedent.

Failure modes to handle explicitly, all already partially covered by `FileReadTool` itself:
- Path missing, does not exist, is a directory, permission denied, OS error (all already returned as failed `ToolResult`s today).
- File appears binary (already refused today).
- AI reasoning inactive or unavailable at the moment of the request (already handled by `AIReasoningEngine.is_active()`/`reason()` returning `None`) — the new command must produce a clear, non-crashing message distinct from "file not found," e.g. "AI reasoning is not enabled, so I can't summarise this file's contents."

A failure at any stage must still return a well-formed `JarvisResponse` with `success=False` and a clear message — never an unhandled exception reaching the CLI.

---

## 14. Size/Token-Limit Strategy

No new size-limiting mechanism, and no provider-specific tokenizer dependency. `FileReadTool`'s existing `max_chars` parameter (default 4000, hard cap 100,000, already deterministic and tested) is reused as-is; the new command decides what `max_chars` value to request for AI-consumption purposes (a value informed by, but not required to exactly match, `Settings.ai_max_tokens`) rather than inventing a second truncation mechanism. This preserves provider independence (the Master Specification's own principle) and avoids a new dependency for character-to-token estimation.

---

## 15. Persistence Decision

**Ephemeral only.** No new storage table, no new persisted row, no new file. Ingested file content exists only for the duration of the single request that ingested it — matching how `AIReasoningRequest.context` already behaves today, and how Batch 5A deliberately never logs the raw matched text. This avoids opening a new data-retention question (how long would ingested file snapshots be kept? who could read them later?) that Phase 8's conservative scope does not need to answer.

---

## 16. Logical Implementation Batches

### Batch 1 — File Content Ingestion Foundation

**Purpose.** Build the one new, narrow, file-specific adapter that acquires a file's contents and labels them as `UNTRUSTED` AI context atomically, and fix the `AIReasoningEngine` source/trust defect found in §6, corrected per this review.

**Components included.** A new, small, **file-specific** (not source-agnostic) function, e.g. `ingest_file_for_ai(executor: ToolExecutor, path: str, *, session_id: int | None, max_chars: int) -> IngestionResult`, which itself calls `ToolExecutor.execute("file_read", {"path": path, "max_chars": max_chars}, session_id=session_id)` and, only on success, returns `AIContextBlock.from_untrusted(text, source=f"file:{path}")` — never accepting a pre-existing `ToolResult` or an independently-supplied path from an external caller (Architectural Constraint 9). `ai/reasoning_models.py`: `AIReasoningRequest` gains `context_block: AIContextBlock | None = None`, replacing the role of the old `context: str` field. `ai/reasoning_engine.py`: `reason()` forwards `request.context_block` directly to `AIRouter.route(context=...)` instead of constructing one itself from a raw string.

**Why they belong together.** Both are prerequisites for any real ingestion to be trustworthy — the adapter without the trust/provenance fix would hand a correctly-labelled block to a method that discards the label and reconstructs its own (wrong) one; the fix without the adapter has nothing real to supply it.

**Main architectural risk.** Under-scoping the ingestion function into "just a wrapper" and quietly duplicating `FileReadTool`'s own truncation/binary-detection logic instead of reusing its already-tested output, or — the specific risk this review exists to prevent — designing the function to accept a `ToolResult` and a `path` as two separate arguments, reopening the provenance-drift problem this batch exists to close. Mitigation: the function's only external input is `path`; it performs its own single acquisition call and derives everything else from that one call's own result.

**Tests required.** Unit tests: a successful acquisition → correct `AIContextBlock` with `trust=UNTRUSTED` and a truthful `source` matching the exact `path` requested; a failed acquisition (not found, binary, permission denied) → a represented failure, never a raised exception; a test proving the function cannot be misused to label content it did not itself acquire (i.e., its signature has no seam for that); `AIReasoningRequest.context_block` defaults to `None` so every existing test is unaffected; `AIReasoningEngine.reason()` forwards a supplied `context_block` unchanged, with no internal `AIContextBlock` construction remaining. No new production code beyond this batch's stated scope.

### Batch 2 — Command and Orchestrator Wiring

**Purpose.** Give Nathan an explicit way to ask Jarvis to reason about one named file's contents, using Batch 1's adapter, with full Batch 4 unexpected-action coverage.

**Components included.** `core/command_router.py`: a new, explicit command pattern (e.g. "summarise file <path>") — command recognition and path extraction stay here, not in the orchestrator, consistent with Batch 1 of Phase 7 extracting exactly this kind of logic out of `JarvisOrchestrator`. `core/orchestrator.py`: one new, terminal response-building method that reads the file through the real `ToolExecutor` (unchanged GREEN gate), calls Batch 1's `ingest_file_for_ai`, calls `AIReasoningEngine.reason()`, **calls the existing `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods directly** (reused, not duplicated, not bypassed), and returns the advisory result as the response's primary message, clearly labelled. It does not reuse `_attach_ai_suggestion`'s own suggestion-formatting logic — that method's "annotate an already-decided response" shape does not fit a request whose entire point is the AI's own output — but it is not exempt from Batch 4's policy coverage; only the formatting logic differs, not the security coverage. `_attach_ai_suggestion` itself is not modified.

**Why they belong together.** The command and the orchestrator path are two halves of one user-facing feature; neither is independently testable end-to-end without the other.

**Main architectural risk.** Two, both corrected by this review rather than discovered later: (a) building this as a fully isolated path that silently skips Batch 4's unexpected-action evaluation — an accidental policy-coverage gap in exactly the path most exposed to adversarial content, since `AIReasoningEngine._parse()` can turn any multi-line file summary into `AISuggestedAction` entries; (b) concentrating command-matching or ingestion logic directly in `JarvisOrchestrator` rather than delegating it, which would conflict with the Master Specification's Core-coordination boundary and the rationale behind Phase 7's own Batch 1. Mitigation: command-matching stays in `CommandRouter`, acquisition-and-labelling stays in Batch 1's adapter, and the orchestrator's own new method does only what `_attach_ai_suggestion` already does at comparable scale — coordinate calls to existing collaborators and shape a response, reusing Batch 4's evaluation methods rather than reinventing them. Run the complete `test_ai_core_safety.py` suite unchanged as a regression gate for this batch specifically, even though that file is not touched.

**Tests required.** Unit tests for the new command match/build-input logic. A test proving a multi-line AI summary response produces `AISuggestedAction` entries that are evaluated and audited via the reused Batch 4 methods (GREEN/YELLOW/RED synthetic cases, mirroring `test_security_unexpected_action.py`'s own style). Integration tests: full request → real file read → real ingestion → real (fake-provider) AI reasoning → response, covering success, AI-disabled, file-not-found, and binary-file cases. A test proving `_attach_ai_suggestion`'s own pre-existing tests still pass unchanged.

### Batch 3 — End-to-End Security Verification and Documentation

**Purpose.** Prove the complete path against genuine (not synthetic) file content, including an injection attempt, and document Phase 8 in the established voice of Phases 1–7.

**Components included.** One consolidated integration test (e.g. `tests/integration/test_file_content_ingestion_end_to_end.py`) using a real temporary file (via `tmp_path`) containing a known injection pattern, exercised through the real command → real file read → real ingestion → real `AIReasoningEngine`/`AIRouter`/`PromptBuilder`/`SecurityManager` stack, fake AI provider, real trust/scan/audit assertions. `docs/phase_8_completion_report.md` and a README update, once implementation is complete.

**Why they belong together.** Verification and documentation are inseparable in this project's established discipline — every prior phase's completion report is written from, and cites, its own consolidated end-to-end test.

**Main architectural risk.** Understating what was actually proven, the same risk Phase 7's own Batch 5 encountered — this batch must not claim more than its tests demonstrate, and must honestly report any gap it finds, exactly as Phase 7 did with the injection-audit gap.

**Tests required.** The consolidated end-to-end file described above; a final full-suite run reporting the new authoritative total.

---

## 17. Integration Verification

Required before Phase 8 can be considered complete:
- The full pre-existing suite (every Phase 1–7 test) passes with zero assertion changes.
- The new consolidated end-to-end test (Batch 3) passes against a real file, not a synthetic string, proving the trust/scan/audit pipeline generalises.
- `git diff --check` clean at every batch boundary.
- A manual or scripted run confirms the CLI experience: asking Jarvis to summarise a real file produces a clearly-labelled advisory response, with AI reasoning both enabled and disabled (the disabled case must fail gracefully, not crash).

---

## 18. Phase Completion Criteria

- All three batches individually meet their own success criteria.
- The full test suite passes throughout, count only growing.
- The §11, item 6 `AIReasoningEngine` trust/provenance defect is fixed at its corrected, stronger boundary (`context_block`, not a parallel `context_source` string), not merely documented.
- No GREEN/YELLOW/RED classification changed for any existing action string.
- No new approval gate exists for reading a file or supplying it to AI.
- File content is provably `UNTRUSTED` at every point in the path, by the same standard of proof Phase 7 held itself to (direct test assertions, not narrative claims).
- The Batch 4 unexpected-action policy is proven to apply to AI output derived from file content, via the reused `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods — not merely assumed to, and not silently skipped.

---

## 19. Risks and Rollback

- **Batch 1** is low-risk and independently revertible: it adds one new module and one new, default-preserving field; nothing existing depends on either yet.
- **Batch 2** carries this phase's main risk: a new orchestrator response path that must not disturb `_attach_ai_suggestion`'s existing guarantees, and must not silently skip Batch 4's unexpected-action evaluation for AI output derived from file content. Mitigated by treating `test_ai_core_safety.py`'s full, unchanged pass, plus a dedicated test proving reused unexpected-action coverage, as hard gates for this batch, not merely a courtesy check.
- **Batch 3** is documentation- and test-only; minimal risk.
- Phase-level rollback: each batch is an independent, revertible commit, following Phase 7's exact practice. No batch introduces a database migration or any persisted state, so no batch has schema rollback concerns.

---

## 20. Deferred Work

Explicitly out of scope for Phase 8, to be revisited only in their own, separately-scoped phases:

1. Stored-memory ingestion (Master Specification Ch. 8/18) — the natural second source, reusing this phase's ingestion adapter pattern.
2. Web/browser/research-content ingestion (Ch. 11's `web_search`, Ch. 20's AI Agent System) — requires a new dependency and new tool; deferred until after a second, memory-based proof of the ingestion pattern.
3. A plugin/manifest-based Tool Manager (Ch. 11) — the current code-based `ToolRegistry` remains sufficient for as many sources as this plan anticipates needing in the near term.
4. Any expansion of AI execution authority, or any path from an `AISuggestedAction` to a `ToolRequest` — unchanged, still explicitly out of scope.
5. Persistent storage of ingested content, or a content cache of any kind.
6. Token-aware, provider-specific size limiting.

---

## 21. Exact Recommended Post-Phase-8 Action

Once Phase 8 is complete and closed: begin planning **stored-memory ingestion** as the second content source, reusing the ingestion adapter this phase establishes, following the same batch discipline and the same "smallest sensible first capability" reasoning applied here. Web/browser ingestion should follow only after that second proof point, once a dependency and tool-safety design for outbound network access has been separately scoped and reviewed — it is explicitly not the immediate next step.

---

## Summary

Phase 8's first batch of real external-content ingestion is deliberately small: one already-complete, already-hardened tool (`FileReadTool`), one thin, narrowly file-specific adapter that acquires and labels content atomically (never accepting a pre-existing result and a separate label from an external caller), one corrected trust/provenance defect fixed at its strongest boundary (`AIReasoningRequest.context_block` carrying a real `AIContextBlock`, not a parallel string), one new user-facing command, and full reuse — never a bypass — of Batch 4's unexpected-action evaluation and audit for AI output derived from file content. All of this flows through Phase 7's trust and injection-defence pipeline completely unmodified. Nothing here adds new AI authority, new approval requirements, new dependencies, or new persistence. The phase's purpose is narrow and specific: prove, with real content instead of synthetic strings, that the defence Phase 7 built actually holds — and leave behind a pattern the next content source can reuse rather than reinvent.
