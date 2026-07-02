# Jarvis

Jarvis is Nathan's modular AI operating system project, designed to reduce workload while keeping Nathan in control.

Jarvis is **not** a chatbot. It is an orchestration layer that plans requests, classifies their safety, runs safe tools, remembers information, and asks for approval before doing anything sensitive — with every action recorded.

---

## Current Status

**Phase 3 complete: Live CLI Approval Execution and Practical Workflow Tools.**

The approval flow built in Phase 2 is now fully usable in everyday interaction. You can type a request, see a clear approval prompt for anything sensitive, and approve or decline it on the spot — approved actions run, declined actions are cancelled. Jarvis can also browse and read your project files with safe, read-only commands. The whole live experience is covered by end-to-end tests.

> **Note on API credits:** Jarvis still runs **without any Anthropic API credits**. The Claude provider layer exists in the codebase, but the current interface uses safe, local tools and does not make live Claude calls. You do not need to add API credits to run or test Jarvis.

---

## Core Design Principle

**Reduce Nathan's workload while keeping Nathan in control.**

Automation should always enhance control, never replace it. Jarvis does the repetitive work, but a human stays in charge of every consequential choice.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at a single gate — the **Tool Executor** — that the rest of the system cannot bypass. Every action is classified into one of three tiers:

- **GREEN — safe.** Read-only actions (searching memories, listing a folder, reading a file) run automatically.
- **YELLOW — sensitive.** Actions that change something are held and require explicit approval before they run.
- **RED — dangerous.** Actions such as formatting a drive, disabling antivirus, or stealing passwords are blocked and never run.

Two rules never change:

- **Approval never overrides RED.** An approval can only permit a YELLOW action; it can never unlock a RED one.
- **Every action is logged**, including every approval decision, in the append-only audit log.

The core promise: **automation never comes at the cost of user control.**

---

## Phase 1 — Foundation (complete)

Phase 1 built the core of Jarvis and a command-line interface to use it: configuration, a local SQLite database, structured event logging and an append-only audit log, a Memory Engine, the Security Manager, a Planner, a Tool Manager with safe read-only built-in tools (`echo`, `info`, `memory`), the Core orchestrator, and the CLI. Tagged `phase-1-foundation`.

---

## Phase 2 — Controlled Intelligence & Approval Flow (complete)

Phase 2 added a real approval flow: approval models, an Approval Manager, a CLI approval prompt, Core integration that creates an approval request for YELLOW actions, a Tool Executor path that runs an approved YELLOW action through the security gate, two read-only file tools (`file_list` and `file_read`), approval audit logging, and end-to-end tests of the whole lifecycle. Tagged `phase-2-approval-flow`.

---

## Phase 3 — Live CLI Approval Execution and Practical Workflow Tools (complete)

Phase 3 makes the approval flow usable in real, everyday interaction, and adds safe read-only file commands.

### The live approval flow

When you type a request into the live CLI:

- **GREEN actions run automatically** — no prompt, just the result.
- **YELLOW actions show an approval prompt** with the request's action, reason, and risk tier.
- **Approved YELLOW actions execute** through the Tool Executor.
- **Declined YELLOW actions are cancelled** — nothing runs.
- **RED actions are blocked** — refused with no prompt.

### Read-only file commands

Jarvis can list folders and read text files directly from the CLI. Natural commands:

```
list files in .
list files in docs
read file README.md
```

Plus friendly workflow shortcuts:

```
show project files
show docs
read readme
show phase 3 plan
```

**All file tools are strictly read-only.** They do not write, delete, move, rename, or edit anything. Reading is bounded (large files are truncated, binary files are refused), and listing does not descend into subfolders.

### Clearer CLI output

Every response is labelled so its outcome is obvious at a glance:

- `[OK]` — a safe action ran successfully.
- `[NEEDS APPROVAL]` — a sensitive action is waiting for your decision.
- `[BLOCKED]` — a dangerous action was refused.
- `[FAILED]` — a tool ran but could not complete (for example, a missing file).
- `[NOT HANDLED]` — Jarvis has no capability for this request yet.

### Tested end to end

The complete live experience is covered by end-to-end tests that drive the real CLI with scripted input: GREEN runs, YELLOW approve-and-run, YELLOW decline-and-cancel, RED blocked, and clean exit — all without a real terminal and without any Claude API calls.

Phase 3 lives on the branch `phase-3-live-cli`.

---

## How to Run

Install dependencies and start Jarvis:

```powershell
poetry install
poetry run python main.py
```

On startup Jarvis prints `Jarvis Online.` You can then type requests. Type `exit`, `quit`, or `bye` to leave.

Try these in a live session:

```
show project files
read readme
send email to Alex      (sensitive - you'll be asked to approve)
format drive C          (dangerous - always blocked)
```

---

## How to Test

```powershell
# The full test suite
poetry run pytest -v

# All integration tests (approval flow + live CLI journeys)
poetry run pytest tests/integration/ -v

# Just the live CLI end-to-end tests
poetry run pytest tests/integration/test_cli_end_to_end.py -v
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
│   └── integration/ Approval-flow and live-CLI end-to-end tests
├── docs/           Specifications, implementation plans, and reports
└── main.py         Entry point — starts Jarvis
```

---

## What Jarvis Is Not Yet

Jarvis is a foundation under active development. It is deliberately **not** yet:

- **Fully autonomous** — it acts only in response to the user.
- **Connected to live AI decision-making** — the Claude provider exists but is not used to drive decisions yet.
- **Controlling the computer** — it cannot click, type, or run programs on the machine.
- **Writing, deleting, or changing files** — all file access is read-only.
- **Connected to a phone** — there is no mobile control.

These limitations are intentional. Each is a candidate for a future phase, added only behind the existing safety model.

---

## Next Phase

**Phase 4 — planning.** With a usable live approval flow and safe read-only tools in place, the natural next steps are connecting live AI reasoning (once API credits are available, as a deliberate step) and introducing the first guarded write actions behind a stronger approval design — always behind the Security Manager, and always with the user in control. Detailed goals will be captured in a dedicated Phase 4 implementation plan.

---

*Jarvis is a personal project under active development. Phase 3 is a working, safe milestone, not a finished product.*
