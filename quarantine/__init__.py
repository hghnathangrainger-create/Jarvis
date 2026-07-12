"""
quarantine package

Durable metadata storage for Jarvis's file-quarantine feature (Phase 37).

This package contains only the storage layer (quarantine.quarantine_store).
It records where a quarantined file originally came from, so a future
restore command has trustworthy information to work with - it does not
itself restore, clean up, or permanently delete anything.

Does NOT:
    - Execute, approve, restore, or clean up anything.
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      AIReasoningEngine, AIRouter, WebSearchTool, or any ai/workflow/
      scheduler/dashboard/inbox module.
    - Define any tool, command, or UI code.
"""
