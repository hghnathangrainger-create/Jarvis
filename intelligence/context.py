"""
context.py

Bounded, deterministic Context Intelligence for Jarvis's "ask jarvis:
<request>" command (Phase 90, Batch 1; contracts fixed by
docs/phase_90_implementation_plan.md, Section 24.A - the Planning Gate
Amendment, which supersedes Section 6's original, less-constrained
ContextItem/AssembledContext shapes).

Responsibilities:
    - Derive a small set of deterministic query terms from a live
      request, excluding the command's own trigger words.
    - Select a bounded, ordered set of stored memories: lexical matches
      first (in query-term order, deduplicated by id), then a recency
      fallback filling any remaining slots.
    - Read the single, manually-maintained ProjectState record and
      render it with the same Phase 89 honesty disclosures Prompt
      Studio already established (manually recorded, not
      auto-detected, may be stale, "[FILL IN]"/"not recorded yet" for
      absent fields) - reimplemented here as a small, local, pure
      formatter rather than importing ai/prompt_studio.py's own
      private helpers across an architectural layer boundary.
    - Apply fixed, hand-maintained character budgets (Section 24.A.5):
      500 characters per item, a 500-character fixed ProjectState
      reservation, and a 2,500-character fixed memory allocation - two
      independent budgets, never one shared, reallocatable pool.
    - Combine the assembled, always-UNTRUSTED ContextItems into a
      single AIContextBlock for the existing, unmodified
      PromptBuilder/AIRouter/AIReasoningEngine path to consume -
      mirroring ai/memory_ingestion.py's own established
      multi-record-into-one-block combination pattern exactly.

Does NOT:
    - Call any AI provider, or perform any AI-assisted selection or
      ranking. Every decision here is plain, deterministic string
      processing and two already-existing, already-tested read calls
      (MemoryManager.search()/list_recent(), ProjectStateStore.get()).
    - Execute a tool, create an approval, or touch WorkflowEngine/
      ToolExecutor/ApprovalManager/SecurityManager in any way. This
      module only ever reads.
    - Ever construct a ContentTrust.JARVIS_TRUSTED ContextItem. Every
      ContextItem this module produces is UNTRUSTED by construction;
      the live request text itself is never represented as a
      ContextItem at all (see AssembledContext.request_text).
    - Import ai/prompt_studio.py's own private
      _field_or_fill_in/_last_updated_or_not_recorded helpers. Those
      are Prompt Studio's own implementation detail; this module
      reimplements the same small, pure formatting logic locally
      instead of reaching across an architectural layer boundary for a
      few lines of string formatting.
    - Retry a failed retrieval, replan, or fabricate substitute content
      for a source that failed. A failure is represented honestly as a
      short, fixed, non-sensitive note - never a raw exception message,
      filesystem path, or database string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai.context_models import AIContextBlock
from config.constants import ContentTrust
from memory.memory_manager import MemoryManager
from project_state.project_state_store import ProjectStateRecord, ProjectStateStore

#: The fixed Section 24.A.4 stopword tuple, verbatim. Removed from every
#: derived query, alongside _COMMAND_PREFIX_WORDS below, before the
#: minimum-length filter is applied.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "what", "have", "has",
        "had", "i", "my", "me", "you", "your", "it", "do", "does", "did",
        "can", "could", "and", "or", "to", "for", "on", "in", "of", "about",
        "currently", "current",
    }
)

#: The command's own trigger words, excluded from query terms even when
#: they appear inside the user's actual request text (e.g. "ask jarvis:
#: what is jarvis doing today") - a requirement distinct from, and in
#: addition to, the fixed Section 24.A.4 stopword tuple above.
_COMMAND_PREFIX_WORDS: frozenset[str] = frozenset({"ask", "jarvis"})

#: Splits on any run of non-alphanumeric characters, so punctuation never
#: survives into a query term.
_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")

_MIN_TERM_LENGTH = 4
_MAX_QUERY_TERMS = 5

#: Section 24.A.5's exact hard limits. Two independent budgets - a fixed
#: 500-character ProjectState reservation and a fixed 2,500-character
#: memory allocation - never one shared, reallocatable pool: an
#: under-used ProjectState reservation is never handed to memory items.
_MAX_CHARS_PER_ITEM = 500
_PROJECT_STATE_CHAR_BUDGET = 500
_MEMORY_CHAR_BUDGET = 2500
_MAX_MEMORY_ITEMS = 5

#: Per-item truncation notice. Mirrors ai/memory_ingestion.py's own
#: _TRUNCATION_NOTICE_TEMPLATE convention exactly (truncate the raw
#: content to max_chars, then append an honest, disclosed notice) - the
#: notice's own length is included in the item's final counted length,
#: so a fully-truncated item's true contribution to its budget can
#: exceed max_chars, exactly as it already does for that precedent.
_TRUNCATION_NOTICE_TEMPLATE = (
    "\n[... truncated: showing the first {max_chars} characters of this "
    "item.]"
)

_FILL_IN = "[FILL IN]"
_NOT_RECORDED_YET = "not recorded yet"

_NO_MEMORIES_NOTE = "no matching or recent memories found"
_MEMORY_RETRIEVAL_FAILED_NOTE = "memory retrieval failed"
_PROJECT_STATE_RETRIEVAL_FAILED_NOTE = "project state retrieval failed"
_PROJECT_STATE_NEVER_RECORDED_NOTE = "project state has not been recorded yet"


class ContextSource(Enum):
    """The bounded set of sources a Batch 1 ContextItem may come from.

    Fixed by Section 24.A.1/A.3: exactly these two members for Batch 1.
    A future batch may add a new member only when a real consumer
    exists for it - never speculatively.
    """

    MEMORY = "memory"
    PROJECT_STATE = "project_state"


@dataclass(frozen=True, slots=True)
class ContextItem:
    """A single, provenance-tagged piece of assembled context.

    Fixed by Section 24.A.1. `context_id` is deterministic and built
    only from `source` and `source_record_id` - never from `.text`, a
    memory's content, a project-state field value, or a credential -
    so it can never leak raw or secret content by construction.

    Attributes:
        context_id: "memory:<id>" for a memory item, or
            "project_state:current" for the singleton ProjectState
            item (exactly one ProjectState record can ever exist).
        source: Which ContextSource produced this item.
        source_record_id: The real memory id as a string, or None for
            the singleton ProjectState item.
        text: The item's own, possibly truncated, text.
        trust: Always ContentTrust.UNTRUSTED for every ContextItem this
            module produces.
        relevance_reason: A short, human-readable reason this item was
            included.
    """

    context_id: str
    source: ContextSource
    source_record_id: str | None
    text: str
    trust: ContentTrust
    relevance_reason: str


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """The result of assembling context for one "ask jarvis:" request.

    Fixed by Section 24.A.2. The live request itself is never itemized
    - it stays here, structurally separate, as the one
    ContentTrust.JARVIS_TRUSTED-eligible piece of the whole assembly.

    Attributes:
        request_text: The live request text, verbatim (never itemized;
            never counted toward the item character budget below).
        items: The assembled, ordered ContextItems - up to six total
            (up to five memory + up to one ProjectState).
        total_chars: The sum of every included item's own final
            (post-truncation) text length. Never includes
            request_text, and never includes delimiter/label framing.
        truncated: True if any item was truncated, or if any candidate
            item was wholly omitted, because of a character budget.
            False only when no budget-driven truncation or omission
            happened.
        notes: Zero or more independently-true, honest, bounded notes
            about omissions, truncations, or retrieval failures - never
            a raw exception message, filesystem path, or database
            string, and never more than one generic reason collapsed
            into a single note.
    """

    request_text: str
    items: tuple[ContextItem, ...]
    total_chars: int
    truncated: bool
    notes: tuple[str, ...]


def derive_query_terms(request_text: str) -> tuple[str, ...]:
    """Deterministically derive up to five memory-search query terms.

    Implements Section 24.A.4's exact algorithm, extended (per this
    batch's own instructions) to also exclude the command's own
    trigger words "ask"/"jarvis", even when they appear inside the
    request's own content rather than merely as a stripped-away
    prefix.

    Args:
        request_text: The live request text (already stripped of the
            "ask jarvis:" prefix by the command router).

    Returns:
        Up to five lowercased tokens, in their original left-to-right
        order, with the fixed stopwords, the command's own trigger
        words, and any token shorter than four characters removed. May
        be empty.
    """
    lowered = request_text.casefold()
    raw_tokens = [token for token in _TOKEN_PATTERN.split(lowered) if token]

    terms: list[str] = []
    for token in raw_tokens:
        if token in _STOPWORDS or token in _COMMAND_PREFIX_WORDS:
            continue
        if len(token) < _MIN_TERM_LENGTH:
            continue
        terms.append(token)
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    return tuple(terms)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Shorten text to max_chars, with an honest, disclosed notice.

    Mirrors ai/memory_ingestion.py's own _truncate() convention: the
    notice is appended after slicing, so a truncated result's true
    length can exceed max_chars - this is deliberate and disclosed, not
    a bug, and is what makes real whole-item-budget omission (rather
    than only per-item truncation) reachable at all.

    Args:
        text: The raw text to (possibly) truncate.
        max_chars: The maximum number of characters of the raw text to
            keep before the notice is appended.

    Returns:
        A tuple of (text, truncated). When text already fits within
        max_chars, text is returned unchanged and truncated is False.
    """
    if len(text) <= max_chars:
        return text, False
    notice = _TRUNCATION_NOTICE_TEMPLATE.format(max_chars=max_chars)
    return f"{text[:max_chars]}{notice}", True


