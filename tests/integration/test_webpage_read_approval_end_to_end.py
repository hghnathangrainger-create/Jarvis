"""
test_webpage_read_approval_end_to_end.py

End-to-end integration tests for the webpage-read approval flow
(Phase 33, Batch 2).

These wire the real Security Manager, Tool Registry, Tool Executor,
Approval Manager, Planner, and CommandRouter together (mirroring
test_write_approval_end_to_end.py's own established pattern) and trace
a "read webpage <url>" request through its full journey: request ->
YELLOW approval -> approved-and-fetched-and-displayed, or
declined/timed-out-and-never-fetched.

A fake fetcher (duck-typing SafeWebFetcher.fetch()) is used for the
happy-path/denied/timeout tests, so no real network call is ever made.
One test uses the real SafeWebFetcher/WebFetchPolicy specifically to
prove an unsafe URL is rejected cleanly after approval, without ever
touching the network either (WebFetchPolicy rejects it before any I/O
is attempted).

Run with:
    pytest tests/integration/test_webpage_read_approval_end_to_end.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import EchoTool
from tools.builtin.webpage_read_tool import WebpageReadTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.approval_prompt import format_approval_request
from web.safe_web_fetcher import FetchedPage, SafeWebFetcher, WebFetchSuccess

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))

    def approval_events(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action_type") == "approval_decision"]


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class _FakeFetcher:
    """A minimal stand-in for SafeWebFetcher, returning a canned result."""

    def __init__(self, result: WebFetchSuccess) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebFetchSuccess:
        self.calls.append(url)
        return self._result


def _success_page(body: bytes, *, url: str = "https://example.com/") -> WebFetchSuccess:
    return WebFetchSuccess(
        page=FetchedPage(
            url=url,
            status_code=200,
            content_type="text/html",
            charset="utf-8",
            body=body,
            byte_count=len(body),
        )
    )


class _System:
    """The real components wired together, backed by a given fetcher."""

    def __init__(
        self,
        fetcher: object,
        *,
        timeout_seconds: int | None = None,
        clock: _FakeClock | None = None,
    ) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.registry.register_tool(EchoTool())
        self.fetcher = fetcher
        self.registry.register_tool(WebpageReadTool(fetcher))  # type: ignore[arg-type]
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,  # type: ignore[arg-type]
        )
        self.approvals = ApprovalManager(
            audit_logger=self.logger,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
            clock=clock,
        )
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            command_router=CommandRouter(self.registry),
            approval_manager=self.approvals,
        )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Requires approval before execution
# ---------------------------------------------------------------------------


def test_read_webpage_requires_yellow_approval_before_execution(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>Hello World</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )

    assert response.requires_confirmation is True
    assert response.success is False
    assert fetcher.calls == []  # nothing fetched yet


def test_security_classification_is_fixed_and_not_url_dependent(
    workspace: Path,
) -> None:
    """The *displayed* ApprovalRequest.action is the full, human-readable
    request sentence (by design - see JarvisOrchestrator.handle_request(),
    which passes the raw text through purely for display), so it varies
    with the URL. What must never vary is the *security tier*: the
    ToolExecutor classifies WebpageReadTool.action_for()'s own fixed
    "read webpage" string, never the raw sentence or the URL - proven
    here by two very different URLs (one entirely ordinary, one an
    SSRF-shaped adversarial target) both requiring the exact same
    YELLOW confirmation, with the identical reason text."""
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    system = _System(fetcher)

    response_one = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    response_two = system.orchestrator.handle_request(
        "read webpage http://169.254.169.254/latest/meta-data/; rm -rf /"
    )

    assert response_one.requires_confirmation is True
    assert response_two.requires_confirmation is True
    assert response_one.approval_request.reason == response_two.approval_request.reason
    assert response_one.approval_request.security_tier == (
        response_two.approval_request.security_tier
    )


# ---------------------------------------------------------------------------
# Approved: executes and returns webpage text
# ---------------------------------------------------------------------------


def test_approved_request_executes_the_tool_and_returns_webpage_text(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<html><body><p>Hello World</p></body></html>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert "Hello World" in executed.tool_result.output
    assert fetcher.calls == ["https://example.com/"]


def test_approved_request_output_never_contains_ansi_escape_sequences(
    workspace: Path,
) -> None:
    body = "<p>Hello \x1b[31mRED\x1b[0m World</p>".encode("utf-8")
    fetcher = _FakeFetcher(_success_page(body))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert "\x1b" not in executed.tool_result.output


# ---------------------------------------------------------------------------
# Denied: never executes
# ---------------------------------------------------------------------------


def test_denied_request_does_not_execute_the_tool(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>should never be fetched</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert fetcher.calls == []


# ---------------------------------------------------------------------------
# Timed out: never executes
# ---------------------------------------------------------------------------


def test_timed_out_approval_does_not_execute_the_tool(workspace: Path) -> None:
    clock = _FakeClock(_START)
    fetcher = _FakeFetcher(_success_page(b"<p>should never be fetched</p>"))
    system = _System(fetcher, timeout_seconds=60, clock=clock)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    clock.now = _START + timedelta(seconds=60)

    with pytest.raises(ApprovalError):
        system.approvals.approve(response.approval_request.request_id)

    assert fetcher.calls == []


def test_timeout_is_recorded_as_a_timeout_not_a_decision(workspace: Path) -> None:
    clock = _FakeClock(_START)
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    system = _System(fetcher, timeout_seconds=60, clock=clock)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    clock.now = _START + timedelta(seconds=60)
    system.approvals.has_pending(response.approval_request.request_id)  # trigger sweep

    assert system.approvals.list_pending() == []
    assert fetcher.calls == []


# ---------------------------------------------------------------------------
# Approval metadata/reason/action are safe and understandable
# ---------------------------------------------------------------------------


def test_approval_reason_is_specific_and_understandable(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    reason = response.approval_request.reason.lower()

    assert "external" in reason or "web" in reason or "network" in reason


def test_formatted_approval_prompt_shows_the_url_but_no_other_metadata(
    workspace: Path,
) -> None:
    """Nathan can see exactly what he is approving: the approval prompt's
    Action line carries the full original request sentence (including
    the URL) - this is deliberate transparency, mirroring every other
    tool-backed command (e.g. "copy file a.txt to b.txt" shows both
    paths the same way). Separately, ApprovalRequest.metadata itself
    stays empty for this tool, exactly like every other simple,
    single-tool YELLOW request (metadata is only ever populated by
    JarvisOrchestrator for other request shapes, never here) - so
    "Details:" never appears in the formatted prompt."""
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    system = _System(fetcher)

    distinctive_url = "https://a-very-distinctive-marker-url.example/path"
    response = system.orchestrator.handle_request(f"read webpage {distinctive_url}")

    formatted = format_approval_request(response.approval_request)
    assert distinctive_url in formatted
    assert "read webpage" in formatted
    assert response.approval_request.metadata == {}
    assert "Details:" not in formatted


# ---------------------------------------------------------------------------
# Unsafe/rejected URL: clean failure, never bypasses approval/security
# ---------------------------------------------------------------------------


def test_unsafe_url_still_requires_approval_and_then_fails_cleanly(
    workspace: Path,
) -> None:
    """A URL that WebFetchPolicy will reject still goes through the exact
    same YELLOW approval gate first (classification depends only on the
    fixed "read webpage" action, never the URL) - approval is not a
    safety check for URL-shape, and rejecting the URL is not a way to
    skip approval either. Uses the real SafeWebFetcher: no network call
    ever happens, since WebFetchPolicy rejects the target before any
    I/O is attempted."""
    system = _System(SafeWebFetcher())

    response = system.orchestrator.handle_request(
        "read webpage http://169.254.169.254/latest/meta-data/"
    )
    assert response.requires_confirmation is True
    assert response.approval_request.reason  # a real, non-empty reason was given

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert executed.tool_result.success is False


def test_declined_unsafe_url_also_never_fetches(workspace: Path) -> None:
    system = _System(SafeWebFetcher())

    response = system.orchestrator.handle_request(
        "read webpage http://localhost/admin"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False


# ---------------------------------------------------------------------------
# No AI/workflow/scheduler/dashboard/Inbox integration; no persistence
# ---------------------------------------------------------------------------


def test_no_ai_or_workflow_involvement_in_the_end_to_end_path(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>Hello</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert response.ai_suggestion is None
    assert response.workflow_trace == ()
    assert executed.ai_suggestion is None
    assert executed.workflow_trace == ()


def test_approved_read_writes_no_file_to_disk(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>Hello</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert list(workspace.iterdir()) == []


def test_decisions_are_audited(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>Hello</p>"))
    system = _System(fetcher)

    response = system.orchestrator.handle_request(
        "read webpage https://example.com/"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    approval_events = system.logger.approval_events()
    assert len(approval_events) == 1
    assert "outcome=approved" in str(approval_events[0]["detail"])
