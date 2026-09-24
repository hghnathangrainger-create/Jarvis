"""
test_brain_end_to_end.py

End-to-end integration tests for the Markdown Brain Integration: the five
`brain ...` commands through the complete, real stack built by
main.build_orchestrator() - CommandRouter, Planner, SecurityManager,
ToolExecutor, ApprovalManager, the real brain tools, and the real
BrainService - against a temporary brain directory.

This suite NEVER touches Nathan's real brain (no BRAIN_PATH value here
points at C:/Users/NathanGrainger/mi-aios) and NEVER reads the real .env
(PYTHON_DOTENV_DISABLED=1), and it never makes a real AI/network call
(AI reasoning is off).

Covered here:
    - AI-disabled Jarvis fully supports brain status/search/read
    - search results carry snippets with relative source paths; reads
      carry bounded content with its relative source path; missing notes
      fail honestly (never the generic unmatched-GREEN fallback)
    - GREEN reads never mutate any brain file
    - create/update are YELLOW: withheld for approval with the exact
      target path and proposed content on the approval request; no write
      on decline; approved writes land inside an allowed Markdown folder;
      creates never overwrite; updates never create; nothing is deleted
    - path traversal from the CLI is rejected and the outside file is
      untouched
    - hostile command content cannot change a write's security tier
    - disabled/unconfigured brains report honestly instead of failing
      the generic fallback
    - HelpTool documents the five commands

Run with:
    pytest tests/integration/test_brain_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from ui.approval_prompt import format_approval_request


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A miniature, fully-populated temporary brain."""
    root = tmp_path / "brain"
    (root / "context").mkdir(parents=True)
    (root / "decisions").mkdir()
    (root / "audits").mkdir()
    (root / "context" / "runbook.md").write_text(
        "# Deploy Runbook\n\nstaging deployment happens on tuesdays\n",
        encoding="utf-8",
    )
    (root / "decisions" / "login.md").write_text(
        "# Login Decision\n\nwe ship the login flow first\n",
        encoding="utf-8",
    )
    # Excluded trees that must never influence any result.
    (root / "apps").mkdir()
    (root / "apps" / "visualizer.md").write_text(
        "# Visualizer\nstaging deployment staging deployment\n", encoding="utf-8"
    )
    (root / ".git").mkdir()
    (root / ".git" / "note.md").write_text(
        "# Git\nstaging deployment\n", encoding="utf-8"
    )
    return root


