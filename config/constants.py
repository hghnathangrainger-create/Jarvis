"""
constants.py

Central location for shared, immutable constants used across the Jarvis
AI Operating System.

Responsibilities:
    - Define application identity constants (name, version).
    - Define the SecurityTier enum used by the Security Manager and Planner.
    - Define other shared enumerations (intent types, action types, task states)
      that multiple subsystems must agree on.
    - Provide a single source of truth for values that would otherwise be
      duplicated or hardcoded across modules.

Does NOT:
    - Implement any application, AI, database, or workflow logic.
    - Read environment variables or load configuration (see settings.py).
    - Hold mutable state of any kind.

No magic numbers or magic strings should appear elsewhere in the codebase.
If a constant is shared by more than one module, it belongs here.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------

APP_NAME: Final[str] = "Jarvis"
APP_VERSION: Final[str] = "0.1.0"
APP_DESCRIPTION: Final[str] = "Jarvis AI Operating System"

#: Message printed when the application starts successfully.
STARTUP_BANNER: Final[str] = "Jarvis Online."


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class SecurityTier(Enum):
    """Risk classification applied to every action before execution.

    The Security Manager assigns one of these tiers to every action. The tier
    determines whether the action executes automatically, requires a timed
    confirmation, or requires explicit user approval.

    Attributes:
        GREEN: Safe, read-only, or reversible actions. Executed automatically.
        YELLOW: State-changing but recoverable actions. Executed after a timed
            user confirmation (see APPROVAL_TIMEOUT_SECONDS in settings).
        RED: Irreversible or high-consequence actions. Always require explicit
            user approval and never time out.
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# ---------------------------------------------------------------------------
# AI context trust (Phase 7, Batch 2)
# ---------------------------------------------------------------------------


class ContentTrust(Enum):
    """The trust origin of a piece of text supplied as context to an AI call.

    This is deliberately narrower than "do I trust this content" as a
    judgement call - it is a structural fact about origin, enforced by
    ai.context_models.AIContextBlock, not a label any caller can assign
    freely.

    Attributes:
        JARVIS_TRUSTED: Text authored directly by Jarvis's own code (for
            example, a system instruction), or the user's own literal,
            current-turn typed input. Never applies to stored memory, file
            or web content, tool output, prior AI-generated text, or any
            other historical conversation text, regardless of who originally
            wrote it - see AIContextBlock for the enforced construction
            guard that keeps this true.
        UNTRUSTED: Any other source. Structurally isolated from system
            instructions in every AI prompt (Phase 7, Batch 2) and scanned
            for injection patterns before use (Phase 7, Batch 3).
    """

    JARVIS_TRUSTED = "jarvis_trusted"
    UNTRUSTED = "untrusted"


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


class IntentType(Enum):
    """Classification of an incoming user request.

    The Intent Classifier assigns one of these types to every request. The
    type determines which subsystems the Jarvis Core activates to handle it.

    Attributes:
        CONVERSATIONAL: A question or statement requiring a direct response.
        TASK_SINGLE: A single-step action.
        TASK_MULTI: A goal requiring a multi-step plan.
        MEMORY_QUERY: A request to recall previously stored information.
        MEMORY_COMMAND: An instruction to remember or forget something.
        SYSTEM_COMMAND: A request to configure or control Jarvis itself.
    """

    CONVERSATIONAL = "conversational"
    TASK_SINGLE = "task_single"
    TASK_MULTI = "task_multi"
    MEMORY_QUERY = "memory_query"
    MEMORY_COMMAND = "memory_command"
    SYSTEM_COMMAND = "system_command"


# ---------------------------------------------------------------------------
# Planning and execution
# ---------------------------------------------------------------------------


