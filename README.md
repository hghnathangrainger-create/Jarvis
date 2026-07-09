# Jarvis

Jarvis is Nathan's modular AI operating system project, designed to reduce workload while keeping Nathan in control.

Jarvis is **not** a chatbot. It is an orchestration layer that plans requests, classifies their safety, runs safe tools, remembers information, asks for approval before doing anything sensitive, and can optionally use AI to help interpret requests — with every action recorded.

---

## Current Status

**Phase 5 complete: Better Memory and Personal Knowledge System.**
**Phase 6 complete: Durable Approvals and Approval-Lifecycle Timeout Enforcement.**
**Phase 7 complete: Core Simplification and AI Safety Hardening.**
**Phase 8 complete: Real External-Content Ingestion.**
**Phase 9 complete: Stored-Memory Ingestion for Advisory AI.**
**Phase 10 complete: Multi-Memory Retrieval and Selection for Advisory AI.**
**Phase 11 complete: Deterministic Query-Based Memory Selection for Advisory AI.**
**Phase 12 complete: Deterministic Category-Based Memory Selection for Advisory AI.**
**Phase 13 complete: Deterministic Recency-Based Automatic Memory Selection for Advisory AI.**
**Phase 14 complete: User-Controlled Bounded Recent-Memory Count for Advisory AI.**
**Phase 15 complete: Sequential Workflow Execution — Minimal Multi-Step Planner and Workflow Engine.**

Building on the advisory AI reasoning and guarded write actions from Phase 4, Jarvis now has a real personal knowledge system. Memories can be organised into categories, listed and searched (including within a category), reviewed one at a time, and — behind approval — corrected, re-filed, or forgotten. Reading memory is effortless and automatic; anything that changes or removes a memory asks first.

Phase 6 adds a durable, read-only record of every approval decision, so it survives a restart — without making any past decision resumable or replayable — and a bounded lifecycle for pending approvals: a YELLOW request left unanswered now expires automatically instead of waiting forever. See the Phase 6 section below.

Phase 7 is a **safety and structure phase, not a capability phase**: it simplifies the Core's request-routing code, and completes the Master Specification's prompt-injection defence — trusted-vs-untrusted AI context, automatic scanning of untrusted context for instruction-like patterns (audited when suspicious), and an audited policy for an AI-suggested action that falls outside a request's own plan. No new user-facing command, no new AI power, and no new execution authority were added. See the Phase 7 section below.

Phase 8 is Jarvis's first real use of that trust boundary: an explicit `summarise file <path>` command reads a real file and supplies its contents to the advisory AI as typed, untrusted context — scanned, audited, and never able to gain new authority, exactly as Phase 7 already guarantees. See the Phase 8 section below.

Phase 9 is the second real use of that same trust boundary: an explicit `summarise memory <id>` command reads one already-stored memory and supplies its content to the advisory AI the same way — typed, untrusted, scanned, audited, and never able to gain new authority. See the Phase 9 section below.

Phase 10 extends that same trust boundary to more than one memory at once: an explicit `summarise memories <ids>` command reads a small, user-named set of already-stored memories by id and combines them into one typed, untrusted context for the advisory AI — still scanned, still audited, still never able to gain new authority. Every memory must be named explicitly; nothing is selected automatically. See the Phase 10 section below.

Phase 11 answers the question Phase 10 left open: an explicit `summarise memories about <query>` command deterministically **searches** stored memory content for a query, selects up to 10 matching memories, and combines them the same way Phase 10 already does — still a plain, case-insensitive content-pattern match, not semantic search or AI-selected memory, and still scanned, still audited, still never able to gain new authority. See the Phase 11 section below.

Phase 12 extends automatic selection to a second, complementary dimension: an explicit `summarise memories in <category>` command deterministically looks up stored memories already filed under one of your known categories (`general`, `personal`, `project`, `preference`, `note`) and combines them the same way Phase 10 already does. An unrecognised category is honestly rejected — it is never silently treated as a request for your general-category memories. See the Phase 12 section below.

Phase 13 adds a third, complementary dimension: an explicit `summarise recent memories` command deterministically selects the **newest** up to 10 stored memories across all of your categories and combines them the same way Phase 10 already does. "Recent" here means exactly the newest stored memory records, in deterministic newest-first order — not a time window such as "last 24 hours" or "today." See the Phase 13 section below.

Phase 14 lets you choose exactly how many recent memories to summarise: an explicit `summarise latest <count> memories` command deterministically selects the newest **N** stored memories, where N is a number you supply (1–10). An invalid count (zero, above 10, or not a whole number) is honestly rejected rather than silently rounded or clamped. The original `summarise recent memories` command is unchanged and still means exactly the newest 10. See the Phase 14 section below.

Phase 15 is a genuinely new kind of capability, not another memory selector: Jarvis can now run a short, fixed, two-step **workflow** — a real multi-step job, not just a single reply — through a new Sequential Workflow Engine, with every step still individually classified and gated by the same Security Manager and Tool Executor as always. Two exact commands exist today: `remember this and show it back: <text>` (save, then immediately read back what was saved) and `remember this and forget it: <text>` (save, then forget — which asks for approval first, exactly like `forget memory <id>` already does). Nothing about this is AI-planned, general-purpose, or user-definable — see the Phase 15 section below for exactly what it is and is not.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. AI reasoning is off by default and, when off, Jarvis behaves exactly as it did in Phase 3. Every test uses a fake provider, so no live Claude call is ever required to run or test Jarvis.

> **Verified:** `poetry run pytest -v` — **1815 passed, 0 failed** (Python 3.14.6, pytest 9.1.1). This covers every Phase 1–15 test.

---

## Core Design Principle

**Reduce Nathan's workload while keeping Nathan in control.**

