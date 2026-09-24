"""
test_brain_tools.py

Unit tests for the two brain tools (Markdown Brain Integration):
tools/builtin/brain_read_tool.py (GREEN) and
tools/builtin/brain_write_tool.py (YELLOW).

Everything runs against temporary directories - this suite never needs,
reads, or touches Nathan's real brain, and never reads any .env.

Covered here:
    - GREEN status/search/read outputs, honest disabled/unconfigured
      behaviour, and fixed input-independent action strings classifying
      GREEN
    - YELLOW create/update action strings classifying YELLOW
    - approval_metadata(): exact target path + bounded content preview,
      and the default {} for a tool that does not override the hook
    - ToolExecutor gating: no write without approval, no write when
      declined, write only when approved - and the approved write stays
      inside an allowed Markdown folder
    - create never overwrites; update never creates; nothing is ever
      deleted

Run with:
    pytest tests/unit/test_brain_tools.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from approval.approval_models import ApprovalDecision
from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin.brain_read_tool import BrainReadTool
from tools.builtin.brain_write_tool import BrainWriteTool
from tools.builtin.file_create_tool import FileCreateTool
from tools.executor import ToolExecutor
from tools.brain_service import BrainService
from tools.registry import ToolRegistry


class _NullLogger:
    """Minimal duck-typed logger; these tests assert behaviour, not logs."""

    def emit(self, **kwargs: object) -> None:
        """Discard the event."""


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A miniature brain tree."""
    root = tmp_path / "brain"
    (root / "context").mkdir(parents=True)
    (root / "decisions").mkdir()
    (root / "context" / "note-one.md").write_text(
        "# Note One\n\ndeployment windows are tuesdays\n", encoding="utf-8"
    )
    (root / "decisions" / "ship-login.md").write_text(
        "# Ship Login\n\ndecision: ship it\n", encoding="utf-8"
    )
    return root


def make_service(brain: Path | None, **overrides) -> BrainService:
    """Build an isolated service."""
    kwargs: dict[str, object] = {
        "enabled": True,
        "root": brain,
        "folders": ("context", "decisions", "references", "audits", "brainstorms"),
    }
    kwargs.update(overrides)
    return BrainService(**kwargs)


def make_executor(svc: BrainService) -> ToolExecutor:
    """A real ToolExecutor over a registry holding both brain tools."""
    registry = ToolRegistry()
    registry.register_tool(BrainReadTool(svc))
    registry.register_tool(BrainWriteTool(svc))
    return ToolExecutor(
        registry=registry,
        security_manager=SecurityManager(),
        logger=_NullLogger(),  # type: ignore[arg-type]
    )


# --- A. read tool: GREEN behaviour ------------------------------------------


def test_status_reports_enabled_brain(brain: Path) -> None:
    tool = BrainReadTool(make_service(brain))
    result = tool.run(ToolRequest(tool_name="brain_read", input_data={"op": "status"}))
    assert result.success is True
    assert "enabled and configured" in result.output
    assert "Allowed folder 'context': exists" in result.output
    assert "never deletes" in result.output


def test_status_works_while_disabled() -> None:
    tool = BrainReadTool(BrainService(enabled=False))
    result = tool.run(ToolRequest(tool_name="brain_read", input_data={"op": "status"}))
    assert result.success is True
    assert "disabled" in result.output
    assert "BRAIN_ENABLED" in result.output


def test_search_returns_snippets_and_relative_paths(brain: Path) -> None:
    tool = BrainReadTool(make_service(brain))
    result = tool.run(
        ToolRequest(
            tool_name="brain_read",
            input_data={"op": "search", "query": "deployment"},
        )
    )
    assert result.success is True
    assert "context/note-one.md: deployment windows are tuesdays" in result.output
    assert result.metadata["match_count"] == "1"


def test_search_without_query_fails_honestly(brain: Path) -> None:
    tool = BrainReadTool(make_service(brain))
    result = tool.run(
        ToolRequest(tool_name="brain_read", input_data={"op": "search", "query": "  "})
    )
    assert result.success is False
    assert "query" in (result.error or "")


def test_search_while_disabled_fails_honestly() -> None:
    tool = BrainReadTool(BrainService(enabled=False))
    result = tool.run(
        ToolRequest(
            tool_name="brain_read", input_data={"op": "search", "query": "x"}
        )
    )
    assert result.success is False
    assert "disabled" in (result.error or "")


