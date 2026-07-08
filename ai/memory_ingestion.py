"""
memory_ingestion.py

Stored-memory ingestion for the Jarvis AI Operating System (Phase 9, Batch 1;
extended in Phase 10, Batch 1 with a multi-record ingestion primitive).

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
    - (Phase 10, Batch 1) Acquire a validated, ordered, already-deduplicated
      set of stored memories, retrieved in the supplied order, and combine
      them into exactly one UNTRUSTED AI context, with full, itemized,
      disclosed accounting for every requested id - never silently
      collapsing missing/errored/omitted ids into a single generic failure.

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
    - (Phase 10, Batch 1) Deduplicate, reorder, sort, or otherwise reinterpret
      the supplied memory_ids sequence. Stable deduplication and ordering
      validation are the exclusive responsibility of the future command-
      parsing layer (docs/phase_10_implementation_plan.md, Section 10.1) -
      exactly the same ownership split Phase 9 already established between
      _parse_memory_id (validation, in the orchestrator) and
      ingest_memory_for_ai (acquisition, here). This function trusts its
      caller's ordering and uniqueness contract; it does not enforce it.
    - (Phase 10, Batch 1) Add a second injection scanner. Combined context
      still reaches PromptBuilder's existing, unmodified, automatic scan
      unchanged - this module never scans anything itself (Phase 10 plan,
      Section 8.3).
    - (Phase 10, Batch 1) Claim that its per-record delimiter framing is a
      security boundary, a parser, or cryptographic isolation of any kind.
      It is structural serialization only - plain text, embedded inside one
      UNTRUSTED block, exactly as untrusted as the memory content around it
      (Phase 10 plan, Section 8.3).

This module is the only new production component this batch adds.
"""

from __future__ import annotations

from collections.abc import Sequence
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


# ---------------------------------------------------------------------------
# Multi-record ingestion (Phase 10, Batch 1)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RECORDS = 10
_DEFAULT_MAX_TOTAL_CHARS = 20_000

#: Per-record framing. Structural serialization only - plain text embedded
#: inside one UNTRUSTED block, never a security boundary, never parsed back
#: out by any Jarvis code (Phase 10 plan, Section 8.3). Chosen to be
#: distinctive enough to reduce *accidental* collision with ordinary
#: user-typed notes; it cannot, and is not claimed to, prevent a *deliberate*
#: imitation - see the module docstring and the Phase 10 plan for the full
#: disclosure of that residual, accepted ambiguity.
_RECORD_DELIMITER_TEMPLATE = "\n----- Memory {memory_id} -----\n"