Automation should always enhance control, never replace it. Jarvis does the repetitive work, but a human stays in charge of every consequential choice — and the AI advises, it never decides.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at a single gate — the **Tool Executor** — that the rest of the system cannot bypass. Every action is classified into one of three tiers:

- **GREEN — safe.** Read-only actions (searching memories, listing a folder, reading a file) run automatically.
- **YELLOW — sensitive.** Actions that change something — including all write actions and all memory changes — are held and require explicit approval before they run.
- **RED — dangerous.** Actions such as formatting a drive, disabling antivirus, or forgetting all memories are blocked and never run.

Rules that never change:

- **Approval never overrides RED.** An approval can only permit a YELLOW action; it can never unlock a RED one.
- **The AI never executes anything.** AI reasoning may suggest and summarise, but every real action still passes through the Security Manager, Tool Executor, and Approval Manager. The AI never stores, changes, or forgets a memory on its own.
- **Every action is logged**, including every approval decision, in the append-only audit log.

The core promise: **automation never comes at the cost of user control.**

---

## Phases 1–4 (complete)

- **Phase 1 — Foundation** (`phase-1-foundation`): configuration, SQLite storage, audit logging, memory, the Security Manager, the Planner, the Tool Registry and Executor, and a CLI.
- **Phase 2 — Controlled Intelligence & Approval Flow** (`phase-2-approval-flow`): approval models, the Approval Manager, the CLI approval prompt, approval audit logging, and the read-only `file_list` and `file_read` tools.
- **Phase 3 — Live CLI Approval Execution** (`phase-3-live-cli`): the approval flow made usable in the live CLI, approved actions executing, clear output labels, and read-only workflow commands.
- **Phase 4 — Live AI Reasoning & Guarded Write Actions** (`phase-4-ai-reasoning-and-write-actions`): advisory AI reasoning behind a configuration flag (off by default, never able to execute), and the first guarded write tools — `file_create` and `file_append` — both YELLOW and approval-gated.

---

## Phase 5 — Better Memory and Personal Knowledge System

Phase 5 turns Jarvis's basic memory into an organised, searchable, correctable personal knowledge store, delivered in four controlled batches:

- **Batch 1 — Memory categories.** Every memory can carry a category (for example `general`, `personal`, `project`, `preference`, `note`), with a safe default of `general`. Existing databases are upgraded automatically, and old memories keep working, filed as `general`.
- **Batch 2 — Memory commands.** Friendly commands to save, list, and search categorised memories from the live CLI — all read-only or explicit-save, and all GREEN.
- **Batch 3 — Review, update, and forgetting.** Reviewing a single memory (GREEN), and approval-gated ways to update, re-file, or forget one specific memory (YELLOW). Bulk forgetting is blocked (RED).
- **Batch 4 — Documentation, tests, and checkpoint.** This README, the completion report, and the phase tag.

### Memory commands

**Read and save — GREEN, run automatically:**

| Command | What it does |
|---|---|
| `remember this: <text>` | Saves a memory under the default category, `general`. |
| `remember this as <category>: <text>` | Saves a memory under the given category. Unknown categories safely become `general`. |
| `show memories` | Lists your most recent memories. |
| `show memories in <category>` | Lists recent memories in one category. |
| `search memories for <query>` | Searches all memories by text. |
| `search memories in <category> for <query>` | Searches within one category. |
| `show memory <id>` | Shows a single memory by its id. |

**Change memory — YELLOW, require approval first:**

| Command | What it does |
|---|---|
| `update memory <id>: <new text>` | Replaces the content of one memory. **Asks for approval.** |
| `move memory <id> to <category>` | Changes one memory's category. **Asks for approval.** |
| `forget memory <id>` | Forgets (deletes) one specific memory. **Asks for approval.** |

**Blocked — RED, never runs:**

| Command | Why |
|---|---|
| `forget all memories` | Bulk forgetting is irreversible and is **blocked**. There is no bulk delete. |

A declined approval leaves memory completely unchanged; only an approved change is applied, and every change is recorded in the audit log.

The "do not remember" rule still applies to saving: if you say *do not remember* something, Jarvis will not store it, even via an explicit `remember this` command.

### What is deliberately NOT included

Jarvis still cannot, by design: delete, move, rename, or edit-in-place **files**; install software; control the computer; connect to a phone; use voice; act autonomously; **bulk-delete memories**; or let the **AI store, change, or forget memories on its own**. Each remains a candidate for a future phase, added only behind the safety model.

---

## Phase 6 — Durable Approvals and Approval-Lifecycle Timeout Enforcement (complete)

Phase 6 makes approval decisions durable: every approval request and its eventual outcome is recorded in SQLite, so the record survives a restart. This is a **read-only history**, not a queue of actions waiting to run — see the safety note below for exactly why that distinction is enforced structurally, not just by convention. Phase 6 also gives a pending approval a bounded lifecycle: it no longer waits forever for an answer.

- **Batch 1 — Durable approval history.** Every created request and every approve/decline decision is written to a new `approval_history` table. A restart no longer loses the record of what was asked and how it was decided. As part of this batch, a pre-existing gap was also closed: `main.py` now actually connects the audit logger to the Approval Manager, so approval decisions reach the audit log as they always should have.
- **Batch 2 — CLI polish and documentation.** The five read-only commands below now show every field — request id, status, action, security tier, created time, and, once decided, decided time, decided by, and decision reason — cleanly, with fields that don't apply yet (a pending request has no decision) simply omitted rather than shown blank.
- **Batch 3 — YELLOW approval-window timeout enforcement.** A pending YELLOW request that goes unanswered for a configurable window (**default 60 seconds**, `APPROVAL_TIMEOUT_SECONDS`) now **expires automatically**. An expired request becomes a distinct `EXPIRED` outcome — recorded in durable history as `expired`, never as declined — and can never afterward be approved or declined. **RED remains completely outside this lifecycle**: it can never become a pending, timeable approval in the first place, so there is nothing for a timeout to apply to.