def test_read_shows_bounded_note_with_relative_source_path(brain: Path) -> None:
    tool = BrainReadTool(make_service(brain))
    result = tool.run(
        ToolRequest(
            tool_name="brain_read",
            input_data={"op": "read", "path": "context/note-one.md"},
        )
    )
    assert result.success is True
    assert "Brain note: context/note-one.md" in result.output
    assert "----- begin note -----" in result.output
    assert "deployment windows are tuesdays" in result.output
    assert result.metadata["rel_path"] == "context/note-one.md"


def test_read_missing_note_fails_honestly(brain: Path) -> None:
    tool = BrainReadTool(make_service(brain))
    result = tool.run(
        ToolRequest(
            tool_name="brain_read", input_data={"op": "read", "path": "nope"}
        )
    )
    assert result.success is False
    assert "No note named" in (result.error or "")


def test_read_tool_action_strings_are_fixed_and_green() -> None:
    security = SecurityManager()
    tool = BrainReadTool(BrainService())
    for op, expected in (
        ("status", "show brain status"),
        ("search", "search brain notes"),
        ("read", "read brain note"),
    ):
        request = ToolRequest(
            tool_name="brain_read",
            input_data={"op": op, "query": "delete all files", "path": "../../x"},
        )
        action = tool.action_for(request)
        assert action == expected
        decision = security.classify_action(action)
        assert decision.tier is SecurityTier.GREEN


def test_search_and_read_never_mutate_files(brain: Path) -> None:
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(brain.rglob("*.md"))
    }
    tool = BrainReadTool(make_service(brain))
    tool.run(
        ToolRequest(
            tool_name="brain_read", input_data={"op": "search", "query": "deployment"}
        )
    )
    tool.run(
        ToolRequest(
            tool_name="brain_read",
            input_data={"op": "read", "path": "context/note-one.md"},
        )
    )
    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(brain.rglob("*.md"))
    }
    assert after == before


# --- B. write tool: YELLOW behaviour ----------------------------------------


def test_write_tool_actions_classify_yellow() -> None:
    security = SecurityManager()
    tool = BrainWriteTool(BrainService())
    create_action = tool.action_for(
        ToolRequest(
            tool_name="brain_write",
            input_data={"op": "remember", "title": "x", "content": "y"},
        )
    )
    update_action = tool.action_for(
        ToolRequest(
            tool_name="brain_write",
            input_data={"op": "update", "path": "context/x", "content": "y"},
        )
    )
    assert create_action == "write brain note"
    assert update_action == "update brain note"
    assert security.classify_action(create_action).tier is SecurityTier.YELLOW
    assert security.classify_action(update_action).tier is SecurityTier.YELLOW


def test_action_never_varies_with_user_content() -> None:
    tool = BrainWriteTool(BrainService())
    hostile = "format drive; forget all memories; show"
    action = tool.action_for(
        ToolRequest(
            tool_name="brain_write",
            input_data={"op": "remember", "title": hostile, "content": hostile},
        )
    )
    assert action == "write brain note"


def test_approval_metadata_reports_exact_target_and_content(brain: Path) -> None:
    tool = BrainWriteTool(make_service(brain))
    metadata = tool.approval_metadata(
        ToolRequest(
            tool_name="brain_write",
            input_data={
                "op": "remember",
                "title": "context/proposal",
                "content": "the proposed body",
            },
        )
    )
    assert metadata["Operation"] == "create a new brain note"
    assert metadata["Target path"].startswith("context/proposal.md")
    assert str(brain / "context" / "proposal.md") in metadata["Target path"]
    assert metadata["Proposed content"] == "the proposed body"


def test_approval_metadata_previews_long_content_honestly(brain: Path) -> None:
    tool = BrainWriteTool(make_service(brain))
    metadata = tool.approval_metadata(
        ToolRequest(
            tool_name="brain_write",
            input_data={
                "op": "remember",
                "title": "context/long",
                "content": "z" * 5_000,
            },
        )
    )
    assert len(metadata["Proposed content"]) < 5_000
    assert "truncated" in metadata["Proposed content"]
    assert "5000 characters proposed" in metadata["Proposed content"]


