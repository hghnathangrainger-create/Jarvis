"""
workflow_plan_factory.py

Deterministic Plan construction for the approved fixed workflow commands:

    remember this and show it back: <text>              (Phase 15)
    remember this and forget it: <text>                 (Phase 15)
    create file <path> with <content> and show it        (Phase 17)
    update memory <id>: <content> and show it back        (Phase 17)
    search files for <pattern> and copy first to <destination>  (Phase 29)

Responsibilities:
    - Build an exact, fixed, two-step Plan for each approved workflow
      command, using only already-registered tool names ("memory",
      "memory_forget", "file_create", "file_read", "memory_update",
      "file_search", "file_copy") and the exact input shapes those tools
      already require.

Does NOT:
    - Parse general natural language, or accept any tool name/argument
      derived from user input beyond the free-text content/path/pattern
      the command already carries. Parsing of the command text itself is
      CommandRouter's responsibility (Phase 17, Batch 2; Phase 29); this
      module only ever receives already-extracted, plain values.
    - Call AIReasoningEngine, Planner.create_plan(), SecurityManager,
      ToolExecutor, or ToolRegistry. This module has none of those
      dependencies.
    - Execute anything, or create an approval request.
    - Access the result of any step for the two Phase 17 workflows'
      literal-sharing case (create_and_read): the same already-known
      `path` value is placed directly into both steps' tool_input by
      this factory itself - never propagated by WorkflowEngine, and
      never read from FileCreateTool's own metadata["path"]. For
      update_and_show and search_and_copy (Phase 29), this factory marks
      step 2's input_from_previous_step=True and never inspects or
      guesses what step 1 will actually produce - identical to the two
      Phase 15 workflows' own established convention. For
      search_and_copy specifically, this factory never reads, selects
      among, or disambiguates search matches itself - that is entirely
      WorkflowEngine's existing, unmodified previous-step propagation
      mechanism, keyed off FileSearchTool's own "matched_path" metadata
      (set only for exactly one match).

This is a narrow, fixed-shape factory - not a general Plan-building
framework. It creates Plans only for the five workflow types named
above, each always exactly two steps, in a fixed order, using fixed
tool names.

Design constraint (Phase 30, Post-Phase-29 review): every workflow this
factory builds is deterministic and tool-only, by design, not by
accident. AI reasoning steps are intentionally excluded and must not be
added without a separate, approved architecture review. Reason: the
approval prompt shown before a YELLOW step runs (ui/approval_prompt.py)
displays only the action, reason, risk tier, and ApprovalRequest.metadata
- never the step's full tool_input. That is safe today because every
propagated or literal value written by an existing workflow is either
text Nathan typed directly in his own command, or a plain path/id
propagated from a trusted tool result (WorkflowEngine's own
_PROPAGATED_FIELDS). It would not be safe for an AI-summary step whose
generated text then flowed silently into a following write step: Nathan
would be asked to approve a file write without ever seeing the text
being written. Do not pipe AI-generated prose into a write tool this way.
More templates beyond the five above are also paused, not closed - add
one only for a specific request or a clearly demonstrated recurring
task, not because the machinery exists.
"""

from __future__ import annotations

from config.constants import SecurityTier
from planner.plan_models import Plan, PlanStep

_MEMORY_TOOL_NAME = "memory"
_MEMORY_FORGET_TOOL_NAME = "memory_forget"
_MEMORY_UPDATE_TOOL_NAME = "memory_update"
_FILE_CREATE_TOOL_NAME = "file_create"
_FILE_READ_TOOL_NAME = "file_read"
_FILE_SEARCH_TOOL_NAME = "file_search"
_FILE_COPY_TOOL_NAME = "file_copy"