### Durable approval history commands

**All GREEN, all read-only:**

| Command | What it does |
|---|---|
| `show approval history` | Lists the most recent approval requests, any status, newest first. |
| `show recent approvals` | Lists the last 10 requests, any status. |
| `show approved actions` | Lists only requests that were approved. |
| `show declined actions` | Lists only requests that were declined. |
| `show approval <id>` | Shows full detail for one specific request by its id. |

Example output for `show approval history`:

```
jarvis> [OK] Approval history:
        [a1b2c3d4-...] APPROVED - update memory 3: corrected address
            tier: yellow | created: 2026-07-04T10:22:00 | decided: 2026-07-04T10:23:05 by user | reason: looks right
        [e5f6g7h8-...] PENDING - forget memory 9
            tier: yellow | created: 2026-07-04T10:25:11
```

### Safety note: read-only, and it stays that way

The `approval_history` table has **no `tool_name` column and no `tool_input` column** — not a rule that could be forgotten, a structural fact about the schema. A history entry can tell you *what* was asked and *how* it was decided; it can never be used to *re-run* the original action, because the data needed to run anything was never written there in the first place.

Concretely, in this phase:

- There is **no `approve <id>` for an old request.** A restart clears in-memory pending state exactly as it always did — the Approval Manager never reads history back into memory to repopulate it.
- **No automatic execution from history**, ever.
- **No resumable approvals.** Making a past pending request resumable is an explicit, separate decision, deliberately deferred with its own safety review, its own reclassification analysis, and its own expiry-interaction rules — not something this phase enables by accident. An **expired** approval is no exception: it produces a terminal `EXPIRED` outcome, not a reactivatable one.

### Approval timeouts (Batch 3)

A pending YELLOW request that nobody answers within `APPROVAL_TIMEOUT_SECONDS` (default **60 seconds**) expires automatically:

- The boundary is exact: a request **59.999 seconds old is still pending**; a request **exactly 60.000 seconds old has expired**.
- Expiry is checked lazily, only when the approval system is next asked about pending requests — there is no background timer or polling loop.
- An expired request is recorded in durable history as `expired`, decided by `"timeout"` — never as `declined`, and never as a result anyone actually decided.
- **RED never enters this lifecycle.** It is rejected before it can ever become a pending approval, so there is nothing for a timeout to reach.

### What is deliberately NOT included in Phase 6

Resumable approvals, an `approve <id>` command for anything not currently pending in memory, automatic execution of any kind, and any change to what gets classified GREEN/YELLOW/RED. Resumable approvals in particular remain a deliberately separate future decision, requiring its own safety review and architecture decision before it can even be scoped.

---

## Phase 7 — Core Simplification and AI Safety Hardening (complete)

Phase 7 is a **safety and structure phase, not a capability phase**: it removes the one identified piece of Core architectural debt, and completes the Master Specification's prompt-injection defence, delivered in six controlled batches. See `docs/phase_7_completion_report.md` for the full write-up, including the history of a verification finding and its closure.

- **Batch 1 — Command routing extraction.** The Core's request-text-to-tool matching logic moved out of `JarvisOrchestrator` into its own `CommandRouter`, with zero behaviour change.
- **Batch 2 — Trusted vs untrusted AI context, and one AI request path.** A typed `AIContextBlock` (`JARVIS_TRUSTED` or `UNTRUSTED`) replaces bare strings in every AI prompt; `JARVIS_TRUSTED` can only be produced by two guarded factory methods, never by an arbitrary caller. Every AI call — including the advisory reasoning engine's — now travels through exactly one construction path. A real gap was also fixed: AI reasoning had never actually been wired into the running application before this batch, regardless of the `AI_REASONING_ENABLED` setting.
- **Batch 3 — Prompt-injection pattern detection.** Untrusted AI context is automatically scanned for instruction-like patterns (imperatives directed at an AI, role/system-override phrasing, tool-call-like syntax, jailbreak phrasing) before it reaches a provider. Detection never blocks or rewrites anything by itself.
- **Batch 4 — Unexpected AI action escalation.** An AI-suggested action outside the current request's own plan is evaluated against the existing GREEN/YELLOW/RED classification and audited: GREEN is flagged, YELLOW is escalated, RED is blocked — as a policy verdict and an audit event only. See the safety note below for exactly what this does and does not protect today.
- **Batch 5 — End-to-end verification and documentation.** One consolidated integration test exercising the real stack together, this README section, and `docs/phase_7_completion_report.md`. This batch's own verification found that a detected injection pattern was never audited anywhere — reported rather than silently patched, since Batch 5 itself added no production code.
- **Batch 5A — Injection detection audit closure.** The gap Batch 5 found is closed: a suspicious injection detection is now audited through the existing observability system, the same way the Batch 4 escalation verdict already was — using the existing audit vocabulary, with a failure-resilient reporter, and no change to detection remaining detection-only.

### Safety note: AI suggestions remain advisory only

Nothing in Phase 7 gives the AI any new authority. An AI-suggested action can never become a tool call, can never grant itself approval, can never change a security tier, and can never modify a plan — this is proven directly by tests, not just asserted. **The Batch 4 escalation policy is armed but currently unreachable**: no code path anywhere in this codebase lets an AI suggestion execute in the first place, so the YELLOW/RED verdicts have no live action to protect yet. Phase 7 builds the gate for the day a future phase lets Jarvis read real external content (a webpage, a file) into an AI prompt; it does not open that door itself — no tool in this codebase feeds external content into an AI prompt today.

### What is deliberately NOT included in Phase 7

Any new user-facing command or tool, any new AI capability, any path that lets an AI suggestion execute, a Workflow Engine of any kind, real external-content ingestion into an AI prompt (web pages, files, or memory fed into a prompt), and any change to what gets classified GREEN/YELLOW/RED.

---

## Phase 8 — Real External-Content Ingestion (complete)