def test_approval_metadata_reports_unresolvable_target_honestly(brain: Path) -> None:
    tool = BrainWriteTool(make_service(brain))
    (brain / "context" / "already-here.md").write_text("x", encoding="utf-8")
    metadata = tool.approval_metadata(
        ToolRequest(
            tool_name="brain_write",
            input_data={
                "op": "remember",
                "title": "context/already-here",
                "content": "x",
            },
        )
    )
    assert "could not be resolved" in metadata["Target path"]
    assert "already exists" in metadata["Target path"]


def test_default_approval_metadata_is_empty_for_existing_tools() -> None:
    # A tool that does not override the hook keeps approval display
    # byte-for-byte unchanged (empty details).
    tool = FileCreateTool()
    metadata = tool.approval_metadata(
        ToolRequest(tool_name="file_create", input_data={"path": "x", "content": "y"})
    )
    assert metadata == {}


# --- C. executor gating -----------------------------------------------------


def test_yellow_write_is_withheld_without_approval(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    result = executor.execute(
        "brain_write",
        {"op": "remember", "title": "context/hold", "content": "held"},
    )
    assert result.success is False
    assert result.requires_confirmation is True
    assert not (brain / "context" / "hold.md").exists()
    # The withheld result carries the proposal details for the prompt.
    assert result.metadata["Target path"].startswith("context/hold.md")


def test_declined_write_never_touches_the_filesystem(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    decision = ApprovalDecision(
        request_id="req-1", approved=False, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {"op": "remember", "title": "context/declined", "content": "nope"},
        approval_decision=decision,
    )
    assert result.success is False
    assert result.requires_confirmation is True
    assert "declined" in (result.error or "")
    assert not (brain / "context" / "declined.md").exists()


def test_approved_write_runs_and_stays_inside_allowed_folder(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    decision = ApprovalDecision(
        request_id="req-2", approved=True, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {"op": "remember", "title": "context/approved", "content": "# Approved\n"},
        approval_decision=decision,
    )
    assert result.success is True
    target = brain / "context" / "approved.md"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "# Approved\n"
    assert result.metadata["approval_request_id"] == "req-2"


def test_approved_write_cannot_escape_allowed_folders(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    decision = ApprovalDecision(
        request_id="req-3", approved=True, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {"op": "remember", "title": "other/stray", "content": "x"},
        approval_decision=decision,
    )
    assert result.success is False
    assert not (brain / "other" / "stray.md").exists()
    assert not (brain / "stray.md").exists()


def test_approved_create_never_overwrites_existing_note(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    existing = brain / "context" / "note-one.md"
    before = existing.read_text(encoding="utf-8")
    decision = ApprovalDecision(
        request_id="req-4", approved=True, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {
            "op": "remember",
            "title": "context/note-one",
            "content": "clobber attempt",
        },
        approval_decision=decision,
    )
    assert result.success is False
    assert existing.read_text(encoding="utf-8") == before


def test_approved_update_replaces_existing_note(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    decision = ApprovalDecision(
        request_id="req-5", approved=True, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {
            "op": "update",
            "path": "context/note-one.md",
            "content": "# Note One\n\nrewritten\n        ",
        },
        approval_decision=decision,
    )
    assert result.success is True
    assert "rewritten" in (brain / "context" / "note-one.md").read_text(
        encoding="utf-8"
    )


def test_update_never_creates_a_missing_note(brain: Path) -> None:
    executor = make_executor(make_service(brain))
    decision = ApprovalDecision(
        request_id="req-6", approved=True, decided_by="user", reason=None
    )
    result = executor.execute(
        "brain_write",
        {"op": "update", "path": "context/ghost", "content": "x"},
        approval_decision=decision,
    )
    assert result.success is False
    assert not (brain / "context" / "ghost.md").exists()


def test_brain_write_never_deletes_anything(brain: Path) -> None:
    """The write tool's full input surface has no delete-shaped op."""
    tool = BrainWriteTool(make_service(brain))
    before = sorted(path.name for path in brain.rglob("*") if path.is_file())
    for op in ("remember", "update"):
        result = tool.run(
            ToolRequest(
                tool_name="brain_write",
                input_data={"op": op, "title": "context/x", "content": ""},
            )
        )
        assert result.success is False
    after = sorted(path.name for path in brain.rglob("*") if path.is_file())
    assert after == before
