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

Building on the advisory AI reasoning and guarded write actions from Phase 4, Jarvis now has a real personal knowledge system. Memories can be organised into categories, listed and searched (including within a category), reviewed one at a time, and — behind approval — corrected, re-filed, or forgotten. Reading memory is effortless and automatic; anything that changes or removes a memory asks first.

Phase 6 adds a durable, read-only record of every approval decision, so it survives a restart — without making any past decision resumable or replayable — and a bounded lifecycle for pending approvals: a YELLOW request left unanswered now expires automatically instead of waiting forever. See the Phase 6 section below.

Phase 7 is a **safety and structure phase, not a capability phase**: it simplifies the Core's request-routing code, and completes the Master Specification's prompt-injection defence — trusted-vs-untrusted AI context, automatic scanning of untrusted context for instruction-like patterns (audited when suspicious), and an audited policy for an AI-suggested action that falls outside a request's own plan. No new user-facing command, no new AI power, and no new execution authority were added. See the Phase 7 section below.

Phase 8 is Jarvis's first real use of that trust boundary: an explicit `summarise file <path>` command reads a real file and supplies its contents to the advisory AI as typed, untrusted context — scanned, audited, and never able to gain new authority, exactly as Phase 7 already guarantees. See the Phase 8 section below.

Phase 9 is the second real use of that same trust boundary: an explicit `summarise memory <id>` command reads one already-stored memory and supplies its content to the advisory AI the same way — typed, untrusted, scanned, audited, and never able to gain new authority. See the Phase 9 section below.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. AI reasoning is off by default and, when off, Jarvis behaves exactly as it did in Phase 3. Every test uses a fake provider, so no live Claude call is ever required to run or test Jarvis.

> **Verified:** `poetry run pytest -v` — **903 passed, 0 failed** (Python 3.14.6, pytest 9.1.1). This covers every Phase 1–9 test, including all of Phase 9's batches and its AIRouter audit-failure-isolation closure fix.

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
│                   typed trusted/untrusted AIContextBlock model, and
│                   file-content and stored-memory ingestion for the AI
│                   reasoning path (ai/file_ingestion.py,
│                   ai/memory_ingestion.py)
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and built-in tools
│   └── builtin/    echo, info, memory (list/search/save/get), file_list,
│                   file_read (GREEN); file_create, file_append,
│                   memory_update, memory_forget (YELLOW, approval-gated)
├── approval/       Approval models and the Approval Manager
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

**Phase 9 is complete**: Jarvis can now retrieve a real stored memory by id and have the advisory AI summarise it, entirely through Phase 7's trust and injection-defence pipeline, with no new AI authority and no new approval gate. What comes next, per `docs/phase_9_completion_report.md`, is **multi-memory retrieval and selection** — the first capability that requires a real answer to "which memories, how many, and how are they combined," now that single-record ingestion has been proven twice (file, memory). A separately-scoped, pre-existing observability finding (Phase 7's `AIRouter` not guarding its own audit-logging calls) is also recommended for its own independent review — see `docs/phase_9_completion_report.md` for the full account. Web/browser ingestion, and any Semantic/Entity Memory work, remain explicitly further out, each requiring its own separately-scoped design review before being started.

Resumable approvals, deeper but still-advisory AI assistance, and optional smarter search over memory remain deliberately deferred from earlier phases, each requiring its own safety review and architecture decision before it could even be scoped. Every future addition continues to go only behind the Security Manager, with the user in control.

---

*Jarvis is a personal project under active development. Phase 5 is a complete, tagged milestone; Phase 6, Phase 7, Phase 8, and Phase 9 are complete for their defined scope, not yet tagged. None is a finished product.*