Phase 8 is the first phase in which genuine external content — a real file's contents — is intentionally read and supplied to the advisory AI, through the Phase 7 trust boundary, completely unmodified. It is deliberately narrow: one content source (local files), delivered in three controlled batches. See `docs/phase_8_completion_report.md` for the full write-up.

- **Batch 1 — File content ingestion foundation.** A new, narrow module reads a file through the existing, already-secured `file_read` tool and labels it as untrusted AI context, with provenance established by construction: the module is the only thing that both reads the file and writes its label, so the two can never describe different things. A design defect found along the way was fixed at its strongest boundary rather than patched: the AI reasoning engine now receives an already-typed, already-trust-tagged context object instead of a raw string it had to guess a label for.
- **Batch 2 — Command and orchestrator wiring.** An explicit `summarise file <path>` (or `summarize file <path>`) command, recognised by the Core's command router. The orchestrator coordinates the read, the AI reasoning call, and the same unexpected-action policy every other AI-advised response already uses — it never reads a file itself and never builds the AI's context directly.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against a real temporary file, including a real prompt-injection attempt, this README section, and `docs/phase_8_completion_report.md`.

### File summary command

| Command | What it does |
|---|---|
| `summarise file <path>` / `summarize file <path>` | Reads the file (GREEN, same as `read file`) and asks the advisory AI to summarise its contents. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI file summary - advisory only]`. If AI reasoning is off, or the file can't be read (missing, a directory, binary, or otherwise unreadable), Jarvis says so plainly — it never presents a failure as if it were a real summary.

### Safety note: file content is untrusted, scanned, and audited — nothing new is trusted

A file's contents are always typed as untrusted AI context, exactly like any other non-live, non-Jarvis-authored text: automatically scanned for instruction-like patterns before reaching the AI, with a suspicious finding audited through the same observability path Phase 7 already built. File content can never become the user's live authority, system authority, or an executable instruction, no matter what it contains. Reading a file is already safe (GREEN) and unchanged; asking advisory AI about content you already asked Jarvis to read adds no new approval requirement. As in Phase 7, any AI-suggested action arising from a file summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 8

Stored-memory ingestion, web or browser content ingestion, a generic multi-source ingestion framework, any new AI execution authority, any new approval gate for reading or summarising a file, and token-aware size limiting (file content is truncated by a simple character limit, not a model-aware token budget).

---

## Phase 9 — Stored-Memory Ingestion for Advisory AI (complete)

Phase 9 is the second content source proven through the Phase 7 trust and injection-defence pipeline: one already-stored Episodic Memory, retrieved by its explicit numeric id and supplied to the advisory AI, through the identical, completely unmodified Phase 7/8 machinery. It is deliberately narrow: one memory, by id, per request, delivered in three controlled batches. See `docs/phase_9_completion_report.md` for the full write-up.

- **Batch 1 — Stored-memory ingestion foundation.** A new, narrow module reads one memory directly through the Memory Manager and labels it as untrusted AI context, with provenance established by construction from the record actually returned, not merely the id requested. A real design mistake was caught and corrected before any code was written: the memory tool's own "get" operation returns a CLI-formatted display string, not the memory's raw content, so this module depends on the Memory Manager directly instead.
- **Batch 2 — Command and orchestrator wiring.** An explicit `summarise memory <id>` (or `summarize memory <id>`) command, recognised by the Core's command router. The orchestrator coordinates the retrieval, the AI reasoning call, its own acquisition audit event, and the same unexpected-action policy every other AI-advised response already uses — it never retrieves the memory itself and never builds the AI's context directly.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against a real, saved memory, including a real prompt-injection attempt, this README section, and `docs/phase_9_completion_report.md`.

### Memory summary command

| Command | What it does |
|---|---|
| `summarise memory <id>` / `summarize memory <id>` | Retrieves the memory by id (GREEN, same as `show memory`) and asks the advisory AI to summarise its content. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI memory summary - advisory only]`. If AI reasoning is off, the id is missing or not a number, or no memory has that id, Jarvis says so plainly — it never presents a failure as if it were a real summary. If the memory's content is longer than the character limit, only the retained portion is sent to the AI, and the response says so honestly rather than implying the whole memory was reviewed.

### Safety note: stored memory is untrusted, scanned, and audited — nothing new is trusted

A memory's content is always typed as untrusted AI context, exactly like file content: automatically scanned for instruction-like patterns before reaching the AI, with a suspicious finding audited through the same observability path Phase 7 already built. A memory being something Jarvis itself stored does not make it trusted — it was not typed live, in this turn, and could itself have been influenced by something injected earlier. Memory content can never become the user's live authority, system authority, grant approval, or an executable instruction, no matter what it contains. Reading a memory is already safe (GREEN) and unchanged; asking advisory AI about a memory you already asked Jarvis to remember adds no new approval requirement. As in Phase 7 and 8, any AI-suggested action arising from a memory summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 9

Multi-memory retrieval or selection (exactly one memory, by explicit id, per request), automatic memory selection or ranking, semantic/vector search over memories, Session/Working/Project/Semantic/Procedural/Entity Memory, the Knowledge Library, a generic multi-source ingestion framework, any new AI execution authority, any new approval gate for reading or summarising a memory, and token-aware size limiting (memory content is truncated by a simple character limit, not a model-aware token budget). Memory retrieval by id is not session-isolated — the same, already-existing characteristic of `show memory <id>` — which is not a concern in Jarvis's current single-user, local architecture, but would need review before any future multi-user or remotely-shared use.

---

## Phase 10 — Multi-Memory Retrieval and Selection for Advisory AI (complete)

Phase 10 answers the question Phase 9 deliberately left open: how more than one stored memory can be safely combined into one AI-facing context. It requires **explicit, user-named memory ids for every request** — nothing is selected automatically, and no semantic search, embeddings, vector database, recency-based selection, or AI-driven memory choice exists anywhere in this codebase. It is deliberately narrow: a small, explicit set of memories, combined and reasoned about together, delivered in three controlled batches. See `docs/phase_10_completion_report.md` for the full write-up.

