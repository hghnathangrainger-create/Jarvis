"""
_process_lock_subprocess_helper.py

Standalone helper script for test_process_lock_subprocess.py (Approval-
to-Resume Handoff Interlock, Batch 1). Run as a real, independent
Python process - never imported - so ExecutionProcessLock's own
OS-enforced exclusivity is proven against a genuine second process,
not a mock.

Usage:
    python _process_lock_subprocess_helper.py <database_path> <hold_seconds>

Behaviour:
    - Attempts to acquire ExecutionProcessLock(Path(database_path)).
    - On success: prints "ACQUIRED" (flushed immediately, so the
      parent test can synchronise on it), sleeps for hold_seconds
      seconds, releases, prints "RELEASED", and exits 0.
    - On failure (ExecutionLockError, e.g. another process already
      holds it): prints "REJECTED" and exits 1.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from runtime.process_lock import ExecutionLockError, ExecutionProcessLock  # noqa: E402


def main() -> int:
    database_path = Path(sys.argv[1])
    hold_seconds = float(sys.argv[2])

    lock = ExecutionProcessLock(database_path)
    try:
        lock.acquire()
    except ExecutionLockError:
        print("REJECTED", flush=True)
        return 1

    print("ACQUIRED", flush=True)
    time.sleep(hold_seconds)
    lock.release()
    print("RELEASED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
