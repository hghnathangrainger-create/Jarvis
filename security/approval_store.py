"""
approval_store.py

SQLite-backed persistence for approval requests in the Jarvis AI Operating System.

Responsibilities:
    - Save, retrieve, and list approval requests.
    - Expire old requests based on TTL.
    - Provide recent approval history.

Does NOT:
    - Implement security manager logic (see security_manager.py).
    - Implement approval workflows (see security_manager.py).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from security.models import ApprovalRequest, ApprovalStatus, SecurityLevel


class ApprovalStore:
    """SQLite-backed store for approval request persistence.

    Attributes:
        _db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the approval store.

        Args:
            db_path: Path to the SQLite database. Uses in-memory if None.
        """
        if db_path is None:
            self._db_path = ":memory:"
        else:
            self._db_path = str(db_path)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        """Create the approval_requests table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                request_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_data TEXT NOT NULL DEFAULT '{}',
                level TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                response TEXT,
                responded_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_status
            ON approval_requests(status)
        """)
        self._conn.commit()

    def save_request(self, request: ApprovalRequest) -> None:
        """Save or update an approval request.

        Args:
            request: The approval request to persist.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO approval_requests
            (request_id, action, tool_name, input_data, level, requested_at,
             expires_at, status, response, responded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.action,
                request.tool_name,
                json.dumps(request.input_data),
                request.level.value,
                request.requested_at.isoformat(),
                request.expires_at.isoformat() if request.expires_at else None,
                request.status.value,
                request.response,
                request.responded_at.isoformat() if request.responded_at else None,
            ),
        )
        self._conn.commit()

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Retrieve an approval request by ID.

        Args:
            request_id: The unique request identifier.

        Returns:
            The ApprovalRequest if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM approval_requests WHERE request_id = ?",
            (request_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_request(row)

    def list_pending(self) -> list[ApprovalRequest]:
        """List all pending approval requests.

        Returns:
            List of pending ApprovalRequest objects, ordered by creation time.
        """
        cursor = self._conn.execute(
            "SELECT * FROM approval_requests WHERE status = 'pending' "
            "ORDER BY requested_at ASC"
        )
        return [self._row_to_request(row) for row in cursor.fetchall()]

    def list_recent(self, limit: int = 50) -> list[ApprovalRequest]:
        """List recent approval requests (all statuses).

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of ApprovalRequest objects, newest first.
        """
        cursor = self._conn.execute(
            "SELECT * FROM approval_requests ORDER BY requested_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_request(row) for row in cursor.fetchall()]

    def expire_old_requests(self, ttl_seconds: int = 300) -> int:
        """Expire requests that are past their TTL.

        Args:
            ttl_seconds: Time-to-live in seconds for pending requests.

        Returns:
            Number of requests that were expired.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
        cursor = self._conn.execute(
            """
            UPDATE approval_requests
            SET status = 'expired', responded_at = ?
            WHERE status = 'pending' AND requested_at < ?
            """,
            (datetime.now(timezone.utc).isoformat(), cutoff.isoformat()),
        )
        self._conn.commit()
        return cursor.rowcount

    def update_status(
        self,
        request_id: str,
        status: ApprovalStatus,
        response: str | None = None,
    ) -> bool:
        """Update the status of an approval request.

        Args:
            request_id: The request to update.
            status: The new status.
            response: Optional response text.

        Returns:
            True if the request was found and updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, response = ?, responded_at = ?
            WHERE request_id = ?
            """,
            (status.value, response, now, request_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _row_to_request(self, row: Any) -> ApprovalRequest:
        """Convert a database row to an ApprovalRequest."""
        return ApprovalRequest(
            request_id=row["request_id"],
            action=row["action"],
            tool_name=row["tool_name"],
            input_data=json.loads(row["input_data"]),
            level=SecurityLevel(row["level"]),
            requested_at=datetime.fromisoformat(row["requested_at"]),
            expires_at=(
                datetime.fromisoformat(row["expires_at"])
                if row["expires_at"]
                else None
            ),
            status=ApprovalStatus(row["status"]),
            response=row["response"],
            responded_at=(
                datetime.fromisoformat(row["responded_at"])
                if row["responded_at"]
                else None
            ),
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