def _field_or_fill_in(value: str | None) -> str:
    """Render one ProjectState field: its real value, or "[FILL IN]".

    A small, local, pure reimplementation of
    ai/prompt_studio.py's own private _field_or_fill_in - not an import
    of it, per this batch's explicit instruction not to reach across
    that architectural layer boundary for a few lines of formatting.

    Args:
        value: The field's manually-recorded value, or None.

    Returns:
        value if set, otherwise "[FILL IN]".
    """
    return value if value else _FILL_IN


def _format_last_updated(value: datetime | None) -> str:
    """Render ProjectState's last-updated timestamp honestly.

    Mirrors ProjectStateShowTool's/PreparePromptTool's own established
    "YYYY-MM-DD HH:MM:SS UTC" display convention exactly, reimplemented
    locally rather than imported, for the same reason as
    _field_or_fill_in above.

    Args:
        value: The record's real last_updated timestamp, or None if no
            ProjectState record exists at all yet.

    Returns:
        A pre-formatted string, or "not recorded yet" if value is None.
    """
    if value is None:
        return _NOT_RECORDED_YET
    return f"{value.strftime('%Y-%m-%d %H:%M:%S')} UTC"


def _format_project_state_text(record: ProjectStateRecord | None) -> str:
    """Render the single ProjectState ContextItem's text, honestly.

    Embeds the same Phase 89 disclosures Prompt Studio's own "Project
    Context" section already established: manually recorded, not
    auto-detected, may be stale; "[FILL IN]" for any field never
    recorded; a real or "not recorded yet" last-updated line. This is a
    direct reuse of that established wording, not new wording invented
    for this batch.

    Args:
        record: The real ProjectStateRecord, or None if no record has
            ever been written.

    Returns:
        The ProjectState item's full, honest text.
    """
    branch = record.branch if record is not None else None
    phase = record.phase if record is not None else None
    commit = record.commit if record is not None else None
    suite_result = record.suite_result if record is not None else None
    focus = record.focus if record is not None else None
    last_updated = record.last_updated if record is not None else None

    lines = [
        "Project state (manually recorded by the user; never "
        "auto-detected from git, a subprocess, or the filesystem; may "
        "be stale):",
        f"- Current branch: {_field_or_fill_in(branch)}",
        f"- Latest closed phase: {_field_or_fill_in(phase)}",
        f"- Latest commit hash: {_field_or_fill_in(commit)}",
        f"- Latest full test-suite result: {_field_or_fill_in(suite_result)}",
        f"- Current focus: {_field_or_fill_in(focus)}",
        f"- Last updated: {_format_last_updated(last_updated)}",
    ]
    return "\n".join(lines)


