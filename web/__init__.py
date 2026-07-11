"""
web

Webpage fetch/read safety foundation for the Jarvis AI Operating System
(Phase 32 — Webpage Fetch/Read Safety Foundation).

Batch 1 (this batch) provides only WebFetchPolicy: pure, deterministic
URL validation with no network I/O. There is no registered tool, no
CommandRouter grammar, and no AI/workflow/dashboard/scheduler
integration - nothing in the running system calls this package yet.

See docs/phase_32_implementation_plan.md for the full phase plan and
batch sequence.
"""

from __future__ import annotations
