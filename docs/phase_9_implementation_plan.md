# Jarvis Phase 9 Implementation Plan

**Version:** Phase 9 — Stored-Memory Ingestion for Advisory AI
**Builds on:** `6fedac1` (Phase 8 complete: Real External-Content Ingestion — file content, Batches 1–3)
**Date:** 2026-07-08

---

## 1. Purpose

Phase 8 proved that Jarvis's Phase 7 trust and injection-defence pipeline generalises from synthetic strings to genuine external content, using exactly one source: local file content. Phase 8's own completion report explicitly recommended stored memory as the second content source, reusing the same ingestion pattern rather than inventing a new one.

Phase 9 is that second proof point. It is not a research or knowledge-ingestion system, and it does not complete the Master Specification's Memory Engine. It takes the one memory-retrieval primitive that already exists — fetching a single stored memory by its id — and lets Nathan ask the advisory AI to reason about it, through the identical, completely unmodified Phase 7/8 machinery. Its purpose is to confirm the ingestion pattern (acquire atomically → label by construction → forward unchanged) is genuinely source-agnostic in practice, on a source with a structurally different acquisition mechanism (a database primary key, not a filesystem path) — before any shared ingestion abstraction is ever considered.

---

## 2. Scope

**In scope:** reading a single stored memory, by its existing numeric id, at the user's explicit request, and supplying its content to the advisory AI reasoning path as `UNTRUSTED` context — through the existing, unmodified Phase 7/8 trust and injection-defence pipeline.

**Out of scope:** every other memory type named in the Master Specification (Session, Working, Project, Semantic, Procedural, Entity Memory), the Knowledge Library, multi-memory retrieval or search feeding AI, a generic multi-source ingestion framework, and any new AI execution authority.

---

## 3. Success Criteria

- A user can ask Jarvis to have the AI reason about one specific, already-stored memory, and receive an advisory, clearly-labelled AI response derived from it.
- The memory's content is provably `UNTRUSTED` at every step, exactly as Phase 7's own documentation already named "memory" as a canonical untrusted source.
- A synthetic injection pattern stored as a real memory is detected and audited exactly as Phase 8 already proved for file content, confirming the defence generalises to a second, structurally different source.
- No existing Phase 1–8 test's assertions change.
- No new approval gate is introduced for reading a memory or for supplying its content to AI.
- Full test suite passes throughout, count only growing.

---

## 4. Explicit Non-Goals

- No Session, Working, Project, Semantic, Procedural, or Entity Memory — only the existing Episodic Memory store.
- No Knowledge Library (Master Specification Ch. 9/19).
- No multi-memory retrieval, search-driven selection, or ranking feeding AI — exactly one memory, named by id, per request.
- No new dependency (no vector database, no embeddings) — Chapter 18's own "Phase 2" retrieval strategy (semantic/ChromaDB) is explicitly the Master Specification's *own* future work, not this phase's.
- No new AI execution authority, no new approval requirement, no persistence of ingested content.
- No change to `SecurityManager.classify_action`, `scan_for_injection`, `evaluate_unexpected_action`, or any GREEN/YELLOW/RED classification.
- No change to `ai/context_models.py`'s trust-provenance guard, `ai/prompt_builder.py`'s scanning/reporting behaviour, `core/orchestrator.py`'s existing `_attach_ai_suggestion` or `_handle_file_summary_request` paths, or `ai/file_ingestion.py`.
- No generic, multi-source ingestion framework — a second narrow, source-specific module, not a shared abstraction.

---

## 5. Architectural Constraints

Carried forward unchanged from Phase 8 (itself carried from Phase 7):

1. Narrow interfaces and dependency injection over broad ones.
2. No new subsystem, no new distributed/async mechanism.
3. Every audit-relevant event emits through the existing `EventLogger`/`EventOutcome` machinery — reuse before adding a new outcome value.
4. A batch is not complete until its own tests pass **and** the full suite, including every pre-existing test, passes unchanged.
5. `classify_action` remains the sole tier authority.
6. AI remains advisory in every batch, in every configuration, without exception.
7. One batch per short-lived branch; no batch is committed without an explicit, per-batch approval.
8. No real network call anywhere, in any test.
9. **Provenance is established by construction, never by an independently caller-supplied label** (Phase 8, Architectural Constraint 9) — the acquisition module must be the sole caller of the retrieval operation it labels.
10. **A second concrete example does not justify a shared framework.** Phase 9 proves the ingestion *pattern* generalises; it does not extract a common base class or generic `Ingestor` interface. That decision is deferred until a third source exists, per Phase 8's own recommendation.

---

## 6. Current-State Memory Assessment

Confirmed by direct inspection, not assumption:

- **`memory/memory_manager.py`'s `MemoryManager`** owns `save` (with the "do not remember" policy), `list_recent`, `list_by_category`, `search` (case-insensitive substring), `count`, `get(memory_id)`, `update_content`, `move_category`, and `forget`. All delegate to `memory/episodic_memory.py`'s `EpisodicMemoryStore`.
- **Memories are persisted in SQLite** via the `EpisodicMemory` ORM model (`storage/models.py`): `id` (autoincrement primary key), `session_id` (nullable FK), `content` (unbounded `Text`), `source` (defaults `"conversation"`), `category` (organisational only — `general`/`personal`/`project`/`preference`/`note` — explicitly documented as never affecting safety classification), `created_at`.
- **Retrieval already returns typed, structured `MemoryRecord` objects**, never loose strings — `id`, `content`, `source`, `session_id`, `category`, `created_at` — directly analogous to Phase 8's `ToolResult`.
- **`MemoryManager.get(memory_id) -> MemoryRecord | None`** already exists: a single-record, by-primary-key retrieval, exposed today as `MemoryTool`'s `"get"` operation (`action_for` returns `"show memory"`, classified GREEN), reachable via the existing `"show memory <id>"` command. This is the direct memory analogue of `FileReadTool` for Phase 8 — already complete, already tested, nothing to build.
- **Retrieval is deterministic**: ordered by `created_at DESC, id DESC`, a plain case-insensitive substring filter (`ilike`) for search, a caller-supplied `limit` (clamped 1–50 by `MemoryTool`). No relevance ranking, no semantic scoring.
- **No character limit exists at read time.** Unlike `FileReadTool`'s `max_chars`, neither `MemoryManager.get()` nor `MemoryTool`'s `"get"` operation truncates `content` — a real, disclosed difference from the file case (§13).
- **Memory is never populated from automatic conversation logging.** A memory is written only via an explicit `"remember this: ..."` user command (GREEN, single explicit save) — it is a curated notes store, not a transcript.
- **Memory can already be edited and deleted**, both YELLOW and approval-gated (`memory_update`, `memory_forget`); bulk forgetting is RED and blocked. Reading remains GREEN throughout. Phase 9 changes none of this.
- **No memory-to-AI path exists today.** Confirmed by direct inspection: no code anywhere constructs an `AIContextBlock` from `MemoryManager` output. `ai/context_models.py`'s own docstring already names `"memory"` as a canonical `UNTRUSTED` source example — the trust decision is already made and documented; only the wiring does not exist yet, exactly as was true for file content before Phase 8.
- **`MemoryManager.get(memory_id)` performs a deterministic, unscoped primary-key lookup, not a session-authorized retrieval.** `EpisodicMemoryStore.get_by_id()` fetches by `id` alone; there is no `session_id` filter anywhere in that path. `session_id` is stored on `MemoryRecord` and used throughout Jarvis as metadata for observability and organisation — it is never enforced anywhere in the codebase as an authorization or ownership boundary. This is not new or introduced by this phase: the existing, already-shipped GREEN `"show memory <id>"` command exposes this exact same unscoped-by-id lookup today. Phase 9 inherits this retrieval model unchanged; `ingest_memory_for_ai()` must not create a broader lookup capability than `MemoryManager.get()` already exposes, and no documentation produced by this phase may describe memory ingestion as session-isolated.

---

## 7. Master Specification vs. Production Gap Analysis

Confirmed against Chapters 8, 15, and 18 directly:

- **Episodic Memory is implemented, and matches the specification's own "Phase 1" retrieval strategy exactly** (Ch. 18: "Keyword search for exact-match queries. Recency weighting."). The current substring-search-plus-recency-ordering implementation is not a simplified stand-in for the spec — it *is* the spec's own documented first phase.
- **Session Memory, Working Memory, and Project Memory** (Ch. 8's original four memory types) do not exist as distinct mechanisms; only a single flat store with an organisational `category` label exists, which is a different concept (cross-cutting label, not lifecycle/scope).
- **Semantic Memory, Procedural Memory, and Entity Memory** (Ch. 18's extended types) do not exist. Semantic Memory is explicitly specified as vector embeddings retrieved via ChromaDB — the Master Specification's own **"Phase 2"** of the Memory Engine's retrieval strategy, not a currently-blocking gap.
- **The Knowledge Library** (Ch. 9/19) does not exist in any form.
- **Goal Management** (Ch. 15) does not exist; the specification itself states goals would be stored "in the Memory Engine as Entity Memory," which does not exist either.
- **Conclusion:** the production Memory Engine implements exactly the specification's own first phase of Episodic Memory, cleanly and completely for what it claims to be. Building Semantic/Procedural/Entity Memory now would mean building the specification's *own documented future work* ahead of schedule, not filling a gap this phase's narrow ingestion goal actually depends on.

---

## 8. Candidate Comparison

### Candidate A — Existing stored-memory record → AI context (single record, by id)

| Criterion | Assessment |
|---|---|
| Master Specification consistency | Directly implements Ch. 18's own "Phase 1" retrieval strategy; already-documented `UNTRUSTED` source |
| Existing production support | Complete: `MemoryManager.get()`, `MemoryTool`'s GREEN `"get"` operation |
| Required architecture changes | One narrow new module, mirroring `ai/file_ingestion.py`; no new dependency |
| Security/trust risk | Identical in kind to the already-mediated file risk; fully covered by the unmodified Phase 7 pipeline |
| Provenance quality | Excellent — a stable, immutable database primary key, arguably more stable than a filesystem path |
| Prompt-injection exposure | Present, fully mediated, zero new scanning/auditing code needed |
| Approval implications | None new — reading is already GREEN |
| Observability requirements | Acquisition audit is not free here (§10/§15): since the true acquisition boundary is `MemoryManager.get()`, not a `ToolExecutor`-mediated call, the orchestrator must emit its own acquisition audit event rather than inheriting one |
| Persistence implications | None — ephemeral, matching Phase 8 |
| Search/ranking complexity | None — a single record by id sidesteps this entirely |
| Testing complexity | Low — mirrors Phase 8's own test patterns, real in-memory SQLite, no new external dependency |
| Risk of cementing incomplete architecture | Low — `get(id)` is a complete, stable primitive regardless of what memory types are added later |
| Long-term value | High — proves the ingestion *pattern* on a structurally different acquisition mechanism |
| Reusable foundation vs. one-off | Establishes the second concrete example of the pattern, strengthening the case for (not yet building) a shared abstraction |

### Candidate B — Complete the Memory Engine first

Rejected as this phase's prerequisite. The Master Specification itself labels Semantic Memory (vector embeddings, ChromaDB) as its own "Phase 2" — building it now would mean implementing the specification's *own documented future work* out of sequence, requiring a new external dependency, new schema, and new retrieval APIs with their own unreviewed security/data-handling questions (do embeddings themselves require the same trust treatment as raw text?). This is real, valuable future work — just not a prerequisite for proving the ingestion pattern generalises, and pursuing it now would repeat the exact sequencing mistake Phase 8 avoided by not building a web-fetching tool before proving the pattern on files.

### Candidate C — Introduce memory retrieval/search before AI ingestion

Rejected as a prerequisite, for a narrower reason: retrieval is *already* deterministic, already limited, and already exposed through a clean, single-purpose interface (`MemoryManager.get`/`search`/`list_recent`). A new "retrieval boundary" would be redundant with what exists. The genuinely hard part of this candidate — selecting and combining *multiple* relevant memories for one AI call — is a real, valuable next step, but it is a strictly harder version of the same problem Candidate A solves narrowly by asking for exactly one memory by id, mirroring how Phase 8 avoided web-search-and-rank complexity by starting with one named file. Deferred, not rejected outright — see §20.

**Selected: Candidate A.** It is the only candidate requiring no new dependency, no new subsystem, and no work the Master Specification itself schedules for a later phase of the Memory Engine — only a thin adapter connecting two already-complete, already-tested pieces (`MemoryManager.get()` and the Phase 7/8 trust pipeline).

---

## 9. Chosen Architecture

Revised by explicit architecture review (2026-07-08) — see §10 for what changed and why. The acquisition dependency is `MemoryManager` directly, not `ToolExecutor`/`MemoryTool`, because `MemoryManager.get()` — not `MemoryTool`'s `"get"` operation — is the true, already-typed acquisition boundary for this source (§10).

```
User request ("summarise memory 42")
    │
    ▼
CommandRouter.match_memory_summary()   (Batch 2: recognises the command,
    │                                    extracts the raw id text only)
    ▼
JarvisOrchestrator._handle_memory_summary_request()   (Batch 2: terminal path,
    │                                                    mirrors
    │                                                    _handle_file_summary_request
    │                                                    exactly; never reaches
    │                                                    _handle_request_core or
    │                                                    _attach_ai_suggestion)
    │
    ├── Planner.create_plan()             (unchanged: normal Plan generation)
    │
    ├── ai.memory_ingestion.ingest_memory_for_ai()   (Batch 1: the only new
    │       │                                         acquisition component)
    │       └── MemoryManager.get(memory_id) -> MemoryRecord | None   (unchanged,
    │               already-typed, no MemoryTool/ToolExecutor involvement -
    │               MemoryTool's own "get" operation is CLI display formatting,
    │               a different concern, and is never invoked by this path)
    │       → truncate ONLY record.content to a character limit, never any
    │         metadata (Batch 1: new, narrow, ingestion-layer-only logic -
    │         MemoryTool/MemoryManager are NOT modified); truncated: bool
    │         recorded on the result, never silently hidden
    │       → AIContextBlock.from_untrusted(text, source=f"memory:{record.id}")
    │         (the RETURNED record's own id, not merely the caller's requested
    │         memory_id - the strongest available construction guarantee)
    │
    ├── JarvisOrchestrator emits its own "memory acquired"/"memory not found"
    │       audit event via self._logger (Batch 2) - this is now an explicit,
    │       disclosed responsibility, not a free byproduct of ToolExecutor,
    │       since ToolExecutor is no longer on this path (§15)
    │
    ├── AIReasoningRequest(context_block=<the block above>)   (unchanged field,
    │                                                           Phase 8)
    │
    ├── AIReasoningEngine.reason()  →  AIRouter.route()  →  PromptBuilder.build()
    │       (unchanged: UNTRUSTED framing, injection scan, audit_suspicious_injection)
    │
    └── _evaluate_unexpected_actions() / _audit_unexpected_action()
            (Phase 7 Batch 4, reused unchanged)
```

The only new production components are: the narrow, memory-specific `ingest_memory_for_ai()` function; the new `match_memory_summary()` command; and one new orchestrator method that mirrors `_handle_file_summary_request()`'s own shape. Everything from `AIContextBlock` downward is completely unmodified Phase 7/8 code.

---

## 10. Memory Provenance Model

**Revised by explicit architecture review.** The original proposal for this section had `ingest_memory_for_ai()` own a call to `ToolExecutor.execute("memory", {"operation": "get", ...})` and convert its `ToolResult.output` into an `AIContextBlock` — mirroring Phase 8's file-ingestion mechanics literally. Direct inspection of `MemoryTool`'s `"get"` operation found this would be a mistake specific to this source, corrected before implementation:

- **`MemoryTool`'s `"get"` operation does not return `MemoryRecord.content` as `ToolResult.output`.** It returns `f"[{record.id}] ({record.category}) {record.content}"` — a formatted, human-facing display string, with the memory's id and category baked directly into the same text as its content. This is CLI presentation formatting, not the memory's actual content.
- **Using that formatted string as AI context would couple the AI ingestion boundary to `MemoryTool`'s display formatting.** A future, purely cosmetic change to that one-line format (adding a timestamp, changing the bracket style, localising the category name) would silently change what text the AI actually reasons about, without anyone deciding that on purpose. It would also flatten the id and category into the untyped content payload itself — the same value this plan already needs for the `AIContextBlock` source label, now duplicated and baked into the text a second time, incidentally.
- **`MemoryManager.get(memory_id) -> MemoryRecord | None` is the true, already-typed acquisition boundary for this source** — not `MemoryTool`, and not `ToolExecutor`. Unlike `FileReadTool` (which performs real, non-trivial acquisition work — binary sniffing, character-limited reading — worth reusing rather than duplicating), `MemoryTool`'s `"get"` operation performs no acquisition-side transformation of its own beyond that one cosmetic wrapper; the real acquisition already happened one layer below, in `MemoryManager`/`EpisodicMemoryStore`. Chapter 18 of the Master Specification states this directly: "The Memory Manager provides a single unified query interface. Callers are not affected when the retrieval mechanism is upgraded between phases" — an explicit mandate that other subsystems depend on `MemoryManager`'s own interface, not a tool-level wrapper built for CLI display.
- **Corrected design:** `ingest_memory_for_ai(memory_manager: MemoryManager, memory_id: int, *, max_chars: int = <default>) -> MemoryIngestionResult` is the sole caller of `memory_manager.get(memory_id)` for this purpose. It never accepts a pre-existing `ToolResult` or `MemoryRecord`, never accepts memory content and a source label as independently-supplied values, and never accepts a caller-supplied trust level. `record.content` (never any metadata) is what gets truncated and wrapped; `AIContextBlock.source` is derived from **the returned record's own `record.id`**, not merely the caller-supplied `memory_id` parameter — the strongest available construction guarantee, since it is truthful to what was actually retrieved rather than merely what was asked for, even though the two are equal in every case today (a primary-key lookup).
- **`source=f"memory:{record.id}"`** — the stable, immutable database primary key, not the stored record's own `.source` **field**, a same-named but unrelated concept: `MemoryRecord.source` records how the memory was originally captured (e.g. `"conversation"`), and is never read by the ingestion module at all. `record.source` cannot become an `AIContextBlock` trust classification, and a record whose stored `.source` happens to read `"user"` or any other value still cannot become `JARVIS_TRUSTED` — trust is unconditionally `UNTRUSTED` for every record this path ever touches, regardless of that field's value.
- **`MemoryIngestionResult` mirrors `FileIngestionResult`'s structure**: exactly one of `context`/`error` is ever populated, enforced via `__post_init__`, from the start rather than as a later correction. It additionally carries a `truncated: bool` field (§16), which `FileIngestionResult` did not need, since Phase 8 could rely on `FileReadTool`'s own text already carrying a truncation notice — no equivalent exists one layer below `MemoryManager.get()`, so this phase must represent it explicitly rather than losing it.
- **Bypassing `ToolExecutor` for this source is a deliberate, disclosed exception, not a general rule change.** Phase 8's own principle stands: a source-specific ingestion component owns acquisition and establishes provenance by construction. For file content, `ToolExecutor`/`FileReadTool` *was* that boundary, because no stronger typed alternative existed beneath it. For stored memory, `MemoryManager` already *is* that boundary — a cleaner one than the tool built on top of it. The one real, disclosed consequence of this choice is observability (§15): the free `tool_call` audit event `ToolExecutor` provided for file acquisition does not exist on this path, and must be replaced deliberately, not assumed away.

---

## 11. Trust Model

- Memory content is **always** `UNTRUSTED`. It is constructed only via `AIContextBlock.from_untrusted(text, source=f"memory:{record.id}")` — never `from_system()` or `from_live_user_input()`. The Phase 7 Batch 2 provenance guard (`_TRUSTED_ORIGIN_KEY` sentinel) makes this structurally impossible to bypass, unchanged.
- This is not a new trust decision — `ai/context_models.py`'s own docstring already names `"memory"` as a canonical `UNTRUSTED` example, alongside file contents, web/network content, tool output, and historical conversation text. Phase 9 is the first phase to actually exercise that already-documented rule against the real `MemoryManager`.
- A memory being "Jarvis's own" storage does not upgrade its trust. The exact same reasoning Phase 7's Trust-Boundary Rules already state for stored memory applies unchanged: "even though the user wrote it, it was not written in this live turn and could itself have been influenced by something injected earlier." A memory that was itself populated by copying suspicious text (from a file, a webpage, or anywhere else) into a `"remember this: ..."` command remains untrusted for exactly this reason when later retrieved.
- The user's own live request text (e.g., `"summarise memory 42"`) remains `JARVIS_TRUSTED` via `from_live_user_input()`, exactly as always — never conflated with the memory's own content.

---

## 12. Security Invariants

1. Memory content is always `UNTRUSTED`; never `JARVIS_TRUSTED`; never a `SecurityTier` override; never Nathan approval.
2. Memory content always passes through `PromptBuilder`'s automatic injection scan before reaching a provider, because it travels through the same, completely unmodified `AIContextBlock`/`PromptBuilder` path as file content.
3. A suspicious detection in memory content is audited through the existing `audit_suspicious_injection()` reporter (Batch 5A), inherited for free, with the same "never log the raw matched text" property.
4. AI output derived from memory content remains advisory: it cannot execute, approve, reclassify, or modify a Plan.
5. The AI cannot trigger its own memory retrieval. Every retrieval remains user-initiated. Acquisition goes through `MemoryManager.get()` directly rather than `ToolExecutor` (§10) — a deliberate, disclosed exception justified by `MemoryManager` already being the true typed acquisition boundary for this source, not a general relaxation of the security gate: the operation is unconditionally GREEN and read-only regardless of which path it takes, and no dynamic security decision is skipped by this choice.
6. The Batch 4 unexpected-action policy applies to memory-derived AI output exactly as it does to file-derived output and every other advisory path, via the same, unmodified `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods — not optional, not bypassed.
7. `MemoryTool` and `MemoryManager` are not modified. Any size-limiting logic this phase needs lives in the new ingestion module only (§16).
8. A memory that has been deleted (forgotten) between being referenced and being ingested produces an honest failure (`MemoryManager.get()` already returns `None` for a nonexistent id) — never fabricated content.
9. `MemoryRecord.source` (how a memory was originally captured, e.g. `"conversation"`) is never read by the ingestion module and cannot influence `AIContextBlock.trust` or `.source` — the two `source` concepts are unrelated, and only the record's `.id` and `.content` are ever used.
10. Memory retrieval is not session-scoped, and this phase must never claim otherwise. `MemoryManager.get(memory_id)`/`EpisodicMemoryStore.get_by_id()` perform a deterministic, unscoped primary-key lookup with no session-ownership check — identical in kind to the existing GREEN `"show memory <id>"` path, and not widened by `ingest_memory_for_ai()`. This is an inherited, pre-existing characteristic of a single-user, local system with no defined user/session authorization model, not a defect introduced by, or specific to, Phase 9. See §21/§22 for the corresponding risk disclosure and deferred-work item.

---

## 13. Prompt-Injection Implications

No new code is required for injection defence. Memory content reaches `PromptBuilder.build()` as an `UNTRUSTED` `AIContextBlock` exactly like file content did in Phase 8; the existing `scan_for_injection()`/`audit_suspicious_injection()` path applies automatically. The one thing this phase must prove, not merely assert, is that a memory record *specifically* (not just "another untrusted string") carries a real injection pattern through the real `MemoryManager` stack and is still detected and audited — this is Batch 3's job, mirroring Phase 8's own real-file injection proof.

A related question this plan answers explicitly (per the review brief): **could a malicious file or webpage stored earlier as a memory later bypass Phase 7 because it is now "Jarvis memory"?** No — provided the ingestion module never treats stored memory as anything other than `UNTRUSTED`, which is what this plan requires and Batch 3 proves. Nothing about content having previously passed through `save memory` (itself GREEN, since saving arbitrary user-provided text has no side effect beyond storage) grants it elevated trust later.

---

## 14. Approval Decision

Reading a memory (already GREEN, unchanged) and supplying its content to advisory AI creates no new side effect beyond what Phase 7/8 already defend against via the trust/injection pipeline. Consistent with Phase 8's own decision for file content: **no new approval gate is introduced for reading a memory or for summarising it via advisory AI.** Approval remains tied to actions with real consequences (`memory_update`, `memory_forget`, both unchanged and untouched by this phase).

---

## 15. Observability Requirements

**Revised by architecture review.** Because acquisition now goes through `MemoryManager.get()` directly (§10) rather than `ToolExecutor`, the free `tool_call` audit event Phase 8 relied on for file acquisition does **not** exist on this path. This must be replaced deliberately, mirroring how Batch 4 itself added a wholly new, explicit audit responsibility (`_audit_unexpected_action`) rather than assuming one already existed:

- **Memory retrieved (success) / memory not found (failure):** no longer free. `JarvisOrchestrator`'s new `_handle_memory_summary_request()` method (Batch 2) must emit its own audit event for the acquisition outcome via the orchestrator's existing, already-optional `self._logger` — reusing the existing `EventLogger`/`EventOutcome` machinery, not a new logging subsystem. This is a small, explicit, disclosed addition, exactly the kind of gap Batch 5A exists to prevent from going unnoticed a second time.
- **Memory content truncated:** an open question, carried forward with the same evidence-based caution Phase 8 applied to file truncation — whether this warrants a distinct audit event, and if so which `EventOutcome` truthfully fits, is for Batch 1/2 to decide with evidence, not by default. The `truncated: bool` field on `MemoryIngestionResult` (§16) at minimum makes the fact available to whichever layer decides to audit it.
- **Memory supplied to AI:** already covered by the existing `ai_call` event (`AIRouter.route()`), unchanged.
- **Injection detected in memory content:** fully inherited from Batch 5A. Zero new work.
- **Multiple memories selected:** not applicable to this phase's single-record scope.

No audit event may embed the raw memory content itself — only identifying, non-sensitive detail, matching the precedent already set for file content and injection audits.

---

## 16. Size/Quantity Limiting Strategy

**Quantity:** exactly one memory per request, by explicit id — no quantity policy is needed, by scope choice (§8, Candidate A vs. C).

**Size:** unlike `FileReadTool`, neither `MemoryManager.get()` nor `MemoryTool`'s `"get"` operation truncates content today — a real, disclosed difference from the file case, and now a more direct one, since Batch 1 depends on `MemoryManager.get()` directly (§10) rather than any tool. Rather than modifying `MemoryManager` (which would change the return contract for every existing caller, including `MemoryTool`'s own human-facing `"show memory <id>"` output — an unrelated regression risk this phase must not introduce), the new `ingest_memory_for_ai()` function applies its own character-limit truncation to **`record.content` only** — never `record.id`, `.category`, `.source`, `.session_id`, or `.created_at`, none of which are ever part of the truncatable text payload; they only ever inform the `AIContextBlock.source` label, never its `.text`.

**Truncation is represented honestly, not silently.** Unlike Phase 8, where `FileReadTool` already baked a `"[... truncated ...]"` notice into its own returned text (so `ingest_file_for_ai` needed no additional bookkeeping), no equivalent exists one layer below `MemoryManager.get()` — Batch 1 must both perform the truncation and represent that it happened:
- `MemoryIngestionResult` carries a new `truncated: bool` field, so later workflow or audit code can distinguish full memory content from shortened content without re-parsing text.
- The `AIContextBlock.text` itself also carries an explicit, human- and AI-readable truncation notice when truncation occurred, mirroring `FileReadTool`'s own convention — so the AI's own reasoning about the memory is honest about its incompleteness too, not just the structured result.

**The default character limit is a disclosed judgement call, not a re-derived policy.** Reusing Phase 8's `4000`-character default for consistency across ingestion sources is a reasonable starting point, but it is not independently justified by anything specific to typical memory size — memories are short, user-typed notes, so `4000` is a generous ceiling here, not a tight budget. Batch 1 is free to choose a smaller default if evidence (e.g. existing memory content lengths in testing) supports it; this is implementation-level judgement, not a fixed requirement of this plan. As in Phase 8, this remains a simple, deterministic character count — **not** token-aware model budgeting, and no tokenizer dependency is introduced.

---

## 17. Persistence Decision

**Ephemeral only**, unchanged from Phase 8. No new storage table, no persisted row, no cache. Ingested memory content exists only for the duration of the single request that ingested it.

---

## 18. Logical Implementation Batches

### Batch 1 — Stored-Memory Ingestion Foundation

**Purpose.** Build the one new, narrow, memory-specific adapter that acquires a single memory by id and labels it as `UNTRUSTED` AI context atomically.

**Components included.** A new module, `ai/memory_ingestion.py`: `ingest_memory_for_ai(memory_manager: MemoryManager, memory_id: int, *, max_chars: int = <default>) -> MemoryIngestionResult`, which itself calls `memory_manager.get(memory_id)` (never `ToolExecutor`/`MemoryTool` — §10), truncates **only** `record.content` to `max_chars` if needed (recording `truncated: bool`), and returns `AIContextBlock.from_untrusted(text, source=f"memory:{record.id}")` on success (the *returned* record's own id), or a represented failure on a not-found id. `MemoryIngestionResult` — a frozen dataclass mirroring `FileIngestionResult`'s shape, enforcing via `__post_init__` that exactly one of `context`/`error` is ever set, from the start, plus the new `truncated: bool` field.

**Why they belong together.** Both are one cohesive acquisition boundary; the truncation policy and the result type are both intrinsic to what "ingestion" means for this source, exactly as Phase 8 Batch 1 bundled `FileIngestionResult`'s invariant with the adapter itself.

**Main architectural risk.** Reaching for `ToolExecutor`/`MemoryTool` out of surface-level consistency with Phase 8's file adapter, when `MemoryTool`'s `"get"` operation returns CLI-formatted display text (id and category baked directly into the content string) rather than the memory's actual content — using it as AI context would couple the AI boundary to presentation formatting that could change for cosmetic reasons alone (§10). Mitigation: depend on `MemoryManager.get()` directly, which already returns a clean, typed `MemoryRecord`; this is a deliberate, disclosed exception to "always go through `ToolExecutor`," justified because `MemoryManager` — not the tool built on top of it — is the true acquisition boundary for this source. The corresponding, equally real risk this creates — losing the free `tool_call` audit event `ToolExecutor` would have provided — is not this batch's to silently absorb; it is Batch 2's explicit responsibility (§15).

**Tests required.** A successful acquisition → correct `AIContextBlock` with `trust=UNTRUSTED` and `source=f"memory:{record.id}"`; a not-found id → a represented failure, never a raised exception; a test proving the function's signature has no seam for supplying content and a source label independently, or a pre-existing `MemoryRecord`/`ToolResult`; truncation behaviour for an oversized memory, proving `record.content` is truncated while `record.id`/`.category`/`.source`/`.created_at` are never part of the truncated text and the result's `truncated` flag is set accurately; a test proving the source label always reflects the truncated result's own record id; `MemoryIngestionResult` rejects a contradictory (`both`/`neither`) construction, proven directly, mirroring `test_file_ingestion.py`'s own invariant tests from the start.

### Batch 2 — Command and Orchestrator Wiring

**Purpose.** Give Nathan an explicit way to ask Jarvis to reason about one named memory's contents, using Batch 1's adapter, with full Batch 4 unexpected-action coverage and an explicit acquisition audit trail.

**Components included.** `core/command_router.py`: `match_memory_summary(text) -> str | None`, recognising `"summarise memory <id>"` / `"summarize memory <id>"` and extracting the raw (unparsed) trailing id text, reusing the existing numeric-id-extraction convention already used for `"forget memory <id>"`/`"show memory <id>"`. `core/orchestrator.py`: `JarvisOrchestrator.__init__` gains a new `memory_manager: MemoryManager | None = None` constructor parameter (mirroring the existing optional-collaborator pattern already used for `approval_manager`/`reasoning_engine`/`security_manager`), so the orchestrator can pass it to Batch 1's adapter. One new, terminal method, `_handle_file_summary_request`'s direct sibling, that parses the id, calls `ingest_memory_for_ai`, **emits its own acquisition audit event via `self._logger`** (replacing the `tool_call` event this path no longer gets for free — §15), calls `AIReasoningEngine.reason()`, and calls the existing `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods directly. An invalid or non-numeric id produces an honest failure, exactly like an empty file path. `main.py`'s composition root passes the existing `memory` instance through to the orchestrator.

**Why they belong together.** The command and the orchestrator path are two halves of one user-facing feature, mirroring Phase 8 Batch 2 exactly.

**Main architectural risk.** Three risks, the first new to this phase: (a) silently dropping acquisition observability now that `ToolExecutor` is not on this path — mitigated by making the orchestrator's own audit emission an explicit, tested part of this batch, not an afterthought; (b) silently skipping Batch 4's unexpected-action evaluation; (c) concentrating command-matching or acquisition logic in the orchestrator. Mitigation for (b)/(c): identical to Phase 8 — command-matching stays in `CommandRouter`, acquisition stays in Batch 1's adapter, and the orchestrator's new method does only what its file-summary sibling already does at the same scale.

**Tests required.** Unit tests for `match_memory_summary`'s match/extract logic, including a non-numeric or missing id. Orchestrator-level tests mirroring `test_file_summary_workflow.py`'s own suite: successful summary, memory-not-found, AI disabled/unavailable/failure/empty-response, Plan unaffected, no tool execution/approval from an AI suggestion, and GREEN/YELLOW/RED unexpected-action coverage — plus a new test proving the acquisition audit event actually fires (success and not-found cases), since it is no longer implicit. A new integration test file, `tests/integration/test_memory_summary_end_to_end.py`, proving the real stack for a successful case.

### Batch 3 — End-to-End Security Verification and Documentation

**Purpose.** Prove the complete path against a genuine (not synthetic) memory record, including a real injection attempt, and document Phase 9 in the established voice of Phases 1–8.

**Components included.** `tests/integration/test_memory_summary_end_to_end.py` (from Batch 2) extended with: a real memory saved through the real `MemoryManager`, containing a known injection pattern, exercised through `"summarise memory <id>"` end to end; direct provenance verification (the exact `AIContextBlock.source` reaching `AIRouter.route()` equals `f"memory:{memory_id}"`); the same workflow-integrity proofs Phase 8 Batch 3 added (provider failure, empty response, exactly-one-acquisition, multi-line-summary unexpected-action coverage). `docs/phase_9_completion_report.md` and a README update.

**Why they belong together.** Verification and documentation are inseparable in this project's established discipline, exactly as in Phase 8.

**Main architectural risk.** Understating what was actually proven, or overstating Phase 9 into a general memory/knowledge capability it is not. Mitigation: the same disclosure discipline every prior phase's Batch 3 has followed.

**Tests required.** The extended consolidated end-to-end file; a final full-suite run reporting the new authoritative total.

---

## 19. Integration Verification

- The full pre-existing suite (every Phase 1–8 test) passes with zero assertion changes.
- The new consolidated end-to-end test passes against a real, saved memory record, not a synthetic string.
- `git diff --check` clean at every batch boundary.
- A manual or scripted run confirms the CLI experience: asking Jarvis to summarise a real memory produces a clearly-labelled advisory response, with AI reasoning both enabled and disabled.

---

## 20. Phase Completion Criteria

- All three batches individually meet their own success criteria.
- The full test suite passes throughout, count only growing.
- No GREEN/YELLOW/RED classification changed for any existing action string.
- No new approval gate exists for reading a memory or supplying it to AI.
- Memory content is provably `UNTRUSTED` at every point in the path, by direct test assertion.
- The Batch 4 unexpected-action policy is proven to apply to memory-derived AI output, not merely assumed to.
- `MemoryTool`/`MemoryManager` are unmodified — confirmed by a zero-diff check, exactly as `ai/context_models.py`/`ai/prompt_builder.py` were confirmed unmodified in Phase 8.
- The orchestrator's own acquisition audit event (§15) is proven to fire for both the success and not-found cases, not merely assumed to replace the `tool_call` event this path no longer receives for free.
- `AIContextBlock.source` is proven, by direct test assertion, to be derived from the *returned* `MemoryRecord.id`, not merely echoed from the caller-supplied `memory_id` parameter.

---

## 21. Risks and Rollback

- **Batch 1** is low-risk and independently revertible: one new module, no changes to existing memory code.
- **Batch 2** carries this phase's main risk, identical in kind to Phase 8 Batch 2: a new orchestrator response path that must not disturb `_attach_ai_suggestion` or `_handle_file_summary_request`'s existing guarantees, and must not silently skip Batch 4's unexpected-action evaluation. Mitigated the same way: treating the full existing test suite's unchanged pass as a hard gate, plus a dedicated test proving reused unexpected-action coverage.
- **Batch 3** is documentation- and test-only; minimal risk.
- Phase-level rollback: each batch is an independent, revertible commit. No batch introduces a database migration or persisted state.
- **Not a Phase 9 risk, but disclosed for completeness:** memory retrieval by id has no session-ownership check (§6, §12 item 10) — `MemoryManager.get(memory_id)` returns any memory with a matching id regardless of which session created it. This predates Phase 9, is already exposed by the shipped `"show memory <id>"` command, and is not widened by this phase. It is not treated as a blocking risk here because Jarvis is presently single-user and local, and `session_id` is not defined anywhere in the system as a security principal. This plan does not redesign memory session authorization, and no change to `MemoryManager`, `EpisodicMemoryStore`, `MemoryTool`, or existing memory retrieval behaviour is made or proposed to add one.

---

## 22. Deferred Work

Explicitly out of scope for Phase 9, to be revisited only in their own, separately-scoped phases:

1. **Multi-memory retrieval and selection feeding a single AI call** (Candidate C, §8) — the natural next step once single-record ingestion is proven, requiring its own design for ordering, delimiting, and a combined size budget across several `AIContextBlock`s or one combined block, with an explicit owner for that logic.
2. **Semantic, Procedural, and Entity Memory** (Master Specification Ch. 18) and the **Knowledge Library** (Ch. 9/19) — the specification's own later phases, requiring new dependencies (vector embeddings, ChromaDB) not yet introduced anywhere in this codebase.
3. **Goal Management** (Ch. 15) — depends on Entity Memory, which does not exist.
4. Web/browser content ingestion — still deferred from Phase 8, unaffected by this phase.
5. A generic, multi-source ingestion framework or shared base class — still premature with only two concrete examples (file, memory); reconsider only with a third.
6. Sensitivity-aware filtering of memory categories (e.g. treating `"personal"` differently from `"general"` before AI ingestion) — categories are explicitly documented as organisational only, never security-relevant, today; introducing a sensitivity policy would be a new, separate security decision, not a default of this phase.
7. Token-aware, provider-specific size limiting.
8. **Session/user authorization model for memory retrieval.** If Jarvis later becomes multi-user, remotely shared, or begins treating sessions as security principals, `MemoryManager.get(memory_id)`'s unscoped-by-id retrieval — inherited unchanged by this phase's `ingest_memory_for_ai()` — must be reviewed before relying on a memory id alone as a sufficient access identifier. Not applicable to the current single-user, local architecture, and not a prerequisite for this phase.

---

## 23. Exact Recommended Post-Phase Action

Once Phase 9 is complete and closed: begin planning **multi-memory retrieval and selection** (Deferred Work item 1) as the natural continuation — the first capability that requires a real answer to "which memories, how many, and how are they combined" now that single-record ingestion has been proven twice (file, memory). Web/browser ingestion, and any Semantic/Entity Memory work, remain explicitly further out, each requiring its own separately-scoped design review before being started.

---

## Summary

Phase 9 is Phase 8's own recommended next step, executed with the same discipline: one already-complete, already-tested retrieval primitive (`MemoryManager.get`, not the `MemoryTool` CLI-display wrapper built on top of it — an architecture review found and corrected this distinction before implementation), one thin new adapter establishing provenance by construction from the *returned* record, an explicit, disclosed replacement for the audit event lost by depending on `MemoryManager` directly instead of `ToolExecutor`, one new explicit command, and full reuse — never a bypass — of every other Phase 7 and Phase 8 guarantee (trust, injection scanning and auditing, unexpected-action policy, advisory-only AI authority). Nothing here completes the Master Specification's Memory Engine, and nothing here builds a shared ingestion framework prematurely. The phase's purpose is narrow and specific: prove, for a second time, that the ingestion pattern Phase 8 established generalises — this time to a source acquired by database identity rather than filesystem path, and to a source whose existing tool wraps its typed retrieval in display formatting rather than passing it through raw — before any generalisation is considered.