class ActionType(Enum):
    """The kind of action a single plan step performs.

    Assigned by the Planner to each step and read by the Workflow Engine to
    decide how the step is executed.

    Attributes:
        AI_CALL: The step requests an AI response via the Jarvis Core.
        TOOL_CALL: The step executes a registered tool via the Tool Manager.
        USER_APPROVAL: The step pauses and waits for explicit user approval.
        BRANCH: The step is a conditional decision point.
        PARALLEL_GROUP: The step contains sub-steps that may run simultaneously.
    """

    AI_CALL = "ai_call"
    TOOL_CALL = "tool_call"
    USER_APPROVAL = "user_approval"
    BRANCH = "branch"
    PARALLEL_GROUP = "parallel_group"


class StepStatus(Enum):
    """The execution state of a single plan step.

    Managed by the Workflow Engine as it executes a plan. Every step moves
    through these states during execution.

    Attributes:
        PENDING: Scheduled but not yet started.
        RUNNING: Currently executing.
        WAITING: Awaiting an approval or an unmet dependency.
        PAUSED: Temporarily suspended by the user.
        COMPLETED: Finished successfully.
        FAILED: Could not complete after all retries.
        SKIPPED: Optional step bypassed due to failure or an unmet condition.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OnFailure(Enum):
    """The action taken when a plan step fails after exhausting its retries.

    Assigned by the Planner to each step and read by the Workflow Engine when
    a step's retry attempts are exhausted.

    Attributes:
        RETRY_WITH_ALTERNATIVE_PROVIDER: Retry the step using a different AI
            provider.
        RETRY_WITH_ALTERNATIVE_TOOL: Retry the step using a different tool.
        SKIP: Skip the step. Only valid for steps marked optional.
        ESCALATE_TO_USER: Pause the workflow and ask the user how to proceed.
        ABORT_PLAN: Stop the entire plan and report the failure.
    """

    RETRY_WITH_ALTERNATIVE_PROVIDER = "retry_with_alternative_provider"
    RETRY_WITH_ALTERNATIVE_TOOL = "retry_with_alternative_tool"
    SKIP = "skip"
    ESCALATE_TO_USER = "escalate_to_user"
    ABORT_PLAN = "abort_plan"


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


class LogLevel(Enum):
    """Supported logging verbosity levels.

    Mirrors the standard logging levels. Used to validate the LOG_LEVEL
    configuration value loaded by settings.py.

    Attributes:
        DEBUG: Detailed diagnostic information.
        INFO: Routine operational messages.
        WARNING: Recoverable problems or unexpected conditions.
        ERROR: Failures that prevented an operation from completing.
        CRITICAL: Severe failures that may compromise the running system.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventOutcome(Enum):
    """The result of an action recorded in the audit log.

    Attached to every event emitted to the Observability subsystem.

    Attributes:
        SUCCESS: The action completed successfully.
        FAILURE: The action failed.
        PENDING: The action is awaiting completion or approval.
        TIMEOUT: The action was aborted because an approval window expired.
        BLOCKED: The action was prevented by the Security Manager.
        FLAGGED: An anomaly recorded for review, without being executed,
            blocked, or awaiting approval - e.g. an AI-suggested GREEN
            action outside a plan's expected scope (Phase 7, Batch 4), or a
            suspicious prompt-injection pattern detected in untrusted AI
            context (Phase 7, Batch 5A). Distinct from SUCCESS, which is
            only ever recorded after something actually ran.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    FLAGGED = "flagged"


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryType(Enum):
    """The category of a stored memory entry.

    Used by the Memory Manager to route storage and retrieval to the correct
    backend and to scope queries.

    Attributes:
        WORKING: Short-lived context for the current session only.
        EPISODIC: Timestamped record of events, persisted across sessions.
        SEMANTIC: Facts and preferences (vector storage; Phase 2).
        PROCEDURAL: Reusable step-by-step processes.
        ENTITY: Structured records of people, projects, tools, and goals.
    """

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    ENTITY = "entity"


#: Phrase the user can include to suppress storage of the current exchange.
DO_NOT_REMEMBER_PHRASE: Final[str] = "do not remember this" 