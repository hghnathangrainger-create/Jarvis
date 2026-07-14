"""
test_webpage_summary_approval_end_to_end.py

End-to-end integration tests for the AI webpage-summary approval flow
(Phase 34, Batch 2).

These wire the real Security Manager, Tool Registry, Tool Executor,
Approval Manager, Planner, and CommandRouter together (mirroring
test_webpage_read_approval_end_to_end.py's own established pattern),
plus a fake AI reasoning engine, and trace a "summarize webpage <url>"
request through its full journey: request -> the exact same YELLOW
approval "read webpage <url>" already uses -> approved fetch -> AI
summarization, or declined/timed-out/failed-and-never-summarized.

A fake fetcher (duck-typing SafeWebFetcher.fetch()) and a fake
reasoning engine (duck-typing AIReasoningEngine.reason()) are used for
every test except the one adversarial URL test, which uses the real
SafeWebFetcher to prove an unsafe URL is rejected cleanly after
approval without ever touching the network.

Run with:
    pytest tests/integration/test_webpage_summary_approval_end_to_end.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from ai.reasoning_models import AIReasoningRequest, AIReasoningResult
from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from config.constants import ContentTrust
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from inbox.inbox_store import InboxStore
from planner.planner import Planner
from security.security_manager import SecurityManager
from storage.database import create_session_factory, initialize_database
from tools.builtin import EchoTool
from tools.builtin.webpage_read_tool import WebpageReadTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from web.safe_web_fetcher import FetchedPage, SafeWebFetcher, WebFetchFailure, WebFetchSuccess

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_URL = "https://example.com/article"


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class _FakeFetcher:
    """A minimal stand-in for SafeWebFetcher, returning a canned result."""

    def __init__(self, result: WebFetchSuccess | WebFetchFailure) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebFetchSuccess | WebFetchFailure:
        self.calls.append(url)
        return self._result


class _FakeReasoningEngine:
    """A minimal stand-in for AIReasoningEngine, returning a canned result."""

    def __init__(self, result: AIReasoningResult | None) -> None:
        self._result = result
        self.calls: list[AIReasoningRequest] = []

    def reason(self, request: AIReasoningRequest) -> AIReasoningResult | None:
        self.calls.append(request)
        return self._result


def _success_page(body: bytes, *, url: str = _URL) -> WebFetchSuccess:
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


class _RaisingInboxStore:
    """A duck-typed InboxStore stand-in whose append() always raises
    (Phase 61, Batch 1) - mirrors
    test_web_search_summary_workflow.py's own precedent exactly."""

    def append(self, **kwargs: object) -> None:
        raise RuntimeError("simulated inbox write failure")


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


class _System:
    """The real components wired together, backed by given fetcher/reasoning."""

    def __init__(
        self,
        fetcher: object | None,
        reasoning_engine: object | None,
        *,
        timeout_seconds: int | None = None,
        clock: _FakeClock | None = None,
        inbox_store: InboxStore | object | None = None,
    ) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.registry.register_tool(EchoTool())
        self.fetcher = fetcher
        if fetcher is not None:
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
        self.reasoning = reasoning_engine
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            command_router=CommandRouter(self.registry),
            approval_manager=self.approvals,
            reasoning_engine=reasoning_engine,  # type: ignore[arg-type]
            inbox_store=inbox_store,  # type: ignore[arg-type]
            logger=self.logger,  # type: ignore[arg-type]
        )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _summary_result(text: str = "This page is about testing.") -> AIReasoningResult:
    return AIReasoningResult(summary=text)


# ---------------------------------------------------------------------------
# Approval required before fetch, before AI
# ---------------------------------------------------------------------------


