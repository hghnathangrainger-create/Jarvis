"""
file_ingestion.py

File-content ingestion for the Jarvis AI Operating System (Phase 8, Batch 1).

Responsibilities:
    - Acquire a single named file's contents through the existing, unmodified
      security gate (ToolExecutor executing the real "file_read" tool), and
      wrap a successful result as UNTRUSTED AI context.
    - Establish file provenance by construction: this module is the sole
      caller of ToolExecutor.execute("file_read", ...) for this purpose, so
      the content it labels and the path it labels it with can never be
      supplied independently and drift apart (Phase 8 plan, Architectural
      Constraint 9).
    - Represent every acquisition failure as data, never as a raised
      exception, matching ToolResult's own convention.

Does NOT:
    - Accept a pre-existing ToolResult from an external caller.
    - Accept file content and its source label as two independently-supplied
      values - both are derived from the one acquisition call this module
      makes itself.
    - Accept a caller-supplied trust level or an arbitrary source label.
    - Ever produce ContentTrust.JARVIS_TRUSTED - only
      AIContextBlock.from_untrusted() is ever used here.
    - Re-implement file reading, truncation, or binary detection - all of
      that already exists, tested, in tools.builtin.file_read_tool.FileReadTool;
      this module only ever consumes its result through ToolExecutor.
    - Decide what a caller should do with a failed ingestion (that is a
      Phase 8, Batch 2 concern) - it only reports the failure honestly.
    - Introduce a generic, multi-source ingestion framework. This module is
      deliberately file-specific; a future source (stored memory, a webpage)
      gets its own equally narrow module, following the same pattern, not a
      shared base class invented ahead of a second real example.

This module is the only new production component this batch adds beyond the
AIReasoningRequest/AIReasoningEngine fix in ai/reasoning_models.py and
ai/reasoning_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.context_models import AIContextBlock
from tools.executor import ToolExecutor

_TOOL_NAME = "file_read"
_DEFAULT_MAX_CHARS = 4000


@dataclass(frozen=True, slots=True)
class FileIngestionResult:
    """The result of attempting to ingest a file's contents for AI reasoning.

    Exactly one of `context`/`error` is populated, mirroring ToolResult's own
    success/error convention.

    Attributes:
        context: An UNTRUSTED AIContextBlock wrapping the file's contents, on
            success. None on failure.
        error: A human-readable failure reason, taken directly from the
            underlying file_read ToolResult. None on success.
    """

    context: AIContextBlock | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        """Reject any construction that does not represent exactly one outcome.

        Raises:
            ValueError: If both `context` and `error` are set (a success and
                a failure claimed at once), or if neither is set (no outcome
                at all). Exactly one must be present.
        """
        if self.context is not None and self.error is not None:
            raise ValueError(
                "FileIngestionResult cannot carry both a context and an "
                "error - ingestion either succeeded (context) or failed "
                "(error), never both."
            )
        if self.context is None and self.error is None:
            raise ValueError(
                "FileIngestionResult must carry either a context (success) "
                "or an error (failure) - it cannot represent neither."
            )

    @property
    def success(self) -> bool:
        """Return whether ingestion produced usable AI context.

        Returns:
            True if `context` is present, False otherwise.
        """
        return self.context is not None


def ingest_file_for_ai(
    executor: ToolExecutor,
    path: str,
    *,
    session_id: int | None = None,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> FileIngestionResult:
    """Read a file through the real security gate and wrap it as AI context.

    This function performs exactly one acquisition: it calls
    ToolExecutor.execute("file_read", ...) itself, with the given path, and
    derives both the returned content and its provenance label from that same
    call's own result. There is no parameter through which a caller could
    supply file content and a path label independently, so the two can never
    describe different things.

    The file_read tool is GREEN and already classified, gated, and audited by
    ToolExecutor exactly like any other call to it; this function adds no new
    security tier, approval requirement, or execution path.

    Args:
        executor: The ToolExecutor used to run the real, already-secured
            "file_read" tool.
        path: The file to read. The same value is used both for the
            acquisition call and for the returned context's source label, so
            the label always truthfully describes what was actually read.
        session_id: Optional session identifier, forwarded to ToolExecutor
            for the audit trail, exactly as any other tool call would.
        max_chars: The maximum number of characters to read, forwarded
            unchanged to FileReadTool's own existing, tested truncation
            policy. Defaults to FileReadTool's own default.

    Returns:
        A FileIngestionResult. On success, `context` is an
        AIContextBlock.from_untrusted(...) - never JARVIS_TRUSTED - labelled
        `source=f"file:{path}"`. On failure (missing path, not found, is a
        directory, permission denied, binary content, or any other reason
        FileReadTool/ToolExecutor already represents as a failed ToolResult),
        `context` is None and `error` carries the underlying failure message
        unchanged - never mislabelled as acquired file content.
    """
    result = executor.execute(
        _TOOL_NAME,
        {"path": path, "max_chars": max_chars},
        session_id=session_id,
    )

    if not result.success:
        return FileIngestionResult(error=result.error or "Failed to read file.")

    return FileIngestionResult(
        context=AIContextBlock.from_untrusted(result.output, source=f"file:{path}")
    )
