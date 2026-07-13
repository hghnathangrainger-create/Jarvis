# Jarvis — Phase 37 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 37 — Quarantine Restore Metadata Foundation (medium: 2 batches, complete)
**Date:** 2026-07-13

---

## Executive Summary

Phase 37 closes the specific gap the Post-Phase-36 review identified: no durable record anywhere connected a quarantined file's random-suffixed name back to its original directory, which meant a restore command could not be designed safely. Phase 37 adds exactly that missing metadata — nothing more. Batch 1 added a durable `quarantine_records` table and `QuarantineStore`, and taught `FileDeleteTool` to record `(original_path, quarantine_path, quarantined_at, session_id)` for every newly quarantined file. Batch 2 extended `QuarantineListTool` to display that recorded original path when known, with an honest fallback for files quarantined before this table existed. **Phase 37 does not build restore, empty-trash, permanent delete, or any cleanup/retention policy** — it only makes a future restore command safer to design later.

## Baseline

```
Branch:                     phase-4-ai-reasoning-and-write-actions
Phase 36 final commit:      d591b84
Full suite before Phase 37: 3207 passed, 1 skipped, 0 failed
```

## Scope

Delivered in 2 batches, matching its "medium" classification:

- **Batch 1** (commit `b62c536`): `QuarantineRecord` model, `QuarantineStore`, `FileDeleteTool` metadata recording, `main.py` wiring, focused tests.
- **Batch 2** (this closing batch): `QuarantineListTool` original-path display, shared `QuarantineStore` wiring for both quarantine tools, backward-compatibility tests, documentation, this report.

## Metadata Table/Store Behavior