class ContextAssembler:
    """Assembles bounded, deterministic context for one "ask jarvis:" request.

    Attributes:
        _memory_manager: Used only for search()/list_recent() - never
            for any write method.
        _project_state_store: Used only for get() - never for
            update().
    """

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        project_state_store: ProjectStateStore,
    ) -> None:
        """Initialise the assembler with its two read-only collaborators.

        Args:
            memory_manager: The MemoryManager used for deterministic
                memory selection.
            project_state_store: The ProjectStateStore used to read the
                single, manually-maintained project-state record.
        """
        self._memory_manager = memory_manager
        self._project_state_store = project_state_store

    def assemble(self, request_text: str) -> AssembledContext:
        """Assemble bounded context for one live request.

        ProjectState is always attempted first (Section 24.A.5's fixed
        source priority), then memory selection. A failure in either
        source never aborts the other, and never aborts the overall
        assembly - each is isolated in its own try/except, represented
        as a short, fixed, non-sensitive note.

        Args:
            request_text: The live request text (already stripped of
                the "ask jarvis:" prefix and surrounding whitespace).

        Returns:
            An AssembledContext with up to six items, honest notes,
            and correct truncated/total_chars accounting.
        """
        notes: list[str] = []
        any_truncated_or_omitted = False

        project_state_item, ps_truncated, ps_notes = (
            self._build_project_state_item()
        )
        notes.extend(ps_notes)
        any_truncated_or_omitted = any_truncated_or_omitted or ps_truncated

        memory_items, mem_truncated, mem_notes = self._build_memory_items(
            request_text
        )
        notes.extend(mem_notes)
        any_truncated_or_omitted = any_truncated_or_omitted or mem_truncated

        items: list[ContextItem] = []
        if project_state_item is not None:
            items.append(project_state_item)
        items.extend(memory_items)

        total_chars = sum(len(item.text) for item in items)

        return AssembledContext(
            request_text=request_text,
            items=tuple(items),
            total_chars=total_chars,
            truncated=any_truncated_or_omitted,
            notes=tuple(notes),
        )

    def _build_project_state_item(
        self,
    ) -> tuple[ContextItem | None, bool, list[str]]:
        """Build the single ProjectState ContextItem, isolating failure.

        Returns:
            A tuple of (item, truncated, notes). item is None only when
            ProjectStateStore.get() itself raised.
        """
        try:
            record = self._project_state_store.get()
        except Exception:
            return None, False, [_PROJECT_STATE_RETRIEVAL_FAILED_NOTE]

        text, truncated = _truncate(
            _format_project_state_text(record), _MAX_CHARS_PER_ITEM
        )
        item = ContextItem(
            context_id="project_state:current",
            source=ContextSource.PROJECT_STATE,
            source_record_id=None,
            text=text,
            trust=ContentTrust.UNTRUSTED,
            relevance_reason=(
                "the current manually-recorded project state, always "
                "included"
            ),
        )
        notes = [_PROJECT_STATE_NEVER_RECORDED_NOTE] if record is None else []
        return item, truncated, notes

    def _build_memory_items(
        self, request_text: str
    ) -> tuple[list[ContextItem], bool, list[str]]:
        """Select and budget up to five memory ContextItems.

        Implements Section 24.A.4's full selection algorithm (lexical
        pass in query-term order, deduplicated by id, then a recency
        fallback filling any remaining slots, skipping ids already
        selected) and Section 24.A.5's budget (a fixed 2,500-character
        allocation, per-item truncation, and whole-item omission for
        any item that would not fit the remaining budget even after
        truncation).

        Args:
            request_text: The live request text.

        Returns:
            A tuple of (items, truncated_or_omitted, notes).
        """
        terms = derive_query_terms(request_text)

        seen_ids: set[int] = set()
        # Ordered (record, relevance_reason) pairs, lexical matches
        # first (in query-term order), recency-fallback matches
        # appended after - Section 24.A.4's exact merge order.
        selected: list[tuple[object, str]] = []
        any_retrieval_failure = False

        for term in terms:
            if len(selected) >= _MAX_MEMORY_ITEMS:
                break
            try:
                results = self._memory_manager.search(term, limit=5)
            except Exception:
                any_retrieval_failure = True
                continue
            for record in results:
                if record.id in seen_ids:
                    continue
                seen_ids.add(record.id)
                selected.append(
                    (record, f"matched the search term '{term}'")
                )
                if len(selected) >= _MAX_MEMORY_ITEMS:
                    break

        remaining = _MAX_MEMORY_ITEMS - len(selected)
        if remaining > 0:
            try:
                recent = self._memory_manager.list_recent(limit=remaining)
            except Exception:
                any_retrieval_failure = True
                recent = []
            for record in recent:
                if record.id in seen_ids:
                    continue
                seen_ids.add(record.id)
                selected.append((record, "included as a recent memory"))
                if len(selected) >= _MAX_MEMORY_ITEMS:
                    break

        notes: list[str] = []
        if any_retrieval_failure:
            notes.append(_MEMORY_RETRIEVAL_FAILED_NOTE)
        if not selected:
            notes.append(_NO_MEMORIES_NOTE)

        items: list[ContextItem] = []
        running_total = 0
        truncated_or_omitted = False
        omitted_count = 0

        for record, reason in selected:
            text, was_truncated = _truncate(record.content, _MAX_CHARS_PER_ITEM)
            if running_total + len(text) > _MEMORY_CHAR_BUDGET:
                omitted_count += 1
                truncated_or_omitted = True
                continue

            running_total += len(text)
            if was_truncated:
                truncated_or_omitted = True

            items.append(
                ContextItem(
                    context_id=f"memory:{record.id}",
                    source=ContextSource.MEMORY,
                    source_record_id=str(record.id),
                    text=text,
                    trust=ContentTrust.UNTRUSTED,
                    relevance_reason=reason,
                )
            )

        if omitted_count:
            notes.append(
                f"{omitted_count} memory item(s) omitted to stay within "
                "the context budget"
            )

        return items, truncated_or_omitted, notes


def build_ai_context_block(assembled: AssembledContext) -> AIContextBlock | None:
    """Combine every assembled ContextItem into one UNTRUSTED AIContextBlock.

    Mirrors ai/memory_ingestion.py's own established
    multi-record-into-one-block combination pattern: PromptBuilder only
    ever accepts a single optional context block, so every ContextItem
    is combined, in order, into one block, delimited by its own
    context_id - structural serialization only, never a security
    boundary. The combined block is scanned exactly once by
    PromptBuilder's existing, unmodified injection scanner, exactly as
    any other UNTRUSTED context already is.

    Args:
        assembled: The AssembledContext to combine.

    Returns:
        A single AIContextBlock.from_untrusted(...), or None when there
        are no items to combine (an empty context is never represented
        as an empty block).
    """
    if not assembled.items:
        return None

    parts = [
        f"\n----- {item.context_id} -----\n{item.text}" for item in assembled.items
    ]
    combined_text = "".join(parts).strip()
    if not combined_text:
        return None

    return AIContextBlock.from_untrusted(combined_text, source="intelligence_context")
