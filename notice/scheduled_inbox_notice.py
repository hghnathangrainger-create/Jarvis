"""
scheduled_inbox_notice.py

The pure, content-free CLI startup notice builder (Phase 22, Batch 1).

Responsibilities:
    - Read the last-seen marker, count scheduled Inbox entries newer
      than it, and build one honest, content-free notice line - or
      decide there is nothing to report.
    - Advance the marker to the highest entry id actually counted.
    - Initialize the marker silently on the very first call, never
      dumping a historical backlog into a noisy first notice.

Does NOT:
    - Ever read or include an entry's source_query or body in the
      returned text - only a count, an id, and a timestamp, all drawn
      from InboxStore.count_since()'s own narrow return shape.
    - Raise. Every failure (a raising notice_store or inbox_store) is
      treated as "nothing to report this run" - never a reason to
      affect CLI startup.
    - Count interactive ("web_search_summary") entries - only
      SCHEDULED_SOURCE_TYPE, imported directly from
      scheduling.scheduled_summary_runner rather than redefined here, so
      the two values can never silently drift apart.
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      or any AI-facing module. This function's only two collaborators
      are InboxStore and ScheduledInboxNoticeStore.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from scheduling.scheduled_summary_runner import SCHEDULED_SOURCE_TYPE


class _InboxCountSource(Protocol):
    def count_since(
        self, *, source_type: str, after_id: int | None
    ) -> tuple[int, int | None, datetime | None]: ...


class _NoticeMarkerStore(Protocol):
    def get_last_seen_entry_id(self) -> int | None: ...
    def set_last_seen_entry_id(self, entry_id: int) -> None: ...


def build_scheduled_inbox_notice(
    inbox_store: _InboxCountSource, notice_store: _NoticeMarkerStore
) -> str | None:
    """Build one honest scheduled-Inbox startup notice, or None.

    Args:
        inbox_store: The store to count scheduled Inbox entries from.
        notice_store: The store holding the last-seen marker.

    Returns:
        A single, content-free notice line naming only a count and a
        timestamp, or None when there is nothing to report (no marker
        yet - silent first-run initialization; no new scheduled entries;
        or any internal failure, which is never allowed to raise out of
        this function).
    """
    try:
        last_seen_id = notice_store.get_last_seen_entry_id()
    except Exception:  # noqa: BLE001 - a marker read failure must never block startup
        return None

    is_first_run = last_seen_id is None

    try:
        count, latest_id, latest_created_at = inbox_store.count_since(
            source_type=SCHEDULED_SOURCE_TYPE, after_id=last_seen_id
        )
    except Exception:  # noqa: BLE001 - an Inbox read failure must never block startup
        return None

    if is_first_run:
        # Silent initialization: never dump a historical backlog into
        # the very first notice after upgrading to this phase. The
        # marker is always advanced here - even to the sentinel 0 when
        # no scheduled entries exist yet - so a "first run" state can
        # never persist across multiple calls and silently swallow the
        # very first real entry whenever it eventually appears.
        try:
            notice_store.set_last_seen_entry_id(
                latest_id if latest_id is not None else 0
            )
        except Exception:  # noqa: BLE001 - a write failure must never block startup
            pass
        return None

    if latest_id is not None:
        try:
            notice_store.set_last_seen_entry_id(latest_id)
        except Exception:  # noqa: BLE001 - a write failure must never block startup
            # The same notice may reappear next launch - honest and
            # safe, never a crash and never lost/fabricated content.
            pass

    if count == 0:
        return None

    entry_word = "entry" if count == 1 else "entries"
    was_were = "was" if count == 1 else "were"
    timestamp = (
        latest_created_at.strftime("%Y-%m-%d %H:%M")
        if latest_created_at is not None
        else "unknown"
    )
    return (
        f"Jarvis notice: {count} scheduled inbox {entry_word} {was_were} added "
        f"since your last check. Latest: {timestamp}. Open the dashboard Inbox "
        "to review them."
    )