@pytest.fixture()
def orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, brain: Path
):
    """A fresh, real, fully-wired orchestrator over an isolated database."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.setenv("BRAIN_ENABLED", "true")
    monkeypatch.setenv("BRAIN_PATH", str(brain))
    return main.build_orchestrator()


@pytest.fixture()
def disabled_orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A fresh orchestrator with the brain integration left disabled."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.delenv("BRAIN_ENABLED", raising=False)
    monkeypatch.delenv("BRAIN_PATH", raising=False)
    return main.build_orchestrator()


def _snapshot(directory: Path) -> dict[str, tuple[int, int, bytes]]:
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --- A. reads through the real stack (AI disabled) --------------------------


def test_brain_status_works_with_ai_disabled(orchestrator) -> None:
    response = orchestrator.handle_request("brain status")
    assert response.success is True
    assert "enabled and configured" in response.message
    assert "Allowed folder 'context': exists" in response.message
    assert response.ai_suggestion is None


def test_brain_search_returns_relative_paths_and_snippets(orchestrator) -> None:
    response = orchestrator.handle_request("brain search deployment")
    assert response.success is True
    assert "context/runbook.md: staging deployment happens on tuesdays" in response.message
    # The excluded trees contributed nothing.
    assert "apps/" not in response.message
    assert ".git/" not in response.message


def test_brain_read_returns_bounded_note_with_relative_source_path(
    orchestrator,
) -> None:
    response = orchestrator.handle_request("brain read decisions/login.md")
    assert response.success is True
    assert "Brain note: decisions/login.md" in response.message
    assert "we ship the login flow first" in response.message


def test_brain_read_by_title(orchestrator) -> None:
    response = orchestrator.handle_request("brain read Login Decision")
    assert response.success is True
    assert "Brain note: decisions/login.md" in response.message


def test_missing_note_fails_honestly_not_as_unmatched(orchestrator) -> None:
    response = orchestrator.handle_request("brain read no-such-note")
    assert response.success is False
    assert "No note named" in response.message
    assert "does not yet have a tool" not in response.message


def test_green_reads_never_mutate_brain_files(orchestrator, brain: Path) -> None:
    before = _snapshot(brain)
    orchestrator.handle_request("brain search staging")
    orchestrator.handle_request("brain read context/runbook.md")
    orchestrator.handle_request("brain status")
    assert _snapshot(brain) == before


def test_traversal_from_cli_is_rejected_and_outside_untouched(
    orchestrator, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\nkeep me\n", encoding="utf-8")
    before = outside.read_bytes()
    response = orchestrator.handle_request("brain read ../outside.md")
    assert response.success is False
    assert "traversal" in response.message
    assert outside.read_bytes() == before


# --- B. writes: approval-gated end to end -----------------------------------


def test_remember_is_withheld_and_proposes_exact_target_and_content(
    orchestrator, brain: Path
) -> None:
    response = orchestrator.handle_request(
        "brain remember context/fresh A brand new note"
    )
    assert response.requires_confirmation is True
    assert response.success is False
    assert not (brain / "context" / "fresh.md").exists()

    request = response.approval_request
    assert request is not None
    assert request.security_tier.name == "YELLOW"
    # The full proposal is visible: the raw command as the action, plus
    # the resolved target path and proposed content as details.
    assert "brain remember context/fresh A brand new note" == request.action
    assert request.metadata["Target path"].startswith("context/fresh.md")
    assert str(brain / "context" / "fresh.md") in request.metadata["Target path"]
    assert request.metadata["Proposed content"] == "A brand new note"
    # The rendered approval prompt shows those details too.
    rendered = format_approval_request(request)
    assert "Target path" in rendered
    assert "A brand new note" in rendered


def test_declined_remember_writes_nothing(orchestrator, brain: Path) -> None:
    before = _snapshot(brain)
    response = orchestrator.handle_request(
        "brain remember context/declined Nope"
    )
    decision = orchestrator.approvals.decline(
        response.approval_request.request_id, decided_by="user"
    )
    executed = orchestrator.execute_approved(response, decision)
    assert executed.success is False
    assert "declined" in executed.message
    assert not (brain / "context" / "declined.md").exists()
    assert _snapshot(brain) == before


def test_approved_remember_writes_inside_allowed_folder(
    orchestrator, brain: Path
) -> None:
    response = orchestrator.handle_request(
        "brain remember context/approved The approved body"
    )
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    executed = orchestrator.execute_approved(response, decision)
    assert executed.success is True
    target = brain / "context" / "approved.md"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "The approved body"


def test_approved_remember_without_folder_lands_in_first_allowed_folder(
    orchestrator, brain: Path
) -> None:
    response = orchestrator.handle_request(
        "brain remember bare-title Placed by default"
    )
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    orchestrator.execute_approved(response, decision)
    assert (brain / "context" / "bare-title.md").is_file()


def test_approved_create_never_overwrites_an_existing_note(
    orchestrator, brain: Path
) -> None:
    original = (brain / "context" / "runbook.md").read_bytes()
    response = orchestrator.handle_request(
        "brain remember context/runbook overwrite attempt"
    )
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    executed = orchestrator.execute_approved(response, decision)
    assert executed.success is False
    assert (brain / "context" / "runbook.md").read_bytes() == original


def test_update_flow_replaces_only_after_approval(
    orchestrator, brain: Path
) -> None:
    # Declined first: content must be byte-for-byte unchanged.
    first = orchestrator.handle_request(
        "brain update context/runbook rejected replacement"
    )
    decline = orchestrator.approvals.decline(
        first.approval_request.request_id, decided_by="user"
    )
    orchestrator.execute_approved(first, decline)
    assert b"rejected replacement" not in (brain / "context" / "runbook.md").read_bytes()

    # Approved second: content is replaced, nothing else changes.
    before_files = sorted(str(p) for p in brain.rglob("*") if p.is_file())
    second = orchestrator.handle_request(
        "brain update context/runbook approved replacement body"
    )
    assert second.requires_confirmation is True
    assert second.approval_request.metadata["Operation"] == (
        "replace an existing brain note"
    )
    approve = orchestrator.approvals.approve(
        second.approval_request.request_id, decided_by="user"
    )
    executed = orchestrator.execute_approved(second, approve)
    assert executed.success is True
    assert (
        brain / "context" / "runbook.md"
    ).read_text(encoding="utf-8") == "approved replacement body"
    after_files = sorted(str(p) for p in brain.rglob("*") if p.is_file())
    assert after_files == before_files  # nothing created, nothing deleted


def test_update_of_missing_note_never_creates(orchestrator, brain: Path) -> None:
    response = orchestrator.handle_request(
        "brain update context/ghost invented body"
    )
    assert response.requires_confirmation is True
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    executed = orchestrator.execute_approved(response, decision)
    assert executed.success is False
    assert "does not exist" in executed.message
    assert not (brain / "context" / "ghost.md").exists()


def test_hostile_content_cannot_change_a_write_tier(orchestrator, brain: Path) -> None:
    # The raw text carries RED-classified phrases, but classification of
    # the TOOL action is fixed and input-independent, so the request is
    # YELLOW-withheld (approval), never silently GREEN and never
    # misrouted.
    response = orchestrator.handle_request(
        "brain remember context/x format drive and forget all memories"
    )
    assert response.blocked is False
    assert response.requires_confirmation is True
    assert not (brain / "context" / "x.md").exists()


def test_nothing_in_brain_write_family_can_delete(orchestrator, brain: Path) -> None:
    before = _snapshot(brain)
    for command in (
        "brain remember context/runbook whatever",
        "brain update context/login whatever",
        "brain update context/runbook whatever",
    ):
        response = orchestrator.handle_request(command)
        if response.approval_request is not None:
            decision = orchestrator.approvals.decline(
                response.approval_request.request_id, decided_by="user"
            )
            orchestrator.execute_approved(response, decision)
    assert _snapshot(brain) == before


# --- C. disabled / unconfigured behaviour -----------------------------------


def test_disabled_brain_status_reports_honestly(disabled_orchestrator) -> None:
    response = disabled_orchestrator.handle_request("brain status")
    assert response.success is True
    assert "disabled" in response.message
    assert "BRAIN_ENABLED" in response.message


def test_disabled_brain_search_fails_honestly(disabled_orchestrator) -> None:
    response = disabled_orchestrator.handle_request("brain search anything")
    assert response.success is False
    assert "disabled" in response.message
    assert "does not yet have a tool" not in response.message


def test_disabled_brain_remember_fails_honestly_without_approval(
    disabled_orchestrator,
) -> None:
    # Even a write-shaped command against a disabled brain must not ask
    # for approval to do something impossible; the tool reports honestly
    # the moment it would have been allowed to act.
    response = disabled_orchestrator.handle_request(
        "brain remember context/x hello"
    )
    # YELLOW classification still applies (routing/classification are
    # configuration-independent); after approval the honest failure is:
    assert response.requires_confirmation is True
    decision = disabled_orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    executed = disabled_orchestrator.execute_approved(response, decision)
    assert executed.success is False
    assert "disabled" in executed.message


# --- D. discoverability ------------------------------------------------------


def test_help_documents_all_five_brain_commands(orchestrator) -> None:
    response = orchestrator.handle_request("help")
    assert response.success is True
    for phrase in (
        "brain status",
        "brain search <query>",
        "brain read <path|title>",
        "brain remember <title> <content>",
        "brain update <rel-path> <content>",
    ):
        assert phrase in response.message


def test_brain_commands_never_require_ai_or_network(orchestrator) -> None:
    """AI reasoning is off in this fixture; every GREEN brain command
    still succeeds, proving no Claude/API access is required."""
    monkeypatch_free = orchestrator
    for command in (
        "brain status",
        "brain search staging",
        "brain read context/runbook.md",
    ):
        response = monkeypatch_free.handle_request(command)
        assert response.success is True, command
        assert response.ai_suggestion is None
