# Jarvis — Phase 2 Implementation Plan

**Version:** Phase 2 (Controlled Intelligence & Approval Flow)
**Builds on:** `phase-1-foundation`
**Date:** _______________

---

## Purpose

Phase 1 built the foundation of Jarvis: it can plan a request, classify its safety, run safe read-only tools, remember information, and record everything it does. But one important thing is missing. When Jarvis detects a **sensitive (YELLOW)** action, it currently stops and says "this needs confirmation" — and then nothing more happens. There is no way for the user to actually approve the action and have it carried out.

Phase 2 fixes this. Its purpose is to give Jarvis **controlled intelligence**: the ability to do more than read-only work, while keeping the user firmly in control of every sensitive decision. The centrepiece is the **YELLOW approval flow** — a safe, clear process where Jarvis asks, the user approves or declines, and only then does the action run.

This phase builds directly on the `phase-1-foundation` checkpoint. Nothing from Phase 1 is thrown away; Phase 2 extends it.

---

## Phase 2 Scope

Phase 2 delivers the following, in priority order:

1. **The YELLOW approval flow.** When an action is sensitive, Jarvis pauses, clearly explains what it wants to do and why, and asks the user to approve or decline. Only an approved action is carried out. A declined action is safely cancelled.

2. **Improved safe tool execution.** Strengthen the tool executor so approved actions run cleanly, with better error handling and clearer results.

3. **Safe file tools.** Add two new tools:
   - **file listing** — show the files in a folder (read-only).
   - **file reading** — show the contents of a file (read-only).
   Both are read-only and safe. Writing, moving, and deleting files remain out of scope for this phase.

4. **Approval-aware audit logging.** Record every approval decision — approved or declined — in the audit log, so there is a complete history of what the user allowed.

5. **Preparation for live Claude.** Keep the Claude provider ready to connect, so that when API credits are added, enabling live responses is a small, well-defined step rather than a large change.

---

## What Is NOT Included in Phase 2

To keep Phase 2 focused and safe, the following are intentionally excluded:

- **Live Claude API responses by default.** The provider will be prepared, but live calls are only enabled once API credits are available, and even then as a deliberate, separate step.
- **File writing, moving, or deleting.** Only read-only file tools are added in this phase.
- **Any RED action becoming allowed.** Dangerous actions stay blocked, always.
- **Voice input or output.**
- **Phone or mobile control.**
- **Autonomous computer control** — Jarvis still does not click, type, or run programs on its own.
- **Multi-provider AI routing, vector memory, and the web dashboard.** These are valuable but belong to later phases.

---

## Development Principles

Phase 2 follows the same principles that made Phase 1 stable:

1. **Build one feature at a time.** Finish and test each piece before starting the next.
2. **The user is always in control.** No sensitive action happens without explicit approval.
3. **Never bypass the Security Manager.** Every action, new or old, passes through the same security gate.
4. **Read-only before read-write.** Add safe read-only capabilities first; do not add destructive ones in this phase.
5. **Keep it modular.** New tools and the approval flow must plug into the existing structure without rewriting it.
6. **Test as you build.** A feature is not done until its tests pass.
7. **RED stays blocked.** No change in this phase weakens the block on dangerous actions.

---

## Technical Plan

Phase 2 extends existing subsystems rather than replacing them.

**Approval flow.** A new approval component will sit between the Core and the execution of a YELLOW action. When a plan or tool action is classified YELLOW, the Core will request approval, present the details to the user through the CLI, wait for a clear yes or no, and then either run the action through the existing security gate or cancel it. The design will allow a future graphical or voice interface to reuse the same approval logic.

**Tool executor improvements.** The executor already blocks RED and holds YELLOW. Phase 2 adds the "approved YELLOW" path: an action that has been explicitly approved may proceed, still passing through the security gate, with the approval recorded. Error handling around tool execution will be strengthened so that a failing tool always returns a clear result rather than an unexpected error.

**Safe file tools.** Two new read-only tools — file listing and file reading — will be added to the tool registry, each declaring a safe, read-only action so the Security Manager classifies them GREEN. They will include sensible limits (for example, refusing to read extremely large files) and will never modify anything.

