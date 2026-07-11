"""
inbox package

Durable, append-only storage for saved Jarvis-produced outputs (Phase 20).

This package contains only the storage layer (inbox.inbox_store). Producer
wiring (which existing command writes to it) and the dashboard's Inbox
view are separate, later batches - this package has no dependency on
either.

Does NOT:
    - Execute, approve, mutate, or schedule anything.
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      AIReasoningEngine, AIRouter, or WebSearchTool.
    - Define any producer or UI code.
"""
