# Jarvis Phase 5 Implementation Plan

**Version:** 1.0
**Phase name:** Better Memory and Personal Knowledge System
**Builds on:** `phase-4-ai-reasoning-and-write-actions`
**Date:** _______________

---

## 1. Purpose of Phase 5

Through Phase 4, Jarvis gained advisory AI reasoning and its first guarded write actions, while keeping every dangerous capability firmly behind the Security Manager. Its memory, however, is still basic: it can save a memory, list recent memories, and do a simple text search. There is no way to organise memories, review them carefully, correct a mistaken one, or safely forget something.

Phase 5 turns Jarvis's memory into a genuine personal knowledge system. It adds categories so memories can be organised, better search and review so they can be found, and safe, approval-gated ways to update or forget a memory so the store stays accurate over time. As always, reading stays effortless and anything that changes or removes a memory asks first.

> **Central design rule:** Reading, listing, and searching memory are GREEN and run automatically. Updating or forgetting an important memory is YELLOW and requires approval. The AI may summarise and suggest, but never stores, changes, or forgets a memory on its own.

Phase 5 builds directly on the `phase-4-ai-reasoning-and-write-actions` checkpoint. Everything from Phases 1–4 is preserved; Phase 5 deepens memory behind the same safety model.

---

## 2. Scope

Phase 5 delivers the following, in priority order:

1. **Memory categories** — add an optional category to each memory (for example: personal, project, preference, note) so memories can be organised and filtered.
2. **Richer memory model** — extend the memory record and store to support categories, filtering, and counting by category, without breaking existing records.
3. **Better search & review** — improve search (by text and by category) and add a clear way to review memories before acting on them.
4. **Memory CLI commands** — friendly read-only commands: remember (save), show memories, search memories, show memories in a category.
5. **Approval-gated update** — a guarded way to correct or update an existing memory. This changes state, so it is YELLOW and requires approval.
6. **Approval-gated forgetting** — a guarded way to forget (delete) a specific memory. This removes data, so it is YELLOW and requires approval; declined forgets do nothing.
7. **AI memory assistance** — let the AI summarise or suggest what might be worth remembering — advisory only, never storing or forgetting on its own.

---

## 3. What Is NOT Included in Phase 5

To keep Phase 5 safe and focused, the following are firmly excluded:

- Deleting or forgetting memory without approval. Every forget is YELLOW and must be confirmed.
- Bulk-wiping all memory. Only specific, identified memories can be forgotten, one at a time, each with approval.
- The AI storing, changing, or forgetting memories on its own. AI assistance is advisory only.
- Silent storage of sensitive information. The existing "do not remember" rule is respected and strengthened; nothing sensitive is stored without clear rules.
- Any dangerous OS power, autonomous behaviour, install, delete-file, move, rename, phone, or voice capability. None of these are added in Phase 5.

> **The hard line:** Phase 5 improves how memory is organised, searched, updated, and forgotten — all behind approval for anything that changes or removes data. It adds no OS powers and no autonomy.

---

## 4. Safety Rules

The safety model from Phases 1–4 is preserved in full and applied to memory:

- **GREEN — may run automatically.** Reading, listing, searching, and reviewing memory. These never change or remove anything.
- **YELLOW — must ask the user first.** Updating an existing memory, or forgetting (deleting) a memory. Approved YELLOW may execute; declined YELLOW must not. Nothing is changed or removed without approval.
- **RED — must always stay blocked.** Dangerous actions remain refused and never run, and no approval can unlock them.

Rules specific to Phase 5:

- Read/search/list/review memory is GREEN.
- Update and forget memory is YELLOW and requires approval; a declined action makes no change.
- The AI may summarise or suggest memory, but must not store, change, or forget it, and must not bypass the memory rules.
- The "do not remember" rule is respected; sensitive information is not stored silently.
- Every memory change and every memory forget is recorded in the audit log.

---

## 5. Proposed Batches

Phase 5 is delivered in four controlled batches. Each is planned, reviewed, and tested before the next begins.

| Batch | Focus | What it delivers |
|---|---|---|
| Batch 1 | Memory model & categories | Extend the memory record and store with an optional category; filtering and counting by category; migration-safe defaults. Unit tests. |
| Batch 2 | Memory commands & CLI | Read-only memory commands (remember, show, search, show by category) routed through the Core and shown clearly in the live CLI. Routing and CLI tests. |
| Batch 3 | Review, update & forgetting | Approval-gated update and forget tools (YELLOW), review-before-acting, full audit. Unit, routing, and end-to-end approval tests. |
| Batch 4 | Docs, tests & tag | README update, Phase 5 completion report, full-suite verification, and the phase-5 checkpoint tag. |

Batches 1–2 are read-and-organise (safe, GREEN). Batch 3 introduces the only state-changing memory actions, all YELLOW and approval-gated. Batch 4 is wrap-up only.