#: Display-only classification metadata, reused here only for PlanStep.tier
#: transparency (matching planner.planner.Planner._classify's own existing
#: use of SecurityManager.classify_action() for the same display purpose).
#: These are the exact, already-established, unconditional classifications
#: security.security_manager's own rule table already assigns to these
#: exact action strings ("save memory" -> GREEN, "show memory" -> GREEN,
#: "forget memory" -> YELLOW, "create text file" -> YELLOW, "read file" ->
#: GREEN, "update memory" -> YELLOW) - confirmed by direct inspection, not
#: guessed. This module never imports or calls SecurityManager itself:
#: PlanStep.tier remains non-authoritative metadata regardless, and
#: ToolExecutor re-classifies the real action fresh, at execution time,
#: every time - this is true whether or not these values are populated at
#: all.
_SAVE_TIER = SecurityTier.GREEN
_SAVE_REASON = "Saving a memory the user explicitly asked to store is safe."
_SHOW_TIER = SecurityTier.GREEN
_SHOW_REASON = "Showing information is read-only and safe."
_FORGET_TIER = SecurityTier.YELLOW
_FORGET_REASON = "Forgetting a memory removes it and must be confirmed."
_CREATE_FILE_TIER = SecurityTier.YELLOW
_CREATE_FILE_REASON = "Creating a file changes state and must be confirmed."
_READ_FILE_TIER = SecurityTier.GREEN
_READ_FILE_REASON = "Reading a file is read-only and safe."
_UPDATE_MEMORY_TIER = SecurityTier.YELLOW
_UPDATE_MEMORY_REASON = (
    "Updating a memory changes stored content and must be confirmed."
)
_SEARCH_FILES_TIER = SecurityTier.GREEN
_SEARCH_FILES_REASON = "Searching files by name or content is read-only and safe."
_COPY_FILE_TIER = SecurityTier.YELLOW
_COPY_FILE_REASON = "Copying a file creates new state and should be confirmed."


def build_remember_and_show_plan(content: str) -> Plan:
    """Build the fixed, two-step Plan for "remember this and show it back".

    Step 1 saves `content` as a new memory. Step 2 shows the memory just
    saved - its input_from_previous_step=True marks that its "memory_id"
    input must come from step 1's own result; this factory never computes,
    guesses, or reads that value itself.

    Args:
        content: The raw, unvalidated free text to remember. Emptiness is
            not checked here - the underlying memory tool already rejects
            empty content honestly at execution time.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Save this as a new memory.",
        action="save memory",
        tier=_SAVE_TIER,
        reason=_SAVE_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "save", "content": content},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Show the memory that was just saved.",
        action="show memory",
        tier=_SHOW_TIER,
        reason=_SHOW_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "get"},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=f"remember this and show it back: {content}",
        steps=(step_1, step_2),
    )


def build_remember_and_forget_plan(content: str) -> Plan:
    """Build the fixed, two-step Plan for "remember this and forget it".

    Step 1 saves `content` as a new memory. Step 2 forgets the memory
    just saved - its input_from_previous_step=True marks that its
    "memory_id" input must come from step 1's own result; this factory
    never computes, guesses, or reads that value itself, and never
    creates an approval request (WorkflowEngine's existing, unmodified
    pause/ApprovalManager path handles that when step 2 is classified
    YELLOW at execution time).

    Args:
        content: The raw, unvalidated free text to remember.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Save this as a new memory.",
        action="save memory",
        tier=_SAVE_TIER,
        reason=_SAVE_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "save", "content": content},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Forget the memory that was just saved.",
        action="forget memory",
        tier=_FORGET_TIER,
        reason=_FORGET_REASON,
        tool_name=_MEMORY_FORGET_TOOL_NAME,
        tool_input={},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=f"remember this and forget it: {content}",
        steps=(step_1, step_2),
    )