- **Batch 1 — Multi-memory ingestion foundation.** A new function retrieves each requested memory by id, in the order given, and combines them into one untrusted AI context, reusing Phase 9's own per-record truncation unchanged. A single bad id never discards the rest of an otherwise-usable request.
- **Batch 2 — Command and orchestrator wiring.** An explicit `summarise memories <ids>` (or `summarize memories <ids>`) command. Duplicate ids are removed while keeping the order you typed them in, and a request naming too many ids is rejected honestly, naming the limit, rather than silently trimmed.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against real, multiple saved memories, including a genuine multi-record prompt-injection attempt, this README section, and `docs/phase_10_completion_report.md`.

### Multi-memory summary command

| Command | What it does |
|---|---|
| `summarise memories <id>, <id>, ...` / `summarize memories <id>, <id>, ...` | Retrieves each named memory by id (GREEN, same as `show memory`) and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI multi-memory summary - advisory only]`. Ids may be separated by commas, spaces, or both. Up to 10 distinct ids are accepted per request; naming more is rejected honestly, telling you the limit. If some ids are missing, unreadable, or too large to fit alongside the others, Jarvis says so plainly in the response — it never claims to have summarised memories it could not actually include.

### Safety note: combining memories never upgrades trust

Every memory in the set remains untrusted, exactly as a single memory already is — combining several untrusted memories together never makes them trusted, and nothing about how they are combined can change what Jarvis is allowed to do. The combined content is scanned for instruction-like patterns exactly as single-memory or file content already is, with a suspicious finding audited the same way. As in Phase 7, 8, and 9, any AI-suggested action arising from a multi-memory summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 10

Automatic memory selection of any kind (recency-based, category-based, or search-based), semantic or vector memory retrieval, AI-selected or AI-ranked memory ids, autonomous memory discovery, memory ranking by an LLM, any change to `MemoryManager`, `MemoryTool`, or `EpisodicMemoryStore`, any new AI execution authority, and any new approval gate for reading or summarising memories. Every memory in a request must still be named explicitly, by id, by you.

---

## Phase 11 — Deterministic Query-Based Memory Selection for Advisory AI (complete)

Phase 11 answers the question Phase 10 deliberately left open: how Jarvis turns an explicit user query about stored memory into a deterministic, bounded, explainable set of memory records for AI reasoning — without pretending that keyword/database search is semantic intelligence, and without giving the AI any authority to choose its own context. It requires **an explicit query for every request**; it reuses Phase 10's own combination architecture completely unchanged, delivered in three controlled batches. See `docs/phase_11_completion_report.md` for the full write-up.

- **Batch 1 — Deterministic query-based memory selection foundation.** A new, narrow module deterministically searches stored memories by content, using the repository's existing `MemoryManager.search()` exactly as it already behaves, capped at 10 matches, preserving the store's own result order exactly.
- **Batch 2 — Query command and orchestrator wiring.** An explicit `summarise memories about <query>` (or `summarize memories about <query>`) command. A concrete command-routing collision — this command's own prefix is a superset of Phase 10's explicit-id command prefix — was found during planning and fixed by checking the more specific query command first, so both commands keep working exactly as intended.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against real, multiple saved memories, including a genuine stored-content injection attempt, this README section, and `docs/phase_11_completion_report.md`.

### Query-based memory summary command

| Command | What it does |
|---|---|
| `summarise memories about <query>` / `summarize memories about <query>` | Deterministically searches stored memory content for matching memories (GREEN, same authority as `search memories for <query>`), selects up to 10 matches, and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI query-based memory summary - advisory only]`. This is a **deterministic content search** — a plain, case-insensitive content-pattern (substring) match over stored memory content, ordered newest-first — never semantic search, embeddings, vector retrieval, or any form of AI-selected memory. If no stored memory matches your query, or the search itself could not run, Jarvis says so plainly rather than presenting an empty or failed search as if it were a real summary. Up to 10 matching memories are selected; if more than 10 match, Jarvis says so honestly rather than claiming to have compared or ranked them by relevance.

### Safety note: search selects, it never trusts or executes

Searching stored memory is exactly as safe (GREEN, read-only) as searching already is via `search memories for <query>`. Every matched memory's content remains untrusted, exactly as it already is for `summarise memory <id>` and `summarise memories <ids>` — a memory being *found* by your search query does not make it trusted. The query itself is never mixed into that untrusted memory content; it is only ever used to search, and it reaches the advisory AI the same way any other typed request text already does. As in Phase 7, 8, 9, and 10, any AI-suggested action arising from a query-based summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 11

Semantic or vector memory retrieval, embeddings, similarity ranking, AI-selected or AI-ranked memory ids, autonomous memory discovery, recency-based or category-based automatic selection, query rewriting or synonym expansion, any change to `MemoryManager`, `MemoryTool`, or `EpisodicMemoryStore`, any new AI execution authority, and any new approval gate for searching or summarising memories. A query is deterministic content search only — it is never treated as an instruction, and it never changes what Jarvis is allowed to do.

---

## Phase 12 — Deterministic Category-Based Memory Selection for Advisory AI (complete)

Phase 12 answers the question Phase 11 left open: an explicit `summarise memories in <category>` command deterministically looks up already-stored memories filed under one of your known categories and combines them for the advisory AI, reusing Phase 10's own combination architecture unchanged. It requires **a known category for every request**; an unrecognised category is honestly rejected rather than silently substituted with your general-category memories. See `docs/phase_12_completion_report.md` for the full write-up.

