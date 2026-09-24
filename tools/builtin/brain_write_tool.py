"""
brain_write_tool.py

The YELLOW (approval-gated) brain tool: create ("remember") and update
one Markdown note in Nathan's external 3D brain.

BrainWriteTool is a YELLOW tool: creating or replacing a note changes
state, so its action is classified YELLOW and it runs only after explicit
approval through the normal ToolExecutor and ApprovalManager path - the
same gate every other write tool already uses. It is deliberately
conservative:

    - "remember" creates a NEW note only; it never overwrites an existing
      one (use an explicitly approved "update" for that).
    - "update" replaces an existing note only; it never creates a new one.
    - It never deletes, moves, renames, or edits any other file, never
      creates parent folders, and never touches anything outside the
      configured root/allowed folders (BrainService re-validates both).
    - Writes are atomic: a temporary file in the destination folder,
      then os.replace().

Before the approval prompt is shown, approval_metadata() reports the
exact resolved target path and a bounded preview of the proposed content
(as "Details" lines on the existing approval prompt), so a decision is
always made with the concrete target and proposal in view. The full
proposal itself is also present verbatim in the approval request's own
Action line (the raw command text), exactly like every other write
command in this repository.

Supported input (via input_data):
    op:      "remember" | "update" (required).
    title:   the note title or relative path (for op="remember").
    path:    the relative path of an existing note (for op="update").
    content: the full new note content (required for both).

Security classification (see action_for): two fixed, input-independent
action strings - "write brain note" and "update brain note" - each
YELLOW. User content never reaches the classified action string, so it
can never influence the tier.

Safety note:
    This tool does not enforce approval itself. Approval is enforced by
    the Tool Executor, which classifies this tool's action YELLOW and
    withholds it until an approved decision is supplied. This tool
    simply performs the write when it is finally allowed to run.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.brain_service import BrainError, BrainService

#: Maximum characters of the proposed content echoed on the approval
#: prompt's "Details" lines. The approval request's own Action line still
#: carries the complete raw command text; this preview exists so the
#: prompt stays readable, and its truncation is always disclosed.
_PREVIEW_CHARS = 1_500


class BrainWriteTool(BaseTool):
    """Creates or replaces one Markdown brain note (YELLOW; gated).

    Attributes:
        _service: The shared BrainService built from Settings in main.py.
    """

    def __init__(self, service: BrainService) -> None:
        """Initialise the tool with its shared service.

        Args:
            service: The configured BrainService instance.
        """
        self._service = service

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "brain_write".
        """
        return "brain_write"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Creates a new Markdown brain note or replaces an existing "
            "one. Sensitive: requires approval. Never deletes."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the fixed action string used for classification.

        A create changes state, so it is phrased as a "write brain note"
        action and an update as an "update brain note" action - both
        YELLOW. The string depends only on the fixed sub-command, never
        on the title, path, or content supplied, so classification can
        never vary with user input.

        Args:
            request: The request being handled.

        Returns:
            "update brain note" for op="update", otherwise "write brain
            note" - both classified YELLOW by SecurityManager's explicit
            brain rules.
        """
        if request.input_data.get("op") == "update":
            return "update brain note"
        return "write brain note"

    def approval_metadata(self, request: ToolRequest) -> dict[str, str]:
        """Describe the exact target and proposal for the approval prompt.

        Called by the Tool Executor only when this YELLOW action is
        withheld pending confirmation, so the existing approval prompt
        can show the concrete resolved target path and a bounded preview
        of the content that would be written. Never writes anything, and
        never raises: an unresolvable proposal is reported honestly as
        text instead.

        Args:
            request: The request being withheld.

        Returns:
            String key/value details for the approval request's "Details"
            section: operation, exact target path, and proposed content
            (bounded by _PREVIEW_CHARS with a disclosed marker).
        """
        op = request.input_data.get("op")
        content = request.input_data.get("content")
        content_text = content if isinstance(content, str) else ""

        metadata: dict[str, str] = {}
        reference = (
            request.input_data.get("path")
            if op == "update"
            else request.input_data.get("title")
        )
        reference_text = reference if isinstance(reference, str) else ""

        try:
            if op == "update":
                metadata["Operation"] = "replace an existing brain note"
                rel_path, target = self._service.plan_update(reference_text)
            else:
                metadata["Operation"] = "create a new brain note"
                rel_path, target = self._service.plan_create(reference_text)
            metadata["Target path"] = f"{rel_path}  ({target})"
        except BrainError as exc:
            metadata["Operation"] = (
                "replace an existing brain note"
                if op == "update"
                else "create a new brain note"
            )
            metadata["Target path"] = f"could not be resolved: {exc}"

        preview = content_text
        if len(preview) > _PREVIEW_CHARS:
            preview = (
                preview[:_PREVIEW_CHARS]
                + f"... [truncated: {len(content_text)} characters proposed "
                "in full via the command itself]"
            )
        metadata["Proposed content"] = preview if preview else "(empty)"
        return metadata

    def run(self, request: ToolRequest) -> ToolResult:
        """Perform the approved write.

        Only ever reached after the Tool Executor has classified this
        action YELLOW and an approved decision has been supplied. Both
        operations re-validate scope through BrainService before anything
        is written; writes are atomic.

        Args:
            request: The request. Recognised input keys: op, title (for
                remember), path (for update), content.

        Returns:
            A successful ToolResult naming the written note and its
            bounds, or a failed result with an honest reason. Nothing is
            ever written on failure, and nothing is ever deleted.
        """
        op = request.input_data.get("op")
        content = request.input_data.get("content")
        if not isinstance(content, str):
            return self.fail("Input 'content' must be text.")

        try:
            if op == "update":
                return self._run_update(request, content)
            if op == "remember":
                return self._run_remember(request, content)
        except BrainError as exc:
            return self.fail(str(exc))
        except OSError as exc:
            return self.fail(f"Could not write brain note: {exc}")

        return self.fail(
            "Missing or invalid 'op' (must be 'remember' or 'update')."
        )

    def _run_remember(self, request: ToolRequest, content: str) -> ToolResult:
        """Create a new note (never overwrites an existing one).

        Args:
            request: The request carrying "title".
            content: The new note's content.

        Returns:
            A successful ToolResult, or a failed one when the title is
            unsafe, the folder missing, the note already exists, or the
            content is empty/too large.
        """
        raw_title = request.input_data.get("title")
        if not isinstance(raw_title, str) or not raw_title.strip():
            return self.fail("Missing required input: 'title'.")

        rel_path, target = self._service.plan_create(raw_title)
        written = self._service.write(target, content, exclusive=True)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Created brain note: {rel_path} ({written} bytes written "
                f"to {target})."
            ),
            metadata={
                "rel_path": rel_path,
                "path": str(target),
                "chars_written": str(len(content)),
                "operation": "create",
            },
        )

    def _run_update(self, request: ToolRequest, content: str) -> ToolResult:
        """Replace an existing note (never creates, never deletes).

        Args:
            request: The request carrying "path".
            content: The replacement content.

        Returns:
            A successful ToolResult including an honest old/new size
            summary, or a failed one when the note is missing, out of
            scope, a symlink, or the content is empty/too large.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail("Missing required input: 'path'.")

        rel_path, target = self._service.plan_update(raw_path)
        try:
            old_bytes = target.stat().st_size
        except OSError:
            old_bytes = 0
        written = self._service.write(target, content)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Updated brain note: {rel_path} (replaced {old_bytes} "
                f"bytes with {written} bytes at {target})."
            ),
            metadata={
                "rel_path": rel_path,
                "path": str(target),
                "chars_written": str(len(content)),
                "operation": "update",
            },
        )