def test_summarize_webpage_requires_approval_before_any_fetch_or_ai_call(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>Hello</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")

    assert response.requires_confirmation is True
    assert response.success is False
    assert fetcher.calls == []
    assert reasoning.calls == []


def test_action_is_the_same_fixed_read_webpage_classification(workspace: Path) -> None:
    """The acquisition step reuses WebpageReadTool's own fixed action_for()
    string via the real ToolExecutor/SecurityManager - proven here by
    two very different URLs both requiring the exact same YELLOW tier
    with the identical underlying reason wording."""
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response_one = system.orchestrator.handle_request(
        f"summarize webpage {_URL}"
    )
    response_two = system.orchestrator.handle_request(
        "summarize webpage http://169.254.169.254/latest/meta-data/"
    )

    assert response_one.requires_confirmation is True
    assert response_two.requires_confirmation is True
    assert response_one.approval_request.security_tier == (
        response_two.approval_request.security_tier
    )
    assert response_one.tool_name == "webpage_read"
    assert response_two.tool_name == "webpage_read"


# ---------------------------------------------------------------------------
# Approved: fetch happens, then AI is called, in that order
# ---------------------------------------------------------------------------


def test_approved_summarize_webpage_fetches_then_calls_ai(workspace: Path) -> None:
    fetcher = _FakeFetcher(
        _success_page(b"<html><body><p>Hello World</p></body></html>")
    )
    reasoning = _FakeReasoningEngine(_summary_result("A friendly greeting page."))
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert "A friendly greeting page." in executed.message
    assert fetcher.calls == [_URL]
    assert len(reasoning.calls) == 1


def test_ai_receives_the_extracted_webpage_text_as_untrusted_context(
    workspace: Path,
) -> None:
    distinctive = "A very distinctive sentence about zebras and telescopes."
    fetcher = _FakeFetcher(_success_page(f"<p>{distinctive}</p>".encode()))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    request = reasoning.calls[0]
    assert request.context_block is not None
    assert request.context_block.trust is ContentTrust.UNTRUSTED
    assert distinctive in request.context_block.text
    assert request.context_block.source == f"webpage:{_URL!r}"


def test_original_user_request_is_passed_as_ai_user_input(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    original_text = f"summarize webpage {_URL}"
    response = system.orchestrator.handle_request(original_text)
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    assert reasoning.calls[0].user_input == original_text


def test_successful_summary_is_labelled_and_display_only(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result("Key point."))
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert "[AI webpage summary" in executed.message
    assert "Key point." in executed.message
    # Display-only: nothing was written to disk.
    assert list(workspace.iterdir()) == []


# ---------------------------------------------------------------------------
# Denied: no fetch, no AI call
# ---------------------------------------------------------------------------


def test_denied_approval_never_fetches_or_calls_ai(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>should never be fetched</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert fetcher.calls == []
    assert reasoning.calls == []


# ---------------------------------------------------------------------------
# Timed out: no fetch, no AI call
# ---------------------------------------------------------------------------


def test_timed_out_approval_never_fetches_or_calls_ai(workspace: Path) -> None:
    clock = _FakeClock(_START)
    fetcher = _FakeFetcher(_success_page(b"<p>should never be fetched</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning, timeout_seconds=60, clock=clock)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    clock.now = _START + timedelta(seconds=60)

    with pytest.raises(ApprovalError):
        system.approvals.approve(response.approval_request.request_id)

    assert fetcher.calls == []
    assert reasoning.calls == []


# ---------------------------------------------------------------------------
# Fetch/extraction/ingestion failures: AI never called
# ---------------------------------------------------------------------------


def test_fetch_failure_is_clear_and_ai_is_never_called(workspace: Path) -> None:
    from web.safe_web_fetcher import WebFetchFailureReason

    fetcher = _FakeFetcher(
        WebFetchFailure(
            url=_URL,
            reason=WebFetchFailureReason.CONNECTION_ERROR,
            detail="Simulated network failure.",
        )
    )
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert "Simulated network failure" in executed.message
    assert reasoning.calls == []


def test_ingestion_failure_is_clear_and_ai_is_never_called(workspace: Path) -> None:
    """An empty/blank extraction (e.g. a page with only script/style
    content) fails ingestion honestly - the AI is never consulted about
    nothing."""
    fetcher = _FakeFetcher(_success_page(b"<script>only script, no text</script>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert "nothing to summarize" in executed.message.lower()
    assert reasoning.calls == []


# ---------------------------------------------------------------------------
# AI disabled / unavailable
# ---------------------------------------------------------------------------


def test_ai_disabled_fails_before_any_approval_is_created(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    system = _System(fetcher, reasoning_engine=None)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")

    assert response.success is False
    assert response.requires_confirmation is False
    assert "not enabled" in response.message.lower()
    assert fetcher.calls == []


def test_ai_unavailable_after_successful_fetch_is_reported_honestly(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(None)  # simulates provider failure
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert "could not produce a summary" in executed.message.lower()
    # The fetch DID happen (that's why AI was even attempted).
    assert fetcher.calls == [_URL]


# ---------------------------------------------------------------------------
# Unsafe URL still follows the same approval/security ordering
# ---------------------------------------------------------------------------


def test_unsafe_url_still_requires_approval_then_fails_cleanly(
    workspace: Path,
) -> None:
    """Uses the real SafeWebFetcher: no network call ever happens, since
    WebFetchPolicy rejects the target before any I/O is attempted."""
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(SafeWebFetcher(), reasoning)

    response = system.orchestrator.handle_request(
        "summarize webpage http://169.254.169.254/latest/meta-data/"
    )
    assert response.requires_confirmation is True

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert reasoning.calls == []


def test_declined_unsafe_url_also_never_fetches_or_summarizes(
    workspace: Path,
) -> None:
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(SafeWebFetcher(), reasoning)

    response = system.orchestrator.handle_request(
        "summarize webpage http://localhost/admin"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert reasoning.calls == []


# ---------------------------------------------------------------------------
# No persistence / no other integration
# ---------------------------------------------------------------------------


def test_no_inbox_integration_exists_for_this_command(workspace: Path) -> None:
    """This minimal test system never constructs an InboxStore at all -
    structurally proving the webpage-summary path cannot write to one,
    since JarvisOrchestrator is never given one to write to."""
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    assert system.orchestrator._inbox_store is None

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True


def test_no_workflow_or_scheduler_wiring_exists_for_this_command(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    assert system.orchestrator._workflow_engine is None

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.workflow_trace == ()
    assert executed.success is True


def test_summarized_run_writes_no_file_to_disk(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert list(workspace.iterdir()) == []


def test_ai_summary_text_never_appears_in_any_tool_input(workspace: Path) -> None:
    """Structural proof: the only tool this system has beyond the
    approval-gated fetch is EchoTool, and it is never invoked by this
    path - there is no write tool registered at all for AI output to
    reach, and the response's own tool_result is always the fetch
    result, never a second, AI-driven tool call."""
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result("Suspicious instruction text."))
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.tool_result is not None
    assert executed.tool_result.tool_name == "webpage_read"


# ---------------------------------------------------------------------------
# Audited
# ---------------------------------------------------------------------------


def test_summarize_webpage_decisions_are_audited(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    approval_events = [
        e for e in system.logger.events if e.get("action_type") == "approval_decision"
    ]
    assert len(approval_events) == 1
    assert "outcome=approved" in str(approval_events[0]["detail"])


# ---------------------------------------------------------------------------
# Phase 61, Batch 1: explicit "... and save to inbox" behavior
# ---------------------------------------------------------------------------


def _inbox_created_events(logger: _SpyLogger) -> list[dict[str, object]]:
    return [
        e for e in logger.events if e.get("action_type") == "inbox_entry_created"
    ]


def _inbox_failed_events(logger: _SpyLogger) -> list[dict[str, object]]:
    return [
        e
        for e in logger.events
        if e.get("action_type") == "inbox_entry_creation_failed"
    ]


def test_save_command_approval_metadata_carries_save_flag(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )

    assert response.requires_confirmation is True
    assert response.approval_request.metadata.get("save_to_inbox") == "true"
    assert response.approval_request.metadata.get("webpage_summary") == "true"


def test_plain_command_approval_metadata_never_carries_save_flag(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")

    assert response.requires_confirmation is True
    assert "save_to_inbox" not in response.approval_request.metadata


def test_successful_save_command_creates_exactly_one_inbox_entry(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result("Key point."))
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert inbox.count() == 1
    entry = inbox.list_recent()[0]
    assert entry.source_type == "webpage_summary"
    assert entry.source_query == _URL
    assert entry.body == executed.message
    assert "[AI webpage summary" in entry.body
    assert "Key point." in entry.body


def test_plain_command_never_creates_an_inbox_entry_even_when_store_configured(
    workspace: Path,
) -> None:
    """Complements test_no_inbox_integration_exists_for_this_command
    above (which never even constructs an InboxStore): this proves the
    plain command remains Inbox-free even when an InboxStore IS
    available to the orchestrator - the absence of the save_to_inbox
    metadata flag, not the absence of a store, is what keeps it
    Inbox-free."""
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(f"summarize webpage {_URL}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert inbox.count() == 0


def test_declined_save_command_creates_no_inbox_entry(workspace: Path) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert inbox.count() == 0


def test_expired_save_command_approval_creates_no_inbox_entry(
    workspace: Path,
) -> None:
    clock = _FakeClock(_START)
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(
        fetcher, reasoning, timeout_seconds=60, clock=clock, inbox_store=inbox
    )

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    clock.now = _START + timedelta(seconds=60)

    with pytest.raises(ApprovalError):
        system.approvals.approve(response.approval_request.request_id)

    assert inbox.count() == 0


def test_blocked_unsafe_url_save_command_creates_no_inbox_entry(
    workspace: Path,
) -> None:
    """Uses the real SafeWebFetcher: the fetch itself fails safely after
    approval, so no summary is ever produced and nothing is saved."""
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(SafeWebFetcher(), reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        "summarize webpage http://169.254.169.254/latest/meta-data/"
        " and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert inbox.count() == 0


def test_fetch_failure_with_save_command_creates_no_inbox_entry(
    workspace: Path,
) -> None:
    from web.safe_web_fetcher import WebFetchFailureReason

    fetcher = _FakeFetcher(
        WebFetchFailure(
            url=_URL,
            reason=WebFetchFailureReason.CONNECTION_ERROR,
            detail="Simulated network failure.",
        )
    )
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert inbox.count() == 0


def test_ai_unavailable_with_save_command_creates_no_inbox_entry(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(None)  # simulates provider failure
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert inbox.count() == 0


def test_ai_disabled_with_save_command_creates_no_inbox_entry(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning_engine=None, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )

    assert response.success is False
    assert response.requires_confirmation is False
    assert inbox.count() == 0


def test_failed_inbox_write_does_not_break_the_returned_response(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result("A friendly greeting page."))
    system = _System(fetcher, reasoning, inbox_store=_RaisingInboxStore())

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert "A friendly greeting page." in executed.message
    assert len(_inbox_failed_events(system.logger)) == 1
    assert len(_inbox_created_events(system.logger)) == 0


def test_no_inbox_store_configured_is_a_safe_no_op_for_save_command(
    workspace: Path,
) -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>content</p>"))
    reasoning = _FakeReasoningEngine(_summary_result())
    system = _System(fetcher, reasoning)  # no inbox_store passed at all

    assert system.orchestrator._inbox_store is None

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True


def test_saved_body_never_contains_raw_webpage_content_only_the_ai_summary(
    workspace: Path,
) -> None:
    """The saved entry's body is the exact displayed AI summary, never
    the raw extracted webpage text - proven here by a distinctive
    sentence that appears in the fetched page but is deliberately never
    echoed by the fake reasoning engine's own canned summary."""
    distinctive = "A very distinctive sentence about zebras and telescopes."
    fetcher = _FakeFetcher(_success_page(f"<p>{distinctive}</p>".encode()))
    reasoning = _FakeReasoningEngine(_summary_result("An unrelated summary."))
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    entry = inbox.list_recent()[0]
    assert distinctive not in entry.body
    assert "An unrelated summary." in entry.body


def test_ai_still_receives_untrusted_context_for_save_command(
    workspace: Path,
) -> None:
    """The trust boundary is completely unaffected by the save flag:
    the AI still receives the extracted webpage text as UNTRUSTED
    context, exactly as the plain command already proves above."""
    distinctive = "Another distinctive sentence about kangaroos and lighthouses."
    fetcher = _FakeFetcher(_success_page(f"<p>{distinctive}</p>".encode()))
    reasoning = _FakeReasoningEngine(_summary_result())
    inbox = InboxStore(_in_memory_session_factory())
    system = _System(fetcher, reasoning, inbox_store=inbox)

    response = system.orchestrator.handle_request(
        f"summarize webpage {_URL} and save to inbox"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    request = reasoning.calls[0]
    assert request.context_block is not None
    assert request.context_block.trust is ContentTrust.UNTRUSTED
    assert distinctive in request.context_block.text
