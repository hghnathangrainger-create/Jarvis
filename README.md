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
**Durable Workflow Lifecycle Foundation complete (a prerequisite turn, not a numbered phase).**
**Phase 16 complete: Web Search Tool and External Content Boundary.**
**Phase 17 complete: Broader Deterministic Workflow Commands.**
**Phase 18 complete: AI Summarization of Web Search Results.**
**Phase 19 complete: Local Read-Only Dashboard for Existing Jarvis State.**
**Phase 20 complete: Durable Jarvis Inbox with a Web-Search-Summary Producer.**

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

The **Durable Workflow Lifecycle Foundation** is a small, narrow prerequisite turn that followed Phase 15's closure — deliberately **not** a numbered phase, since it adds no new capability of its own beyond one read-only command. A workflow's lifecycle (started, each step's outcome, paused, resumed, completed, or stopped) is now durably recorded, so `show workflow history` can honestly answer "what happened to that workflow?" even after a restart — something Phase 15 alone could not do, since its paused-workflow state lived only in memory. This still does **not** make any workflow resumable, replayable, or exactly-once after a crash; see the section below for exactly what it closes and what it deliberately leaves open.

Phase 16 gives Jarvis its **first real external-network capability**: a deterministic, read-only `search the web for <query>` command that returns live search results — titles, URLs, and short snippets — directly to Nathan. There is no AI involvement of any kind: no AI-authored queries, no AI summarisation of results, no autonomous browsing, and no fetching of the pages a result links to. Every search is classified GREEN by the same Security Manager every other read-only command already goes through, and the query's own content can never influence that classification. See the Phase 16 section below for the full security and architecture treatment.

Phase 17 adds two more fixed, two-step workflow commands (`create_and_read`, `update_and_show`) on the same Sequential Workflow Engine Phase 15 already built — no engine change, no new tool, no AI involvement. See the Phase 17 section below.

Phase 18 gives Jarvis its **first AI-facing use of live web search**: an explicit `summarise web search for <query>` command performs exactly one real search, converts the returned titles/URLs/snippets into bounded, typed, untrusted AI context using the same trust boundary Phases 7–14 already established, and returns an advisory synthesis honestly labelled as based on search-result snippets — never on full webpages Jarvis never visited. No AI-authored or AI-rewritten query, no second or follow-up search, and no new execution authority of any kind. See the Phase 18 section below.

Phase 19 gives Jarvis its **first visual surface**: a separate, local, strictly read-only dashboard (`poetry run python dashboard.py`) that displays real durable state — memory, approval history, and workflow lifecycle history — without reading CLI scrollback or issuing multiple `show`/`list` commands by hand. It is a second, independent process that only ever reads the same SQLite file the CLI already writes to; it cannot execute a tool, approve or deny anything, mutate memory, or start a workflow, and its failure never affects the Jarvis CLI process. See the Phase 19 section below.

Phase 20 gives Jarvis its **first durable output**: a `summarise web search for <query>` (or `summarize ...`) command now also saves its advisory AI summary to a durable Inbox, shown in a new dashboard tab, so it survives past CLI scrollback and a restart instead of disappearing the moment the terminal session ends. Every other command is completely unaffected; the CLI's own response is byte-for-byte unchanged. See the Phase 20 section below.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. AI reasoning is off by default and, when off, Jarvis behaves exactly as it did in Phase 3. Every test uses a fake provider, so no live Claude call is ever required to run or test Jarvis, and no test makes a real web search either.

> **Verified:** `poetry run pytest -v` — **2252 passed, 0 failed** (Python 3.14.6, pytest 9.1.1). This covers every Phase 1–20 test plus the Durable Workflow Lifecycle Foundation.

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

## Durable Workflow Lifecycle Foundation (prerequisite turn, not a phase)

**This is explicitly not a phase** — it adds no scheduling, no resumable checkpoints, no workflow replay, no exactly-once execution, and no new workflow command grammar. It closes exactly one gap Phase 15's own closure review identified: a workflow's lifecycle (started, each step's outcome, paused, resumed, completed, or stopped) previously lived only in memory and in the generic, unstructured audit log. It is now also recorded durably, in a structured, `workflow_id`-queryable form, so it survives a restart. See `docs/durable_workflow_lifecycle_foundation_plan.md` and `docs/durable_workflow_lifecycle_foundation_completion_report.md` for the full write-up.

- **Batch 1 — Durable history store.** A new, append-only `workflow_history` table and `WorkflowHistoryStore`, mirroring the existing `ApprovalHistoryStore` pattern.
- **Batch 2 — WorkflowEngine integration.** `WorkflowEngine` gains one new optional collaborator, recording every one of its seven existing lifecycle transitions durably, additively, alongside (never instead of) its existing audit events — using the same narrow observability-isolation pattern already proven for a raising audit logger, so a failing history write can never alter an authoritative `WorkflowResult`.
- **Batch 3 — Read-only command.** A new `WorkflowHistoryTool` (GREEN, read-only), wired through the ordinary `CommandRouter` → `ToolExecutor` path — no bypass, no special case.

### Workflow-history commands

| Command | What it does |
|---|---|
| `show workflow history` | Lists the most recent workflow lifecycle transitions, across all workflows, newest first. |
| `show recent workflows` | The last 10 transitions, across all workflows. |
| `show workflow <workflow_id>` | One workflow's full lifecycle, oldest first — the whole story of what happened to it. |

### Safety note: still exactly the same gate, nothing new granted

`show workflow history` and its siblings are ordinary GREEN tool calls, classified fresh by the same Security Manager "show" rule every other read-only command already uses — no new rule was added or needed. A durable history row never carries a `tool_input`, a resolved step input, or a serialised plan, so nothing shown by this command can ever be replayed, resumed, or re-executed — that boundary is a structural fact about the schema, not a rule that could be forgotten.

### What this closes, and what it deliberately still leaves open

**Closes:** a crashed or restarted Jarvis process can no longer make a workflow's history silently vanish — `show workflow history` (or `show workflow <id>`) now gives an honest answer even after a restart.

**Deliberately still open, unchanged from Phase 15:** a paused workflow still cannot be resumed after a restart (only its *history* survives, not its executable state); there is still no idempotency mechanism, so a step still cannot be safely replayed after an uncertain crash; there is still no scheduling, background execution, or notification of any kind; and there is still exactly one active workflow at a time. Durable, resumable checkpoints and any exactly-once execution guarantee remain explicitly out of scope for this turn, deferred to a future, separately-authorized and separately-reviewed phase.

---

## Phase 16 — Web Search Tool and External Content Boundary (complete)

Jarvis's first real external-network capability: a deterministic, read-only web search that returns live results directly to Nathan. See `docs/phase_16_completion_report.md` for the full closure write-up.

- **Batch 1 — Search provider boundary.** A new, Jarvis-owned `SearchResult` model (title, URL, snippet) and a `WebSearchProvider` abstraction, plus the concrete `DuckDuckGoSearchProvider` adapter — modelled on the existing `AIProvider`/`ClaudeProvider` boundary, deliberately scaled down to exactly one provider with no registry or multi-provider routing.
- **Batch 2 — Read-only tool and command routing.** A new `WebSearchTool` (GREEN), reachable via `search the web for <query>`, routed through the ordinary, unmodified `CommandRouter` → `ToolExecutor` path.
- **Batch 3 — End-to-end verification and closure.** Full real-stack proof (real Security Manager, real Tool Executor, real Command Router, a fake injected search provider — never a real network call in any test) that query content cannot influence security classification and that malicious-looking result content is displayed only as inert data.

### Web search command

| Command | What it does |
|---|---|
| `search the web for <query>` | Performs a live web search and returns up to 5 results — title, URL, and a short snippet each. GREEN, read-only. |

### Safety note: the query never controls classification, and results are display-only

`WebSearchTool`'s security classification is a **fixed string**, `"search the web"`, completely independent of the query's own content — a query containing words like "delete" or "execute" is classified exactly the same as any other query. Nothing a search result contains — its title, URL, or snippet — can ever become a Jarvis instruction, trigger an approval prompt, or be fetched/opened automatically: results are inert text, displayed to Nathan and nothing else. There is no AI-facing path in Phase 16 at all — no summarisation, no AI-authored queries, no AI-selected execution — so none of Phase 7's prompt-injection defences are exercised by this command, and none need to be: a human reading plain text is not an AI context window.

### What is deliberately NOT included in Phase 16

Autonomous browsing, arbitrary webpage fetching, webpage summarisation, AI summarisation of search results, AI-authored queries, AI-selected tool execution, a Research Agent, scheduling or background execution, notifications, any workflow-resumption change, a plugin architecture, and multi-provider search routing. Jarvis has not "read" a webpage in this phase — only the search provider's own title/URL/snippet metadata is ever returned, and the tool's own output says so explicitly. The installed `duckduckgo-search` package's own disclosed rename to `ddgs` is confined entirely to `tools/duckduckgo_search_provider.py` and was not acted on this phase.

---

## Phase 17 — Broader Deterministic Workflow Commands (complete)

Two more fixed, hand-authored, two-step workflow commands, reusing the exact same Sequential Workflow Engine, Security Manager, and Approval Manager every prior workflow already uses — no engine change, no new tool, no AI involvement. See `docs/phase_17_completion_report.md` for the full closure write-up.

- **Batch 1 — Workflow plan factories.** `build_create_and_read_plan()` and `build_update_and_show_plan()` added to the same factory `workflow_plan_factory.py` already holds the two Phase 15 workflows, in the identical style.
- **Batch 2 — Command routing and dispatch.** Two new exact commands, each requiring both an existing command's own prefix and one new fixed trailing suffix — routed through the same shared workflow-execution path every prior workflow command already uses.
- **Batch 3 — End-to-end verification and closure.** Full real-stack proof (real Security Manager, Tool Executor, Approval Manager, Command Router, Workflow Engine, and a real filesystem/database — no fakes at this level) of approval pause/resume, genuine re-verification of persisted state, and inert handling of adversarial content.

### New workflow commands

| Command | What it does |
|---|---|
| `create file <path> with <content> and show it` | Creates a new file with the given content, then reads that exact file back. Step 1 (create) is YELLOW and asks for approval; step 2 (read) is GREEN. |
| `update memory <id>: <content> and show it back` | Updates an existing memory's content, then shows the memory back. Step 1 (update) is YELLOW and asks for approval; step 2 (show) is GREEN. |

Both commands require their exact fixed trailing phrase (`and show it` / `and show it back`); the standalone `create file <path> with <content>` and `update memory <id>: <content>` commands (with no trailing phrase) are completely unaffected and continue to work exactly as before.

### Safety note: real verification, not an echo

Step 2 of both workflows independently re-reads the actual, persisted result — `file_read` reads the real file from disk, and `memory` (`get`) re-fetches the real row from the database — neither ever simply repeats back what step 1 was given. `update_and_show`'s step 2 relies entirely on the exact same `memory_id` propagation mechanism the two Phase 15 workflows already use; `create_and_read` needs no propagation at all, since Nathan's own path is already known before either step runs. Every step is still classified fresh, live, by the Security Manager, exactly as before — a workflow command never grants, caches, or bypasses an approval.

### Disclosed limitation: the trigger phrase is a suffix, not a prefix

Unlike Phase 15's two commands (where the trigger phrase comes first, so anything after it can never be mistaken for the trigger), both of this phase's commands recognise their trigger phrase at the **end** of the command. This means if the content or replacement text you actually want to store legitimately ends in the exact words "and show it" or "and show it back", Jarvis cannot tell the difference — it will always treat it as the workflow trigger and strip those words from what is stored. This is a known, accepted limitation, not a bug: fixing it would require a quoting or escaping convention this codebase does not otherwise have, and inventing one — or guessing intent, or asking AI to disambiguate — was explicitly out of scope for this phase.

### What is deliberately NOT included in Phase 17

`move_and_show`, `create_and_append`, any list-then-act or search-then-act workflow, any history-chaining workflow, any workflow using web search, any change to the Workflow Engine's single `memory_id` propagation mechanism (no path propagation, no arbitrary output-field mapping, no multiple-output propagation, no template or expression language, no branching, retries, rollback, or compensation), any new tool, and any AI involvement of any kind. `WorkflowEngine` still propagates exactly one field, `metadata["memory_id"]` — a known, disclosed limitation for any future workflow that would need to propagate something else, not fixed here.

---

## Phase 18 — AI Summarization of Web Search Results (complete)

Jarvis's first AI-facing use of live web search: an explicit `summarise web search for <query>` command performs exactly one real search and asks the advisory AI to synthesise the returned snippets — reusing the exact same `AIReasoningEngine`/`AIRouter`/`PromptBuilder` pipeline, `ContentTrust` rules, and injection scanning every prior AI-summary command (Phases 8–14) already goes through, unchanged. See `docs/phase_18_completion_report.md` for the full closure write-up.

- **Batch 1 — Narrow ingestion module.** A new `ai/web_search_ingestion.py` calls `WebSearchProvider.search()` directly — the same direct-acquisition pattern `ai/memory_ingestion.py` already established, never through `WebSearchTool`/`ToolExecutor` — exactly once per request, and combines up to 5 results into one bounded, typed `UNTRUSTED` context block (per-result and total character budgets, whole-result omission when a budget is exceeded, never partial re-inclusion).
- **Batch 2 — Command routing and orchestrator wiring.** A new `summarise web search for <query>` (or `summarize web search for <query>`) command, recognised by the Core's command router and dispatched to a new terminal handler that acquires results, builds the AI request, and applies the same unexpected-action audit policy every other AI-advised response already uses.
- **Batch 3 — End-to-end verification and closure.** Full real-stack proof (real Security Manager, Tool Executor, Command Router, `AIRouter`, `PromptBuilder`, and injection scanner; only the search provider and the AI provider are faked — never a real network or Claude call) that adversarial title/URL/snippet content, including fake system/developer/Nathan-impersonating instructions, remains inert `UNTRUSTED` data that can never trigger a second search, a tool call, an approval, or a workflow.

### Web search summary command

| Command | What it does |
|---|---|
| `summarise web search for <query>` / `summarize web search for <query>` | Performs exactly one live web search for `<query>` (GREEN, same authority as `search the web for <query>`) and asks the advisory AI to synthesise the returned titles, URLs, and snippets. Requires AI reasoning to be enabled. |

The response is clearly labelled `[AI web search summary - based on search-result snippets, not full webpages]`. This label is fixed and code-enforced — it appears exactly as written regardless of anything the AI itself claims (for example, if the AI's own text asserts it "read the full article," the label still honestly says otherwise). If the query is empty, AI reasoning is disabled, web search is unavailable, the search itself fails, or no results are found, Jarvis says so plainly and never calls the AI at all.

### Safety note: search-result content is untrusted, scanned, and audited — nothing new is trusted, and nothing new can act

Every title, URL, and snippet returned by the search provider is combined into a single `UNTRUSTED` `AIContextBlock` via `AIContextBlock.from_untrusted()` — the same factory, the same fixed untrusted-context framing, and the same automatic injection scan every prior AI-summary command already uses. A snippet claiming to be a system message, a developer instruction, or "from Nathan" gains no trust from that claim; it is still wrapped in `PromptBuilder`'s own fixed header telling the AI to treat it strictly as information, not instructions, and a detected instruction-like pattern is audited, never blocked or acted on, exactly as Phase 7 already established. The query itself never becomes part of that untrusted content and is never rewritten by the AI — it is used to search exactly once, and the AI cannot trigger a second search, no matter what the results or its own output suggest. As in every prior AI-summary command, any AI-suggested action is only ever a policy/audit observation — it can never execute, approve itself, create a workflow, or change what Jarvis is allowed to do.

### What is deliberately NOT included in Phase 18

AI-authored, AI-expanded, or AI-rewritten search queries; a second or follow-up search of any kind; autonomous browsing, URL fetching, page crawling, or link-following; a Research Agent or any multi-turn research loop; any change to `SearchResult`, `WebSearchProvider`, `DuckDuckGoSearchProvider`, or the standalone `search the web for <query>` command's own behaviour; a multi-provider search router; migrating to the `ddgs` package; any new tool; any `WorkflowEngine` involvement; any execution authority derived from search-result content or AI output; and any new `ContentTrust` value or weakening of the existing trust factories. Jarvis has still not "read" a webpage in this phase either — only the search provider's own title/URL/snippet metadata is ever summarised, and the response says so explicitly.

---

## Phase 19 — Local Read-Only Dashboard for Existing Jarvis State (complete)

Jarvis's first visual surface: a separate, local, strictly read-only dashboard window over the same durable state the CLI already reads and writes. It is not the Master Specification's full Chapter 21 Dashboard — no chat interface, no approval interaction, no AI provider status, no Knowledge Library, no Goals, no Settings — it is a narrow viewer over exactly three existing durable domains. See `docs/phase_19_completion_report.md` for the full closure write-up.

- **Batch 1 — Read-model/query layer.** A new `dashboard/read_model.py` composes `MemoryManager`, `ApprovalHistoryStore`, and `WorkflowHistoryStore`'s own existing read methods into small, frozen view-model rows — never a write-capable method, never parsed CLI/tool output. A new `WorkflowHistoryStore.list_recent_workflow_ids()` returns distinct, most-recently-active workflows so one transition-heavy workflow can't crowd others out of the "recent workflows" view. `storage/database.py`'s existing connect-event-listener pattern gained `journal_mode=WAL` and `busy_timeout=2000ms`, empirically verified, to support a real second reader process safely.
- **Batch 2 — tkinter/ttk UI.** A four-tab window (Overview, Memories, Approval History, Workflow History) built entirely on the Python standard library's `tkinter`/`ttk` — no new dependency. A separate `dashboard.py` entry point starts it independently of `main.py`/the CLI.
- **Batch 3 — End-to-end verification and closure.** Full real-stack proof (a real temporary SQLite database, real stores, a real withdrawn Tk window) that refresh sees newly committed writes, that two independent connections against the same database file behave safely under the new WAL configuration, and — the strongest adversarial proof in this phase — that a full, real, live Jarvis execution stack (`SecurityManager`, `ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, `CommandRouter`) sharing the same process is completely unaffected by driving every interaction the dashboard offers over adversarial memory/approval/workflow content.

### Launching the dashboard

```powershell
poetry run python dashboard.py
```

This is a second, independent process — it does not require the Jarvis CLI to be running, and the CLI does not require it either. The two share only the same SQLite database file on disk; there is no IPC, no socket, and no HTTP server anywhere in this phase.

### Dashboard views

| Tab | What it shows |
|---|---|
| Overview | Total memory count, the 5 most recent approval decisions, and the 5 most recently active workflows — every number traces to a real query, nothing estimated or simulated. |
| Memories | Recent memories (optionally filtered by category), each with a 120-character preview; full content is shown only after selecting a row. |
| Approval History | Recent approval history entries — action, tier, status, timestamps. Durable history only, explicitly not a live list of approvals currently awaiting a decision. |
| Workflow History | Recently active workflows and, on selection, that workflow's full recorded transition history. Durable lifecycle history only, explicitly not resumable or executable state. |

Refresh is a fixed, honestly-labelled requery — a "Refresh now" button plus an automatic requery every 5 seconds — never described as "live" or "real-time." Timestamps are shown as `YYYY-MM-DD HH:MM:SS UTC`; the `UTC` suffix is appended literally by the dashboard's own code (every timestamp in these three tables is produced from `datetime.now(timezone.utc)` at write time, confirmed directly, though SQLite itself returns it naive on reload) — it is never derived from timezone metadata that isn't actually there.

### Safety note: read-only, local-process-only, and structurally unable to act

The dashboard cannot construct a `ToolRequest`, call `ToolExecutor` or `CommandRouter`, create or resolve an `ApprovalRequest`, start/resume/cancel a workflow, change a memory, or call any AI or web-search component — none of those objects are ever imported by `dashboard/read_model.py`, `ui/dashboard_app.py`, or `dashboard.py`, confirmed structurally. The only interactive control in the entire window is a single "Refresh now" button; there is no approve, deny, edit, delete, save, run, or open-URL control anywhere, and no row is double-click-executable. Memory content containing command-like text (for example, "forget all memories") is displayed as plain, literal text in a table cell — it is never parsed, routed, or executed. A dashboard failure (a closed database, a transient SQLite lock, a malformed row) is isolated to that one panel or, at worst, the dashboard process itself — it can never affect the Jarvis CLI process, which does not import or depend on the dashboard in any way.

### What is deliberately NOT included in Phase 19

An HTTP server, listener, or served frontend of any kind (no FastAPI, no Uvicorn, no Flask, no WebSocket, no REST API); any remote, LAN, phone, or browser reachability; authentication, sessions, or accounts; any write, execute, approve, decline, cancel, resume, or schedule action from the dashboard; any change to `SecurityManager`, `ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, `CommandRouter`, or any AI-facing module; any new tool; live web-search results or AI web-search summaries (ephemeral, not durable); AI provider status or cost tracking; system-health, plugin, or agent simulations; goals, projects, or tasks; a durable inbox, notification, or scheduled-task model (no producer exists yet — building one now would be infrastructure ahead of a second real use case); voice; and computer control. This is not the Master Specification's full Chapter 21 Dashboard, its "Web Dashboard chat interface," or the FastAPI server named in Chapter 29's startup sequence.

---

## Phase 20 — Durable Jarvis Inbox with a Web-Search-Summary Producer (complete)

Jarvis's first durable output: a saved copy of an AI-generated result that used to disappear the moment CLI scrollback was gone. `summarise web search for <query>` (or `summarize ...`) still works exactly as it did in Phase 18 — same parsing, same single search, same `WebSearchProvider`/`SearchResult` objects, same `UNTRUSTED` context handling, same `PromptBuilder`/`AIRouter`/`AIReasoningEngine` path, same fixed snippet-only disclosure label, same CLI response — but now, only after a real, validated AI summary has been produced, that exact response is also saved as a durable Inbox entry, visible in a new dashboard tab. See `docs/phase_20_completion_report.md` for the full closure write-up.

- **Batch 1 — Durable storage.** A new `inbox_entries` table and `InboxStore` (`inbox/inbox_store.py`), following the same non-`ForeignKey` `session_id` convention `ApprovalHistoryStore`/`WorkflowHistoryStore` already use. Append-only by construction: the store exposes exactly four methods (`append`, `list_recent`, `count`, `get`) and no update, delete, or read/unread-mutation method exists anywhere on it.
- **Batch 2 — Producer wiring and dashboard consumer.** One disclosed, additive line in `_handle_web_search_summary_request`: after the exact success response is built, it saves one entry via the new optional `inbox_store` collaborator — a failed save is caught and audited, never surfaced in, or allowed to delay, the CLI's own response. `dashboard/read_model.py` gained `get_recent_inbox_entries()`; `ui/dashboard_app.py` gained a fifth "Inbox" tab and a real total-count Overview line, plus a modest padding/column-width pass across all five tabs.
- **Batch 3 — End-to-end verification and closure.** Full real-stack proof (a real temporary SQLite database, a real orchestrator, a fake search provider and fake AI provider through the real `AIRouter`/`AIReasoningEngine` path, a real `InboxStore`, a real dashboard) that both command spellings each create exactly one entry, that every failure path (search failure, zero results, AI disabled/unavailable/failed, a raising `InboxStore`) creates none and never alters the CLI response, that no other AI-summary command can reach the inbox, and — the strongest adversarial proof in this phase — that a full, real, live Jarvis execution stack sharing the same process as the dashboard shows zero effect, including a direct spy proving `InboxStore.append()` is never called from the dashboard side.

### Inbox entries

| Field | What it holds |
|---|---|
| Query | The literal search query, stored verbatim — a deliberate choice, since this is a user-facing record only Nathan ever reads, not the audit log Phase 18 already keeps content-free. |
| Body | The exact final text Nathan was shown, disclosure label included, stored byte-for-byte — never reconstructed or re-derived later. |
| Result count | How many search results the summary was based on, if known. |
| Created at | When the entry was saved (UTC). |

The Inbox tab shows these newest-first, with a truncated preview and the full saved body on row selection — the same pattern the Memories tab already established.

### Safety note: a saved summary, not a new authority

An Inbox entry is a stored, user-visible **display string** — never a `ToolRequest`, never a `Plan`, never approval authority, and never fed into `CommandRouter`, `ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, or `AIReasoningEngine` by anything added in this phase. It is not executable, not trusted system context, not a notification, and not a scheduled task — it is exactly, and only, a durable copy of something already shown once. Adversarial content stored in an entry (fake commands, fake tool-call JSON, fake approval/workflow instructions, prompt-injection phrasing, malicious-looking URLs) renders as plain, literal text in the dashboard; storing it changes nothing about its (lack of) authority. Entries are append-only: there is no edit, delete, read/unread, or pin control anywhere, because the store itself has no method capable of mutating one.

### What is deliberately NOT included in Phase 20

Any scheduler, timer loop, background runner, recurring job, missed-run or duplicate-run policy, or timezone scheduling logic; any notification delivery of any kind (desktop, email, push, phone, or CLI-on-next-launch); any dashboard command box, command execution, write action, or URL-opening control; any Core service, HTTP server, IPC bridge, socket bridge, or client/server refactor; an `InboxTool`; and automatic persistence of any other AI-summary command family (file, single-memory, multi-memory, query-based, category-based, recency-based, or count-based memory summaries) — only the web-search-summary command writes to the inbox. Repeated identical queries append separate entries; nothing is deduplicated. This closes one real gap (a saved copy of one kind of AI output) — it does not, by itself, make Jarvis proactive, notify Nathan of anything, or add any new execution authority anywhere.

---

## Phase 21 — GREEN-Only Scheduled Web-Search Summaries to Inbox (complete)

Jarvis's first proactive, unattended behaviour: Nathan can now define a small number of daily, fixed-time web-search-summary schedules that run without him touching the keyboard, saving a successful result straight into the durable Inbox Phase 20 already built. Exactly one scheduled action type exists — there is no general-purpose scheduler, no arbitrary command scheduling, and no stored command string ever executed later. See `docs/phase_21_completion_report.md` for the full closure write-up.

- **Batch 1 — Schedule storage, CRUD tools, and CLI grammar.** A new `schedules` table and `ScheduleStore` (`scheduling/schedule_store.py`) — the first durable table in the project that is mutable rather than append-only, since a schedule's `enabled`/`last_run_at` fields change in place. Four ordinary tools (`schedule_create`, `schedule_list`, `schedule_enable`, `schedule_disable`) are routed through the completely unmodified `CommandRouter` → `ToolExecutor` → `SecurityManager` → `ApprovalManager` pipeline — creating, enabling, or disabling a schedule is YELLOW and requires the same explicit confirmation as any other guarded write; listing is GREEN.
- **Batch 2 — Runner, atomic claim, and trust-safe execution.** `scheduler.py`, a fourth independent composition root (mirroring `dashboard.py`), polls once a minute and, for each enabled schedule, atomically claims it via one SQL `UPDATE ... WHERE ...` statement if it is due — closing the two-runner race at the database layer itself, not in Python. A new, narrow helper (`scheduling/scheduled_summary_runner.py`) performs the search and AI summary; the interactive `summarise web search for <query>` command (`core/orchestrator.py`) and `ai/web_search_ingestion.py` are both completely unmodified.
- **Batch 3 — Dashboard Schedules tab, end-to-end verification, adversarial proof, and closure.** A sixth, read-only dashboard tab; a real-SQLite, real-CLI-approval, real-runner end-to-end proof that a schedule created through the approved command path is later claimed and run exactly once per due day; and — the strongest adversarial proof in this phase — a full, real, live Jarvis execution stack sharing the same process as the dashboard and the runner, seeded with prompt-injection-style scheduled queries, showing zero effect anywhere.

### Schedule commands

```
schedule web search summary for jarvis ai news at 08:00
list schedules
enable schedule 1
disable schedule 1
```

`schedule web search summary for <query> at <HH:MM>` requires approval, exactly like `create file` or `append to file` — Nathan is asked to confirm before Jarvis commits to running something unattended in the future. `time_of_day` is a strict 24-hour `HH:MM`; there is no natural-language time parser and no cron-expression syntax. There is no `update`/`edit`/`reschedule` command — `disable` is the only way to stop a schedule from running, and there is no `delete`.

### The scheduler runner

```powershell
poetry run python scheduler.py
```

A third independent process, alongside `main.py`/the CLI and `dashboard.py` — it does not require either to be running, and shares only the same SQLite database file on disk. It polls every 60 seconds; for each enabled schedule whose `time_of_day` has been reached in host local time and that has not already run today, it atomically claims it, runs the one hard-coded search-and-summarise action, and — only on genuine, validated success — saves one entry to the Inbox with `source_type="scheduled_web_search_summary"` (a distinct value from the interactive command's `"web_search_summary"`, so an overnight result is always honestly distinguishable from one Nathan asked for directly). A schedule "missed" because the runner wasn't running catches up the same day it's next checked, but never backfills more than once, no matter how many days were missed. A claim that is followed by a search failure, an unavailable/failed/invalid AI response, or a failed Inbox write creates no entry and does not retry until the next calendar day — `last_run_at` is set at claim time, before the run's own outcome is known. If AI reasoning is not configured at all, nothing is claimed, so every due schedule remains eligible to catch up later the same day once it becomes available.

**A stored scheduled query is never treated as live input.** The interactive command's `user_message` prompt slot exists specifically because a live human is typing it that moment, and is therefore the one part of a prompt never scanned for injection. A scheduled run has no live human present, so the runner never reuses that path: it passes a fixed, Jarvis-authored instruction as `user_input`, and the stored query only ever appears inside the same scanned, labelled `UNTRUSTED` context block every other piece of external content already receives — a stricter posture than the interactive path, deliberately, because nothing here is confirmed by a human each time it fires.

### Dashboard Schedules tab

| Column | What it shows |
|---|---|
| ID, Name, Query, Time Of Day, Enabled, Last Run At, Created At | Every configured schedule, in the same stable, oldest-first order `ScheduleStore` itself uses. |

Read-only, like every other tab: there is no create, edit, delete, enable, disable, or run-now control anywhere on it, and no "next due" countdown is computed or shown — only `scheduler.py`'s own poll cycle decides whether a schedule is currently due.

### Safety note: one hard-coded action, gated the same way every write already is

There is no `action_type` column and no dispatch table — every claimed schedule runs the exact same, single, hard-coded search-and-summarise call; a second schedule action type, if ever proposed, would be its own separately-reviewed decision, not something this phase's schema quietly already supports. `scheduler.py` never imports `CommandRouter`, `ToolExecutor`, `ApprovalManager`, or `WorkflowEngine` — there is no live command to route and no approval to gate at run time, because the schedule was already approved when it was created. Audit events for the runner (`schedule_claimed`, `scheduled_summary_succeeded`, `scheduled_summary_failed`) are metadata-only, exactly like every other audit event in this project — never the query, never the summary text.

### What is deliberately NOT included in Phase 21

Any general-purpose scheduler, task queue, or background-agent framework (no `Celery`, `Redis`, `APScheduler`); any workflow-triggering, YELLOW, or RED scheduled *action* (only the schedule's own creation/enable/disable is YELLOW — what it runs is always the one GREEN action); approval scheduling; any notification delivery of any kind (desktop, email, push, phone, or CLI-on-next-launch — see Phase 22 for the first, deliberately minimal step in this direction); any dashboard write action, including schedule creation, editing, enabling, disabling, or run-now; any Core service, HTTP server, IPC bridge, socket bridge, or client/server refactor; a natural-language schedule parser or cron-expression system; and full webpage fetching (scheduled summaries use the same search-result snippets/metadata Phase 18 already used — never a full page read). This closes one narrow gap (Jarvis can now do one useful thing without being asked in the moment) — it does not, by itself, make Jarvis a general automation platform, notify Nathan through any channel other than the Inbox he already has to open, or add any new execution authority anywhere.

---

## Phase 22 — Minimal Honest Notice of New Scheduled Inbox Activity (complete)

The one concrete gap Phase 21 created: a scheduled result can now appear in the Inbox without Nathan doing anything, and until this phase, nothing told him it had happened. Phase 22 closes that gap with the smallest possible mechanism — a single durable marker and one honest line printed at CLI startup — not a notification system. See `docs/phase_22_completion_report.md` for the full closure write-up.

- **Batch 1 — Marker, query, notice builder, CLI wiring.** A new, single-row `ScheduledInboxNoticeState` table and `ScheduledInboxNoticeStore` (`notice/scheduled_inbox_notice_store.py`) track only the highest Inbox entry id already reported — never a timestamp, since `InboxEntry.id` is monotonic and immune to clock changes. `InboxStore` gained one read-only method, `count_since(source_type, after_id)`. A small, pure function (`notice/scheduled_inbox_notice.py::build_scheduled_inbox_notice()`) reads the marker, counts new `scheduled_web_search_summary` entries, and builds one content-free notice line, or decides there is nothing to report. `JarvisCLI` gained one optional `startup_notice` parameter, printed once after the banner.
- **Batch 2 — End-to-end verification, adversarial proof, optional dashboard line, closure.** Real-scheduler-to-real-notice proof using the actual `scheduler.py`/`scheduling/scheduled_summary_runner.py` pipeline; an adversarial sweep proving prompt-injection-shaped, URL-shaped, and control-character query/body content never reaches the printed notice; failure verification proving a broken marker, a broken Inbox read, or a broken second database connection never blocks CLI startup; and one new, optional, real-data-only Overview line on the dashboard.

### The CLI startup notice

```
Jarvis notice: 3 scheduled inbox entries were added since your last check. Latest: 2026-07-11 08:00. Open the dashboard Inbox to review them.
```

Printed once, immediately after the startup banner, only when at least one new `scheduled_web_search_summary` Inbox entry exists since the marker's last value. It never says "unread" (no read/unread state exists anywhere), never implies push or real-time delivery (this is a plain check performed once at startup), and never repeats the entry's own query, summary body, URLs, or search snippets — only a count and the latest entry's timestamp, both drawn from `InboxStore.count_since()`'s own narrow return shape, which excludes body/query content entirely. Interactive `web_search_summary` entries (the ones Nathan is already looking at the screen for) are never counted or reported.

**First run is silent.** The very first time this check ever runs, it initializes the marker without printing anything — so upgrading to this phase never dumps a large historical backlog into a noisy first notice; only entries created from that point forward are ever reported. The marker itself is based on `InboxEntry.id`, not a timestamp, specifically to stay correct across clock changes and to make "entries newer than the marker" an exact, unambiguous comparison.

**Failure is always silent and never blocking.** A broken marker read/write, a broken Inbox read, or a failure while opening the small, independent second database connection this check uses (mirroring `dashboard.py`/`scheduler.py`'s own "separate engine over the same SQLite file" pattern) all result in no notice being shown that run — never a crash, never a delay to Jarvis actually starting, and never any content printed that shouldn't be.

### Dashboard Overview addition

The Overview tab gained one new, real-data-only line:

```
Scheduled inbox entries: 3 (most recent: 2026-07-11 08:00 UTC)
```

This is a plain total (via the same `InboxStore.count_since()` method, with no marker), deliberately **not** framed as "since you last checked" — the dashboard never reads or writes the CLI's own marker at all, so there is no ambiguity about whose "last check" is meant. No unread badge, no dismiss control, and no mark-seen action exists anywhere on the dashboard.

### Safety note: a notice, not a notification system

There is no desktop, email, or phone notification, no OS dependency, and no new third-party library anywhere in this phase — `pyproject.toml` is unchanged. There is no read/unread state, no per-entry notification record, and no dismiss/acknowledge control anywhere; the entire durable footprint of this phase is one integer in one row. `scheduler.py` is completely untouched and has no awareness this phase exists. The notice text is plain terminal output — nothing reads it back as input, and it is never passed to `CommandRouter`, `ToolExecutor`, or any AI-facing component.

### What is deliberately NOT included in Phase 22

Desktop/OS toast notifications, a system tray icon, email notifications, phone/push notifications, any notification SDK or new runtime dependency; a notification table with per-entry read/unread/dismiss records; any Inbox read/unread mutation or dismiss button anywhere; any dashboard write action or notification control; any Core service, HTTP server, or IPC bridge; any change to `scheduler.py` or to scheduled-execution behaviour itself; any new schedule action type or arbitrary command scheduling; webpage fetching; and Research Agent or voice/phone work. This closes one narrow gap (Nathan now learns about unattended results without having to remember to check) — it is not a notification center, not a push/delivery framework, and not a step toward a Core service.

---

## Phase 23 — Jarvis Operating Guide (complete)

A documentation-only phase, added retroactively to this section (Phase 30): a practical, task-oriented reference for running and using Jarvis, created as `docs/user_guide.md`. It covers how to run the CLI, dashboard, and scheduler; the full command grammar grouped by task; the Inbox/scheduled-summary/startup-notice flow; the dashboard; the GREEN/YELLOW/RED safety model; example sessions; troubleshooting; and an honest list of what Jarvis cannot do yet. No production code or test changed — every command and behavior described was verified directly against the codebase as it stood after Phase 22. This section was originally omitted from README's own phase list; the omission was never intentional, and is corrected here rather than left as drift.

---

## Phase 24 — File Search Tool (complete)

The one concrete gap in the existing file-command family: `list files`/`read file` require already knowing a path, with no way to find one. Phase 24 adds a single, narrow, read-only tool that searches for files by name or by content across a directory tree — nothing else changes. See `docs/phase_24_completion_report.md` for the full closure write-up.

### File search commands

```
search files for jarvis
find files named jarvis
find files containing scheduled_web_search_summary
search files containing scheduled_web_search_summary
```

The first two are aliases for a **name** search (a case-insensitive substring match against each file's own name); the last two are aliases for a **content** search (a case-insensitive substring match against each file's text, showing a short one-line context snippet per match — never the full file). Both always search recursively from the project directory; there is no `in <directory>` clause. Both are GREEN and run immediately, with no approval required — exactly as read-only as `list files`/`read file`.

### Safety note: read-only, bounded, and inert by construction

`FileSearchTool.action_for()` always returns the same fixed string ("search files") regardless of the search mode or the user's own query text, so its Security Manager classification can never vary with input. Results are capped (50 by default, configurable up to 500, mirroring `FileListTool`'s own limit convention) and a fixed set of noisy directories (`.git`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, virtual environments, `node_modules`, build/cache folders) is never descended into. A content search skips binary files (sniffed the same way `FileReadTool` already does), skips files over 2MB, and treats any unreadable/undecodable file as "no match" rather than an error — one bad file can never abort the rest of a search. No file is ever created, modified, moved, renamed, or deleted by this tool; it calls no AI, no web search, and no subprocess.

### What is deliberately NOT included in Phase 24

File move, copy, rename, or delete of any kind; local application launching; a content-indexing database or cache; semantic or fuzzy AI-assisted search; a background crawler; any dashboard, scheduler, or Inbox change; any Core service, HTTP server, or IPC bridge; webpage fetching; and Research Agent or voice/phone work. This is exactly one small, read-only addition to the existing file-command family — not a file manager, not an indexing service, and not a step toward file-write automation.

---

## Phase 25 — File Copy Tool (complete)

The safest possible next increment in the file-tool family after search: a way to duplicate a file — for example, to back it up before editing — without touching move, rename, or delete. See `docs/phase_25_completion_report.md` for the full closure write-up.

### File copy command

```
copy file notes.txt to notes.txt.bak
```

Copies exactly one existing file to one new destination path. Requires approval (YELLOW), exactly like `create file`/`append to file`. There is no directory-copy, no recursive copy, and no `in <directory>` clause — the source and destination are both plain paths.

### Safety note: never overwrites, never touches the source, approval cannot waive it

The destination must not already exist — this is enforced unconditionally, even after approval: approving a copy command only authorises the *attempt*, never a decision to overwrite something already at the destination. The source file is never opened for anything but a raw, byte-for-byte read (no text interpretation, so binary files copy correctly) and is never modified, moved, renamed, or deleted — verified directly by comparing its bytes before and after every copy. The destination's parent folder must already exist, matching `create file`'s own established behaviour exactly — this tool does not create folders. `FileCopyTool.action_for()` always returns the same fixed string ("copy file") regardless of the source/destination paths, so its Security Manager classification can never vary with input.

### What is deliberately NOT included in Phase 25

File move, rename, or delete of any kind (each a distinct, separately-scoped future decision — move/rename in particular share an underlying mechanism that removes the file from its original location, a different risk class from copy); directory or recursive copying; any overwrite option, with or without approval; local application launching; any dashboard, scheduler, or Inbox change; any Core service, HTTP server, or IPC bridge; webpage fetching; and Research Agent or voice/phone work. This is exactly one small, narrow write capability, built by directly reusing `FileCreateTool`'s own proven approval/path-safety pattern — not a file manager and not a step toward broader file automation.

---

## Phase 26 — File Move/Rename Tool (complete)

The one remaining common file operation after copy: relocating or renaming an existing file. `move file` and `rename file` are two names for the exact same command — a same-directory destination is a rename, a cross-directory destination is a move, and both go through one tool via the same underlying mechanism. See `docs/phase_26_completion_report.md` for the full closure write-up.

### File move/rename command

```
move file draft.txt to final.txt
rename file draft.txt to final.txt
```

Moves or renames exactly one existing file to one new destination path. Requires approval (YELLOW) — the same tier as `copy file`/`create file`, and for the same reason: this changes filesystem state, and unlike copy, the source path stops existing afterward. There is no directory-move, no recursive move, and no `in <directory>` clause.

### Safety note: never overwrites, approval cannot waive it, no delete capability introduced

The destination must not already exist — enforced unconditionally, even after approval, exactly like `copy file`. The destination's parent folder must already exist (this tool does not create folders). `FileMoveTool.action_for()` always returns the same fixed string ("move file") regardless of the source/destination paths, so its Security Manager classification can never vary with input — and that exact phrase already matched a pre-existing YELLOW rule in `security/security_manager.py`, confirmed by direct inspection before writing any code, so no new Security Manager rule was needed. The source path genuinely stops existing after a successful move — that is the nature of "move," not a side effect to hide, and is exactly why approval is required every time. This tool introduces no delete capability of any kind: a failed or refused move always leaves the source exactly where it was.

### What is deliberately NOT included in Phase 26

File delete of any kind (a distinct, separately-scoped future decision); directory or recursive moves; any overwrite option, with or without approval; a separate "rename" tool distinct from "move" (one tool covers both, since they are the same underlying operation); any dashboard, scheduler, or Inbox change; any Core service, HTTP server, or IPC bridge; webpage fetching; and Research Agent or voice/phone work. This is exactly one small, narrow write capability, built by directly reusing `FileCopyTool`'s own proven approval/path-safety pattern — not a file manager and not a step toward broader file automation.

---

## Phase 27 — Durable Pending-Approval / Resumable Workflow State (complete)

Closes a real, previously-silent gap: `ApprovalManager`'s pending approvals and `WorkflowEngine`'s paused workflows lived only in memory — a crash or restart between "prompt shown" and "answer given" silently discarded them, with no record anywhere that anything had been lost. Phase 27 makes both durable, safely. See `docs/phase_27_implementation_plan.md` and `docs/phase_27_completion_report.md` for the full design and closure write-up.

### What survives a restart now

A pending YELLOW approval (for a plain tool call, or for the step a paused workflow is waiting on) and a paused workflow's own plan/progress are both persisted to two new, narrowly-scoped SQLite tables — `pending_approval_state` and `paused_workflow_state` — the moment they're created, and removed the moment they're decided, resumed, or found invalid. Neither table is a history log: `approval_history`/`workflow_history` remain completely unchanged, still permanently hold no tool name, tool input, or serialized plan, and are never read from or written to by this feature.

### Fail-closed by design — reload never executes anything by itself

On every startup, `main.py` reloads any persisted pending approval, then any persisted paused workflow (in that order — a paused workflow's own resumability depends on its linked approval having already been reloaded). Every row is independently re-validated against **live** code before being treated as pending/paused again: the tool must still be registered, its action must still classify YELLOW under a fresh `SecurityManager.classify_action()` call, the JSON must parse, the schema version must be recognised, and the row must not be older than the configured approval timeout. A paused workflow additionally requires its own linked approval to have survived that same check. Anything that fails is removed and recorded as an honest, terminal entry in the existing approval/workflow history — never silently dropped, never executed, never auto-approved, and never auto-resumed. Reload only ever makes a row available for you to explicitly approve or decline, exactly as if the process had never restarted.

### What is deliberately NOT included in Phase 27

No new tools, no file delete, no dashboard write actions or command box, no Core service or multi-client architecture, no approval scheduling, no auto-approval or auto-denial, no changes to Security Manager classification rules, no changes to any file tool's behaviour, no webpage fetching, no notifications, no goals/projects/tasks, and no new workflow templates. Day-to-day use is unchanged unless a restart happens to land exactly mid-approval or mid-workflow-pause — which previously lost that state silently, and now either resumes it safely or tells you honestly that it couldn't.

---

## Phase 28 — Workflow Resume Request-ID Invariant (complete)

A small, narrow hardening pass, closing a gap Phase 27 disclosed but deliberately did not fix: `WorkflowEngine.resume()` never verified that the `ApprovalDecision` it was given actually belonged to the specific paused workflow being resumed — it trusted the caller to supply a matching pair. In every real caller this codebase has (`core/orchestrator.py::execute_approved()`), that pair was already guaranteed to match by construction, so this was never live-exploitable; but it was a real, avoidable gap worth closing narrowly before it could matter more (more workflow templates, or a future multi-client architecture, would both make a caller-side slip-up more plausible). See `docs/phase_28_completion_report.md` for the full write-up.

`resume()` now fails closed — raising `WorkflowError`, executing no tool, mutating nothing — if `decision.request_id` does not match the paused workflow's own recorded `request_id`, and records an honest terminal entry in the existing, unchanged `workflow_history`. A mismatch permanently closes the workflow rather than leaving it open for a retry with a different decision. Every existing, legitimate approval/resume path — live or reloaded after a restart — is completely unaffected; the guard only ever rejects a genuinely mismatched pair, which no production code path produces today.

### What is deliberately NOT included in Phase 28

No new workflow templates, no new tools, no file delete, no dashboard changes, no Core service, no webpage fetching, no notifications, no goals/projects/tasks, no changes to `SecurityManager` or `ApprovalManager` behaviour, and no new approval-correlation subsystem or durable table — this is exactly one additive guard clause inside `WorkflowEngine.resume()`.

---

## Phase 29 — Search File Then Copy File Workflow (complete)

One new, narrow, fully deterministic workflow command — the fifth, after the two Phase 15 memory workflows and the two Phase 17 file/memory workflows — chaining the existing `file_search` (GREEN) and `file_copy` (YELLOW) tools. Fully durable and hardened by construction: it pauses for approval exactly like every other workflow, survives a restart through Phase 27's own durable pending-approval/paused-workflow system, and remains protected by Phase 28's resume request-id invariant, with zero new plumbing for either. See `docs/phase_29_completion_report.md` for the full write-up.

### File search-and-copy command

```
search files for <pattern> and copy first to <destination>
```

Finds files whose name matches `<pattern>`. If **exactly one** file matches, it pauses for your approval to copy that file to `<destination>` — decline and nothing is copied, approve and the copy proceeds exactly like a standalone `copy file` command (never overwriting an existing destination, even after approval). If the search finds **zero** or **more than one** match, the workflow stops honestly without ever attempting a copy — the search step's own result (visible in the response) tells you exactly what was found, so you can narrow the pattern and try again. Only name-mode search is supported for this workflow; content-mode search (`find files containing`/`search files containing`) does not chain into a copy.

### How the file path is safely carried between steps

The matched file's path never comes from parsing this tool's own human-readable output text. `FileSearchTool` now also returns a small piece of structured result metadata — a match count, and (only when there is exactly one match) that match's absolute path — and `WorkflowEngine`'s existing, narrow previous-step propagation mechanism (previously used only for a saved memory's id) carries that one specific field into the copy step's input. No general-purpose dataflow system was introduced: the propagation is a small, fixed, explicitly-named list of exactly two special cases, both pre-existing in spirit, not a generic templating language.

### What is deliberately NOT included in Phase 29

More than this one workflow template; an AI-generated summary as part of any workflow step (`WorkflowEngine` still executes only deterministic tool calls, never AI); file delete; new file tools; any dashboard, scheduler, or Inbox change; any Core service, HTTP server, or IPC bridge; webpage fetching; notifications; goals/projects/tasks; and any database-tamper/integrity work. A small, corrective fix was also made to `workflow/engine.py`'s own module docstring, whose "Does NOT" claims about never calling `SecurityManager`/`ToolRegistry` and never persisting anything had gone stale since Phase 27 — corrected to accurately describe the now-existing, narrowly-scoped reload-revalidation exception.

---

## Phase 30 — Workflow & AI-Summary Direction Closure + Documentation Consolidation (complete)

A documentation-only phase, recording two architectural conclusions reached during the Post-Phase-29 direction review, plus a documentation-accuracy fix. No production code, tool, or test behavior changed. See `docs/phase_30_completion_report.md` for the full write-up.

**The workflow/AI-summary boundary is intentional, not an oversight.** `workflow/workflow_plan_factory.py` now documents directly why every workflow template is deterministic and tool-only: the approval prompt shown before a YELLOW step runs displays only the action, reason, risk tier, and metadata — never the step's full `tool_input`. That's safe today because everything written by an existing workflow is either text Nathan typed himself, or a plain path/id propagated from a trusted tool result. It would not be safe for an AI-generated summary to flow silently into a following write step: Nathan would be approving a file write without ever seeing the text being written. AI summaries remain advisory, terminal responses; saving one to a file remains a manual, separate step for now, and automating that is a distinct, separately-reviewable future decision, not a simple workflow template.

**More workflow templates are paused, not closed.** Five templates now exist, proving the deterministic tool-only pattern twice over (Phases 17 and 29). The next one should come from a specific request or a clearly demonstrated recurring task — not merely because the machinery already exists.

### What is deliberately NOT included in Phase 30

Any AI workflow step; any save-summary-to-file automation; any new workflow template; file delete; new tools; any dashboard, scheduler, or Inbox change; any Core service, HTTP server, or IPC bridge; webpage fetching; notifications; goals/projects/tasks; any database-tamper/integrity work; any change to the approval prompt's own display format; and any change to `SecurityManager` or `WorkflowEngine` execution behavior. This phase only added documentation and code comments.

---

## Phase 31 — Configuration Inspection Tool (complete)

One small, GREEN, read-only tool answering a real, already-documented troubleshooting need: what is Jarvis currently configured with? See `docs/phase_31_completion_report.md` for the full write-up.

### Configuration command

```
show config
show settings
```

Both are the same fixed, no-argument request. Reports every non-secret `Settings` field in full — AI model, AI max tokens, whether AI reasoning is enabled, database path, log level, approval timeout, and debug mode. The one secret field, the Anthropic API key, is reported only as `set` or `not set` — never its value, never a masked or partial form, never its length, and never a hash or fingerprint of it. The tool reads only the already-loaded `Settings` object; it never re-reads `.env`/`os.environ` itself, never mutates anything, never uses a subprocess, and never calls AI or the web.

### What is deliberately NOT included in Phase 31

No subprocess usage of any kind (this remains true of every tool in this codebase); no git/repo-health reporting; no test-running; no configuration mutation or `.env` editing; no new dependency; no secret display in any form, partial or otherwise; webpage fetching; file delete; Core service; goals/projects/tasks; new workflow templates; dashboard, scheduler, or Inbox changes; automated summary-saving; or notifications.

---

## Phase 32 — Webpage Fetch/Read Safety Foundation (complete)

An internal-only safety foundation for fetching and reading a single webpage, built across a planning pass and three batches. At the time this phase closed, nothing in the running system called it yet — no command, no tool, no AI/workflow/scheduler/dashboard integration. **This has since changed**: Phase 33 (below) registers the first, still non-AI, consumer of this foundation. See `docs/phase_32_implementation_plan.md` and `docs/phase_32_completion_report.md` for the full write-up.

### What Phase 32 added

- **`web/fetch_policy.py` — `WebFetchPolicy`** (Batch 1). Pure, deterministic URL validation with no network I/O: allow-lists `http`/`https` only; rejects malformed URLs, missing scheme/hostname, embedded credentials, localhost names, and IP literals in private/loopback/link-local/multicast/reserved/metadata ranges (IPv4 and IPv6), all via the standard library's own `ipaddress` predicates.
- **`web/safe_web_fetcher.py` — `SafeWebFetcher`** (Batch 2). The one module permitted to import `httpx` (promoted from an already-installed transitive dependency to an explicit direct one — zero new packages). Re-validates every target with `WebFetchPolicy`, resolves and validates DNS-resolved IP addresses, then pins the actual connection to the validated IP while preserving the real hostname for the `Host` header and TLS SNI — closing the DNS-rebinding window rather than merely documenting it. GET-only, manual re-validated redirects (capped), streaming size-limit enforcement, content-type allow-list, and structured failures — never a raised exception.
- **`web/html_text_extractor.py`** (Batch 3). A deterministic, standard-library-only (`html.parser`) HTML-to-text extractor: strips script/style/noscript/template content entirely, ignores comments, decodes entities safely, collapses whitespace, and enforces a hard output character cap with honest truncation reporting. `text/plain` is passed through with only line-ending normalisation. Never raises on malformed HTML.

### What is deliberately NOT included in Phase 32

No CLI command or registered tool of any kind — fetching a webpage is not yet something Nathan can ask Jarvis to do. No `SecurityManager` rule (nothing is classified, since nothing is callable). No AI integration: no `AIContextBlock` is ever constructed by this foundation, and no fetched/extracted content has been shown to an AI. No webpage summarization, no Research Agent, no autonomous browsing. No workflow, scheduler, dashboard, or Inbox integration. No automated save-to-file. No Core service, file delete, voice, phone, goals, projects, or tasks. Every one of `web/`'s three modules is proven, by structural test, to import nothing from `ai/`, `workflow/`, `scheduler.py`, `ui/`/dashboard, `tools/`, `core/`, `security/`, `approval/`, or `storage/`. Future integration must explicitly route any extracted text through `AIContextBlock.from_untrusted()` and rely on `PromptBuilder`'s existing automatic injection scan before any AI use.

---

## Phase 33 — Webpage Read Command (No AI Summarization) (complete)

The first user-facing consumer of Phase 32's safety foundation: one new, approval-gated command that fetches a single webpage and shows Nathan its extracted plain text — nothing more. See `docs/phase_33_completion_report.md` for the full write-up.

### Webpage read command

```
read webpage <url>
```

Classified **YELLOW** — reading a webpage brings external network content onto the system and displays it to Nathan, so it always requires approval, exactly like the existing (previously unused) `download` rule's own reasoning. Unlike `search the web for <query>` (GREEN, one fixed and vetted provider), this command sends a request to an arbitrary, Nathan-supplied target, which is why it is held to a stricter default. On approval, Jarvis fetches the page through `WebFetchPolicy`/`SafeWebFetcher` (Phase 32) exactly as before, extracts its text with `html_text_extractor` (Phase 32), strips any ANSI/terminal-control escape sequences the page's own text might contain, and shows the result — bounded, with truncation honestly disclosed if the safety limit was hit. The tool's security classification is always the fixed string `"read webpage"`, never the URL itself.

### What is deliberately NOT included in Phase 33

No summarization of any kind — the text shown is exactly what was extracted, never rewritten or condensed. **This has since changed**: Phase 34 (below) adds AI summarization as a distinct, separately-approved command; `read webpage <url>` itself is unchanged and still never summarizes. No AI involvement: no `AIContextBlock` is constructed, no AI provider is called. No autonomous browsing, and no following of links or instructions the fetched page's own text might contain — the page is fetched exactly once, and its content is always treated as data to display, never as a command. No saving of fetched content to a file, the database, or anywhere else — every read is fresh, with nothing persisted. No scheduled webpage monitoring, no workflow template, no dashboard or Inbox integration. No new command aliases beyond the one exact grammar. No Research Agent, Core service, file delete, voice, phone, goals, projects, or tasks.

---

## Phase 34 — AI Webpage Summarization (complete)

A second, distinct consumer of Phase 32's safety foundation: one new command that summarizes a webpage with AI, built specifically to avoid a bypass risk found during its own architectural review. See `docs/phase_34_implementation_plan.md` and `docs/phase_34_completion_report.md` for the full write-up.

### Webpage summary command

```
summarize webpage <url>
summarise webpage <url>
```

Both spellings route identically. **The central safety design point**: Phase 18's existing `"summarise web search for <query>"` command is safe to leave un-approval-gated only because it always calls one fixed, vetted search provider — that pattern cannot be safely copied for an arbitrary webpage URL, which is exactly the risk category Phase 33 already classified YELLOW. So this command reuses Phase 33's `WebpageReadTool`/`ToolExecutor`/`SecurityManager` path unchanged for acquisition: a first request always requires the same YELLOW approval `read webpage <url>` already uses, classified via the tool's own fixed `"read webpage"` action string, never the URL. Only after Nathan approves and the fetch actually succeeds does `ai/webpage_ingestion.py` wrap the extracted text as `AIContextBlock.from_untrusted(text, source=f"webpage:{url!r}")` — with a preamble explicitly warning the AI that the content may be incomplete, outdated, malicious, or contain prompt-injection attempts — and `AIReasoningEngine.reason()` produce a display-only summary. The summary is never saved anywhere: no Inbox entry, no file, no database row.

### What is deliberately NOT included in Phase 34

No new command aliases beyond the two spellings. No autonomous browsing, no multi-page crawling — exactly one fetch per request. No acting on instructions inside the webpage's own text — it is always treated as data to summarize, never a command, regardless of what it says. No automated save-to-file or Inbox integration (unlike the web-search-summary command, which does auto-save — a deliberate difference, since this content is approval-gated in a way that one isn't). No workflow, scheduler, or dashboard integration. No `PromptBuilder` changes — the existing, already-proven automatic injection scan covers this new untrusted source unmodified. No Research Agent, Core service, voice, phone, goals, projects, or tasks. **File delete has since been added** — see Phase 35 below — as a distinct, separately-reviewed capability unrelated to webpage work.

---

## Phase 35 — File Delete with Trash/Quarantine (complete)

Jarvis's first file-delete capability — not a permanent, irreversible delete, but a safe quarantine move. See `docs/phase_35_completion_report.md` for the full write-up.

### File delete command

```
delete file <path>
```

Classified **YELLOW**, reusing the pre-existing `"delete file"` rule in `SecurityManager` (no new rule was needed). On approval, the file is moved into `.jarvis_trash/` — a Jarvis-managed quarantine directory, created on demand, relative to the current working directory. The file is **not destroyed**: it still exists on disk afterward, just no longer at its original path. Quarantined files are named with a unique random suffix so two files with the same original name never collide or overwrite each other. Directories, symlinks, and files already inside the quarantine directory are all rejected with a clear explanation. There is deliberately no restore command, no "empty trash" command, and no automatic cleanup or retention policy in this phase — once quarantined, a file stays there until Nathan manages it himself outside of Jarvis.

### What is deliberately NOT included in Phase 35

No permanent/irreversible delete of any kind — no production code path calls `os.remove()`, `Path.unlink()`, `shutil.rmtree()`, or any equivalent. No restore/undo command. No "empty trash" command. No automatic cleanup or retention policy. No dashboard, scheduler, Inbox, workflow, or AI integration. No Research Agent or autonomous behavior. No Core service, voice, phone, goals, projects, or tasks. No command aliases beyond the one exact grammar (`remove file`, `trash file`, `quarantine file`, `rm`, etc. were all deliberately not added). **Listing quarantine contents has since been added** — see Phase 36 below — still with no restore/empty-trash/cleanup behavior of any kind. **Durable original-path metadata recording has since been added** — see Phase 37 below — still not a restore command itself. **A restore command has since been added** — see Phase 38 below — still no empty-trash/permanent-delete/cleanup behavior of any kind.

---

## Phase 36 — List Quarantine Contents (complete)

One small, read-only companion to Phase 35's quarantine command: a way to see what's currently inside `.jarvis_trash/` without leaving Jarvis. See `docs/phase_36_completion_report.md` for the full write-up.

### Quarantine listing commands

```
list quarantine
show quarantine
```

Both phrases route to the same fixed, no-argument request. Classified **GREEN**, via the existing generic `"list"` rule — no new `SecurityManager` rule was needed. Reports each quarantined file's name, size in bytes, and modified time; reports honestly if the quarantine directory doesn't exist yet or is empty; never creates `.jarvis_trash/` just to list it. Purely informational — it does not restore, delete, clean up, move, or modify anything, and does not imply any of those capabilities exist (they don't).

### What is deliberately NOT included in Phase 36

No restore/undo command. No "empty trash" command. No automatic cleanup or retention policy. No dashboard, scheduler, Inbox, workflow, or AI integration. No file content is ever read — only filesystem metadata (name, size, modified time). No command aliases beyond the two exact phrases (`list trash`, `show trash`, `open quarantine`, `quarantine list`, etc. were all deliberately not added). **Original-path display has since been added** — see Phase 37 below — still read-only, still no restore. **A restore command has since been added** — see Phase 38 below.

---

## Phase 37 — Quarantine Restore Metadata Foundation (complete)

Lays the groundwork for a future restore command, without building restore itself. See `docs/phase_37_completion_report.md` for the full write-up.

Every new file quarantined via `delete file <path>` now also records durable metadata — its resolved original path, its resolved quarantine path, when it was quarantined, and the session it happened under — in a dedicated database table (`quarantine_records`, via a new `QuarantineStore`). `list quarantine`/`show quarantine` display that recorded original path for each file when a record exists.

Files quarantined before this phase (Phase 35/36) have no such record — `list quarantine`/`show quarantine` show an honest `original path: unknown (quarantined before metadata tracking)` for those, never a guess derived from the filename (the quarantine filename only ever preserves the original stem/suffix, never the original directory).

### What is deliberately NOT included in Phase 37

No restore/undo command — this phase only makes a future restore command *safer to build later*; it does not restore anything itself. No "empty trash" command. No permanent delete. No automatic cleanup or retention policy. No dashboard visibility into quarantine contents. No migration or backfill of pre-Phase-37 quarantined files — a missing record is always treated as the ordinary, expected case, never an error. No dashboard, scheduler, Inbox, workflow, or AI integration. `QuarantineStore` itself exposes no update, delete, restore, or cleanup method of any kind — only recording a new row and reading one back by quarantine path. **A restore command has since been added** — see Phase 38 below.

---

## Phase 38 — Quarantine Restore Command (complete)

Completes the quarantine feature family started in Phase 35: a command that restores one previously-quarantined file back to its recorded original location, using the durable metadata Phase 37 added. See `docs/phase_38_completion_report.md` for the full write-up.

### File restore command

```
restore file <quarantine-file-or-path>
```

Classified **YELLOW**, via a new dedicated `SecurityManager` rule (`"restore file"`, fixed and input-independent). On approval, `FileRestoreTool` looks up the quarantined file's recorded metadata via `QuarantineStore`, and — only if a record exists — moves the file (`Path.rename()`, never a copy) from `.jarvis_trash/` back to its exact recorded `original_path`. The identifier can be either a bare filename as shown by `list quarantine`/`show quarantine` (resolved directly inside `.jarvis_trash/`), or any path that resolves to a file directly inside the quarantine directory — anything else, including path traversal attempts, is rejected.

A file with no metadata record (quarantined before Phase 37, or otherwise unrecorded) cannot be restored automatically — Jarvis never guesses an original location from the quarantine filename. If the recorded `original_path` already exists, or its parent folder no longer exists, the restore is refused and the quarantined file is left untouched — this tool never overwrites anything and never recreates folders.

### What is deliberately NOT included in Phase 38

No empty-trash command. No permanent delete. No automatic cleanup or retention policy. No bulk/"restore all" command — exactly one file per request. No overwrite behavior, ever. No destination-choice — the restored path is always exactly the recorded `original_path`, never something Nathan types. No dashboard, scheduler, Inbox, workflow, or AI integration. No command aliases beyond the one exact grammar (`undo delete`, `restore quarantine`, `restore trash`, `recover file`, `untrash file`, `move back file`, etc. were all deliberately not added). `FileDeleteTool`, `QuarantineStore`, and `QuarantineListTool` were not changed in this phase beyond sharing the existing `QuarantineStore` instance with the new tool. **Read-only dashboard visibility for quarantine contents has since been added** — see Phase 39 below.

---

## Phase 39 — Dashboard Quarantine Visibility (complete)

Gives the dashboard a seventh tab showing what's recorded in quarantine — the one subsystem in the file/quarantine family that previously had no dashboard presence, now that delete/list/restore all exist. See `docs/phase_39_completion_report.md` for the full write-up.

### Dashboard Quarantine tab

Read-only, exactly like every other dashboard tab: shows each quarantined file's name, original path, quarantine path, quarantined-at time, and session id (when known), sourced from `DashboardReadModel.get_quarantine_entries()`, which itself reads only `QuarantineStore.list_recent()` — the same durable metadata records `list quarantine`/`show quarantine` and `restore file` already use. A missing/empty state is shown honestly ("No files currently in quarantine.") rather than an error. A row here does not guarantee the file still physically exists in `.jarvis_trash/` — it may have already been restored via the CLI, since a restore never deletes or updates the underlying `QuarantineRecord`.

### What is deliberately NOT included in Phase 39

No restore button, delete button, empty-trash button, or cleanup button anywhere — the Quarantine tab, like every other dashboard tab, has no write, execute, approve, decline, run, retry, resume, or cancel control of any kind. No filesystem inspection from the dashboard — it never reads `.jarvis_trash/` directly and never duplicates `QuarantineListTool`'s own filesystem-listing logic; it only reads durable database records. No empty-trash command, permanent delete, or cleanup/retention policy. No AI, workflow, scheduler, or Inbox integration. `FileDeleteTool`, `FileRestoreTool`, `QuarantineListTool`, and `QuarantineStore`'s own write behavior were not changed in this phase — `QuarantineStore` gained one new read-only method (`list_recent()`) and nothing else.

---

## Phase 43 — Command Discoverability: a Read-Only "help" Command (complete)

One small, GREEN, read-only tool answering a real usability gap: with 25+ built-in commands and no in-CLI way to discover them, `HelpTool` lists every currently supported command grammar phrase and a short one-line description, from inside the running program. See `docs/phase_43_completion_report.md` for the full write-up.

### Help command

```
help
list commands
show commands
```

All three are the same fixed, no-argument request. The output is a static, hand-maintained constant — never AI-generated, and never derived from `CommandRouter` at runtime (which has no machine-readable grammar table to read from). It is grouped to match `docs/user_guide.md`'s own "Command Reference" section (§6) exactly, so both stay easy to keep in sync by hand.

### What is deliberately NOT included in Phase 43

No generic or introspectable command registry (`CommandRouter`'s matching logic was not refactored). No AI-generated help text. No write action of any kind, and no change to approval behavior or to the security classification of any existing action. No dashboard integration. No voice/audio/microphone/hotkey work of any kind. No new dependency. `.env.example`'s own, separate staleness gap was left untouched, as explicitly scoped — a distinct, separately-tracked future item.

---

## Phase 57 — Read-Only System Health Check Tool (complete)

A small, GREEN, read-only tool answering a real, explicitly-expressed need: after the Phase 43–56 config/help/logging/dashboard/scheduler hardening work, a way to confirm — from inside the running program — that everything is actually configured and wired correctly. `HealthCheckTool` reports eight checks, each read-only introspection of an object `main.py`'s own composition root already built. See `docs/phase_57_completion_report.md` for the full write-up.

### Health check command

```
health check
show health
system health
```

All three are the same fixed, no-argument request. Checks: settings loaded; database path reachable (a plain filesystem check, never opening a new database connection); tool registry populated with the expected core tools; console logging configured (Phase 54's `configure_console_logging()`); Inbox store reachable; Schedule store reachable; Quarantine store reachable; and a `SecurityManager` self-classification sanity check. Every store check reuses the exact same `InboxStore`/`ScheduleStore`/`QuarantineStore` instances `main.py` already constructs for other tools — never a new database connection, never a new store instance, never a row created.

### What is deliberately NOT included in Phase 57

No write action of any kind. No new database connection or store instance created solely to check health. No secrets or API key values shown. No invocation of `dashboard.py` and no `DashboardReadModel` construction — the dashboard is a wholly separate process with its own database connection; the shared SQLite file's existence is already covered by the database-path check. No change to approval behavior or to the security classification of any existing action beyond the one new, additive GREEN rule for this tool's own action. No new dependency. No broader "system inspector" scope beyond the eight checks above.

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
├── storage/        SQLite database and ORM models: memory, approval/workflow
│                   history, inbox entries, schedules, quarantine records,
│                   and durable pending-approval/paused-workflow state
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
│                   ai/memory_ingestion.py), web-search and webpage
│                   ingestion (ai/web_search_ingestion.py,
│                   ai/webpage_ingestion.py), and deterministic query-based,
│                   category-based, recency-based, and count-bounded
│                   recency-based memory selection (ai/memory_selection.py)
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, built-in tools, and the
│                   WebSearchProvider abstraction plus the concrete
│                   DuckDuckGoSearchProvider adapter (Phase 16)
│   └── builtin/    GREEN (read-only): echo, info, help, health_check,
│                   memory, file_list, file_read, file_search, web_search,
│                   quarantine_list, config, approval_history,
│                   workflow_history, schedule_list. YELLOW guarded read: webpage_read.
│                   YELLOW approval-gated write: file_create,
│                   file_append, file_copy, file_move, file_delete
│                   (quarantine-only, never permanent), file_restore,
│                   memory_update, memory_forget, schedule_create,
│                   schedule_enable, schedule_disable
├── approval/       Approval models and the Approval Manager
├── workflow/       Sequential Workflow Engine, the deterministic
│                   two-step workflow plan factory, and the durable
│                   workflow lifecycle history store
├── inbox/          Durable Inbox store for saved AI-generated outputs
│                   (Phase 20) - today, one producer: web-search-summary
│                   results, both interactive and scheduled
├── scheduling/     Durable schedule store, the atomic due/claim guard, and
│                   the scheduled web-search-summary execution helper
│                   (Phase 21) - scheduler.py's own poll loop is the
│                   process that actually runs a due schedule
├── quarantine/     Durable quarantine metadata store (QuarantineStore,
│                   Phase 37): records original_path/quarantine_path for
│                   every file FileDeleteTool moves into .jarvis_trash/,
│                   so FileRestoreTool (Phase 38) can move it back -
│                   storage layer only, no tool/command/UI code
├── core/           Orchestrator that wires everything together, plus the
│                   CommandRouter that matches request text to a tool
├── ui/             Command-line interface and approval prompts, plus the
│                   tkinter/ttk dashboard presentation layer
│                   (ui/dashboard_app.py, Phase 19)
├── web/            Webpage fetch/read safety foundation (Phase 32):
│                   WebFetchPolicy (URL/target validation), SafeWebFetcher
│                   (the sole module permitted to import httpx), and a
│                   deterministic HTML text extractor - used by the
│                   registered "read webpage"/"summarize webpage" tools
│                   (Phase 33/34)
├── dashboard/      Read-only DashboardReadModel composition layer
│                   (Phase 19) over the durable stores above - the sole
│                   persistence-facing layer ui/dashboard_app.py depends
│                   on; contains no tool/command/UI code itself
├── voice/          Voice interface foundation (Phase 41) - fake/mock
│                   provider abstractions only, disabled by default,
│                   no real audio, no microphone, no dependency:
│                   voice/tts.py (TextToSpeechProvider, SpeechResult,
│                   FakeTextToSpeechProvider), voice/output.py
│                   (VoiceOutputService), voice/stt.py
│                   (SpeechToTextProvider, TranscriptionResult,
│                   FakeSpeechToTextProvider), voice/input.py
│                   (VoiceInputService) - wired into ui/cli.py behind
│                   four independent opt-in settings; voice input is
│                   reachable only from tests today, not from the
│                   interactive CLI loop
├── tests/          Unit and integration tests
├── docs/           Specifications, implementation plans, and reports
├── main.py         Entry point — starts Jarvis (the CLI)
├── dashboard.py    Entry point — starts the read-only dashboard window,
│                   a separate local process sharing only the SQLite file
└── scheduler.py    Entry point — polls and runs due, enabled schedules,
                    a separate local process sharing only the SQLite file
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

**As of this section's last update, console logging has been wired up using the already-validated `LOG_LEVEL` setting** (check the `docs/` directory for a higher-numbered `phase_NN_completion_report.md` if a newer phase has closed since this paragraph was last edited, and see `docs/deferred_decisions.md` item 1 for the current, authoritative status of this and other deferred decisions): `observability/logging_setup.py`'s `configure_console_logging()` attaches one console handler to Jarvis's app logger, idempotently, with its level set from `settings.log_level` — wired into both `main.py`'s and `scheduler.py`'s real entry points, never into shared construction paths used by the wide test suite. GREEN/successful events now genuinely appear on the console, a real, disclosed increase in default console output. See `docs/phase_54_completion_report.md` for the full closure write-up.

This followed directly from earlier work: Phase 45 updated the unmatched-GREEN fallback message so an unsupported request now points Nathan toward `help`/`list commands`/`show commands` (see `docs/phase_45_completion_report.md`). Phase 46 validated `LOG_LEVEL` against `config.constants.LogLevel`'s own values, case-insensitively, closing a prior mismatch where any string was silently accepted (see `docs/phase_46_completion_report.md`). A planning-only stage (no completion report, matching this project's own established precedent for planning-only stages) then investigated whether `LOG_LEVEL` should also be wired into real console logging behavior, and found that console visibility had never actually worked for INFO-level events, independent of `LOG_LEVEL` — see `docs/phase_47_logging_console_visibility_plan.md` for the full investigation and the two options it compared. The safer, documentation-only option was implemented first (see `docs/phase_48_completion_report.md`); once Nathan explicitly confirmed he wanted live console visibility restored, wiring `LOG_LEVEL` into real console logging was implemented as its own, separately-approved phase (see above).

Phase 44 (environment-example synchronization), Phase 43 (the `help`/`list commands`/`show commands` command), Phase 42 (a documentation-only accuracy pass reconciling README with Phase 41), and Phase 41 (the voice interface foundation — planning, fake/mock text-to-speech and speech-to-text foundations, four independent disabled-by-default voice settings, opt-in CLI wiring for both voice output and voice input, a proven-safe shared request/security/approval path for voice-originated text, and a push-to-talk trigger design review) all remain complete and unchanged — see their respective completion reports (`docs/phase_44_completion_report.md`, `docs/phase_43_completion_report.md`, `docs/phase_42_completion_report.md`, `docs/phase_41_completion_report.md`). Phase 39 (read-only dashboard visibility for quarantine contents) and Phase 40 (a prior documentation-only accuracy pass) remain complete and unchanged as well.

The quarantine feature family remains complete for its declared, safe scope: `delete file <path>` quarantines a file into `.jarvis_trash/` (never permanently); `list quarantine`/`show quarantine` show what's recorded, including original path when known; `restore file <quarantine-file-or-path>` moves a file with known metadata back to its original location; and the dashboard's Quarantine tab shows that same durable metadata, read-only. Webpage commands (`read webpage <url>`, `summarize webpage <url>`/`summarise webpage <url>`) and the seven-tab read-only dashboard (Overview, Memories, Approval History, Workflow History, Inbox, Schedules, Quarantine) also exist today, unrelated to and unchanged by the quarantine work.

Phase 41's voice foundation (see the `voice/` entry in "Project Structure" below) is real, tested code, but delivers no user-reachable voice capability today: `voice_enabled`/`voice_speak_mode`/`voice_provider` (output) and `voice_input_enabled`/`voice_input_provider` (input) all default to off/none, only a fake/mock provider exists for either direction, and voice input is only reachable from tests, not from the interactive CLI loop. **Still not implemented, by design**: real text-to-speech, real speech-to-text, real microphone capture, real push-to-talk, wake-word/always-listening detection, dashboard voice controls, phone integration, and a Core service — each remains its own future, separately-planned phase or review, not committed to by Phase 41's closure. See `docs/phase_41_implementation_plan.md` (Section 14) for the push-to-talk trigger design comparison awaiting Nathan's own choice before any real-capture work begins.

As with every prior phase boundary, the next *numbered* architectural direction has not been chosen and requires its own fresh review before being scoped. Several genuinely valid future directions exist, **none yet selected or committed to**:

- Real push-to-talk/microphone capture, or a real local/free TTS/STT provider — each its own future, separately-planned phase, pending Nathan's own trigger-mechanism and voice choices (see Phase 41's completion report).
- Empty-trash/permanent delete for quarantine — would need its own RED classification and a dedicated safety-design review before being considered at all.
- A cleanup/retention policy for `.jarvis_trash/` — premature without real evidence it's actually needed.
- A scheduler schema/type foundation — currently blocks scheduled webpage summaries and any additional scheduled action type, since `ScheduleEntry` has no `action_type`/`kind` column, but remains unjustified without a concrete second use case.
- Inbox integration for webpage summaries — a producer-policy decision (whether an approval-gated summary should also auto-save) that hasn't been made yet, independent of implementation cost.
- Dashboard write actions of any kind — the dashboard has been strictly read-only since Phase 19; nothing has changed that.
- A Research Agent or autonomous browsing foundation — a standing non-goal unless explicitly selected through its own dedicated review.

None of the above is authorized by any closed phase to date; each remains a separately-scoped decision, to be reviewed fresh against the repository's actual state whenever it's next considered. Every future addition continues to go only behind the Security Manager, with the user in control. See `docs/deferred_decisions.md` for the current, consolidated list of these and other deferred decisions, kept up to date independently of this section.

---

*Jarvis is a personal project under active development. Phase 5 is a complete, tagged milestone; Phase 6 onward through the most recently closed phase are complete for their defined scope, not yet tagged (check the highest-numbered `docs/phase_NN_completion_report.md` to confirm which phase that currently is). None is a finished product.*
