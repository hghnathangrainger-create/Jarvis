"""
test_scheduler_runner.py

Unit tests for scheduler.py's run_one_poll_cycle (Phase 21, Batch 2): the
single-pass poll function that claims and runs due schedules.

These use the real ScheduleStore/InboxStore backed by a real in-memory
SQLite database, the real AIReasoningEngine/AIRouter/PromptBuilder (wired
to a fake AI provider), and a fake WebSearchProvider - proving the full
claim -> run -> Inbox pipeline at the poll-cycle level, without an
infinite loop.

Run with:
    pytest tests/unit/test_scheduler_runner.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.settings import Settings
from inbox.inbox_store import InboxStore
from scheduler import run_one_poll_cycle
from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database
from tools.web_search_provider import SearchResult, WebSearchProvider


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FakeAIProvider(AIProvider):
    def __init__(self, text: str = "A synthesis.") -> None:
        self._text = text
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return True


class _FakeSearchProvider(WebSearchProvider):
    def __init__(self, *, results: list[SearchResult] | None = None) -> None:
        self._results = results if results is not None else []
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return self._results


def _result() -> SearchResult:
    return SearchResult(title="A Title", url="https://example.com", snippet="A snippet.")


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=True,
    )


def _reasoning_engine(text: str = "A synthesis.") -> AIReasoningEngine:
    provider = _FakeAIProvider(text)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=True)


def _make_stores() -> tuple[ScheduleStore, InboxStore]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ScheduleStore(factory), InboxStore(factory)


def _local_now_as_utc(hour: int, minute: int) -> datetime:
    local_naive = datetime.now().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return local_naive.astimezone().astimezone(timezone.utc)


# --- basic poll cycle behavior --------------------------------------------------------


def test_due_schedule_runs_and_creates_one_inbox_entry() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="jarvis ai news", time_of_day="08:00")
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)

    assert ran == 1
    assert inbox.count() == 1


def test_not_due_schedule_does_not_run() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="q", time_of_day="20:00")
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)  # before 20:00

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)

    assert ran == 0
    assert inbox.count() == 0
    assert search_provider.calls == []


def test_disabled_schedule_does_not_run() -> None:
    schedules, inbox = _make_stores()
    record = schedules.create(query="q", time_of_day="08:00")
    schedules.disable(record.id)
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)

    assert ran == 0
    assert inbox.count() == 0


def test_repeated_poll_same_day_does_not_create_duplicate_entries() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="q", time_of_day="08:00")
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    first = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)
    second = run_one_poll_cycle(
        schedules, inbox, search_provider, reasoning, None, now=_local_now_as_utc(15, 0)
    )
    third = run_one_poll_cycle(
        schedules, inbox, search_provider, reasoning, None, now=_local_now_as_utc(23, 0)
    )

    assert first == 1
    assert second == 0
    assert third == 0
    assert inbox.count() == 1


def test_multiple_due_schedules_each_run_once() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="q1", time_of_day="08:00")
    schedules.create(query="q2", time_of_day="08:30")
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)

    assert ran == 2
    assert inbox.count() == 2


# --- AI-disabled / missing configuration ----------------------------------------------


def test_ai_reasoning_none_skips_without_claiming() -> None:
    """When AI reasoning is not enabled at all, no schedule is claimed -
    it remains eligible to catch up the same day once AI becomes
    available, rather than being consumed by a run that could never
    succeed."""
    schedules, inbox = _make_stores()
    record = schedules.create(query="q", time_of_day="08:00")
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    ran = run_one_poll_cycle(schedules, inbox, search_provider, None, None, now=now)

    assert ran == 0
    assert inbox.count() == 0
    # Crucially, the schedule was never claimed - last_run_at is still None.
    assert schedules.get(record.id).last_run_at is None


def test_schedule_can_still_run_same_day_after_ai_becomes_available() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="q", time_of_day="08:00")
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    # First poll: AI not yet enabled.
    run_one_poll_cycle(schedules, inbox, search_provider, None, None, now=now)
    assert inbox.count() == 0

    # Later the same day, AI becomes available.
    reasoning = _reasoning_engine()
    ran = run_one_poll_cycle(
        schedules, inbox, search_provider, reasoning, None, now=_local_now_as_utc(12, 0)
    )
    assert ran == 1
    assert inbox.count() == 1


# --- audit events at the poll-cycle level ---------------------------------------------


def test_claim_emits_schedule_claimed_event() -> None:
    schedules, inbox = _make_stores()
    schedules.create(query="q", time_of_day="08:00")
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    logger = _RecordingLogger()
    now = _local_now_as_utc(9, 0)

    run_one_poll_cycle(schedules, inbox, search_provider, reasoning, logger, now=now)

    claimed_events = [c for c in logger.calls if c["action_type"] == "schedule_claimed"]
    assert len(claimed_events) == 1


# --- malformed schedule resilience ----------------------------------------------------


def test_one_malformed_schedule_does_not_prevent_others_from_running() -> None:
    from storage.database import session_scope
    from storage.models import ScheduleEntry

    schedules, inbox = _make_stores()
    schedules.create(query="good query", time_of_day="08:00")

    # Insert a malformed row directly (bypassing create()'s own validation)
    # to simulate a corrupt/legacy row somehow present in the table.
    with session_scope(schedules._session_factory) as db:  # type: ignore[attr-defined]
        db.add(ScheduleEntry(query="bad", time_of_day="not-a-time", enabled=True))

    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    now = _local_now_as_utc(9, 0)

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None, now=now)

    # The good schedule still ran despite the malformed row sitting
    # alongside it - the poll cycle never crashed.
    assert ran >= 1
    assert inbox.count() >= 1
    entries = inbox.list_recent()
    assert any(e.source_query == "good query" for e in entries)


# --- single-pass contract (no infinite loop) -------------------------------------------


def test_run_one_poll_cycle_returns_and_does_not_loop() -> None:
    """A basic sanity check that this function is a single pass, not a
    loop - it must return promptly even with zero schedules."""
    schedules, inbox = _make_stores()
    reasoning = _reasoning_engine()
    search_provider = _FakeSearchProvider(results=[_result()])

    ran = run_one_poll_cycle(schedules, inbox, search_provider, reasoning, None)

    assert ran == 0


# --- structural: no approval/workflow/command-router involvement --------------------


def test_scheduler_module_imports_no_approval_workflow_or_command_router() -> None:
    import ast
    import inspect

    import scheduler as scheduler_module

    source = inspect.getsource(scheduler_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {"ApprovalManager", "WorkflowEngine", "CommandRouter", "ToolExecutor", "JarvisOrchestrator", "JarvisCLI"}
    assert imported_names & forbidden == set()


def test_scheduled_summary_runner_module_imports_no_approval_workflow_or_command_router() -> None:
    import ast
    import inspect

    import scheduling.scheduled_summary_runner as runner_module

    source = inspect.getsource(runner_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {"ApprovalManager", "WorkflowEngine", "CommandRouter", "ToolExecutor"}
    assert imported_names & forbidden == set()