- **Batch 1 — Deterministic category-based memory selection foundation.** A new selector deterministically looks up stored memories by category, using the repository's existing category helpers, capped at 10 matches, preserving the store's own result order exactly. Crucially, it checks whether a category is actually known *before* looking anything up, so a typo or unrecognised category can never be silently treated as a request for your general-category memories.
- **Batch 2 — Category command and orchestrator wiring.** An explicit `summarise memories in <category>` (or `summarize memories in <category>`) command. A concrete command-routing collision — this command's own prefix is a superset of Phase 10's explicit-id command prefix, the same kind of collision Phase 11 already had — was found during planning and fixed the same way, so all three commands keep working exactly as intended.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against real, multiple saved memories across every known category, including a genuine stored-content injection attempt, this README section, and `docs/phase_12_completion_report.md`.

### Category-based memory summary command

| Command | What it does |
|---|---|
| `summarise memories in <category>` / `summarize memories in <category>` | Deterministically looks up stored memories already filed under the given category (GREEN, same authority as `show memories in <category>`), selects up to 10 matches, and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI category memory summary - advisory only]`. The known categories are `general`, `personal`, `project`, `preference`, and `note` — the same categories Phase 5's `remember this as <category>: ...` command already uses. If the named category isn't one of these, Jarvis says so plainly, naming the known categories, rather than guessing or falling back to a different category. If a known category currently has no stored memories, or the lookup itself could not run, Jarvis says so plainly rather than presenting an empty or failed lookup as if it were a real summary. Up to 10 matching memories are selected; if more than 10 are in the category, Jarvis says so honestly rather than claiming to have compared or ranked them.

### Safety note: category selects, it never trusts, executes, or silently substitutes

Looking up stored memory by category is exactly as safe (GREEN, read-only) as looking it up already is via `show memories in <category>`. Every matched memory's content remains untrusted, exactly as it already is for every other summary command — a memory being *filed under* a category does not make it trusted. The category name itself is never mixed into that untrusted memory content; it is only ever used to select, and it reaches the advisory AI the same way any other typed request text already does. An unrecognised category is never silently treated as "general" — this is checked before any memories are looked up at all. As in Phase 7 through 11, any AI-suggested action arising from a category summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 12

Semantic or vector memory retrieval, embeddings, similarity ranking, AI-selected or AI-classified categories, fuzzy or approximate category matching, multi-category or combined query-and-category selection, autonomous memory discovery, recency-based automatic selection, any change to `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, or the category helper functions, any new AI execution authority, and any new approval gate for looking up or summarising memories by category. A category is deterministic, known-vocabulary selection only — it is never treated as an instruction, and it never changes what Jarvis is allowed to do.

---

## Phase 13 — Deterministic Recency-Based Automatic Memory Selection for Advisory AI (complete)

Phase 13 answers the question left open at the close of Phase 12: an explicit `summarise recent memories` command deterministically selects the **newest** up to 10 stored memory records, across every category, and combines them for the advisory AI, reusing Phase 10's own combination architecture unchanged. Unlike the query- and category-based commands, this one takes **no argument at all** — "recent" is defined honestly as the newest stored records under the repository's own deterministic ordering, never a calendar or time-window meaning. See `docs/phase_13_completion_report.md` for the full write-up.

- **Batch 1 — Deterministic recent-memory selection foundation.** A new selector deterministically retrieves the newest up to 10 stored memory records across all categories, using the repository's existing `list_recent()` ordering, and preserves that newest-first order exactly — no ranking, no re-sorting, no reversal.
- **Batch 2 — Recent-memory command and orchestrator wiring.** An explicit, **exact-match** `summarise recent memories` (or `summarize recent memories`) command — the first summary command with no trailing text to interpret at all, so extra words after it (for example "... about security") are never silently accepted as this command.
- **Batch 3 — End-to-end verification and documentation.** A consolidated integration test proving the complete path against real, multiple saved memories across every known category, including a real budget-pressure case showing why newest-first order matters, a genuine stored-content injection attempt, this README section, and `docs/phase_13_completion_report.md`.

### Recent-memory summary command

| Command | What it does |
|---|---|
| `summarise recent memories` / `summarize recent memories` | Deterministically selects the newest stored memories across all categories (GREEN, the same authority as other read-only memory commands), up to 10 records, and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI recent memory summary - advisory only]`. **"Recent" means newest stored memories, deterministic newest-first selection — not a time window.** Jarvis does not interpret this as "last 24 hours," "today," "this week," or any other calendar meaning; it selects exactly the newest up to 10 records currently in storage, in the same deterministic order the store already uses (newest first, with ties broken deterministically). If nothing is stored yet, or the lookup itself could not run, Jarvis says so plainly rather than presenting an empty or failed lookup as if it were a real summary.

### Safety note: recency selects, it never trusts, executes, or claims a time window

Selecting the newest stored memories is exactly as safe (GREEN, read-only) as every other read-only memory command already is. Every selected memory's content remains untrusted, exactly as it already is for every other summary command — a memory being *recent* does not make it trusted. As in Phase 7 through 12, any AI-suggested action arising from a recent-memory summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 13

Time-window retrieval ("last 24 hours," "today," "this week"), calendar or relative-date interpretation, timezone-aware filtering, user-controlled recency counts, semantic or vector memory retrieval, embeddings, similarity ranking, AI-selected or AI-ranked memory ids, autonomous memory discovery, recently-accessed or recently-modified semantics, any change to `MemoryManager`, `MemoryTool`, or `EpisodicMemoryStore`, any new AI execution authority, and any new approval gate for looking up or summarising recent memories. Recency here is deterministic newest-N selection only — it is never treated as an instruction, and it never changes what Jarvis is allowed to do.

---

## Phase 14 — User-Controlled Bounded Recent-Memory Count for Advisory AI (complete)

Phase 14 answers the question left open at the close of Phase 13: an explicit `summarise latest <count> memories` command deterministically selects the newest **N** stored memories, where N is a whole number you supply, reusing Phase 10's own combination architecture unchanged. It is a sibling to the fixed `summarise recent memories` command, not a replacement — that command's newest-10 semantics are completely unchanged. See `docs/phase_14_completion_report.md` for the full write-up.

- **Batch 1 — Count-based recent selection foundation.** A new selector strictly validates a supplied count and, for a valid one, delegates unchanged to Phase 13's own recency selector at that count.
- **Batch 2 — Count-based command and orchestrator wiring.** An explicit `summarise latest <count> memories` (or `summarize latest <count> memories`) command — the first summary command whose grammar requires both a fixed prefix and a fixed, mandatory suffix, since a count naturally sits before the word "memories," not at the end of the sentence.
- **Batch 3 — End-to-end verification, security-invariant closure, and documentation.** A consolidated integration test proving the complete path against real, multiple saved memories, a new architectural test proving Jarvis's AI-facing memory code only ever calls known read-only methods, matching regression proofs added to the Phase 11 and Phase 12 test suites, this README section, and `docs/phase_14_completion_report.md`.

### Count-based recent-memory summary command

| Command | What it does |
|---|---|
| `summarise latest <count> memories` / `summarize latest <count> memories` | Deterministically selects the newest `<count>` stored memories across all categories (GREEN, the same authority as other read-only memory commands) and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI recent-count memory summary - advisory only]`. **The accepted count is a whole number from 1 to 10.** An invalid count — zero, above 10, a word, a decimal, or a signed number — is honestly rejected before anything is looked up, naming the valid range, rather than silently rounded, clamped, or ignored. If fewer memories are actually stored than requested, Jarvis reports the real number it found rather than pretending it found the number you asked for — asking for the latest 10 when only 6 exist is honestly reported as 6.