@dataclass(frozen=True, slots=True)
class MemorySetIngestionResult:
    """The result of ingesting a set of stored memories for AI reasoning.

    Exactly one of `context`/`error` is populated, mirroring
    MemoryIngestionResult's own success/error convention, generalised from
    one record to a set. Every requested id is accounted for in exactly one
    of `included`, `not_found`, `retrieval_errors`, or `omitted_for_size` -
    no outcome is ever silently collapsed into a single generic failure.

    Attributes:
        context: A single UNTRUSTED AIContextBlock combining every included
            record's content, on partial or full success. None when no
            requested id could be included (total failure).
        error: A human-readable summary of why no memory could be included
            (which ids were not found, errored, or omitted for size). None
            on success.
        included: The ids that were actually retrieved and included in
            `context`, in final included order - never merely echoing the
            requested order, since some requested ids may have been dropped.
        not_found: Requested ids for which MemoryManager.get() returned None.
        retrieval_errors: Requested ids for which the retrieval call itself
            raised an exception - a single bad id never aborts the batch.
        omitted_for_size: Requested ids that were successfully retrieved and
            individually truncated, but were wholly excluded because
            including them would have exceeded the combined total-size
            budget. Never partially included a second time to fill
            remaining space.
        truncated_records: The subset of `included` whose own content was
            shortened by the existing, unmodified per-record _truncate()
            helper - carried through with no new database read.
    """

    context: AIContextBlock | None = None
    error: str | None = None
    included: tuple[int, ...] = ()
    not_found: tuple[int, ...] = ()
    retrieval_errors: tuple[int, ...] = ()
    omitted_for_size: tuple[int, ...] = ()
    truncated_records: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If both `context` and `error` are set, if neither is
                set, if `context` is set but `included` is empty, if
                `context` is None but `included` is non-empty, or if
                `truncated_records` names an id not present in `included`.
        """
        if self.context is not None and self.error is not None:
            raise ValueError(
                "MemorySetIngestionResult cannot carry both a context and an "
                "error - ingestion either succeeded (context) or failed "
                "(error), never both."
            )
        if self.context is None and self.error is None:
            raise ValueError(
                "MemorySetIngestionResult must carry either a context "
                "(success) or an error (failure) - it cannot represent "
                "neither."
            )
        if self.context is not None and not self.included:
            raise ValueError(
                "MemorySetIngestionResult cannot carry a context with no "
                "included records - a combined context implies at least "
                "one record was actually included."
            )
        if self.context is None and self.included:
            raise ValueError(
                "MemorySetIngestionResult cannot report included records "
                "without a context - a represented failure never claims "
                "that any content was actually combined."
            )
        if not set(self.truncated_records) <= set(self.included):
            raise ValueError(
                "MemorySetIngestionResult.truncated_records must be a "
                "subset of included - a record cannot be reported as "
                "truncated unless it was actually included."
            )

    @property
    def success(self) -> bool:
        """Return whether ingestion produced usable, combined AI context.

        Returns:
            True if `context` is present, False otherwise.
        """
        return self.context is not None


def ingest_memories_for_ai(
    memory_manager: MemoryManager,
    memory_ids: Sequence[int],
    *,
    max_records: int = _DEFAULT_MAX_RECORDS,
    max_chars_per_record: int = _DEFAULT_MAX_CHARS,
    max_total_chars: int = _DEFAULT_MAX_TOTAL_CHARS,
) -> MemorySetIngestionResult:
    """Read a set of stored memories and combine them into one AI context.

    This function trusts its caller's ordering and uniqueness contract
    completely: `memory_ids` is expected to already be stably deduplicated
    (first-occurrence order preserved) and already validated against
    `max_records`, by the future command-parsing layer
    (docs/phase_10_implementation_plan.md, Section 10.1/17). This function
    does not deduplicate, sort, or otherwise reorder `memory_ids` itself -
    it retrieves each id exactly once, strictly in the order supplied,
    exactly as many times as it appears. A caller that supplies a duplicate
    id anyway will see that record retrieved and included once per
    occurrence, consuming cardinality and size budget once per occurrence -
    this is a deliberate consequence of trusting the caller's contract, not
    a defect; deduplication belongs exclusively to the command-parsing layer
    (mirroring the same split Phase 9 established between _parse_memory_id
    and ingest_memory_for_ai).

    The exact size-budget sequence (docs/phase_10_implementation_plan.md,
    Section 15.1) is: retrieval in supplied order -> existing, unmodified
    Phase 9 per-record truncation (_truncate(), reused as-is) -> a running
    total-size check in that same supplied order. A record that does not fit
    within the remaining total budget is never truncated a second time - it
    is wholly omitted and itemized in `omitted_for_size`.

    A single id's retrieval error or absence never aborts the batch: every
    other id is still processed, and partial success (a context combining
    only the ids that resolved) is the expected, deliberately-permitted
    common case. Total failure (context=None) occurs only when zero ids
    could be included.

    MemoryManager.get() is already GREEN and read-only; this function adds
    no new security tier, approval requirement, or execution path, and never
    goes through ToolExecutor or MemoryTool, exactly like its single-record
    sibling ingest_memory_for_ai().

    Args:
        memory_manager: The MemoryManager used to retrieve each memory.
        memory_ids: The already-validated, already-deduplicated, ordered
            sequence of memory ids to include. Must be non-empty and no
            longer than max_records.
        max_records: The maximum number of ids this function will process in
            one call. Defaults to 10. Exceeding it raises ValueError - a
            defensive backstop for a contract the command-parsing layer is
            expected to already enforce, mirroring ingest_memory_for_ai's own
            max_chars backstop.
        max_chars_per_record: The maximum number of characters of each
            individual record's content to include, forwarded unchanged to
            the existing _truncate() helper. Defaults to 4000, matching
            ingest_memory_for_ai's own default.
        max_total_chars: The maximum combined number of characters across
            every included record's own framed contribution (its delimiter
            plus its own, already-truncated content). Defaults to 20,000.

    Returns:
        A MemorySetIngestionResult. On success (at least one id included),
        `context` is a single AIContextBlock.from_untrusted(...) - never
        JARVIS_TRUSTED - combining every included record's own delimited
        contribution, labelled source=f"memory-set:{included ids}" using the
        ids actually included, never merely the ids requested. On total
        failure (no id could be included), `context` is None and `error`
        honestly summarises why.

    Raises:
        ValueError: If memory_ids is empty, if len(memory_ids) exceeds
            max_records, or if max_chars_per_record/max_total_chars is not a
            positive integer.
    """
    if not memory_ids:
        raise ValueError("memory_ids must not be empty.")
    if len(memory_ids) > max_records:
        raise ValueError(
            f"Too many memory ids requested ({len(memory_ids)}); the "
            f"maximum is {max_records}."
        )
    if max_chars_per_record < 1:
        raise ValueError(
            f"max_chars_per_record must be a positive integer, got "
            f"{max_chars_per_record}."
        )
    if max_total_chars < 1:
        raise ValueError(
            f"max_total_chars must be a positive integer, got {max_total_chars}."
        )

    included: list[int] = []
    not_found: list[int] = []
    retrieval_errors: list[int] = []
    omitted_for_size: list[int] = []
    truncated_records: list[int] = []
    contributions: list[str] = []
    running_total = 0

    for memory_id in memory_ids:
        try:
            record = memory_manager.get(memory_id)
        except Exception:
            # A single id's retrieval error must never abort the whole
            # batch - itemized here, never a fabricated content path.
            retrieval_errors.append(memory_id)
            continue

        if record is None:
            not_found.append(memory_id)
            continue

        text, truncated = _truncate(record.content, max_chars_per_record)
        contribution = _RECORD_DELIMITER_TEMPLATE.format(memory_id=record.id) + text

        if running_total + len(contribution) > max_total_chars:
            # Never sliced a second time to fit - wholly omitted, itemized.
            omitted_for_size.append(memory_id)
            continue

        running_total += len(contribution)
        included.append(record.id)
        if truncated:
            truncated_records.append(record.id)
        contributions.append(contribution)

    if not included:
        return MemorySetIngestionResult(
            error=_build_total_failure_message(
                not_found, retrieval_errors, omitted_for_size
            ),
            not_found=tuple(not_found),
            retrieval_errors=tuple(retrieval_errors),
            omitted_for_size=tuple(omitted_for_size),
        )

    combined_text = "".join(contributions).strip()
    source = "memory-set:" + ",".join(str(i) for i in included)

    return MemorySetIngestionResult(
        context=AIContextBlock.from_untrusted(combined_text, source=source),
        included=tuple(included),
        not_found=tuple(not_found),
        retrieval_errors=tuple(retrieval_errors),
        omitted_for_size=tuple(omitted_for_size),
        truncated_records=tuple(truncated_records),
    )


def _build_total_failure_message(
    not_found: list[int], retrieval_errors: list[int], omitted_for_size: list[int]
) -> str:
    """Build an honest, itemized summary for a total-failure result.

    Args:
        not_found: Requested ids for which no memory existed.
        retrieval_errors: Requested ids whose retrieval itself raised.
        omitted_for_size: Requested ids omitted for the total-size budget.

    Returns:
        A human-readable message naming every id and why it could not be
        included - never a generic, unitemized failure string.
    """
    parts: list[str] = []
    if not_found:
        parts.append("not found: " + ", ".join(str(i) for i in not_found))
    if retrieval_errors:
        parts.append(
            "could not be retrieved: " + ", ".join(str(i) for i in retrieval_errors)
        )
    if omitted_for_size:
        parts.append(
            "omitted to stay within the combined size limit: "
            + ", ".join(str(i) for i in omitted_for_size)
        )
    return "No requested memories could be included (" + "; ".join(parts) + ")."
