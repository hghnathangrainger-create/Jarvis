# Jarvis

A personal AI Operating System — an orchestration layer that coordinates AI, tools, memory, and workflows behind a single, safe interface.

Jarvis is **not** a chatbot. Its guiding principle is simple: **reduce the user's workload while always keeping the user in control.** Every action is checked for safety before it runs, and nothing dangerous happens without explicit approval.

---

## Current Status: Phase 1 (Foundation)

Phase 1 builds the core of Jarvis and a command-line interface to interact with it. This phase is functional and fully tested.

> **Note on API credits:** Phase 1 runs **without any Anthropic API credits**. The Claude provider layer exists in the codebase, but the current CLI does not make live Claude calls — it uses safe, local, read-only tools. You do **not** need to add API credits to run, test, or explore Jarvis right now.

---

## What Works Now

- **Command-line interface** — type requests to Jarvis and see responses in your terminal.
- **Security classification** — every request is checked and labelled GREEN (safe), YELLOW (needs confirmation), or RED (dangerous).
- **Planner** — turns a request into a simple, structured plan you can see.
- **Safe built-in tools** — all read-only:
  - `echo` — repeats text back to you.
  - `info` — shows basic Jarvis system information.
  - `memory` — lists and searches your stored memories.
- **Memory Engine** — saves, lists, and searches memories in a local SQLite database.
- **Observability** — every action is recorded in an append-only audit log.
- **Full test suite** — the whole foundation is covered by automated tests.

---

## What Does NOT Work Yet

These are intentionally left for later phases:

- **Live Claude API responses** — the provider exists but is not used by the CLI yet.
- **Voice input or output.**
- **Phone / mobile control.**
- **Autonomous computer control** — Jarvis cannot click, type, or run programs on your machine.
- **The YELLOW approval flow** — sensitive actions are correctly detected and held, but the confirmation interface is not fully built. For now, a YELLOW action is reported as "needs confirmation" rather than being carried out.

---

## Safety Rules

Safety is enforced by the **Security Manager**, and it cannot be bypassed by the rest of the system.

- **GREEN — safe.** Read-only actions run automatically (for example, searching memories).
- **YELLOW — sensitive.** Actions that change something (for example, sending an email) are held and reported as needing confirmation. They are **not** carried out automatically.
- **RED — dangerous.** Actions such as formatting a drive, disabling antivirus, or stealing passwords are **blocked** and never run.

Every tool call passes through a single security gate before it runs, and every attempt — allowed, held, or blocked — is written to the audit log.

---

## Getting Started

### Requirements

- Python 3.11 or newer
- [Poetry](https://python-poetry.org/) for dependency management

### 1. Install dependencies

```powershell
poetry install
```

### 2. Set up your environment file

Copy the example environment file and fill it in:

```powershell
Copy-Item .env.example .env
```

You can leave the API key blank for now — Phase 1 does not make live Claude calls. The key is only needed in a later phase.

### 3. Run the tests

Confirm everything works before starting:

```powershell
poetry run pytest -v
```

### 4. Start Jarvis

```powershell
poetry run python main.py
```

You should see:

```
Jarvis Online.
```

---

## Example CLI Commands

Once Jarvis is running, type your request after the prompt. **Type only your request — do not type the `you>` prompt text itself.**

```
you> show me system info
jarvis> [OK] Name: Jarvis ...

you> echo hello world
jarvis> [OK] hello world

you> search memories for trading
jarvis> [OK] Memories matching 'trading': ...

you> send email to Alex
jarvis> [NEEDS CONFIRMATION] This request needs your confirmation ...

you> format drive C
jarvis> [BLOCKED] This request is blocked for safety ...
```

To leave, type `exit`, `quit`, or `bye`.

Response labels:

- `[OK]` — the request was handled.
- `[NEEDS CONFIRMATION]` — a sensitive (YELLOW) action was held.
- `[BLOCKED]` — a dangerous (RED) action was refused.
- `[NOT HANDLED]` — Jarvis understood the request but has no capability for it yet.

---

## Project Structure

```
jarvis/
├── config/         Configuration and shared constants
├── storage/        SQLite database and ORM models
├── observability/  Structured event logging
├── security/       Security Manager and append-only audit log
├── memory/         Memory Engine (save, list, search)
├── ai/             Claude provider layer (not used by the CLI yet)
├── planner/        Turns requests into structured plans
├── tools/          Tool registry, executor, and built-in tools
├── core/           Orchestrator that wires everything together
├── ui/             Command-line interface
├── tests/          Automated test suite
└── main.py         Entry point — starts Jarvis
```

---

## Roadmap

Phase 1 is the foundation. Later phases add voice, multi-model AI routing, a web dashboard, autonomous agents, and more — each built only after the previous phase is complete and stable.

---

*Jarvis is a personal project under active development. Phase 1 is a working, safe foundation, not a finished product.*