### Safety note: a count changes how many, never who decides

Selecting a user-chosen number of the newest stored memories is exactly as safe (GREEN, read-only) as every other read-only memory command already is. Every selected memory's content remains untrusted, exactly as it already is for every other summary command. The count itself never becomes part of that untrusted memory content — it only ever reaches the advisory AI as ordinary, live request text, the same way every other summary command's own wording already does. The AI never chooses, expands, or reorders which memories were selected; it only reasons about the set Jarvis already decided on before consulting it. As in Phase 7 through 13, any AI-suggested action arising from a count-based summary is only ever a policy/audit observation — it can never execute, approve itself, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 14

Time-window retrieval, calendar or relative-date interpretation, counts above 10 or silently clamped counts, semantic or vector memory retrieval, embeddings, similarity ranking, AI-selected or AI-chosen counts, category-plus-recency or oldest-memory selection, source filtering, any change to `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, or the fixed `summarise recent memories` command's own behaviour, any new AI execution authority, and any new approval gate. A count changes how many of the newest memories are selected — it is never treated as an instruction, and it never changes what Jarvis is allowed to do.

---

## Phase 15 — Sequential Workflow Execution — Minimal Multi-Step Planner and Workflow Engine (complete)

Every request before Phase 15 was a single, immediate step: the Planner produced exactly one `PlanStep`, and Jarvis ran at most one tool call (or one AI-advisory reply) per request. Phase 15 adds a real, narrow **Sequential Workflow Engine**: a small, fixed set of already-existing actions can now run one after another, in order, as one job — with every single step still individually classified by the Security Manager and gated by the Tool Executor, exactly as before. This is the first time Jarvis's `workflow/` package (empty since Phase 1) holds real code. See `docs/phase_15_completion_report.md` for the full write-up.

- **Batch 1 — Minimal multi-step plan and workflow models.** `PlanStep` gains three optional fields (`tool_name`, `tool_input`, `input_from_previous_step`) that default safely for every existing single-step command; two new runtime models (`WorkflowStepOutcome`, `WorkflowResult`) describe a workflow's outcome using only the existing `StepStatus` vocabulary.
- **Batch 2 — Headless Sequential Workflow Engine.** `WorkflowEngine` executes a plan's steps strictly in order, delegating every single one to the existing, unmodified Tool Executor — it never classifies an action itself, never calls a tool directly, and never trusts a step's own display tier.
- **Batch 3 — Deterministic workflow commands and Orchestrator wiring.** The two exact commands below, each built from a small, fixed, deterministic plan factory — never natural-language planning, never AI-authored.
- **Batch 4 — CLI workflow trace and end-to-end proof.** An honest, after-the-fact execution trace (not live progress) shown alongside the existing plan display, plus full end-to-end proof through the real approval flow.
- **Batch 4A/4B — Observability closure.** Two narrow, pre-existing gaps (not new to Phase 15, but exposed by its extra step-level activity) were found and fixed: a failing audit logger could previously escape the Tool Executor or the Approval Manager and disrupt an otherwise-valid outcome. Both are now isolated exactly like every other optional audit call in Jarvis — a lost log line is accepted; a distorted result is not.

### Workflow commands

| Command | What it does |
|---|---|
| `remember this and show it back: <text>` | Saves `<text>` as a new memory, then immediately reads that exact memory back by the id it was just given. Both steps are GREEN. |
| `remember this and forget it: <text>` | Saves `<text>` as a new memory, then forgets that exact memory. The forget step is YELLOW and **asks for approval** first, exactly like `forget memory <id>` already does — approve to forget it, decline to keep it. |

Both commands require the mandatory colon shown above and are matched case-insensitively; no other phrasing (missing colon, "and then", semicolons, or any other connector) is recognised as a workflow — it falls through to ordinary command handling instead, exactly as before Phase 15.

### Safety note: every step is still classified on its own, live, every time

A workflow is not classified once as a whole. Each step, when it actually runs, is independently classified by the same Security Manager rule table every other Jarvis action already goes through — a step's own display tier in the plan is shown for transparency only and is never trusted for the real decision. If a step is GREEN, it runs automatically; if a step is YELLOW, the workflow pauses and asks for your approval through the exact same approval flow every other sensitive action already uses, before continuing; a step that would be blocked (RED) stops the workflow immediately and no later step ever runs. Declining an approval, a failed step, or a blocked step all stop the workflow the same way — nothing is retried, and nothing already done is undone.

### What is deliberately NOT included in Phase 15

General-purpose or natural-language workflow creation, AI-authored or AI-selected workflows, user-defined command sequences, arbitrary tool chaining, dependency graphs, branching, retries, parallel steps, more than one active workflow at a time, durable or crash-recoverable workflow state (a paused workflow is forgotten if Jarvis restarts before you answer), scheduled or background workflows, and live/streaming progress display (the workflow trace is shown after each step or the whole job finishes, not while it runs). A workflow step can only ever hand its own stored-memory id forward to the very next step — never any other data, and never to any step further ahead. Any new AI execution authority, and any new approval gate beyond the existing one, are equally out of scope.

---

## Example Session

```
remember this: buy milk on Friday
remember this as project: the API deadline is next Tuesday
show memories
show memories in project
search memories for milk
show memory 2
update memory 2: the API deadline is now Wednesday      (asks for approval)
move memory 1 to personal                                (asks for approval)
forget memory 1                                          (asks for approval)
forget all memories                                      (blocked)
```

When AI reasoning is enabled, responses may also show an advisory line, clearly labelled, that never changes what runs:

```
jarvis> [OK] Recent memories:
          [2] (project) the API deadline is next Tuesday
          [1] (general) buy milk on Friday
        [AI suggestion - advisory only] You are reviewing your saved notes.
