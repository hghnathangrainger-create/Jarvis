"""
dashboard package

Local, read-only dashboard for existing durable Jarvis state (Phase 19).

This package contains only the read-model/query composition layer
(dashboard.read_model). The tkinter/ttk presentation layer lives in
ui/dashboard_app.py, and the process entry point is the repository-root
dashboard.py script - neither is part of this package, mirroring how
ui/cli.py and main.py sit outside core/.

Does NOT:
    - Execute, approve, mutate, or schedule anything.
    - Import CommandRouter, ToolExecutor, the live ApprovalManager,
      WorkflowEngine, AIReasoningEngine, AIRouter, or WebSearchTool.
    - Define any UI code.
"""
