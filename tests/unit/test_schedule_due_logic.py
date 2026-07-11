"""
test_schedule_due_logic.py

Unit tests for ScheduleStore.claim_due() (Phase 21, Batch 2): the atomic
due/claim guard.

These use a real SQLite database, exercising the actual atomic SQL
UPDATE ... WHERE ... construct against real stored rows - the exact
mechanism empirically verified during Batch 2 planning/implementation
(SQLite's date()/time() functions with the 'localtime' modifier
correctly treat this project's naive-but-UTC-in-substance stored values
as UTC).

Run with:
    pytest tests/unit/test_schedule_due_logic.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database


def _make_store() -> ScheduleStore:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ScheduleStore(factory)


@pytest.fixture()
def store() -> ScheduleStore:
    return _make_store()


def _local_now_as_utc(hour: int, minute: int) -> datetime:
    """Build a UTC-aware 'now' whose host-local time is exactly hour:minute today.

    Since claim_due converts its `now` argument to local time via
    .astimezone(), the simplest reliable way to construct "local time is
    exactly H:M" in a timezone-independent test is to build a local
    datetime directly (which astimezone() on an aware value will not
    re-shift if it is already the value we want to appear as local), then
    convert it to UTC only as a formality for the type signature.
    """
    local_naive = datetime.now().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    local_aware = local_naive.astimezone()  # attaches the host's own local tzinfo
    return local_aware.astimezone(timezone.utc)


# --- basic due/not-due cases --------------------------------------------------------


def test_claim_succeeds_when_due_and_never_run(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(9, 0)  # local 09:00, past the 08:00 schedule
    assert store.claim_due(schedule.id, now=now) is True


def test_claim_fails_before_scheduled_time(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(7, 0)  # local 07:00, before 08:00
    assert store.claim_due(schedule.id, now=now) is False


def test_claim_succeeds_exactly_at_scheduled_time(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(8, 0)
    assert store.claim_due(schedule.id, now=now) is True


def test_claim_succeeds_well_after_scheduled_time(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(23, 0)
    assert store.claim_due(schedule.id, now=now) is True


def test_claim_fails_for_disabled_schedule(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    store.disable(schedule.id)
    now = _local_now_as_utc(9, 0)
    assert store.claim_due(schedule.id, now=now) is False


def test_claim_fails_for_unknown_schedule_id(store: ScheduleStore) -> None:
    now = _local_now_as_utc(9, 0)
    assert store.claim_due(99999, now=now) is False


# --- at-most-once-per-local-date / same-day catch-up / no multi-day backfill -------


def test_claim_fails_when_already_claimed_today(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(9, 0)
    assert store.claim_due(schedule.id, now=now) is True
    # A later poll the same day must not claim again.
    later_same_day = _local_now_as_utc(15, 0)
    assert store.claim_due(schedule.id, now=later_same_day) is False


def test_claim_succeeds_again_the_next_day(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    today = _local_now_as_utc(9, 0)
    assert store.claim_due(schedule.id, now=today) is True

    tomorrow = today + timedelta(days=1)
    assert store.claim_due(schedule.id, now=tomorrow) is True


def test_same_day_catch_up_when_runner_was_not_active_at_scheduled_time(
    store: ScheduleStore,
) -> None:
    """The runner "missed" 08:00 entirely (was not running), but checks
    at 11:00 the same day - it should still catch up and run once."""
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(11, 0)
    assert store.claim_due(schedule.id, now=now) is True


def test_no_multi_day_backfill(store: ScheduleStore) -> None:
    """A schedule "missed" for 3 days (the runner was off) must run
    exactly once when it comes back, never three times."""
    schedule = store.create(query="q", time_of_day="08:00")
    day1 = _local_now_as_utc(9, 0)
    assert store.claim_due(schedule.id, now=day1) is True

    # The runner comes back 3 days later - only one claim succeeds.
    day4 = day1 + timedelta(days=3)
    assert store.claim_due(schedule.id, now=day4) is True
    # And it does not somehow allow claiming again the same day.
    assert store.claim_due(schedule.id, now=day4 + timedelta(hours=1)) is False


def test_last_run_at_is_updated_at_claim_time(store: ScheduleStore) -> None:
    schedule = store.create(query="q", time_of_day="08:00")
    assert store.get(schedule.id).last_run_at is None
    now = _local_now_as_utc(9, 0)
    store.claim_due(schedule.id, now=now)
    updated = store.get(schedule.id)
    assert updated.last_run_at is not None


def test_last_run_at_is_updated_even_if_caller_never_runs_the_action(
    store: ScheduleStore,
) -> None:
    """claim_due's own contract: last_run_at is set at claim time, before
    the caller's own run succeeds or fails - so a claimed-then-failed run
    does not retry the same day (the failure-semantics guarantee lives
    one layer up, in scheduled_summary_runner/scheduler, but the
    non-retry property is anchored here, at the store level)."""
    schedule = store.create(query="q", time_of_day="08:00")
    now = _local_now_as_utc(9, 0)
    assert store.claim_due(schedule.id, now=now) is True
    # Simulate "the caller crashed / the run failed" - nothing else is
    # called. A later poll the same day must still not reclaim it.
    later = _local_now_as_utc(20, 0)
    assert store.claim_due(schedule.id, now=later) is False


# --- two-runner / race simulation ----------------------------------------------------


def test_two_concurrent_claim_attempts_only_one_succeeds(tmp_path) -> None:
    """Simulates two independent runner processes (two separate engines
    against the same file-backed database) racing to claim the same
    schedule at the same moment - only one may succeed."""
    from sqlalchemy import create_engine

    db_path = tmp_path / "race_check.db"
    engine_a = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine_a)
    store_a = ScheduleStore(create_session_factory(engine_a))
    schedule = store_a.create(query="q", time_of_day="08:00")
    engine_a.dispose()

    now = _local_now_as_utc(9, 0)

    engine_1 = create_engine(f"sqlite:///{db_path}")
    store_1 = ScheduleStore(create_session_factory(engine_1))
    engine_2 = create_engine(f"sqlite:///{db_path}")
    store_2 = ScheduleStore(create_session_factory(engine_2))

    try:
        result_1 = store_1.claim_due(schedule.id, now=now)
        result_2 = store_2.claim_due(schedule.id, now=now)
        # Exactly one of the two concurrent claim attempts succeeds.
        assert sorted([result_1, result_2]) == [False, True]
    finally:
        engine_1.dispose()
        engine_2.dispose()


# --- malformed/corrupt schedule row handling -----------------------------------------


def test_claim_due_on_malformed_time_of_day_does_not_raise(tmp_path) -> None:
    """A defensive check: even a row somehow bearing a non-standard
    time_of_day string must not raise - the lexical string comparison
    simply evaluates to a boolean, never an exception."""
    from sqlalchemy import create_engine

    from storage.database import session_scope
    from storage.models import ScheduleEntry

    db_path = tmp_path / "malformed_check.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with session_scope(factory) as db:
        entry = ScheduleEntry(query="q", time_of_day="not-a-time", enabled=True)
        db.add(entry)
        db.flush()
        schedule_id = entry.id

    store = ScheduleStore(factory)
    now = _local_now_as_utc(9, 0)
    # Must not raise - whatever the boolean result is, it is safe.
    store.claim_due(schedule_id, now=now)
    engine.dispose()
