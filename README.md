# Jarvis

Jarvis is Nathan's modular AI operating system project, designed to reduce workload while keeping Nathan in control.

Jarvis is **not** a chatbot. It is an orchestration layer that plans requests, classifies their safety, runs safe tools, remembers information, and asks for approval before doing anything sensitive — with every action recorded.

---

## Current Status

**Phase 2 complete: Controlled Intelligence & Approval Flow.**

Phase 1 built the foundation. Phase 2 adds a real approval flow: sensitive actions are now held for explicit approval, run only once approved, and every approval decision is recorded permanently. The complete approval lifecycle is covered by end-to-end integration tests.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. The Claude provider layer exists in the codebase, but the current interface uses safe, local tools and does not make live Claude calls. You do not need to add API credits to run or test Jarvis.

---

## Core Design Principle

**Reduce Nathan's workload while keeping Nathan in control.**

Automation should always enhance control, never replace it. Jarvis does the repetitive work, but a human stays in charge of every consequential choice.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at a single gate — the **Tool Executor** — that the rest of the system cannot bypass. Every action is classified into one of three tiers:

- **GREEN — safe.** Read-only actions (searching memories, listing a folder, reading a file) run automatically.
- **YELLOW — sensitive.** Actions that change something (such as sending a message) are held and require explicit approval before they run.
- **RED — dangerous.** Actions such as formatting a drive, disabling antivirus, or stealing passwords are blocked and never run.

Two rules never change:

- **Approval never overrides RED.** An approval can only permit a YELLOW action; it can never unlock a RED one. RED is blocked before an approval is even considered.
- **Every action is logged.** Actions and approval decisions are recorded in an append-only audit log.

The core promise: **automation never comes at the cost of user control.**

---

## Phase 1 — Foundation (complete)

Phase 1 built the core of Jarvis and a command-line interface to use it:

- **Configuration** loaded from a `.env` file, with shared constants including the security tiers.
- **Storage** — a local SQLite database with tables for sessions, memories, and the audit log.
- **Observability** — structured event logging and an append-only audit log.
- **Memory Engine** — save, list, and search memories, with a "do not remember" option.
- **Security Manager** — GREEN / YELLOW / RED classification with a clear reason for each decision.
- **Planner** — turns a request into a simple, structured plan.
- **Tool Manager** — a registry and a safe executor, plus read-only built-in tools (`echo`, `info`, `memory`).
- **Jarvis Core** — the orchestrator that wires the subsystems into one request lifecycle.
- **CLI** — a terminal interface that prints `Jarvis Online.` and takes typed requests.

Phase 1 is tagged `phase-1-foundation`.

---

## Phase 2 — Controlled Intelligence & Approval Flow (complete)

Phase 2 gives Jarvis the ability to do more than read-only work, while keeping the user in control of every sensitive decision.

### The approval flow

When Jarvis meets a sensitive (YELLOW) action, it no longer simply stops — it now runs a real approval flow:

- **GREEN actions run automatically.** No approval is needed for safe, read-only work.
- **YELLOW actions create an approval request.** The action is described and held. It does **not** run yet.
- **Approved YELLOW actions may execute.** Once the user approves, the action runs through the Tool Executor's security gate.
- **Declined YELLOW actions are cancelled.** A declined action never runs.
- **RED actions are always blocked** — even if an approval decision is supplied.

### New in Phase 2

- **Approval models** — `ApprovalRequest`, `ApprovalDecision`, and `ApprovalStatus` describe every approval.
- **Approval Manager** — creates requests, records approve/decline decisions, and keeps a history. It cannot decide the same request twice.
- **CLI approval prompt** — displays a request clearly and reads the user's yes/no answer.
- **Core approval integration** — the orchestrator creates an approval request whenever it meets a YELLOW action.
- **Tool Executor approved-YELLOW path** — an explicitly approved YELLOW action is allowed to run through the gate; RED can never be unlocked this way.
- **Read-only file tools:**
  - **`file_list`** — lists the files and folders in a directory. It does not read file contents or recurse into subfolders.
  - **`file_read`** — reads the contents of a single text file, up to a character limit, refusing binary files and marking truncated output clearly.
  - Both are read-only, classify as GREEN, and never modify anything.
- **Approval audit logging** — every approve and decline is recorded in the audit log, capturing the request id, action, outcome, who decided, and the reason.
- **End-to-end approval tests** — integration tests trace the complete lifecycle: request → decision → execution or cancellation.

Phase 2 lives on the branch `phase-2-approval-flow`.

---

## How to Run

Install dependencies and start Jarvis:

```powershell
poetry install
poetry run python main.py
```

On startup Jarvis prints:

```
Jarvis Online.
```

You can then type requests. Type `exit`, `quit`, or `bye` to leave.

---

## How to Test

Run the full test suite:

```powershell
poetry run pytest -v
```

Run just the end-to-end approval lifecycle tests:

```powershell
poetry run pytest tests/integration/test_approval_end_to_end.py -v
```

Watch the whole approval flow against the real database (approve, decline, and a blocked RED action):

```powershell
poetry run python approval_end_to_end_smoke_test.py
```

---

## Project Structure

```
jarvis/
├── config/         Configuration and shared constants (including the security tiers)
├── storage/        SQLite database and ORM models
├── observability/  Structured event logging
├── security/       Security Manager and append-only audit log
├── memory/         Memory Engine (save, list, search)
├── ai/             Claude provider layer (not used by the interface yet)
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and safe built-in tools
│   └── builtin/    echo, info, memory, file_list, file_read
├── approval/       Approval models and the Approval Manager
├── core/           Orchestrator that wires everything together
├── ui/             Command-line interface and approval prompts
├── tests/          Unit tests and integration tests
│   ├── unit/       One test file per module
│   └── integration/ Full approval-lifecycle tests
├── docs/           Specifications, implementation plans, and reports
└── main.py         Entry point — starts Jarvis
```

---

## What Jarvis Is Not Yet

Jarvis is a foundation under active development. It is deliberately **not** yet:

- **Fully autonomous** — it does not act on its own initiative.
- **Connected to live AI decision-making** — the Claude provider exists but is not used to drive decisions yet.
- **Controlling the computer** — it cannot click, type, or run programs on the machine.
- **Installing software** — it performs no installations.
- **Connected to a phone** — there is no mobile control.

These limitations are intentional. Each is a candidate for a future phase, added only behind the existing safety model.

---

## Next Phase

**Phase 3 — planning.**

With controlled intelligence and a working approval flow in place, Phase 3 will focus on expanding what Jarvis can safely do while preserving the same control guarantees — likely connecting live AI reasoning (once API credits are available), completing the approval flow inside the interactive interface, and carefully broadening the toolset, always behind the Security Manager. Detailed goals will be captured in a dedicated Phase 3 implementation plan.

---

*Jarvis is a personal project under active development. Phase 2 is a working, safe milestone, not a finished product.*
