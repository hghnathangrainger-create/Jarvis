"""
memory_ingestion.py

Stored-memory ingestion for the Jarvis AI Operating System (Phase 9, Batch 1).

Responsibilities:
    - Acquire a single stored memory's content through MemoryManager.get(),
      and wrap a successful result as UNTRUSTED AI context.
    - Establish memory provenance by construction: this module is the sole
      caller of MemoryManager.get(memory_id) for this purpose, so the content
      it labels and the id it labels it with can never be supplied
      independently and drift apart (Phase 9 plan, Architectural Constraint 9;
      Security Invariant 9).
    - Represent every acquisition failure as data, never as a raised
      exception, matching FileIngestionResult's own convention.

Does NOT:
    - Retrieve through ToolExecutor or MemoryTool. MemoryTool's own "get"
      operation returns a CLI-formatted display string
      (f"[{record.id}] ({record.category}) {record.content}"), not the
      record's raw content; using it here would couple the AI ingestion
      boundary to presentation formatting (Phase 9 plan, Section 10).
    - Accept a pre-existing MemoryRecord or ToolResult.
    - Accept memory content and a source label as two independently-supplied
      values - both are derived from the one acquisition call this module
      makes itself.
    - Accept a caller-supplied trust level or an arbitrary source label.
    - Ever produce ContentTrust.JARVIS_TRUSTED - only
      AIContextBlock.from_untrusted() is ever used here.
    - Read MemoryRecord.source (capture-origin metadata, e.g. "conversation")
      to decide trust - trust is unconditionally UNTRUSTED regardless of
      that field's value.
    - Modify MemoryManager, MemoryTool, or the episodic memory store.
    - Add session-ownership authorization to memory retrieval.
      MemoryManager.get() remains the same unscoped-by-id lookup it already
      is today; that is documented, deferred work, not this batch's scope
      (Phase 9 plan, Sections 6, 12, 21, 22).
    - Introduce a generic, multi-source ingestion framework - this module is
      deliberately memory-specific, mirroring ai/file_ingestion.py's own
      file-specific narrowness (Phase 9 plan, Architectural Constraint 10).

This module is the only new production component this batch adds.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.context_models import AIContextBlock
from memory.memory_manager import MemoryManager

_DEFAULT_MAX_CHARS = 4000

#: Appended to truncated memory text so the AI is never led to believe it
#: received the complete memory content. Mirrors FileReadTool's own
#: truncation-notice convention; carries no memory id, category, or other
#: metadata - only the character limit that was applied.
_TRUNCATION_NOTICE_TEMPLATE = (
    "\n\n[... truncated: showing the first {max_chars} characters of this "
    "memory. Increase max_chars to read more.]"
)


@dataclass(frozen=True, slots=True)
class MemoryIngestionResult:
    """The result of attempting to ingest a stored memory for AI reasoning.

    Exactly one of `context`/`error` is populated, mirroring
    FileIngestionResult's own success/error convention.

    Attributes:
        context: An UNTRUSTED AIContextBlock wrapping the memory's content,
            on success. None on failure.
        error: A human-readable failure reason (for example, that no memory
            exists with the requested id). None on success.
        truncated: True when the memory's content was longer than max_chars
            and had to be shortened. Always False for a represented failure -
            a failure never claims that acquired content was truncated,
            since no content was ever acquired.
    """

    context: AIContextBlock | None = None
    error: str | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        """Reject any construction that does not represent exactly one outcome.

        Raises:
            ValueError: If both `context` and `error` are set, if neither is
                set, or if `truncated` is True without a `context` present.
        """
        if self.context is not None and self.error is not None:
            raise ValueError(
                "MemoryIngestionResult cannot carry both a context and an "
                "error - ingestion either succeeded (context) or failed "
                "(error), never both."
            )
        if self.context is None and self.error is None:
            raise ValueError(
                "MemoryIngestionResult must carry either a context (success) "
                "or an error (failure) - it cannot represent neither."
            )
        if self.context is None and self.truncated:
            raise ValueError(
                "MemoryIngestionResult cannot report truncated=True without "
                "a context - a represented failure never claims that "
                "acquired memory content was truncated, since no content "
                "was ever acquired."
            )

    @property
    def success(self) -> bool:
        """Return whether ingestion produced usable AI context.

        Returns:
            True if `context` is present, False otherwise.
        """
        return self.context is not None


def ingest_memory_for_ai(
    memory_manager: MemoryManager,
    memory_id: int,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> MemoryIngestionResult:
    """Read a stored memory through the real Memory Manager and wrap it as AI context.

    This function performs exactly one acquisition: it calls
    memory_manager.get(memory_id) itself, and derives both the returned
    content and its provenance label from that same call's own returned
    MemoryRecord. There is no parameter through which a caller could supply
    memory content and a source label independently, so the two can never
    describe different things.

    MemoryManager.get() is already GREEN and read-only; this function adds no
    new security tier, approval requirement, or execution path. It never goes
    through ToolExecutor or MemoryTool - MemoryManager.get() is already the
    typed acquisition boundary for this source (Phase 9 plan, Section 10).

    Args:
        memory_manager: The MemoryManager used to retrieve the memory.
        memory_id: The id of the memory to read.
        max_chars: The maximum number of characters of the memory's content
            to include. Defaults to 4000, matching Phase 8's own default for
            consistency across ingestion sources - a disclosed judgement
            call, not token-aware model budgeting (Phase 9 plan, Section 16).

    Returns:
        A MemoryIngestionResult. On success, `context` is an
        AIContextBlock.from_untrusted(...) - never JARVIS_TRUSTED - labelled
        source=f"memory:{record.id}", using the *returned* record's own id,
        never merely the requested memory_id. `truncated` is True only when
        the memory's content exceeded max_chars. On failure (no memory with
        that id), `context` is None and `error` carries an honest,
        non-fabricated failure message.

    Raises:
        ValueError: If max_chars is not a positive integer.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be a positive integer, got {max_chars}.")

    record = memory_manager.get(memory_id)

    if record is None:
        return MemoryIngestionResult(error=f"No memory found with id {memory_id}.")

    text, truncated = _truncate(record.content, max_chars)

    return MemoryIngestionResult(
        context=AIContextBlock.from_untrusted(text, source=f"memory:{record.id}"),
        truncated=truncated,
    )


def _truncate(content: str, max_chars: int) -> tuple[str, bool]:
    """Shorten memory content to max_chars, with an honest truncation notice.

    Args:
        content: The memory's raw content (record.content only). No other
            field - id, category, source, session_id, or created_at - is ever
            part of the truncatable text payload.
        max_chars: The maximum number of characters of content to keep.

    Returns:
        A tuple of (text, truncated). When content already fits within
        max_chars, text is the content unchanged and truncated is False.
        Otherwise, text is the first max_chars characters of content followed
        by an explicit truncation notice, and truncated is True.
    """
    if len(content) <= max_chars:
        return content, False

    notice = _TRUNCATION_NOTICE_TEMPLATE.format(max_chars=max_chars)
    return f"{content[:max_chars]}{notice}", True
