# Jarvis Phase 10 Implementation Plan

**Version:** Phase 10 — Multi-Memory Retrieval and Selection for Advisory AI
**Builds on:** `6f1664b` (Phase 9 complete: Stored-Memory Ingestion for Advisory AI, Batches 1–3 plus AIRouter Audit Failure Isolation closure fix)
**Date:** 2026-07-08

---

## 1. Purpose

Phase 9 proved that a single stored memory, retrieved by its explicit id, can be safely supplied to advisory AI through the completely unmodified Phase 7 trust and injection-defence pipeline. Phase 9's own completion report (Exact Recommended Next Action) and `docs/phase_9_implementation_plan.md §23` both name the same next step: **multi-memory retrieval and selection**.

The problem this phase solves is no longer "can Jarvis put a memory into AI context" — that is proven. The problem is: **which memories are selected, how many, in what order, under what limits, and how are multiple untrusted memory records safely represented and combined for one AI reasoning call?** This is a materially new architectural question — cardinality, ordering, combined-context trust, and cross-record injection composition do not exist for a single record and cannot be answered by re-running Phase 9's own design unchanged.

No repository documentation defines a different number or name for this phase. `docs/` contains `phase_1` through `phase_9` only; no `phase_10_*` file exists yet, and the Master Specification does not mention a "Phase 10" or this capability by name. **Phase 10** is therefore the correct, uncontested next number.

---

## 2. Scope

**In scope:** retrieving a small, explicit, user-named set of existing Episodic Memory records by id, combining their content into one safely-represented AI context, and supplying it to the advisory AI reasoning path — through the existing, unmodified Phase 7/8/9 trust and injection-defence pipeline.

**Out of scope (see §13 for the full list):** any form of automatic, recency-based, category-based, or search-based memory *selection*; semantic/vector retrieval or ranking; AI-selected or AI-ranked memory retrieval; autonomous memory discovery; background indexing; memory mutation or deletion; multi-user/session-isolation redesign; long-context summarization/chunking frameworks; any change to `PromptBuilder`'s or `AIRouter`'s core signatures; any change to `MemoryManager`, `MemoryTool`, or `EpisodicMemoryStore`.

---

## 3. Success Criteria

