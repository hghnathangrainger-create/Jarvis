"""
runtime package

Process-lifetime, cross-process runtime concerns for the Jarvis AI
Operating System - distinct from storage.database's own connection/
schema concerns and from config.settings's own configuration-loading
concerns.

Currently holds exactly one module: process_lock.py (Approval-to-Resume
Handoff Interlock, Batch 1 - docs/phase_98_approval_handoff_plan.md).
"""

from __future__ import annotations
