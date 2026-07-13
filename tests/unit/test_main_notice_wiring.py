"""
test_main_notice_wiring.py

Composition tests for the Phase 22, Batch 1 CLI startup notice wiring in
main.py: main.build_startup_notice() and its use inside main.main().

These confirm the notice check is wired correctly, never blocks startup
on failure, and - critically - that main.build_orchestrator()'s own
return type and behavior are completely unchanged by this phase, since
26 other existing test files depend on it directly.

Run with:
    pytest tests/unit/test_main_notice_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

import main
from core.orchestrator import JarvisOrchestrator
from inbox.inbox_store import InboxStore
from storage.database import create_session_factory, initialize_database


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    and build_startup_notice() never touch the real .env file or the
    real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


# --- build_orchestrator() is unchanged ------------------------------------------


def test_build_orchestrator_still_returns_a_bare_orchestrator() -> None:
    """The widely-depended-on return type must not change for this
    narrow, unrelated addition."""
    result = main.build_orchestrator()
    assert isinstance(result, JarvisOrchestrator)


# --- build_startup_notice() ------------------------------------------------------


def test_build_startup_notice_returns_none_on_a_fresh_database() -> None:
    assert main.build_startup_notice() is None


def test_build_startup_notice_reports_a_scheduled_entry_created_by_another_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Simulates the real topology: a separate process (here, a second
    engine/session_factory over the same file) writes a scheduled Inbox
    entry, and build_startup_notice() - opening its own, independent
    connection - correctly reports it, exactly once."""
    db_path = tmp_path / "notice_wiring_check.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    # First call initializes the marker silently (no prior scheduled
    # entries exist yet) - matches the approved first-run behavior.
    assert main.build_startup_notice() is None

    writer_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(writer_engine)
    writer_inbox = InboxStore(create_session_factory(writer_engine))
    writer_inbox.append(
        source_type="scheduled_web_search_summary", source_query="q", body="b"
    )
    writer_engine.dispose()

    notice = main.build_startup_notice()
    assert notice is not None
    assert "1 scheduled inbox entry was added" in notice

    # A second call must not re-report the same entry.
    assert main.build_startup_notice() is None


def test_build_startup_notice_never_counts_interactive_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "notice_wiring_interactive_check.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    assert main.build_startup_notice() is None  # first-run silent init

    writer_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(writer_engine)
    writer_inbox = InboxStore(create_session_factory(writer_engine))
    writer_inbox.append(
        source_type="web_search_summary", source_query="q", body="b"
    )
    writer_engine.dispose()

    assert main.build_startup_notice() is None


def test_build_startup_notice_never_raises_when_settings_are_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure while opening this second, independent connection must
    never propagate - it is purely informational."""
    monkeypatch.setenv("DATABASE_PATH", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Even under a broken/unusual environment, this call must not raise.
    main.build_startup_notice()


# --- main() wiring: JarvisCLI receives the notice -------------------------------


def test_main_passes_startup_notice_into_jarvis_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeCLI:
        def __init__(
            self,
            orchestrator,
            *,
            startup_notice=None,
            voice_output=None,
            speak_responses=False,
            voice_input=None,
        ) -> None:
            captured["orchestrator"] = orchestrator
            captured["startup_notice"] = startup_notice

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(main, "JarvisCLI", _FakeCLI)
    monkeypatch.setattr(main, "build_startup_notice", lambda: "Jarvis notice: test")

    main.main()

    assert captured["startup_notice"] == "Jarvis notice: test"
    assert captured["ran"] is True
    assert isinstance(captured["orchestrator"], JarvisOrchestrator)


# --- structural: scheduler.py is untouched, notice store never touches Inbox writes --


def test_notice_wiring_does_not_import_scheduler_module() -> None:
    import ast
    import inspect

    source = inspect.getsource(main)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    assert "scheduler" not in imported_modules
    assert "run_one_poll_cycle" not in imported_names