`storage/models.py` defines `QuarantineRecord` (table `quarantine_records`): `id`, `original_path`, `quarantine_path` (unique, indexed), `quarantined_at`, `session_id` (plain `Integer`, not a `ForeignKey`, matching `InboxEntry`/`ApprovalHistoryEntry`/`WorkflowHistoryEntry`'s own established convention). Deliberately excludes `restore_status`, `restored_at`, cleanup/retention fields, and dashboard fields — none is needed until a future, separately-scoped restore phase exists.

`quarantine/quarantine_store.py` defines `QuarantineStore` with exactly two public methods: `record_quarantine()` (write-once) and `get_by_quarantine_path()` (read). Confirmed structurally, by a test enumerating the class's public methods, that no `update`/`delete`/`remove`/`restore`/`cleanup`/`empty`/`purge` method exists anywhere on the class — a missing quarantine metadata record (for anything quarantined before this table existed) always returns `None`, never an error.

## FileDeleteTool Metadata Behavior

`FileDeleteTool` takes an optional `store: QuarantineStore | None = None` constructor argument — every pre-Phase-37 caller/test continues unchanged. On a successful quarantine, if a store was supplied, it records `original_path`/`quarantine_path` as resolved absolute paths (never the raw, possibly-relative user input), plus `session_id` from the request. Metadata is written only after a successful move; every rejection path (missing input, nonexistent source, directory, symlink, already-quarantined, move failure) writes nothing — confirmed by dedicated tests for each case.

**Consistency on partial failure:** if the move succeeds but metadata recording fails, `success=True` is preserved (the file really was quarantined — that is never hidden or contradicted), the output text gets an explicit `WARNING:` block naming the failure, and `metadata["metadata_recorded"] = "False"` is set — never a silent, ordinary-looking success.

## QuarantineListTool Metadata Display Behavior

`QuarantineListTool` also takes an optional `store: QuarantineStore | None = None` constructor argument. For each listed file, it calls only `store.get_by_quarantine_path()` (a read) — never a write method — using the file's resolved absolute path, matching the resolved form `FileDeleteTool` records in. Each listed line now ends with `, original path: <path>` when a record exists, or `, original path: unknown (quarantined before metadata tracking)` when no store was supplied or no record exists for that file. The tool never infers an original path from the quarantine filename itself (confirmed by a dedicated test) — the filename only ever preserves the original stem/suffix (Phase 35), never the original directory, so guessing would be misleading. All Phase 36 behavior (missing/empty-directory reporting, unexpected-subdirectory handling, never reading file content, never creating the directory) is unchanged.

## Backward Compatibility for Metadata-Less Quarantined Files

Files quarantined under Phase 35/36, before `quarantine_records` existed, have no row in the table at all. `QuarantineStore.get_by_quarantine_path()` returns `None` for such a file — the ordinary, expected case, not an error — and `QuarantineListTool` shows the honest "unknown" fallback rather than failing or guessing. This was directly tested: a file written straight into `.jarvis_trash/` with no corresponding store record lists successfully alongside a freshly-quarantined file that does have one, each showing the correct original-path text independently. No migration or backfill of pre-Phase-37 quarantined files was added or attempted.

## QuarantineStore Changes (Batch 2)

None. `get_by_quarantine_path()`, added in Batch 1, was sufficient for `QuarantineListTool`'s display needs — no new read/list helper was required, keeping the store's public surface exactly as narrow as Batch 1 left it (still only `record_quarantine()` and `get_by_quarantine_path()`).

## Main Wiring

`main.py` now constructs exactly one `QuarantineStore(session_factory)` instance and injects it into both `QuarantineListTool` and `FileDeleteTool` — never two separate stores or database connections. Confirmed by a dedicated wiring test asserting `list_tool._store is delete_tool._store`.

## Documentation Updates

- **`README.md`**: added a new "Phase 37 — Quarantine Restore Metadata Foundation (complete)" section; updated the Phase 35 and Phase 36 non-goals paragraphs with forward pointers to Phase 37.
- **`docs/user_guide.md`**: updated the command-reference table row text for `delete file`/`list quarantine`/`show quarantine`; updated the "File delete notes"/"Quarantine listing notes" paragraphs to describe metadata recording and display; corrected the previously-accurate-but-now-outdated §11/§13 claims that "nothing durably records which original path a quarantined file came from" — that specific gap is now closed for newly quarantined files, though restore itself remains unbuilt.

Docs consistently state: metadata is recorded only for newly quarantined files; older files show "unknown"; restore/undo is still not built; this foundation makes a future restore safer but does not restore anything itself; no empty-trash/permanent-delete/cleanup/dashboard-visibility exists.

## Tests Added

**Batch 1 (24):** 11 `QuarantineStore` tests (record/retrieve, optional `session_id`, missing-record returns `None`, multiple independent records, duplicate `quarantine_path` raises without corrupting the original, structural no-update/delete/restore/cleanup check) + 12 `FileDeleteTool` metadata tests (exactly-one-record-written, `original_path`/`quarantine_path`/`session_id` correctness, no-metadata-on-every-rejection-path, move-failure writes nothing, metadata-write-failure disclosed honestly, recorded-flag true/false, no-store backward compatibility) + 1 main-wiring test.

**Batch 2 (13):** 11 `QuarantineListTool` tests (shows known original path, shows "unknown" fallback with a store present but no record, shows "unknown" fallback with no store at all, does not infer from filename, missing metadata does not crash, pre-existing metadata-less file lists correctly, freshly-quarantined file with metadata lists correctly, known and unknown entries appear together correctly, lookup uses the resolved absolute quarantine path, store is only ever read never written during listing, and one end-to-end test using a real `QuarantineStore` + real `FileDeleteTool` confirming listing adds zero new database rows) + 2 main-wiring tests (`QuarantineListTool` backed by a real `QuarantineStore`; both quarantine tools share exactly one store instance).

**Total new tests this phase: 37.**

## Focused Test Result

```
Batch 1 focus: 51 passed, 2 skipped
Batch 2 focus (test_quarantine_list_tool.py, test_main_quarantine_list_wiring.py,
  test_quarantine_store.py, test_file_delete_tool.py, test_main_file_delete_wiring.py): 86 passed, 2 skipped
```

## Full Suite Result

```
poetry run pytest -q: 3244 passed, 2 skipped, 0 failed
(3207 baseline before Phase 37 + 37 new; skip count unchanged from Batch 1's +1 environment-gated symlink skip)
```

## Touched-File Ruff Result

```
poetry run ruff check main.py quarantine/__init__.py quarantine/quarantine_store.py \
  storage/models.py tools/builtin/file_delete_tool.py tools/builtin/quarantine_list_tool.py \
  tests/unit/test_file_delete_tool.py tests/unit/test_main_file_delete_wiring.py \
  tests/unit/test_quarantine_store.py tests/unit/test_quarantine_list_tool.py \
  tests/unit/test_main_quarantine_list_wiring.py

All checks passed, except the accepted, pre-existing E402 pytest.importorskip
pattern in test_quarantine_store.py (Batch 1) - confirmed byte-for-byte
identical to the same accepted pattern already present in
test_inbox_store.py. Not a new issue; no broad ruff cleanup performed.
```

## git diff --check Result

Clean (only benign LF/CRLF line-ending notices from git's own autocrlf handling — no actual whitespace errors).

## Final git status

```
?? dashboard_test.txt
```

(the only entry, once Batch 2's changes are committed)

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout both batches.
- **No restore/empty-trash/permanent-delete/cleanup behavior was added.** `QuarantineStore` exposes only `record_quarantine()` and `get_by_quarantine_path()`. No production code path calls `os.remove()`, `Path.unlink()`, `shutil.rmtree()`, `os.rmdir()`, or `Path.rmdir()`.
- **No AI/workflow/scheduler/dashboard/Inbox integration was added.** `quarantine/` imports only `storage`; `QuarantineListTool` and `FileDeleteTool` gained no new imports beyond `quarantine.quarantine_store.QuarantineStore`.
- **Security tiers unchanged:** `delete file` remains YELLOW (fixed `action_for()` string, pre-existing rule); `list quarantine`/`show quarantine` remain GREEN (pre-existing generic `"list"` rule). No unrelated classification changed.

## Remaining Future Work (named, not built)

- **Restore/undo command** — the specific metadata gap that blocked this is now closed for newly quarantined files, but restore itself is a distinct, separately-reviewed future decision (needs its own approval-tier analysis, collision handling if the original path is now occupied by something else, and behavior for metadata-less legacy files).
- **Empty-trash/permanent delete** — still deferred, needing its own careful, separately-reviewed safety design.
- **Cleanup/retention policy** — still deferred, needing explicit policy decisions not yet made.
- **Dashboard visibility into quarantine contents** — only if separately reviewed later.

---

## Status Statement

**Phase 37 complete for its defined scope: durable original-path metadata is now recorded for every newly quarantined file and displayed by `list quarantine`/`show quarantine` when available, with an honest "unknown" fallback for anything quarantined before this table existed.** No restore, empty-trash, permanent-delete, or cleanup capability was added — this phase only lays the groundwork for a future restore command to be designed safely, exactly as scoped.
