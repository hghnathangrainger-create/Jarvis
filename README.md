# Jarvis

Jarvis is Nathan's modular AI operating system project, designed to reduce workload while keeping Nathan in control.

Jarvis is **not** a chatbot. It is an orchestration layer that plans requests, classifies their safety, runs safe tools, remembers information, asks for approval before doing anything sensitive, and can optionally use AI to help interpret requests — with every action recorded.

---

## Current Status

**Phase 5 complete: Better Memory and Personal Knowledge System.**
**Phase 6 in progress: Durable Approvals (Batches 1–2 complete).**

Building on the advisory AI reasoning and guarded write actions from Phase 4, Jarvis now has a real personal knowledge system. Memories can be organised into categories, listed and searched (including within a category), reviewed one at a time, and — behind approval — corrected, re-filed, or forgotten. Reading memory is effortless and automatic; anything that changes or removes a memory asks first.

Phase 6 adds a durable, read-only record of every approval decision, so it survives a restart — without making any past decision resumable or replayable. See the Phase 6 section below.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. AI reasoning is off by default and, when off, Jarvis behaves exactly as it did in Phase 3. Every test uses a fake provider, so no live Claude call is ever required to run or test Jarvis.

> **Verified (Phase 5):** `poetry run pytest -v` — **477 passed, 0 failed** in 1.81s (Python 3.14.6, pytest 9.1.1). Phase 6 Batches 1–2 add further tests on top of this baseline; see the Phase 6 progress report for the up-to-date count once the full suite has been re-run.

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

## Phase 6 — Durable Approvals (in progress)

Phase 6 makes approval decisions durable: every approval request and its eventual outcome is recorded in SQLite, so the record survives a restart. This is a **read-only history**, not a queue of actions waiting to run — see the safety note below for exactly why that distinction is enforced structurally, not just by convention.

- **Batch 1 — Durable approval history.** Every created request and every approve/decline decision is written to a new `approval_history` table. A restart no longer loses the record of what was asked and how it was decided. As part of this batch, a pre-existing gap was also closed: `main.py` now actually connects the audit logger to the Approval Manager, so approval decisions reach the audit log as they always should have.
- **Batch 2 — CLI polish and documentation.** The five read-only commands below now show every field — request id, status, action, security tier, created time, and, once decided, decided time, decided by, and decision reason — cleanly, with fields that don't apply yet (a pending request has no decision) simply omitted rather than shown blank.

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
- **No resumable approvals.** Making a past pending request resumable is an explicit, separate decision, deliberately deferred to a future batch with its own safety review, its own reclassification analysis, and its own expiry rules — not something this phase enables by accident.

### What is deliberately NOT included (Phase 6 so far)

Resumable approvals, an `approve <id>` command for anything not currently pending in memory, automatic execution of any kind, and any change to what gets classified GREEN/YELLOW/RED. All remain candidates for a clearly separate, future batch.

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
├── security/       Security Manager and append-only audit log
├── memory/         Memory Engine: save, list, search, categories, update, forget
├── ai/             Provider interface, Claude provider, and advisory reasoning
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and built-in tools
│   └── builtin/    echo, info, memory (list/search/save/get), file_list,
│                   file_read (GREEN); file_create, file_append,
│                   memory_update, memory_forget (YELLOW, approval-gated)
├── approval/       Approval models and the Approval Manager
├── core/           Orchestrator that wires everything together
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

**Phase 6 — Durable Approvals and Deeper AI Assistance (in progress).** Batches 1–2 are complete: durable, read-only approval history, and a polished CLI experience for it. Deliberately not yet included, each requiring its own safety review before it is scoped as a batch: resumable approvals (replaying a past pending request after a restart, with its own reclassification and expiry rules), deeper but still-advisory AI assistance (richer summaries and suggestions across memories), and optional smarter search over memory. Every addition continues to go only behind the Security Manager, with the user in control.

---

*Jarvis is a personal project under active development. Phase 5 is a complete, tagged milestone; Phase 6 is in progress. Neither is a finished product.*
