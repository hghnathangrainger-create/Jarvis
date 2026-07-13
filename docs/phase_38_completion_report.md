# Jarvis — Phase 38 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 38 — Quarantine Restore Command (medium: 2 batches, complete)
**Date:** 2026-07-13

---

## Executive Summary

Phase 38 completes the quarantine feature family started in Phase 35: a `restore file <quarantine-file-or-path>` command that moves one previously-quarantined file back to its recorded original location, using the durable metadata Phase 37 added. Restore only ever works for a file with a known `QuarantineRecord`; it never overwrites an existing file, never recreates a missing parent folder, never guesses an original path, and never restores more than one file per request. Batch 1 built the core `FileRestoreTool` and its `SecurityManager` classification in isolation; this closing batch wires it into `CommandRouter`/`main.py` as a real, approval-gated command, adds end-to-end approval-flow tests, and documents it honestly.

## Baseline

```
Branch:                     phase-4-ai-reasoning-and-write-actions
Phase 38 Batch 1 commit:    19569eb
Full suite before Batch 2:  3268 passed, 3 skipped, 0 failed
```

## Scope

Delivered in 2 batches, matching its "medium" classification:

- **Batch 1** (commit `19569eb`): `FileRestoreTool`, dedicated `SecurityManager` "restore file" YELLOW rule, focused unit tests. No command routing or `main.py` registration yet.
- **Batch 2** (this closing batch): `CommandRouter` grammar, `main.py` wiring (sharing the existing `QuarantineStore` instance), end-to-end approval-flow tests, focused routing/wiring tests, documentation, this report.

## User-Visible Command

```
restore file <quarantine-file-or-path>
```