**Audit logging.** The audit log will gain approval events, so each approved or declined YELLOW action is permanently recorded alongside the existing action events.

**Claude readiness.** No live calls are enabled by default. The provider will be kept in a ready state so that connecting it later is a small, controlled change.

---

## Module Order

Build in this order. Each step depends on the previous one being complete and tested.

1. **Approval data models** — define what an approval request and an approval decision look like.
2. **Approval component** — the logic that requests approval and records the decision.
3. **CLI approval prompts** — the terminal interface that shows the request and reads the user's yes or no.
4. **Core integration** — connect the approval flow into the request lifecycle for YELLOW actions.
5. **Tool executor "approved YELLOW" path** — allow an approved action to run through the gate.
6. **Safe file listing tool** — read-only listing of a folder.
7. **Safe file reading tool** — read-only reading of a file.
8. **Approval audit logging** — record every approval decision.
9. **End-to-end testing** — confirm the full approve-and-run and decline-and-cancel journeys.

---

## Safety Rules

The Phase 1 safety model is preserved in full and extended:

- **GREEN (safe)** actions run automatically, as before.
- **YELLOW (sensitive)** actions now follow the approval flow: Jarvis explains, the user decides, and only an approved action runs. A declined action is cancelled and recorded.
- **RED (dangerous)** actions remain **blocked** and never run, with no exception introduced in this phase.
- **Every action still passes through the single security gate.** The approval flow does not create a way around it; an approved action is still executed through the same gate.
- **Every approval decision is logged.** Approved and declined actions are both recorded in the append-only audit log.

The core promise is unchanged: **automation never comes at the cost of user control.**

---

## Testing Strategy

Testing remains part of building, not a final step.

- **Unit tests** for the approval data models, the approval component, and each new file tool.
- **Integration tests** for the full lifecycle: a YELLOW request that is approved and then runs, and a YELLOW request that is declined and is cancelled.
- **Safety tests** confirming that:
  - a RED action is still blocked and can never be approved,
  - a YELLOW action never runs without an explicit approval,
  - the file tools never modify anything.
- **Regression tests** — the entire Phase 1 test suite must continue to pass unchanged.

A Phase 2 feature is only complete when its own tests pass **and** no Phase 1 test has broken.

---

## Definition of Done

Phase 2 is complete when all of the following are true:

- The YELLOW approval flow works end to end: approve-and-run and decline-and-cancel both behave correctly.
- The two safe file tools (listing and reading) work and are read-only.
- Every approval decision is recorded in the audit log.
- Dangerous RED actions remain blocked.
- The Claude provider is ready to connect, but no live call runs without API credits and a deliberate switch.
- The full test suite passes, including all Phase 1 tests.
- The code is clean, documented, and formatted to the project's standards.
- The README and documentation are updated to reflect the new capabilities.
- A Phase 2 completion report is written.

---

## Recommended Git Branch and Tag Strategy

Phase 2 begins from the `phase-1-foundation` tag, so the stable foundation is always recoverable.

**Branching**

- Create a phase branch from the tag:
  ```
  git checkout -b phase-2-approval-flow phase-1-foundation
  ```
- Develop each module on its own short-lived feature branch, merged into the phase branch when complete and tested. For example:
  ```
  git checkout -b feature/approval-flow phase-2-approval-flow
  ```
- Never develop directly on `main`.

**Committing**

- Use clear, conventional commit messages, for example:
  - `feat(approval): add approval request and decision models`
  - `feat(tools): add read-only file listing tool`
  - `test(approval): add decline-and-cancel integration test`

**Tagging**

- When Phase 2 is complete, tested, and documented, merge the phase branch and create a new checkpoint tag:
  ```
  git tag phase-2-approval-flow
  ```
- This preserves a clean, recoverable milestone, just as `phase-1-foundation` does for Phase 1.

---

## Summary

Phase 2 — **Controlled Intelligence & Approval Flow** — gives Jarvis the ability to do more, safely. By building the YELLOW approval flow, strengthening safe tool execution, and adding read-only file tools, Jarvis moves beyond read-only assistance while keeping the user in control of every sensitive decision. Dangerous actions stay blocked, live AI remains a deliberate future switch, and the whole phase builds cleanly on the stable `phase-1-foundation` checkpoint.
