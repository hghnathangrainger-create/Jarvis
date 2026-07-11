"""
scheduling package

Durable storage for Nathan-configured daily web-search-summary schedules
(Phase 21).

This package's Batch 1 contents (scheduling.schedule_store) are storage
only: creating, listing, enabling, and disabling a schedule row. Nothing
in this package performs a web search, calls AI, writes an Inbox entry,
or executes anything - those concerns belong to the runner and the
narrow trust-safe execution helper added in a later batch, which this
package has no dependency on.

Does NOT:
    - Execute, approve, or schedule-run anything (Batch 1).
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      AIReasoningEngine, AIRouter, WebSearchProvider, or InboxStore.
    - Define any tool, CLI grammar, or dashboard code.
"""