One exact grammar only, deliberately no aliases (`undo delete`, `restore quarantine`, `restore trash`, `recover file`, `untrash file`, `restore all`, `restore files`, `move back file` were all considered and rejected, matching this project's "no looser synonym set" discipline). The required prefix (`"restore file "`, with a trailing space) mirrors `_FILE_DELETE_PREFIXES`'s own deliberately stricter grammar: a bare `restore file` with no path at all does not route at all.

## Restore Behavior

On approval, `FileRestoreTool` resolves the identifier either as a bare filename (resolved directly inside `.jarvis_trash/`, exactly as `list quarantine`/`show quarantine` display it) or as a path that must resolve to a file directly inside the quarantine directory — anything else, including `../` path traversal and absolute paths elsewhere, is rejected before any metadata lookup happens. It then looks up `QuarantineStore.get_by_quarantine_path()`; on a match, it moves the file (`Path.rename()`, never a copy) back to the recorded `original_path`. Verified end-to-end: the restored file exists at its original path with byte-for-byte identical content, and the quarantine directory is left empty afterward — no duplicate is ever left behind.

## Approval Behavior

`restore file <path>` requires YELLOW approval before anything moves — confirmed the request returns `requires_confirmation=True` and the file stays in quarantine until approved. A **declined** approval leaves the file in quarantine and never recreates the original path. A **timed-out** approval (verified with a fake clock, mirroring `delete file`'s own precedent) behaves identically — the file stays in quarantine, the original path is never recreated, and `ApprovalManager.approve()` raises `ApprovalError` for the expired request. There is no path from `handle_request()` to a restored file that bypasses `ApprovalManager` entirely. `action_for()` always returns exactly `"restore file"`, confirmed fixed and never dependent on the supplied path — including when that path is a `../../../etc/passwd`-style traversal attempt — while the approval prompt's displayed `action` text (the raw request sentence) is allowed to vary, matching the same trusted distinction already established for `delete file`/`read webpage`.

## Metadata-Less File Behavior

A file with no matching `QuarantineRecord` — simulated by placing a file directly into `.jarvis_trash/` with no corresponding database row, representing anything quarantined before Phase 37's metadata table existed — fails cleanly after approval with an honest explanation that its original location is unknown. The file is left untouched in quarantine; nothing is guessed from the quarantine filename.

## No-Overwrite and Missing-Parent Behavior

If the recorded `original_path` already exists at restore time (e.g. a new file was created at that path after the original was quarantined), the restore is refused after approval, the existing file at that path is left completely unchanged, and the quarantined file stays exactly where it was — verified end-to-end. If the recorded original parent directory no longer exists, the restore is likewise refused after approval, the folder is never recreated, and the quarantined file again stays untouched.

## Documentation Updates

- **`README.md`**: added a new "Phase 38 — Quarantine Restore Command (complete)" section; updated the Phase 35/36/37 non-goals paragraphs with forward pointers to Phase 38.
- **`docs/user_guide.md`**: added a `restore file <quarantine-file-or-path>` row to the file-command table; added a "File restore notes (Phase 38)" paragraph; corrected the Phase 35 notes' now-outdated claim that "there is still no `restore file` command"; updated §11 and §13 to reflect that restore now exists (for files with known metadata), while empty-trash, cleanup/retention, bulk restore, and dashboard visibility remain explicitly unbuilt.

## Completion Report

This document (`docs/phase_38_completion_report.md`).

## Tests Added

**Batch 1 (25):** 22 `FileRestoreTool` unit tests (successful restore/content-preservation/no-duplicate-left-behind, no-metadata-mutation, missing-input/missing-file/missing-metadata clean failures, path-outside-quarantine and traversal rejection, directory/symlink rejection, no-overwrite and missing-parent refusals, move-failure handling, fixed `action_for()`, metadata-lookup behavior, no-guessing-from-filename, structural AST checks for forbidden calls/imports) + 3 `SecurityManager` tests.

**Batch 2 (34):** 11 `CommandRouter` tests (routing, case-insensitivity, unregistered-tool gating, no collision with `delete file`/`copy file`/`move file`/`list quarantine`/`show quarantine`/`list files`/`read file`, 9 required near-misses, empty-path build_input behavior) + 7 `main.py` wiring tests (registration, correct type, routing, exactly-one-instance, real-`QuarantineStore` backing, shared-store-with-delete-and-list confirmation, unchanged `build_orchestrator()` signature) + 16 end-to-end approval-flow tests (YELLOW-requires-approval, fixed/path-independent classification, approval-prompt wording, approved restore moves file back and empties quarantine, byte-for-byte content preservation, denied/timed-out leave quarantine untouched and never recreate the original path, metadata-less-file clean failure, no-overwrite and missing-parent-directory refusals after approval, no-bypass-around-`ApprovalManager`, fixed `action_for()` independent of the approval prompt's own displayed text, audited decisions).

**Total new tests this phase: 59** (25 Batch 1 + 34 Batch 2).

## Final Verification

```
Focused (Batch 2 files + all quarantine-family tests): 536 passed, 3 skipped
poetry run pytest -q:            3302 passed, 3 skipped, 0 failed
  (3268 baseline before Batch 2 + 34 new)
poetry run ruff check (touched files): All checks passed!
git diff --check:                clean
git status --short:              only "?? dashboard_test.txt"
```

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout both batches.
- **No empty-trash/permanent-delete/cleanup/bulk-restore behavior was added.** `FileRestoreTool` restores exactly one file per request; no production code path calls `os.remove()`, `Path.unlink()`, `shutil.rmtree()`, `os.rmdir()`, or `Path.rmdir()` (AST-verified).
- **No AI/workflow/scheduler/dashboard/Inbox integration was added.** `FileRestoreTool` imports only `pathlib`, `tools.base_tool`, `tools.builtin.file_delete_tool` (for the shared `_QUARANTINE_DIR_NAME` constant), and `quarantine.quarantine_store` (AST-verified).
- **Security tiers unchanged elsewhere:** `restore file` and `delete file` are both YELLOW; `list quarantine`/`show quarantine` remain GREEN. No unrelated classification changed.
- **`FileDeleteTool`, `QuarantineStore`, and `QuarantineListTool` were not modified in this phase** beyond `main.py` and the integration test harness sharing the existing `QuarantineStore` instance with the new tool — no production code in any of those three files changed.

## Remaining Future Work (named, not built)

- **Empty-trash/permanent delete** — still deferred, needing its own careful, separately-reviewed safety design.
- **Cleanup/retention policy** — still deferred, needing explicit policy decisions not yet made.
- **Dashboard visibility into quarantine contents** — only if separately reviewed later.
- **Possible restore refinements** (for example, a way to restore to a different destination, or a bulk restore) — only if separately reviewed later; none of this was scoped or built here.

---

## Status Statement

**Phase 38 complete for its defined scope: `restore file <quarantine-file-or-path>` is now a real, YELLOW, approval-gated command that moves exactly one quarantined file with known metadata back to its recorded original location, never overwriting, never guessing, and never recreating a missing folder.** The quarantine feature family (delete → list → metadata → restore), started in Phase 35, is now architecturally complete for its declared scope; further additions (empty-trash, retention, dashboard visibility, bulk restore) remain explicit, separately-reviewed future decisions.