```

---

## How to Run

```powershell
poetry install
poetry run python main.py
```

On startup Jarvis prints `Jarvis Online.` Type your request, or `exit`, `quit`, or `bye` to leave.

To enable AI reasoning (optional, needs an API key and credits), set in your `.env`:

```
AI_REASONING_ENABLED=true
```

Leave it unset or `false` to run entirely rule-based, with no API calls.

---

## How to Test

```powershell
# The full test suite
poetry run pytest -v

# The Phase 5 memory tests
poetry run pytest tests/unit/test_memory.py tests/unit/test_memory_categories.py -v
poetry run pytest tests/unit/test_memory_tool.py tests/unit/test_memory_command_routing.py -v
poetry run pytest tests/unit/test_memory_change_tools.py tests/unit/test_memory_change_routing.py -v
poetry run pytest tests/integration/test_memory_cli_end_to_end.py -v
poetry run pytest tests/integration/test_memory_change_approval_end_to_end.py -v
```

---

## Project Structure

```
jarvis/
├── config/         Configuration and shared constants (security tiers, AI flag)
├── storage/        SQLite database and ORM models (memory category column)
├── observability/  Structured event logging
├── security/       Security Manager: action classification, append-only audit
│                   log, prompt-injection pattern detection, and the
│                   unexpected-AI-action escalation policy
├── memory/         Memory Engine: save, list, search, categories, update, forget
├── ai/             Provider interface, Claude provider, advisory reasoning
│                   routed through one AIRouter/PromptBuilder path, the
│                   typed trusted/untrusted AIContextBlock model,
│                   file-content and single/multi-memory ingestion for the
│                   AI reasoning path (ai/file_ingestion.py,
│                   ai/memory_ingestion.py), and deterministic query-based,
│                   category-based, recency-based, and count-bounded
│                   recency-based memory selection (ai/memory_selection.py)
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and built-in tools
│   └── builtin/    echo, info, memory (list/search/save/get), file_list,
│                   file_read (GREEN); file_create, file_append,
│                   memory_update, memory_forget (YELLOW, approval-gated)
├── approval/       Approval models and the Approval Manager
├── workflow/       Sequential Workflow Engine and the deterministic
│                   two-step workflow plan factory
├── core/           Orchestrator that wires everything together, plus the
│                   CommandRouter that matches request text to a tool
├── ui/             Command-line interface and approval prompts
├── tests/          Unit and integration tests
├── docs/           Specifications, implementation plans, and reports
└── main.py         Entry point — starts Jarvis
```

---

## Checkpoints

- `phase-1-foundation`
- `phase-2-approval-flow`
- `phase-3-live-cli`
- `phase-4-ai-reasoning-and-write-actions`
- `phase-5-better-memory`

---

## Next Phase

**Phase 15 is complete**: Jarvis can now run a short, fixed, two-step workflow through a new headless Sequential Workflow Engine, with every step still individually classified by the Security Manager and gated by the Tool Executor exactly as before — see `docs/phase_15_completion_report.md` for the full closure write-up, including the two narrow observability-isolation defects (Tool Executor, Approval Manager) found and fixed along the way.

Phase 15 was deliberately scoped as a minimal, non-general capability — two fixed, hardcoded workflows, no AI-authored steps, no branching, no retries, no durable state. The next architectural direction has not been chosen and requires its own fresh review after this closure, in the same way every prior phase boundary has: what a general-purpose workflow syntax, AI-assisted or AI-authored planning, scheduled or background execution, or durable/crash-recoverable workflow state would each require of the Security Manager, the approval flow, and Jarvis's single-user, single-session execution model, has not yet been assessed. None of these is authorized by Phase 15 unlocking the underlying engine; each remains a separately-scoped decision.

Resumable approvals beyond a single paused workflow, and deeper but still-advisory AI assistance, remain deliberately deferred from earlier phases, each requiring its own safety review and architecture decision before it could even be scoped. Every future addition continues to go only behind the Security Manager, with the user in control.

---

*Jarvis is a personal project under active development. Phase 5 is a complete, tagged milestone; Phase 6, Phase 7, Phase 8, Phase 9, Phase 10, Phase 11, Phase 12, Phase 13, Phase 14, and Phase 15 are complete for their defined scope, not yet tagged. None is a finished product.*
