# Jarvis

Jarvis is Nathan's modular AI operating system project, designed to reduce workload while keeping Nathan in control.

Jarvis is **not** a chatbot. It is an orchestration layer that plans requests, classifies their safety, runs safe tools, remembers information, asks for approval before doing anything sensitive, and can optionally use AI to help interpret requests — with every action recorded.

---

## Current Status

**Phase 4 in progress: Live AI Reasoning and Guarded Write Actions.**

Building on the live approval flow from Phase 3, Jarvis can now optionally use AI to help interpret a request (advisory only), and can perform its first guarded write actions — creating and appending to text files — always behind approval.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. AI reasoning is off by default and, when off, Jarvis behaves exactly as it did in Phase 3. Every test uses a fake provider, so no live Claude call is ever required to run or test Jarvis.

---

## Core Design Principle

**Reduce Nathan's workload while keeping Nathan in control.**

Automation should always enhance control, never replace it. Jarvis does the repetitive work, but a human stays in charge of every consequential choice — and the AI advises, it never decides.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at a single gate — the **Tool Executor** — that the rest of the system cannot bypass. Every action is classified into one of three tiers:

- **GREEN — safe.** Read-only actions (searching memories, listing a folder, reading a file) run automatically.
- **YELLOW — sensitive.** Actions that change something — including all write actions — are held and require explicit approval before they run.
- **RED — dangerous.** Actions such as formatting a drive, disabling antivirus, or stealing passwords are blocked and never run.

Rules that never change:

- **Approval never overrides RED.** An approval can only permit a YELLOW action; it can never unlock a RED one.
- **The AI never executes anything.** AI reasoning may suggest and summarise, but every real action still passes through the Security Manager, Tool Executor, and Approval Manager.
- **Every action is logged**, including every approval decision, in the append-only audit log.

The core promise: **automation never comes at the cost of user control.**

---

## Phases 1–3 (complete)

- **Phase 1 — Foundation** (`phase-1-foundation`): configuration, SQLite storage, audit logging, memory, the Security Manager, the Planner, the Tool Registry and Executor, and a CLI.
- **Phase 2 — Controlled Intelligence & Approval Flow** (`phase-2-approval-flow`): approval models, the Approval Manager, the CLI approval prompt, approval audit logging, and the read-only `file_list` and `file_read` tools.
- **Phase 3 — Live CLI Approval Execution and Practical Workflow Tools** (`phase-3-live-cli`): the approval flow made usable in the live CLI, approved actions executing, clear output labels, and read-only workflow commands.

---

## Phase 4 — Live AI Reasoning and Guarded Write Actions

### Batch 1 — Advisory AI reasoning

Jarvis can optionally use AI to help interpret a request. This is **advisory only**:

- AI reasoning is controlled by a configuration flag, `AI_REASONING_ENABLED`, which is **false by default**.
- When off, Jarvis is entirely rule-based and needs no API key or credits.
- When on, the AI adds a short, clearly-labelled suggestion to the response.
- The AI can **suggest, summarise, and plan — but never execute.** It holds no ability to run a tool, approve an action, or change a classification. Every real decision stays with the Security Manager, Tool Executor, and Approval Manager.

### Batch 2 — Guarded write tools

Jarvis can now make its first changes to files, safely:

- **`file_create`** — creates a **new** text file. It never overwrites an existing file, and it does not create folders.
- **`file_append`** — appends text to an **existing** text file. It never creates a new file, refuses folders, and refuses binary files.

Both are **YELLOW**: they always require approval before running, flow through the same approval and audit path as every other sensitive action, and do nothing if declined.

### What is deliberately NOT included

Jarvis still cannot, by design: **delete, move, rename, or edit-in-place** files; **install software**; **control the computer**; connect to a **phone**; use **voice**; or act **autonomously**. Each remains a candidate for a future phase, added only behind the safety model.

---

## Example Commands

Read-only (GREEN — run automatically):

```
list files in .
read file README.md
show project files
```

Write actions (YELLOW — ask for approval first):

```
create file notes.txt with Hello Jarvis
append a new line to file notes.txt
```

Always blocked (RED):

```
format drive C
```

When AI reasoning is enabled, responses may also show an advisory line, for example:

```
jarvis> [NEEDS APPROVAL] This action requires your confirmation.
        [AI suggestion - advisory only] You want to create a notes file. Suggested steps: create it
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

# All integration tests (approval flow, live CLI, and write journeys)
poetry run pytest tests/integration/ -v

# The write approval journey through the live CLI
poetry run pytest tests/integration/test_cli_write_end_to_end.py -v
```

---

## Project Structure

```
jarvis/
├── config/         Configuration and shared constants (security tiers, AI flag)
├── storage/        SQLite database and ORM models
├── observability/  Structured event logging
├── security/       Security Manager and append-only audit log
├── memory/         Memory Engine (save, list, search)
├── ai/             Provider interface, Claude provider, and advisory reasoning
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and built-in tools
│   └── builtin/    echo, info, memory, file_list, file_read (GREEN);
│                   file_create, file_append (YELLOW, approval-gated)
├── approval/       Approval models and the Approval Manager
├── core/           Orchestrator that wires everything together
├── ui/             Command-line interface and approval prompts
├── tests/          Unit and integration tests
├── docs/           Specifications, implementation plans, and reports
└── main.py         Entry point — starts Jarvis
```

---

## Next Phase

**Phase 5 — planning.** With advisory AI and the first guarded writes in place, likely next steps are carefully broadening guarded actions (such as editing within a file) behind approval, adding durable storage for pending approvals, and deepening AI assistance while keeping it strictly advisory. Each will be added only behind the Security Manager, and always with the user in control.

---

*Jarvis is a personal project under active development. Phase 4 is a working, safe milestone, not a finished product.*