- A user can ask Jarvis to summarise an explicit, small set of stored memories by id in one request, and receive one advisory, clearly-labelled AI response informed by all of them.
- Every combined memory record remains provably `ContentTrust.UNTRUSTED`; combining N untrusted records never upgrades trust.
- A synthetic cross-record injection (a pattern that only forms when two records' content is read together) is detected and audited, proving the Phase 7 defence generalises to *combined* content, not just single records.
- Ordering, deduplication, cardinality limits, and per-record/total size limits are all deterministic and directly tested.
- Phase 8's file-summary and Phase 9's single-memory-summary workflows are unaffected — their own existing tests pass byte-for-byte unchanged.
- No existing Phase 1–9 test's assertions change. Full test suite passes throughout, count only growing. The current **903-test suite is the regression floor.**
- No new approval gate, no `SecurityTier` change, no new AI execution authority.

---

## 4. Explicit Non-Goals

Restated precisely from §13, so no batch can silently drift into it:

- No vector embeddings, semantic search, or memory ranking by an LLM.
- No AI-selected or autonomously-discovered memory retrieval — every selected memory is named explicitly, by id, by the user, in the live request.
- No recency-based, category-based, or free-text-search-based *automatic selection* (see §8, Candidate Comparison — deliberately deferred, not rejected).
- No background indexing of any kind.
- No multi-user or session-isolation redesign (memory retrieval remains exactly as session-unscoped as it already is — see §11).
- No memory mutation or deletion capability.
- No long-context summarization or chunking framework — size limiting remains a simple, deterministic character count.
- No change to `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `PromptBuilder`'s public signature, `AIRouter`'s public signature, or `AIReasoningRequest`'s existing fields.
- No new `SecurityTier`, no new approval gate, no change to any existing GREEN/YELLOW/RED classification.

---

## 5. Architectural Constraints

Carried forward unchanged from Phase 9 (itself carried from Phase 8/7), plus one new constraint this phase's own investigation requires:

1. Narrow interfaces and dependency injection over broad ones.
2. No new subsystem, no new distributed/async mechanism.
3. Every audit-relevant event emits through the existing `EventLogger`/`EventOutcome` machinery.
4. A batch is not complete until its own tests pass **and** the full suite, including every pre-existing test, passes unchanged.
5. `classify_action` remains the sole tier authority.
6. AI remains advisory in every batch, in every configuration, without exception.
7. One batch per short-lived branch; no batch is committed without explicit, per-batch approval.
8. No real network call anywhere, in any test.
9. Provenance is established by construction, never by an independently caller-supplied label — generalised in this phase from "the one record actually retrieved" to "the set of records actually retrieved."
10. A second/third concrete example does not justify a shared multi-source framework — still true; this phase adds no new *source*, only a new *cardinality* for the existing memory source.
11. **(New) A single combined `AIContextBlock` is the only way multiple untrusted records may reach `PromptBuilder`.** `PromptBuilder.build()`'s existing `context: AIContextBlock | None` signature is not touched. Combination happens entirely upstream, in the ingestion layer, before any AI-routing code is ever reached.

---

## 6. Current-State Assessment

Confirmed by direct inspection this session, not assumption:

- **`PromptBuilder.build()` accepts exactly one optional `context: AIContextBlock | None`.** Confirmed at `ai/prompt_builder.py:198`. There is no seam today for passing more than one context block.
- **`AIReasoningRequest.context_block: AIContextBlock | None`** (`ai/reasoning_models.py:62`) is likewise singular.
- **`MemoryManager` already exposes four retrieval mechanisms**, all deterministic, all already tested: `get(memory_id)` (by-id), `list_recent(limit, category=None)` (recency), `list_by_category(category, limit)`, `search(query, limit, category=None)` (case-insensitive substring). None of these is semantic/vector-based; none requires a new dependency.
- **`ai/memory_ingestion.py` (Phase 9 Batch 1) already owns the single-record acquisition boundary**: `ingest_memory_for_ai(memory_manager, memory_id, *, max_chars=4000) -> MemoryIngestionResult`. It calls `MemoryManager.get()` directly (never `MemoryTool`/`ToolExecutor`), truncates only `record.content`, and derives provenance from the *returned* record's own id. This function, and its internal `_truncate()` helper, are directly reusable building blocks for this phase — not to be duplicated.
- **`JarvisOrchestrator._audit_memory_acquisition()` (Phase 9 Batch 2) already owns the acquisition-audit responsibility** for the direct-`MemoryManager` path, since it never receives `ToolExecutor`'s free `tool_call` event. It emits one `memory_acquisition` event per call, with `detail` containing only `memory_id`/outcome/truncated — never raw content.
- **`AIRouter._emit_audit_event()` (Phase 9 closure fix) already isolates a failing logger** from altering routing success/failure semantics — this protection is inherited for free by any new workflow that routes through `AIReasoningEngine.reason()` → `AIRouter.route()`, with no further change needed.
- **`SecurityManager._RULES` classifies every existing memory-read action ("show memory") GREEN**, via the `"show"` keyword rule; `ingest_memory_for_ai`'s direct-`MemoryManager` path never calls `classify_action` at all, by Phase 9's own disclosed, accepted design (Security Invariant 5). This is unchanged and directly relevant here (see §9).
- **`CommandRouter.match()`'s existing `_MEMORY_KEYWORDS` substring rule** (`("memory", "memories", "remember", "recall")`) already, incidentally, matches any text containing "memories" — confirmed harmless today only because `JarvisOrchestrator.handle_request()` checks the narrower `match_memory_summary()`/`match_file_summary()` methods first and returns terminally. A new plural command must be checked the same way.
- **No file in this repository combines more than one `AIContextBlock`, ever.** Grepped directly: the only `AIContextBlock` construction sites are `ai/context_models.py` (the factories themselves) and `ai/file_ingestion.py`/`ai/memory_ingestion.py` (one block each, one source each). This phase is the first to combine multiple.

---

## 7. Master Specification vs. Production Gap Analysis

- The Master Specification's Ch. 18 "Retrieval Strategy" names its own **"Phase 1"** (keyword search + recency weighting — matches current production exactly) and **"Phase 2"** (semantic/vector embeddings via ChromaDB — not implemented). These are the *Memory Engine's own* internal phase labels, unrelated to this project's Phase 1–10 numbering, and must not be conflated: **this Phase 10 plan stays entirely within the Memory Engine's own documented "Phase 1"** (deterministic, keyword/recency/id-based) — it does not implement the Memory Engine's own "Phase 2" (semantic/vector), which remains explicitly future work, unchanged from Phase 9's own gap analysis.
- No spec chapter names "multi-memory retrieval," "memory combination," or an equivalent capability directly — this is a production-driven, not spec-mandated, evolution, exactly as Phase 9 itself was.

---

## 8. Candidate Comparison

### 8.1 Retrieval/selection mechanism

**Candidate A — Explicit multiple memory ids, named by the user in one request (e.g. `"summarise memories 3, 7, 12"`).** *Selected.*

| Criterion | Assessment |
|---|---|
| Determinism | Total — the exact set is whatever the user typed, nothing else |
| New selection-policy questions introduced | None — "which records" is fully answered by the request text itself |
| Repository support required | None beyond what Phase 9 already built (`MemoryManager.get()` per id) |
| Risk of scope creep into "intelligent" retrieval | None — there is no ranking, no relevance judgement, no AI involvement in selection |
| Testability | High — every input is a closed, enumerable set |

**Candidate B — Recency-based (`"summarise my last N memories"`, via `MemoryManager.list_recent(limit=N)`).** *Deferred, not rejected.*
Fully deterministic and already repository-supported, but introduces a genuinely new selection-policy question this phase should not bundle with proving safe combination: what is the default/maximum N, and does "recent" mean "as of request time" (a moving target that makes tests order-dependent on wall-clock/insertion time, not just on stated inputs)? This is real, valuable future work, but it is a *selection* decision layered on top of whatever *combination* architecture this phase establishes — sequencing it after Candidate A (exactly as Phase 8's file ingestion was proven before Phase 9's memory ingestion) keeps each phase's own hard problem isolated.

**Candidate C — Category-based (`MemoryManager.list_by_category`).** *Deferred, not rejected.* Same reasoning as Candidate B — "which category, how many from it" is a selection-policy decision, not a combination-architecture one.

**Candidate D — Free-text search-based (`MemoryManager.search`).** *Deferred, not rejected.* Same reasoning again, plus an additional open question Candidate A avoids entirely: how many search results is "enough" context, and in what order (search itself is already deterministic — case-insensitive substring, `created_at DESC` — but "how many hits to include" is a fresh policy question). Explicitly, this project's own standing caution against "broad natural-language memory search" (§10 of this plan's own brief) applies most directly here.

**Decision:** Candidate A is selected as the first deterministic capability. Candidates B/C/D are recorded as **Deferred Memory Engine Work** (§13) — they should reuse whatever combination/ordering/limiting architecture Candidate A establishes, not reinvent it, once their own selection-policy questions are separately scoped and reviewed.

### 8.2 How multiple `AIContextBlock` values reach `PromptBuilder`

**Candidate A — Combine upstream into exactly one `AIContextBlock` before `PromptBuilder.build()` is ever called.** *Selected.*
The new ingestion-layer function retrieves each record, truncates each individually, and joins them with explicit per-record provenance delimiters into one combined text, wrapped in one `AIContextBlock.from_untrusted(combined_text, source="memory-set:<ids>")`. `PromptBuilder`, `AIRouter`, and `AIReasoningRequest` require **zero changes** — the existing, already-hardened Phase 7/8/9 core plumbing sees exactly the shape it has always seen: one context block.

**Candidate B — Extend `PromptBuilder.build()`/`AIReasoningRequest.context_block` to accept a sequence of `AIContextBlock`s, each framed and scanned individually.** *Rejected for this phase.*
This would touch the one piece of core AI plumbing every prior phase has deliberately left untouched since Phase 7 Batch 2, requiring changes to `PromptBuilder`'s signature, `AIRouter.route()`'s `context` parameter, and `AIReasoningRequest`'s field shape — a materially larger blast radius for a benefit (individually-scoped per-record framing) that Candidate A also achieves, in weaker but sufficient form, via per-record delimiters inside one combined block (see §8.3). Rejected per Architectural Constraint 11 (§5) and the explicit brief instruction to avoid touching `PromptBuilder` unless clearly required — it is not required here.

### 8.3 Injection scanning: per-record, combined, or both

**Selected for this phase: rely on `PromptBuilder`'s existing, already-free, automatic scan of the one combined block.** No new scanning code is required — `SecurityManager.scan_for_injection()` already runs, unconditionally, on any UNTRUSTED context block `PromptBuilder.build()` receives, and it will see the **full composed context, including every Jarvis-authored delimiter and any memory content that happens to resemble one** — the scan is never applied to a pre-delimiter-stripped or otherwise reduced view of the text.
**Rejected for this phase, deferred:** an *additional* per-record scan inside the new ingestion function (scanning each record's content individually, before combination, for finer-grained "which record" audit attribution). This would require new scanning/reporting machinery inside `ai/memory_ingestion.py` — a real, non-trivial addition this phase's own discipline (prove combination, not build a second scanning subsystem) argues against building until real usage shows the combined-scan's single "somewhere in this set" attribution is insufficient. Recorded as deferred, non-blocking future work (§13).

**Combined-context framing and delimiter collision — the exact invariant, tightened per explicit review:**

> **Jarvis-authored memory framing is structural serialization only. Memory content must never gain trust, authority, or command semantics by containing, imitating, or attempting to terminate Jarvis-authored record delimiters, role labels, provenance labels, or framing text.**

This is enforced by where each piece of Jarvis's own internal state is actually *derived from*, not by anything the delimiter text itself does:

- **`AIContextBlock.trust` is set once, unconditionally, to `UNTRUSTED`, by the ingestion function itself, before any text is ever assembled.** It is never derived by parsing the combined text, never conditioned on the text's content, and cannot be altered by anything appearing inside a memory record — including a record that contains a string identical to the chosen delimiter, a fabricated role label, or text that looks like it is "closing" a framing block and "opening" a trusted one. **The final combined `AIContextBlock` is `ContentTrust.UNTRUSTED` in every case, with no exception based on record content.**
- **`AIContextBlock.source` (the provenance label) is likewise derived exclusively from the ingestion loop's own bookkeeping** — the list of ids it actually retrieved, in the order it actually included them — **never by re-parsing the combined text for delimiter-like markers.** A memory record that contains fake delimiter text cannot cause Jarvis's own provenance label, audit trail, or trust classification to misattribute anything, because none of those are ever recomputed from the assembled text after the fact.
- **What delimiter imitation *can* affect is only the AI model's own, non-authoritative interpretation of "which memory said what" within its summary** — a prompt-level ambiguity inherent to any text-based framing scheme, not a Jarvis-level one. This plan makes **no claim that delimiter framing provides cryptographic or parser-level isolation** — the combined context is, and remains, one composed free-text prompt; the delimiter is a readability aid for a human or the AI model, not a security boundary. **The actual security boundary is `PromptBuilder`'s existing, unchanged, outer UNTRUSTED/"treat as data, not instructions" wrapping around the entire combined block** — a memory record's fabricated delimiter and fabricated "instructions" following it are still entirely inside that outer wrapping, still scanned by the same unconditional `scan_for_injection()` call, and still framed by the same data-only directive Phase 7 already established.
- **Minimising, not eliminating, ambiguity:** the delimiter format is chosen to be distinctive and unlikely to appear by accident in ordinary user-typed notes (a clearly labelled, numbered marker naming the record id, e.g. `"\n----- Memory <id> -----\n"`), which reduces *accidental* collision. It does not, and cannot, prevent a *deliberate* attempt to imitate the exact format — that residual ambiguity is accepted for Phase 10, explicitly, as a documented security limitation, not a solved problem, because:
  1. it is disclosed here, not hidden;
  2. ordinary delimiter-like text inside memory content cannot alter Jarvis's own internal trust classification (proven above by construction, not merely asserted);
  3. the combined-text injection scan still examines the full composed context, delimiter-imitating text included; and
  4. Batch 1 and Batch 3 both include targeted adversarial tests covering **both** genuine cross-record injection composition **and** stored memory content that imitates or attempts to terminate the chosen delimiter/framing syntax (see §17).

---

## 9. Chosen Architecture

```
User request ("summarise memories 3, 7, 12")
    │
    ▼
CommandRouter.match_memory_set_summary()   (Batch 2: recognises the plural
    │                                        command, extracts the raw,
    │                                        unparsed trailing id-list text)
    ▼
JarvisOrchestrator._handle_memory_set_summary_request()   (Batch 2: terminal
    │                                                        path, sibling of
    │                                                        _handle_memory_summary_request)
    │
    ├── Planner.create_plan()             (unchanged: normal Plan generation)
    │
    ├── _parse_memory_ids(raw_ids_text)    (Batch 2: splits on comma/whitespace,
    │       validates each token is digits-only, dedupes preserving
    │       first-occurrence order, enforces the cardinality ceiling -
    │       ALL request-shape validation happens here, before any DB call)
    │
    ├── ai.memory_ingestion.ingest_memories_for_ai()   (Batch 1: the only new
    │       │                                            acquisition component)
    │       ├── MemoryManager.get(id) for each validated id, in order
    │       │       (each call wrapped in its own try/except - a single
    │       │        record's retrieval error never aborts the whole batch)
    │       ├── per-record truncation (reuses Batch 1's _truncate() helper)
    │       ├── running total-size budget check (size-based omission,
    │       │       disclosed, never silent)
    │       └── combine included records into ONE delimited text →
    │           AIContextBlock.from_untrusted(text, source=f"memory-set:{ids}")
    │
    ├── JarvisOrchestrator emits one memory_acquisition audit event PER
    │       requested id (found/not-found/retrieval-error/omitted-for-size),
    │       via a small, compatibility-preserving refactor of the existing
    │       _audit_memory_acquisition into a shared per-id helper reused by
    │       both the Phase 9 singular path and this new plural path
    │
    ├── AIReasoningRequest(context_block=<the ONE combined block above>)
    │                                                    (unchanged field, Phase 8)
    │
    ├── AIReasoningEngine.reason()  →  AIRouter.route()  →  PromptBuilder.build()
    │       (unchanged: UNTRUSTED framing, ONE injection scan over the
    │        combined text, audit_suspicious_injection, AIRouter's own
    │        logger-failure isolation - all inherited for free)
    │
    └── _evaluate_unexpected_actions() / _audit_unexpected_action()
            (Phase 7 Batch 4, reused unchanged)
```

Every box in this diagram below "Planner.create_plan()" is either a Phase 10 addition or unmodified Phase 7/8/9 code. `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `MemoryManager`, `MemoryTool`, and `EpisodicMemoryStore` are untouched.

---

## 10. Multi-Memory Provenance Model

- **`ingest_memories_for_ai()` is the sole caller of `MemoryManager.get()`** for every id in the validated set — it never accepts pre-existing records, pre-combined text, or a caller-supplied combined label.
- **Provenance is derived from the set of *actually retrieved* records, in final included order** — `source=f"memory-set:{','.join(str(id) for id in included_ids)}"` — never merely echoing the originally-requested id list, since some requested ids may be dropped (not-found, retrieval error, or size-omitted) before the final combined block is built. This generalises Phase 9's own "derive from the returned record, not the request" guarantee from one record to a set.
- **`MemorySetIngestionResult`** (frozen, slots, mirroring `MemoryIngestionResult`'s shape) carries: `context: AIContextBlock | None`, `error: str | None` (XOR-enforced, as before), plus itemized, disclosed accounting fields — `included: tuple[int, ...]`, `not_found: tuple[int, ...]`, `retrieval_errors: tuple[int, ...]`, `omitted_for_size: tuple[int, ...]`, `truncated_records: tuple[int, ...]` — so no outcome for any requested id is ever silently absent from the result.
- **Total failure** (`context=None`) occurs only when `included` is empty — i.e. every requested id was not-found, erroring, or omitted. **Partial success** (`context` populated) is explicitly permitted and is the expected common case when some, but not all, requested ids resolve — this is a deliberate design decision (a single bad id must not sink an otherwise-good batch), stated here so it is reviewed as a decision, not discovered as a surprise.

### 10.1 Ordering and Deduplication Contract

**Confirmed and tightened per explicit review — no stronger justified contract exists in the current plan, so this is adopted exactly as specified:**

- **Ordering is first-occurrence, user-specified request order, after stable deduplication. Records are never numerically sorted or otherwise reordered internally.** Example: a request naming `27, 12, 27, 18` selects and orders exactly `27, 12, 18` — the second occurrence of `27` is dropped, and `12`/`18` keep the positions they held relative to each other and to `27`'s first occurrence.
- **This ordering is load-bearing, not cosmetic**, because the total combined-context budget (§15) may cause later records to be wholly omitted — omission must therefore be deterministic and consistent with what the user actually typed, never with an internally-reordered view (for example, an internal numeric sort could silently change *which* records survive a total-size cutoff versus what the user's own request order would produce — this plan explicitly rejects that outcome).
- **Deduplication happens once, at the request-shape validation layer (`_parse_memory_ids`, §17 Batch 2), strictly before cardinality-limit checking and strictly before any `MemoryManager.get()` call.** Consequently: a duplicate id consumes the cardinality ceiling (§15) exactly once, not once per occurrence, and consumes the combined-size budget exactly once, not once per occurrence — `ingest_memories_for_ai()` never sees a duplicate at all, by construction, so there is no seam through which duplicate content could be counted, truncated, or included twice.
- **Duplicates are not itemized as a distinct accounting category in `MemorySetIngestionResult`.** This is a deliberate decision, not an oversight: `included`/`not_found`/`retrieval_errors`/`omitted_for_size` each represent an *outcome that lost the user something they asked for* and must be disclosed; a duplicate is not a loss — the user still receives record `27`'s content, exactly once, which is what "give me memory 27" means regardless of how many times it was named. No test or audit-detail claim should describe deduplication as a failure mode.

### 10.2 Truncation Provenance (confirmed against the actual Phase 9 implementation)

Inspected directly, fresh, before writing this clarification: Phase 9's existing `MemoryIngestionResult` (`ai/memory_ingestion.py`) already carries a `truncated: bool` field, computed once, at ingestion time, by the existing `_truncate()` helper — **no additional database read, and no redesign of Phase 9, is needed to obtain this fact for the multi-memory case.**

- **`ingest_memories_for_ai()` reuses `_truncate()` unchanged, once per included record**, and preserves the resulting per-record `truncated: bool` directly into `MemorySetIngestionResult.truncated_records: tuple[int, ...]` (the ids of every *included* record whose own content was shortened) — computed entirely from information `_truncate()` already produces, not recalculated by any new mechanism.
- **The honest, per-record truncation notice `_truncate()` already appends to a shortened record's own text is preserved verbatim inside that record's own delimited contribution to the combined text.** This extends Phase 9's own principle — "the AI is never led to believe it received complete memory content" — from a single record to each individual record within a set: the AI sees exactly which of the several included memories was cut short, at the point in the combined text where that record's own content appears, not merely an aggregate flag invisible to the AI itself.
- **Goal directly satisfied:** no truncated memory's contribution is ever represented, to the AI or in the result, as though the complete stored record entered context — true per-record (via the preserved notice, inherited unchanged) and true structurally (via `truncated_records`, itemized in the result).

---

## 11. Trust Model

- Every combined record remains **unconditionally `ContentTrust.UNTRUSTED`** — `AIContextBlock.from_untrusted(...)` is the only constructor ever called, exactly as Phase 9. Combining N untrusted records never upgrades trust: trust is not additive, and the Phase 7 Batch 2 sentinel guard (`_TRUSTED_ORIGIN_KEY`) makes `JARVIS_TRUSTED` structurally unreachable regardless of how many records are folded into the one block's text.
- **The per-record delimiter/provenance headers this phase introduces (e.g. `"--- Memory 7 ---"`) are themselves plain untrusted text**, embedded inside the single combined block — they carry no special "structural trust" of their own. `PromptBuilder`'s existing UNTRUSTED framing wraps the *entire* combined block, headers included; nothing about adding internal structure to an untrusted block's own text changes its trust classification.
- `MemoryRecord.source` (capture-origin metadata) continues to be read by nothing except to log which id it belongs to — never as a `ContentTrust` input, unchanged from Phase 9.
- The user's own live request text (e.g. `"summarise memories 3, 7, 12"`) remains `JARVIS_TRUSTED` via `from_live_user_input()` — never conflated with any combined memory content.

---

## 12. Security Invariants

1. Every included memory record's content is always `UNTRUSTED`; never `JARVIS_TRUSTED`; never a `SecurityTier` override; never Nathan approval.
2. The combined context always passes through `PromptBuilder`'s automatic injection scan before reaching a provider — unchanged machinery, now exercised against combined content.
3. A suspicious detection in the combined context is audited through the existing `audit_suspicious_injection()` reporter, inherited for free, with the same "never log the raw matched text" property.
4. AI output derived from multiple memories remains advisory: it cannot execute, approve, reclassify, or modify a Plan — unchanged.
5. The AI cannot trigger its own memory retrieval or expand its own selection; every id in the set is user-named in the live request. Acquisition continues to go through `MemoryManager.get()` directly rather than `ToolExecutor`, per record — the same deliberate, disclosed exception Phase 9 established, unconditionally GREEN and read-only regardless of cardinality.
6. The Batch 4 unexpected-action policy applies to multi-memory-derived AI output exactly as it does everywhere else, via the same, unmodified methods.
7. `MemoryTool`, `MemoryManager`, and `EpisodicMemoryStore` are not modified.
8. A requested id that does not exist, or whose retrieval genuinely errors, produces an honest, itemized accounting entry — never fabricated content, and never a whole-batch crash from one bad id.
9. `MemoryRecord.source` is never read to determine trust for any record in the set.
10. **No new security-tier question is introduced by cardinality.** Reading N memories by explicit id is not more dangerous *in kind* than reading one — it is a larger read, not a write or delete — so no new `SecurityTier` classification, and no bulk-read analogue to `"forget all memories"`'s RED classification, is warranted or added.
11. Memory retrieval remains not session-scoped, exactly as documented in Phase 9 — this phase neither adds nor removes that characteristic, and does not widen the lookup capability beyond retrieval-by-explicit-id (see §Session-Scoping in Phase 9's own report; unchanged here).

---

## 13. Prompt-Injection Implications

Covered in full in §8.3. Restated as the two properties Batch 1/3 must prove, not merely assert:

- A synthetic injection pattern confined to a *single* record within a multi-record request is still detected (proving nothing about the new combination logic weakens the existing single-record guarantee).
- A synthetic pattern that only becomes recognisable when two records' content is read *together* (a genuine cross-record composition test, not achievable with Phase 9's own single-record tests) is also detected, proving the combined-scan design in §8.3 actually holds and is not merely theorised.

---

## 14. Approval Decision

Reading multiple memories (each already GREEN, unchanged) and supplying their combined content to advisory AI creates no new side effect beyond what Phase 7/8/9 already defend against. **No new approval gate is introduced for reading or summarising a set of memories, regardless of how many are requested (up to the cardinality ceiling).** Approval remains tied to actions with real consequences, unchanged.

---

## 15. Cardinality and Size-Limiting Strategy

- **Maximum records per request: a small, conservative, named constant** (candidate default: 10). **Exceeding it is an explicit, honest rejection** ("too many memory ids requested; the maximum is N") — **not** a silent "use only the first N" clamp. This deliberately diverges from this codebase's own existing silent-clamp convention for *listing* limits (`FileListTool`/`MemoryTool`/`ApprovalHistoryStore`'s `_MAX_LIMIT` clamps): those clamp a "give me up to N" request where the user never named individual items, so serving fewer is not surprising; here, the user named specific ids by hand, so silently dropping named items without asking is a materially worse, more surprising failure mode than clamping an open-ended "show me the top N" request. This distinction is deliberate and must be tested, not merely asserted.
- **Maximum content contribution per record**: reuses Phase 9's own `_truncate()` helper and default (4000 characters) — unchanged, per-record semantics, with the same honest, disclosed truncation notice.
- **Maximum combined total size**: a new, separate ceiling (candidate default: 20,000 characters) applied *after* per-record truncation, checked as a running total in requested-then-deduplicated order. A record that would push the running total over the ceiling is **not truncated further** — it is cleanly, wholly omitted from this response, and its id is recorded in `omitted_for_size`, disclosed in the final response wording, never silently dropped.
- **No token-aware or model-specific budgeting anywhere in this phase.** Both limits remain plain, deterministic character counts, exactly as every prior phase's own size-limiting decision.

### 15.1 Size-Budget Interaction — Exact Sequence (confirmed per explicit review)

Whole-record omission for the total combined-context ceiling occurs in exactly this order, and no other:

1. **Stable deduplication** (§10.1) — the requested id list is reduced to its first-occurrence-order, duplicate-free form.
2. **Cardinality-ceiling validation** against the deduplicated list (§17 Batch 2's `_parse_memory_ids`) — an over-limit request is rejected honestly before any retrieval is attempted.
3. **Retrieval**, one `MemoryManager.get()` call per remaining id, strictly in the preserved user-specified order, each call individually guarded so one id's retrieval error never aborts the batch.
4. **Existing, unmodified Phase 9 per-record ingestion/truncation** (`_truncate()`, reused as-is) applied to each successfully-retrieved record's own content, independently of every other record.
5. **The running total-size check**, evaluated strictly in the same preserved user-specified order, against each record's *already-truncated* (step 4) length.

**No record is ever sliced a second time to fill the last remaining combined-context bytes/characters.** A record either fits, in full (after its own, independent, Phase 9-style single-record truncation from step 4), within whatever budget remains when its turn is reached in step 5, or it is wholly, cleanly omitted and itemized in `omitted_for_size` — there is no intermediate "partially include this record a second time, cut differently, to exactly fill the remaining space" behaviour anywhere in this design. Changing this would require a deliberate, separately-justified plan revision before implementation; it is not proposed here.

---

## 16. Persistence Decision

**Ephemeral only**, unchanged from Phase 8/9. No new storage table, no persisted combined-context row, no cache of any kind. The combined context exists only for the duration of the single request that built it.

---

## 17. Logical Implementation Batches

### Batch 1 — Multi-Memory Ingestion Foundation
**Purpose.** Build the one new, narrow adapter that acquires a validated, ordered, deduplicated set of memory ids and safely combines them into one `UNTRUSTED` AI context, with full, itemized, disclosed accounting for every id.
**Components.** `ai/memory_ingestion.py` extended with `MemorySetIngestionResult` and `ingest_memories_for_ai(memory_manager, memory_ids, *, max_records=10, max_chars_per_record=4000, max_total_chars=20000) -> MemorySetIngestionResult`. Reuses the existing `_truncate()` helper unchanged. No command/orchestrator wiring yet — mirrors Phase 9 Batch 1's own scoping discipline exactly.
**Main architectural risk.** Reaching for a second, parallel scanning/combination framework instead of reusing Batch 1 (Phase 9)'s existing `_truncate()` and PromptBuilder's free combined scan. Mitigation: explicit reuse, proven by test, not merely asserted.
**Tests required.** A direct ordering/deduplication test using the exact `27, 12, 27, 18 → 27, 12, 18` example (§10.1); a test proving the duplicate occurrence of `27` consumes cardinality and combined-size budget exactly once, not twice; cardinality ceiling (exact count passes, count+1 rejected honestly); per-record and total-size truncation/omission (under, at, and over each limit, individually and combined), proven to follow the exact five-step sequence in §15.1 (never a second slice to fill remaining budget); not-found and retrieval-error itemization (each producing its own accounting entry, never aborting the batch); total-failure vs. partial-success behaviour; provenance derived from the *returned* set, not the requested set; `truncated_records` proven to reflect `_truncate()`'s own existing per-record fact with no new database read; `MemorySetIngestionResult`'s XOR and empty-set invariants; a genuine cross-record-adjacent-text test proving the delimiter is present and non-empty between every included record; **a targeted adversarial test in which a stored memory's own content contains text identical to the chosen delimiter format, proving the combined block still becomes `ContentTrust.UNTRUSTED`, `AIContextBlock.source` still reflects only the actually-retrieved record ids (never a fabricated one implied by the imitated text), and the imitation is preserved verbatim for the injection scanner to see, never stripped or specially handled.**

### Batch 2 — Command and Orchestrator Wiring
**Purpose.** Give Nathan an explicit way to ask Jarvis to reason about a named set of memories, reusing Batch 1's adapter, with full Batch 4 unexpected-action coverage and itemized acquisition auditing.
**Components.** `core/command_router.py`: `match_memory_set_summary(text) -> str | None`, recognising `"summarise memories <ids>"` / `"summarize memories <ids>"`, extracting the raw trailing id-list text unparsed — confirmed non-overlapping with the existing singular `_MEMORY_SUMMARY_PREFIXES` (verified: "memory" and "memories" diverge at their 5th character, so no prefix collision is possible). `core/orchestrator.py`: `_parse_memory_ids(raw_ids_text)` (splits on comma/whitespace, validates digits-only per token, dedupes preserving first-occurrence order, enforces the cardinality ceiling — all before any DB call); `_handle_memory_set_summary_request()`, the direct sibling of `_handle_memory_summary_request`; **one small, compatibility-preserving internal refactor**: factor `_audit_memory_acquisition`'s single-event-emission body into a shared per-id helper, called once by the existing singular path (unchanged behaviour, proven by Phase 9's own existing tests passing unchanged) and once per id by the new plural path.
**Main architectural risk.** The compatibility-preserving refactor accidentally changing Phase 9's own existing single-record audit event shape. Mitigation: Phase 9's existing `test_memory_acquisition_audit_*` tests are the explicit regression gate for this refactor — they must pass byte-for-byte unchanged, not merely "still pass with different assertions."
**Tests required.** Command-router matching/extraction/non-overlap tests; orchestrator workflow tests mirroring `test_memory_summary_workflow.py`'s own structure (successful multi-summary, invalid/empty/over-limit id lists, partial not-found, memory-manager unavailable, AI disabled/unavailable/failure/empty-response, truncation/omission disclosure, GREEN/YELLOW/RED unexpected-action coverage, itemized audit-event-per-id proof, audit-failure isolation reused from Phase 9/the AIRouter closure fix); an explicit regression test asserting Phase 9's own `_audit_memory_acquisition`-based tests are unaffected by the refactor.

### Batch 3 — End-to-End Security Verification and Documentation
**Purpose.** Prove the complete path against genuine, multiple saved memory records, including a real cross-record injection composition attempt, and document Phase 10 in the established voice of Phases 1–9.
**Components.** A new consolidated integration test, `tests/integration/test_memory_set_summary_end_to_end.py`, built the same way Phase 9's own was: real temporary/in-memory SQLite, real `MemoryManager`, real `CommandRouter`, real `JarvisOrchestrator`, real `ingest_memories_for_ai`, real `AIReasoningEngine`/`AIRouter`/`PromptBuilder`/`SecurityManager`, fake provider only. `docs/phase_10_completion_report.md` and a README update.
**Main architectural risk.** Understating what was actually proven, or overstating Phase 10 into automatic/intelligent memory selection it is not. Mitigation: the same disclosure discipline every prior phase's Batch 3 has followed.
**Tests required.** The new consolidated end-to-end file, including: a genuine two-record cross-composition injection proof (a synthetic pattern only recognisable when two real, saved records' content is read together); a genuine delimiter-imitation proof (a real, saved memory whose own content contains text formatted identically to the chosen record delimiter, proving the resulting combined block is still `ContentTrust.UNTRUSTED`, still fully scanned, and that Jarvis's own provenance/audit state is derived only from the retrieval loop's own bookkeeping, never from re-parsing the delimiter-imitating text); the `27, 12, 27, 18 → 27, 12, 18` ordering/deduplication example proven through the real stack; a final full-suite run reporting the new authoritative total.

---

## 18. Integration Verification

- The full pre-existing suite (every Phase 1–9 test, 903 total) passes with zero assertion changes.
- The new consolidated end-to-end test passes against real, saved memory records, not synthetic strings.
- `git diff --check` clean at every batch boundary.
- A manual or scripted run confirms the CLI experience: asking Jarvis to summarise several real memories by id produces one clearly-labelled advisory response, with itemized disclosure of any id that was not found, erroring, or omitted for size.

---

## 19. Phase Completion Criteria

- All three batches individually meet their own success criteria.
- The full test suite passes throughout, count only growing from 903.
- No GREEN/YELLOW/RED classification changed for any existing action string.
- No new approval gate exists for reading or summarising any number of memories.
- Every included record is provably `UNTRUSTED` at every point in the path, by direct test assertion.
- The Batch 4 unexpected-action policy is proven to apply to multi-memory-derived AI output.
- `MemoryTool`/`MemoryManager`/`EpisodicMemoryStore`/`PromptBuilder`'s public signature/`AIRouter`'s public signature are unmodified — confirmed by a zero-diff check.
- `AIContextBlock.source` for the combined block is proven, by direct test assertion, to be derived from the *actually included* set, not merely the originally requested set.
- The compatibility-preserving `_audit_memory_acquisition` refactor is proven, by Phase 9's own pre-existing tests passing unchanged, to have altered no existing behaviour.
- A genuine cross-record injection composition is proven detected, not merely asserted safe by inspection.

---

## 20. Risks and Rollback

- **Batch 1** is low-risk and independently revertible: one new result type and one new function, no changes to existing memory or AI-plumbing code.
- **Batch 2** carries this phase's main risk: the `_audit_memory_acquisition` refactor, identical in kind to every prior phase's "reuse without regressing" risk, mitigated by treating Phase 9's own existing audit tests as a hard, unchanged-assertion regression gate.
- **Batch 3** is documentation- and test-only; minimal risk.
- Phase-level rollback: each batch is an independent, revertible commit. No batch introduces a database migration or persisted state.

---

## 21. Deferred Work

Explicitly out of scope for Phase 10, to be revisited only in their own, separately-scoped phases:

1. **Recency-based, category-based, or search-based automatic memory selection** (Candidates B/C/D, §8.1) — should reuse this phase's combination/ordering/limiting architecture once separately scoped.
2. **Per-record injection scanning with individual audit attribution** (§8.3) — deferred until real usage shows the combined-scan's coarser "somewhere in this set" attribution is insufficient.
3. **Semantic/vector memory retrieval, memory ranking by an LLM, or AI-selected memory retrieval** — the Master Specification's own later Memory Engine phase, requiring new dependencies not yet introduced anywhere in this codebase.
4. **Background indexing of any kind.**
5. **Multi-user/session-isolation redesign** for memory retrieval — unchanged, non-blocking, single-user-architecture characteristic, unaffected by this phase.
6. **Memory mutation or deletion capability changes** — `memory_update`/`memory_forget` remain untouched.
7. **Long-context summarization or chunking frameworks** — size limiting remains a simple character count.
8. **A raised cardinality/total-size ceiling** — the conservative defaults proposed here (10 records, 20,000 combined characters) are a disclosed starting judgement call, revisable with evidence, not a permanent architectural limit.
9. **The pre-existing `SecurityManager._RULES`/`MemoryTool`-versus-`ingest_memory_for_ai` semantic-drift debt** (Phase 9) — inherited unchanged; still requires reviewing both memory-read paths together before ever reclassifying `"show memory"`.
10. **The pre-existing broad `CommandRouter.match()` memory-keyword overlap** (Phase 9) — inherited unchanged, still non-blocking under the explicit early-dispatch architecture.

---

## 22. Exact Recommended Post-Phase Action

Once Phase 10 is complete and closed: revisit Deferred Work item 1 (recency/category/search-based selection) as the natural continuation, now that the harder combination/ordering/trust/size-limiting architecture is proven — the remaining open question at that point becomes purely "how does Jarvis decide *which* ids to select automatically," not "can multiple untrusted records be safely combined," which this phase will have already answered.

---

## Summary

Phase 10 answers the question Phase 9 deliberately left open: how multiple untrusted, individually-provenanced stored memories can be safely combined into one AI-facing context, without touching the hardened Phase 7 trust/injection/unexpected-action machinery at all. The chosen design combines records upstream into exactly one `AIContextBlock` (never touching `PromptBuilder`/`AIRouter`'s signatures), selects records only by explicit, user-named id (never automatically, never by AI, never semantically), enforces a conservative, honestly-rejected cardinality ceiling and a disclosed, non-silent total-size budget, preserves ordering and deduplication deterministically, and reuses — rather than duplicates — Phase 9's own truncation helper, acquisition-audit pattern, and the just-closed AIRouter logging-isolation fix. Automatic selection of any kind (recency, category, search, semantic, or AI-driven) is deliberately deferred to its own future phase, once this phase's own combination architecture is proven end to end against a genuine cross-record injection attempt.
