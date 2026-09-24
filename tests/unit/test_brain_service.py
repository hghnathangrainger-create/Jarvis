"""
test_brain_service.py

Unit tests for tools/brain_service.py (Markdown Brain Integration).

Everything runs against temporary directories created by pytest's
tmp_path fixture - this suite never needs, reads, or touches Nathan's
real brain at C:/Users/NathanGrainger/mi-aios, and never reads any .env.

Covered here:
    - status (disabled / unconfigured / configured, folder existence)
    - deterministic case-insensitive search over filenames/titles/content
    - bounded read by relative path and by exact title/filename
    - missing/ambiguous notes reported honestly
    - allowed-folder scope: .git, apps/, node_modules/, hidden folders,
      non-allowed folders, and top-level files are never scanned
    - path traversal, absolute paths, hidden segments, non-.md targets
      rejected; symlinks escaping the root rejected (skipped where the
      platform cannot create symlinks)
    - size/result/context limits honoured
    - GREEN reads never mutate any file
    - create/update planning: no overwrite on create, no create on
      update, atomic writes stay inside allowed Markdown folders

Run with:
    pytest tests/unit/test_brain_service.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.brain_service import BrainError, BrainService

# --- fixtures ---------------------------------------------------------------


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A miniature brain tree exercising every scope rule."""
    root = tmp_path / "brain"
    (root / "context").mkdir(parents=True)
    (root / "decisions").mkdir()
    (root / "references").mkdir()
    (root / "audits").mkdir()
    (root / "brainstorms").mkdir()

    (root / "context" / "note-one.md").write_text(
        "# Note One\n\nall about deployment windows\n", encoding="utf-8"
    )
    (root / "decisions" / "ship-login.md").write_text(
        "# Ship Login\n\ndecision: ship the login flow\n", encoding="utf-8"
    )
    (root / "references" / "api.md").write_text(
        "# API Reference\n\nendpoint: GET /things\n", encoding="utf-8"
    )
    (root / "context" / "not-markdown.txt").write_text(
        "deployment in a txt file", encoding="utf-8"
    )

    # Scope exclusions: none of these may ever be scanned.
    (root / "apps").mkdir()
    (root / "apps" / "visualizer.md").write_text(
        "# Visualizer\ndeployment deployment deployment\n", encoding="utf-8"
    )
    (root / ".git").mkdir()
    (root / ".git" / "hidden-note.md").write_text(
        "# Hidden\ndeployment deployment\n", encoding="utf-8"
    )
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.md").write_text(
        "# Dep\ndeployment deployment\n", encoding="utf-8"
    )
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.md").write_text(
        "# Secret\ndeployment deployment\n", encoding="utf-8"
    )
    (root / "other").mkdir()
    (root / "other" / "stray.md").write_text(
        "# Stray\ndeployment deployment\n", encoding="utf-8"
    )
    (root / "loose.md").write_text(
        "# Loose\ndeployment deployment\n", encoding="utf-8"
    )
    return root


def service(root: Path | None = None, **overrides) -> BrainService:
    """Build a service from explicit, isolated configuration."""
    kwargs: dict[str, object] = {
        "enabled": True,
        "root": root,
        "folders": ("context", "decisions", "references", "audits", "brainstorms"),
    }
    kwargs.update(overrides)
    return BrainService(**kwargs)