def build_create_and_read_plan(path: str, content: str) -> Plan:
    """Build the fixed, two-step Plan for "create file ... and show it".

    Step 1 creates a new file at `path` with `content`. Step 2 reads that
    exact same file back. Unlike the memory workflows above, this
    workflow needs no runtime propagation at all: `path` is already
    known in full before either step runs (Nathan supplied it directly
    in his own command text), so this factory simply places the same
    literal `path` value into both steps' tool_input itself.
    input_from_previous_step is False on both steps - WorkflowEngine
    never reads FileCreateTool's own metadata["path"], and this factory
    never asks it to (Phase 17, Batch 1).

    Args:
        path: The raw, unvalidated file path to create and then read
            back. Emptiness is not checked here - FileCreateTool already
            rejects an empty path honestly at execution time.
        content: The raw, unvalidated text to write into the new file.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Create this new file.",
        action="create text file",
        tier=_CREATE_FILE_TIER,
        reason=_CREATE_FILE_REASON,
        tool_name=_FILE_CREATE_TOOL_NAME,
        tool_input={"path": path, "content": content},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Show the file that was just created.",
        action="read file",
        tier=_READ_FILE_TIER,
        reason=_READ_FILE_REASON,
        tool_name=_FILE_READ_TOOL_NAME,
        tool_input={"path": path},
        input_from_previous_step=False,
    )
    return Plan(
        user_request=f"create file {path} with {content} and show it",
        steps=(step_1, step_2),
    )


def build_update_and_show_plan(memory_id: int, content: str) -> Plan:
    """Build the fixed, two-step Plan for "update memory ... and show it back".

    Step 1 updates the memory identified by `memory_id` to `content`.
    Step 2 shows that same memory - its input_from_previous_step=True
    marks that its "memory_id" input must come from step 1's own result,
    via WorkflowEngine's existing, unmodified propagation mechanism; this
    factory never computes, guesses, or reuses the originally-parsed
    `memory_id` for step 2 itself (Phase 17, Batch 1).

    Args:
        memory_id: The id of the memory to update, as parsed from
            Nathan's own command text.
        content: The raw, unvalidated replacement content.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Update this memory's content.",
        action="update memory",
        tier=_UPDATE_MEMORY_TIER,
        reason=_UPDATE_MEMORY_REASON,
        tool_name=_MEMORY_UPDATE_TOOL_NAME,
        tool_input={
            "operation": "update",
            "memory_id": memory_id,
            "content": content,
        },
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Show the memory that was just updated.",
        action="show memory",
        tier=_SHOW_TIER,
        reason=_SHOW_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "get"},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=f"update memory {memory_id}: {content} and show it back",
        steps=(step_1, step_2),
    )


def build_file_search_and_copy_plan(pattern: str, destination: str) -> Plan:
    """Build the fixed, two-step Plan for "search files for <pattern> and
    copy first to <destination>" (Phase 29).

    Step 1 searches for files whose name matches `pattern` (name mode
    only - content-mode search is deliberately not supported by this
    workflow). Step 2 copies the single matched file to `destination` -
    its input_from_previous_step=True marks that its "source" input must
    come from step 1's own result, via WorkflowEngine's existing,
    unmodified previous-step propagation mechanism (keyed off
    FileSearchTool's own "matched_path" result metadata). This factory
    never reads, selects among, or disambiguates search matches itself,
    and never parses FileSearchTool's own human-readable output text.

    FileSearchTool only ever sets "matched_path" when its search finds
    exactly one match - never for zero matches, and never for more than
    one. When it is absent, WorkflowEngine's own existing "usable" check
    stops the workflow honestly before file_copy ever runs, with step
    1's own output (listing what was actually found, or reporting no
    matches) visible in the workflow trace - this factory needs no
    special zero-match/multiple-match handling of its own.

    Args:
        pattern: The raw, unvalidated filename pattern to search for.
            Emptiness is not checked here - FileSearchTool itself rejects
            an empty query honestly at execution time.
        destination: The raw, unvalidated destination path to copy the
            matched file to. Emptiness is not checked here - FileCopyTool
            itself rejects an empty destination honestly at execution
            time.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Search for a file matching this name pattern.",
        action="search files",
        tier=_SEARCH_FILES_TIER,
        reason=_SEARCH_FILES_REASON,
        tool_name=_FILE_SEARCH_TOOL_NAME,
        tool_input={"mode": "name", "query": pattern},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Copy the matched file to the destination.",
        action="copy file",
        tier=_COPY_FILE_TIER,
        reason=_COPY_FILE_REASON,
        tool_name=_FILE_COPY_TOOL_NAME,
        tool_input={"destination": destination},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=(
            f"search files for {pattern} and copy first to {destination}"
        ),
        steps=(step_1, step_2),
    )