---

## 6. Recommended File / Module Structure

Phase 5 extends the existing memory package and adds guarded memory tools, reusing the current architecture.

```
memory/
  episodic_memory.py     (extended: category field, filter/count by category)
  memory_manager.py      (extended: category-aware save/list/search/update/forget)
  memory_models.py       (new: category constants / small value types)
tools/builtin/
  memory_tool.py         (existing read-only list/search - stays GREEN)
  memory_update_tool.py  (new: update a memory - YELLOW)
  memory_forget_tool.py  (new: forget a memory - YELLOW)
core/orchestrator.py     (extended: route memory commands)
ui/cli.py                (only if a small display change is needed)
tests/unit/              (memory model, tools, routing)
tests/integration/       (memory approval end-to-end)
```

The read-only MemoryTool remains GREEN and largely unchanged. The two new tools (update, forget) are YELLOW and inherit the approval gate exactly as the write tools did in Phase 4 — by returning an action string the Security Manager classifies YELLOW. The Security Manager and Tool Executor are not expected to need changes.

---

## 7. Testing Strategy

Testing remains part of building, not a final step.

**Unit tests** — for the extended memory model and store (categories, filtering, counting), and for each new tool in isolation (update, forget), including their YELLOW classification and every refusal path (missing id, unknown memory, empty input).

**Routing tests** — that memory commands map to the right tool with the right input, that read/search/list stay GREEN, and that update/forget come back YELLOW (requiring approval) rather than running immediately.

**Integration / end-to-end tests** — through the real executor and Approval Manager: an approved update actually changes a memory; a declined update leaves it unchanged; an approved forget removes a specific memory; a declined forget keeps it; and every change and forget is audited.

**Regression tests** — all Phase 1–4 tests must continue to pass unchanged. With AI reasoning off, behaviour is exactly as before.

No test makes a live Claude API call. AI memory assistance is tested with a fake provider, as in Phase 4.

---

## 8. Definition of Done

Phase 5 is complete when all of the following are true:

- Memories can carry an optional category, and existing memories still load correctly.
- Memory can be listed, searched, and filtered by category, all GREEN and automatic.
- Friendly memory commands work in the live CLI and are shown clearly.
- Updating a memory is YELLOW and requires approval; a declined update changes nothing.
- Forgetting a memory is YELLOW and requires approval; a declined forget removes nothing.
- Only specific, identified memories can be forgotten — there is no bulk wipe.
- The AI may summarise or suggest memory but never stores, changes, or forgets it.
- Every memory change and forget is recorded in the audit log.
- No dangerous OS power, autonomy, delete-file, install, phone, or voice capability was added.
- The full suite passes (all Phase 1–5 tests); README and completion report are written.

---

## 9. Risks & Known Limitations

These are understood going in, and shape the careful scope of Phase 5:

- **Forgetting removes data.** The mitigation is strict: only a specific, identified memory can be forgotten, it is YELLOW and requires approval, a declined forget does nothing, and every forget is audited. There is no bulk wipe.
- **Categories can be misapplied.** Categories are optional and advisory; a wrong category never affects safety, only organisation, and can be corrected via the approval-gated update.
- **Sensitive information.** The existing "do not remember" rule is respected and strengthened; the AI never silently stores anything.
- **Search remains simple.** Phase 5 improves search but keeps it text- and category-based; semantic or AI-driven search is deferred and would remain advisory.
- **Pending approvals remain in memory.** Durable approval storage is still deferred.

---

## 10. Recommended Next Phase

**Phase 6 — Durable Approvals and Deeper AI Assistance (proposed).**

Once memory is a safe, organised personal knowledge system, the natural next steps are:

- Durable storage for pending approvals, so an approval (including a memory update or forget) can outlive a single session.
- Deeper, still-advisory AI assistance — richer summaries across memories and better suggestions — with the gate always final.
- Optional smarter search over memory, kept advisory and never able to change or remove memories on its own.

The through-line: every phase adds capability only behind the Security Manager, and never lets automation — or AI — run ahead of the user's control.

---

## Summary

Phase 5 — Better Memory and Personal Knowledge System — turns Jarvis's basic memory into an organised, searchable personal knowledge store. Categories bring order, better search and review make memories findable, and safe, approval-gated update and forget keep the store accurate over time. Reading stays effortless; anything that changes or removes a memory asks first; and the AI helps only by advising.

Dangerous actions stay blocked, no OS powers or autonomy are added, Jarvis still runs without credits, and the whole phase builds cleanly on the stable phase-4 checkpoint — delivered in four controlled batches.

**The goal of Phase 5:** give Nathan a memory he can trust and manage — organised, searchable, correctable, and forgettable — without ever losing control of what Jarvis remembers.