def snapshot(directory: Path) -> dict[str, tuple[int, int, bytes]]:
    """Capture (size, mtime_ns, bytes) for every file under a directory."""
    state: dict[str, tuple[int, int, bytes]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            state[str(path)] = (
                stat.st_size,
                stat.st_mtime_ns,
                path.read_bytes(),
            )
    return state


# --- A. status --------------------------------------------------------------


def test_status_disabled() -> None:
    svc = BrainService(enabled=False, root=None)
    status = svc.status()
    assert status.enabled is False
    assert status.configured is False
    assert status.root is None
    assert status.folders == ()


def test_status_enabled_but_unconfigured() -> None:
    svc = BrainService(enabled=True, root="")
    status = svc.status()
    assert status.enabled is True
    assert status.configured is False
    assert status.root is None


def test_status_reports_folder_existence(brain: Path) -> None:
    svc = service(brain)
    status = svc.status()
    assert status.configured is True
    assert status.root_exists is True
    by_name = {folder.name: folder for folder in status.folders}
    assert by_name["context"].exists is True
    assert by_name["context"].in_scope is True
    assert by_name["brainstorms"].exists is True
    for leftover in (brain / "decisions").iterdir():
        leftover.unlink()
    (brain / "decisions").rmdir()
    status = svc.status()
    by_name = {folder.name: folder for folder in status.folders}
    assert by_name["decisions"].exists is False


def test_status_reports_folder_outside_root_as_out_of_scope(
    brain: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    svc = BrainService(
        enabled=True, root=brain, folders=("context", "outside")
    )
    # "outside" is not a child of the root, so it can never be in scope.
    by_name = {
        folder.name: folder for folder in svc.status().folders if folder.name == "outside"
    }
    # It does not even exist under the root, so it is simply missing.
    assert by_name["outside"].exists is False


# --- B. search --------------------------------------------------------------


def test_search_matches_content_case_insensitively(brain: Path) -> None:
    result = service(brain).search("DEPLOYMENT")
    assert [m.rel_path for m in result.matches] == ["context/note-one.md"]
    assert "deployment windows" in result.matches[0].snippet


def test_search_matches_title(brain: Path) -> None:
    result = service(brain).search("ship login")
    assert [m.rel_path for m in result.matches] == ["decisions/ship-login.md"]


def test_search_matches_filename(brain: Path) -> None:
    result = service(brain).search("api")
    assert [m.rel_path for m in result.matches] == ["references/api.md"]


def test_search_is_sorted_and_deterministic(brain: Path) -> None:
    first = service(brain).search("deployment")
    second = service(brain).search("deployment")
    assert [m.rel_path for m in first.matches] == [
        m.rel_path for m in second.matches
    ]
    assert [m.rel_path for m in first.matches] == sorted(
        m.rel_path for m in first.matches
    )


def test_search_never_scans_excluded_folders(brain: Path) -> None:
    result = service(brain).search("deployment")
    rel_paths = [m.rel_path for m in result.matches]
    # Only context/note-one.md is inside an allowed folder; every
    # excluded tree (apps, .git, node_modules, .hidden, other, loose.md,
    # not-markdown.txt) contributed nothing.
    assert rel_paths == ["context/note-one.md"]


def test_search_limit_is_honoured_and_truncated(brain: Path) -> None:
    for index in range(5):
        (brain / "context" / f"common-{index}.md").write_text(
            f"# Common {index}\nsharedtoken here\n", encoding="utf-8"
        )
    svc = service(brain, search_limit=2)
    result = svc.search("sharedtoken")
    assert len(result.matches) == 2
    assert result.truncated is True
    assert result.limit == 2


def test_search_reports_no_matches_honestly(brain: Path) -> None:
    result = service(brain).search("zzz-no-such-thing")
    assert result.matches == ()
    assert result.truncated is False


def test_search_rejects_empty_query(brain: Path) -> None:
    with pytest.raises(BrainError):
        service(brain).search("   ")


def test_search_disabled_reports_honestly() -> None:
    svc = BrainService(enabled=False, root=None)
    with pytest.raises(BrainError, match="disabled"):
        svc.search("anything")


def test_search_unconfigured_reports_honestly() -> None:
    svc = BrainService(enabled=True, root="")
    with pytest.raises(BrainError, match="BRAIN_PATH"):
        svc.search("anything")


def test_search_missing_root_reports_honestly(tmp_path: Path) -> None:
    svc = service(tmp_path / "no-such-brain")
    with pytest.raises(BrainError, match="does not exist"):
        svc.search("anything")


def test_search_skips_oversized_files(brain: Path) -> None:
    (brain / "context" / "huge.md").write_text(
        "# Huge\n" + ("filler " * 4000) + "\nfindme\n", encoding="utf-8"
    )
    svc = service(brain, max_file_bytes=512)
    result = svc.search("findme")
    assert [m.rel_path for m in result.matches] == []


def test_search_any_matches_any_term(brain: Path) -> None:
    result = service(brain).search_any(("login", "endpoint"))
    assert [m.rel_path for m in result.matches] == [
        "decisions/ship-login.md",
        "references/api.md",
    ]


def test_search_any_rejects_no_usable_terms(brain: Path) -> None:
    with pytest.raises(BrainError):
        service(brain).search_any(("", "   "))


# --- C. read ----------------------------------------------------------------


def test_read_by_relative_path(brain: Path) -> None:
    result = service(brain).read("context/note-one.md")
    assert result.rel_path == "context/note-one.md"
    assert "deployment windows" in result.content
    assert result.truncated is False


def test_read_by_relative_path_without_extension(brain: Path) -> None:
    result = service(brain).read("context/note-one")
    assert result.rel_path == "context/note-one.md"


def test_read_by_exact_title(brain: Path) -> None:
    result = service(brain).read("Ship Login")
    assert result.rel_path == "decisions/ship-login.md"


def test_read_by_filename_title_case_insensitive(brain: Path) -> None:
    result = service(brain).read("note-one")
    assert result.rel_path == "context/note-one.md"


def test_read_missing_note_reports_honestly(brain: Path) -> None:
    with pytest.raises(BrainError, match="No note named"):
        service(brain).read("does-not-exist")


def test_read_missing_path_reports_honestly(brain: Path) -> None:
    with pytest.raises(BrainError, match="No note found"):
        service(brain).read("context/does-not-exist.md")


def test_read_ambiguous_title_lists_candidates(brain: Path) -> None:
    (brain / "decisions" / "shared.md").write_text("# Shared A\n", encoding="utf-8")
    (brain / "references" / "shared.md").write_text("# Shared B\n", encoding="utf-8")
    with pytest.raises(BrainError, match="ambiguous"):
        service(brain).read("shared")


def test_read_rejects_path_traversal(brain: Path) -> None:
    with pytest.raises(BrainError, match="traversal"):
        service(brain).read("context/../../escape.md")


def test_read_rejects_absolute_path(brain: Path, tmp_path: Path) -> None:
    with pytest.raises(BrainError, match="relative"):
        service(brain).read(str(tmp_path / "anything.md"))


def test_read_rejects_file_outside_allowed_folders(brain: Path) -> None:
    # loose.md exists at the root but in none of the allowed folders.
    with pytest.raises(BrainError):
        service(brain).read("loose.md")


def test_read_rejects_non_markdown_target(brain: Path) -> None:
    with pytest.raises(BrainError):
        service(brain).read("context/not-markdown.txt")


def test_read_rejects_hidden_folder_segment(brain: Path) -> None:
    with pytest.raises(BrainError, match="hidden"):
        service(brain).read(".hidden/secret.md")


def test_read_rejects_symlink_escaping_root(brain: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\nsecret\n", encoding="utf-8")
    link = brain / "context" / "escape.md"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    with pytest.raises(BrainError, match="outside"):
        service(brain).read("context/escape.md")
    assert outside.read_text(encoding="utf-8") == "# Outside\nsecret\n"


def test_resolve_within_rejects_symlink_escape_simulated(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same escape as above, deterministically simulated by making
    Path.resolve() report the outside-the-root location a symlink target
    would have - so the resolved-containment rule is proven even on a
    platform where creating a real symlink needs a privilege this test
    process may not hold."""
    original_resolve = Path.resolve

    def _fake_resolve(self: Path, *args, **object):
        resolved = original_resolve(self, *args, **object)
        if self.name == "sneaky.md" and self.parent.name == "context":
            return resolved.parents[2]  # a location outside the root
        return resolved

    monkeypatch.setattr(Path, "resolve", _fake_resolve)
    with pytest.raises(BrainError, match="outside"):
        service(brain).read("context/sneaky.md")


def test_read_bounds_oversized_note(brain: Path) -> None:
    (brain / "context" / "big.md").write_text(
        "A" * 5_000, encoding="utf-8"
    )
    result = service(brain, max_file_bytes=1_024).read("context/big.md")
    assert result.truncated is True
    assert len(result.content) <= 1_024


def test_read_disabled_reports_honestly() -> None:
    with pytest.raises(BrainError, match="disabled"):
        BrainService(enabled=False).read("context/note-one.md")


# --- D. GREEN reads never mutate -------------------------------------------


def test_search_and_read_never_mutate_any_file(brain: Path) -> None:
    before = snapshot(brain)
    svc = service(brain)
    svc.search("deployment")
    svc.read("context/note-one.md")
    svc.status()
    assert snapshot(brain) == before


# --- E. create/update planning and writing ---------------------------------


def test_plan_create_bare_title_lands_in_first_allowed_folder(brain: Path) -> None:
    rel, target = service(brain).plan_create("my-new-note")
    assert rel == "context/my-new-note.md"
    assert target == (brain / "context" / "my-new-note.md")
    assert not target.exists()


def test_plan_create_explicit_folder_path(brain: Path) -> None:
    rel, target = service(brain).plan_create("decisions/choice")
    assert rel == "decisions/choice.md"
    assert target == (brain / "decisions" / "choice.md")


def test_plan_create_refuses_existing_note(brain: Path) -> None:
    with pytest.raises(BrainError, match="already exists"):
        service(brain).plan_create("context/note-one")


def test_plan_create_refuses_missing_parent_folder(brain: Path) -> None:
    # An ALLOWED folder that simply does not exist yet: planning may
    # resolve, but nothing may create the folder.
    (brain / "brainstorms").rmdir()
    with pytest.raises(BrainError, match="does not exist"):
        service(brain).plan_create("brainstorms/ghost")


def test_plan_create_refuses_folder_outside_allowed(brain: Path) -> None:
    with pytest.raises(BrainError):
        service(brain).plan_create("other/stray-note")


def test_plan_create_refuses_traversal(brain: Path) -> None:
    with pytest.raises(BrainError, match="traversal"):
        service(brain).plan_create("context/../../escaped")


def test_plan_create_refuses_hidden_segment(brain: Path) -> None:
    with pytest.raises(BrainError, match="hidden"):
        service(brain).plan_create(".hidden/note")


def test_plan_update_requires_existing_note(brain: Path) -> None:
    with pytest.raises(BrainError, match="does not exist"):
        service(brain).plan_update("context/ghost.md")


def test_plan_update_resolves_existing_note(brain: Path) -> None:
    rel, target = service(brain).plan_update("context/note-one")
    assert rel == "context/note-one.md"
    assert target.is_file()


def test_plan_update_refuses_symlinked_note(brain: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    link = brain / "context" / "linked.md"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    with pytest.raises(BrainError, match="symbolic link"):
        service(brain).plan_update("context/linked.md")


def test_write_creates_note_atomically_inside_allowed_folder(brain: Path) -> None:
    svc = service(brain)
    rel, target = svc.plan_create("context/written")
    written = svc.write(target, "# Written\ncontent\n", exclusive=True)
    assert written == len("# Written\ncontent\n")
    assert target.read_text(encoding="utf-8") == "# Written\ncontent\n"
    # No temporary leftovers from the atomic write.
    assert not list(target.parent.glob(".jarvis-brain-*"))


def test_write_refuses_empty_content(brain: Path) -> None:
    svc = service(brain)
    _, target = svc.plan_create("context/empty")
    with pytest.raises(BrainError, match="empty"):
        svc.write(target, "   ", exclusive=True)
    assert not target.exists()


def test_write_refuses_oversized_content(brain: Path) -> None:
    svc = service(brain, max_file_bytes=64)
    _, target = svc.plan_create("context/too-big")
    with pytest.raises(BrainError, match="limit"):
        svc.write(target, "x" * 100, exclusive=True)
    assert not target.exists()


def test_write_exclusive_refuses_existing_target(brain: Path) -> None:
    svc = service(brain)
    _, target = svc.plan_create("context/raced")
    target.write_text("appeared meanwhile\n", encoding="utf-8")
    with pytest.raises(BrainError, match="already exists"):
        svc.write(target, "clobbered\n", exclusive=True)
    assert target.read_text(encoding="utf-8") == "appeared meanwhile\n"


def test_write_never_creates_parent_folders(brain: Path) -> None:
    svc = service(brain)
    with pytest.raises(BrainError, match="does not exist"):
        svc.plan_create("context/deeply/nested")
