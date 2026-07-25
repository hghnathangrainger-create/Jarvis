"""
verified_action_context.py

Phase 100, Batch 1 (dormant foundation) -
docs/phase_100_intelligence_core_gap_audit.md, Section 12A: a narrow,
deterministic, read-only view over already-durable evidence from the
two live compound workflows (ProjectState phase-update,
schedule-enable) plus current pending-approval/handoff state, so a
later, separately-approved batch can let Jarvis's reasoning read back
what it has actually already done.

Responsibilities:
    - Define the bounded VerifiedActionDomain/VerifiedActionStatus
      vocabularies and the VerifiedActionEntry/VerifiedActionContext
      dataclasses exactly as Section 12A.4 specifies.
    - Read, deterministically and read-only, through each compound
      progress store's four bounded, category-specific
      list_recent_*() methods (Phase 100, Batch 1's own bounded-read
      correction - the original list_all()-based reads loaded a
      store's entire history unconditionally, so every read here now
      uses a hard-limited, indexed-by-category query instead) and
      PendingApprovalStore's own get_handoff_status() - never a new
      table, never a new write method, never WorkflowHistoryStore or
      ApprovalHistoryStore (Section 12A.5/12A.6).
    - Keep every stage of one build bounded by a fixed constant,
      independent of how much durable history exists: rows fetched per
      category per store, candidates classified, handoff lookups
      performed, deduplication input size, and final entries.
    - Derive each entry's VerifiedActionStatus by the exact
      source-of-truth precedence in Section 12A.5, failing closed
      (omitting the row) whenever the evidence is missing, malformed,
      or genuinely self-contradictory - never guessing the most
      optimistic interpretation.
    - Deduplicate same-target, same-status rows to the newest
      (Section 12A.8) - a settled fact of one status never suppresses
      a different-status fact for the same target (a decline never
      erases an earlier success; an interrupted attempt coexists with
      the last verified fact).
    - Apply the exact bounds/ordering/tie-break policy in Section
      12A.7 (max 5 total entries, four priority tiers, newest-first
      within a tier, row-id tie-break).
    - Render each surviving entry with a fixed, deterministic template
      per status (Section 12A.9) - never an AI call, never a
      current-state claim from historical evidence (Section 12A.10).

Does NOT:
    - Call ContextAssembler, PromptBuilder, select_tool(), or any other
      live reasoning/prompt path. Nothing in this module is imported by
      intelligence/context.py, ai/, or core/orchestrator.py during
      Batch 1 - wiring is a separately-approved Batch 2 responsibility.
    - Read WorkflowHistoryStore or ApprovalHistoryStore. The former's
      own record deliberately carries no tool_input/target-identity
      column (storage/models.py's own docstring); the latter is fully
      redundant with PendingApprovalStore's current handoff_status for
      this module's purposes (Section 12A.5).
    - Write anything, anywhere. Every store this module touches is
      used only through its own already-existing, narrow read methods.
    - Import a SQLAlchemy model or storage.models directly - only the
      stores' own already-detached, typed record dataclasses are ever
      read.
    - Treat approval/handoff free text (action, reason, tool_input) as
      anything but excluded, unread fields - only the bounded, typed
      columns Section 12A.4's field table names are ever consulted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from approval.approval_models import PendingApprovalHandoffStatus
from approval.pending_approval_store import PendingApprovalStore
from workflow.compound_workflow_progress_store import CompoundWorkflowProgressStore
from workflow.schedule_compound_workflow_progress_store import (
    ScheduleCompoundWorkflowProgressStore,
)

#: The fixed, singleton target identity for the ProjectState domain
#: (Section 12A.8) - mirrors intelligence/context.py's own
#: "project_state:current" convention; only one ProjectState record can
#: ever exist.
_PROJECT_STATE_TARGET_ID = "project_state"

#: Section 12A.7's exact hard total-entry limit.
_MAX_TOTAL_ENTRIES = 5

#: Phase 100, Batch 1 bounded-read correction
#: (docs/phase_100_intelligence_core_gap_audit.md): the per-category,
#: per-store row limit passed to each progress store's four
#: list_recent_*() methods. Equal to _MAX_TOTAL_ENTRIES because no
#: single category, from a single store, can ever legitimately
#: contribute more than the final total-entry bound to the finished
#: context - fetching more would never change the output, only the
#: amount of unnecessary work performed. A fixed, trusted constant,
#: never AI- or user-controlled; each store also independently
#: hard-caps the value it receives.
_MAX_CANDIDATES_PER_CATEGORY_QUERY = _MAX_TOTAL_ENTRIES

#: Bound on the one free-text, user-authored field this module ever
#: renders (the ProjectState approved_phase_value).
_MAX_DETAIL_VALUE_CHARS = 200

_HANDOFF_LOOKUP_FAILED_NOTE = (
    "some approval/handoff evidence was unavailable; affected entries "
    "were omitted"
)
_PROJECT_STATE_STORE_UNAVAILABLE_NOTE = (
    "ProjectState compound progress evidence unavailable; omitted"
)
_SCHEDULE_STORE_UNAVAILABLE_NOTE = (
    "schedule compound progress evidence unavailable; omitted"
)

#: Strips ASCII control characters (including newlines/carriage
#: returns) so stored free text can never fabricate new lines, section
#: headings, or non-printable content inside a rendered sentence.
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")


class VerifiedActionDomain(Enum):
    """The exactly two eligible durable-evidence domains for V1
    (Section 12A.6) - never a generic/open action-type vocabulary."""

    PROJECT_STATE_PHASE = "project_state_phase"
    SCHEDULE_ENABLE = "schedule_enable"


class VerifiedActionStatus(Enum):
    """The bounded, truthful status vocabulary (Section 12A.4).

    Deliberately never collapses approval into execution, execution
    into verification, interrupted into failed, mismatch into
    unavailable, or declined/expired into a tool failure - see
    docs/phase_100_intelligence_core_gap_audit.md, Section 12A.5's
    fail-closed conflict-resolution contract.
    """

    VERIFIED_SUCCESS = "verified_success"
    AWAITING_APPROVAL = "awaiting_approval"
    INTERRUPTED = "interrupted"
    VERIFICATION_MISMATCH = "verification_mismatch"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    DECLINED = "declined"
    EXPIRED = "expired"


#: Section 12A.7's four priority tiers, highest first. Used only as an
#: internal sort key - never exposed on a VerifiedActionEntry itself.
_STATUS_PRIORITY_TIER: dict[VerifiedActionStatus, int] = {
    VerifiedActionStatus.AWAITING_APPROVAL: 0,
    VerifiedActionStatus.INTERRUPTED: 0,
    VerifiedActionStatus.VERIFICATION_MISMATCH: 1,
    VerifiedActionStatus.VERIFICATION_UNAVAILABLE: 1,
    VerifiedActionStatus.VERIFIED_SUCCESS: 2,
    VerifiedActionStatus.DECLINED: 3,
    VerifiedActionStatus.EXPIRED: 3,
}

#: Every distinct VerifiedActionStatus a step_2_verification_outcome
#: value of "verified"/"failed"/"unavailable" maps to directly, taking
#: priority over overall_status entirely (Section 12A.5: compound
#: progress's own verification outcome is authoritative whenever it
#: exists, regardless of the workflow's final overall_status - a
#: verified-enable fact remains true even if the trailing confirmation
#: read afterward happened to fail).
_STEP2_OUTCOME_TO_STATUS: dict[str, VerifiedActionStatus] = {
    "verified": VerifiedActionStatus.VERIFIED_SUCCESS,
    "failed": VerifiedActionStatus.VERIFICATION_MISMATCH,
    "unavailable": VerifiedActionStatus.VERIFICATION_UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class VerifiedActionEntry:
    """One bounded, decision-relevant piece of durable evidence
    (Section 12A.4).

    Attributes:
        domain: Which of the two eligible domains this entry concerns.
        target_id: The trusted target identity - the fixed literal
            "project_state" for VerifiedActionDomain.PROJECT_STATE_PHASE,
            or str(schedule_id) for VerifiedActionDomain.SCHEDULE_ENABLE.
        status: The bounded, truthful VerifiedActionStatus.
        detail_value: The bounded, sanitised approved phase value for
            PROJECT_STATE_PHASE entries; always None for SCHEDULE_ENABLE
            entries (the fixed "enabled" semantic needs no value).
        observed_at: The source row's own last-updated timestamp - the
            entry's only freshness signal (Section 12A.10).
        text: The pre-rendered, deterministic sentence (Section 12A.9).
    """

    domain: VerifiedActionDomain
    target_id: str
    status: VerifiedActionStatus
    detail_value: str | None
    observed_at: datetime
    text: str

    def __post_init__(self) -> None:
        """Enforce the two structural invariants Section 12A.4's own
        field table documents, so an invalid domain/detail_value or
        target_id combination can never be constructed.

        Raises:
            ValueError: If a SCHEDULE_ENABLE entry carries a
                detail_value, or target_id is empty.
        """
        if not self.target_id:
            raise ValueError("VerifiedActionEntry.target_id must be non-empty.")
        if (
            self.domain is VerifiedActionDomain.SCHEDULE_ENABLE
            and self.detail_value is not None
        ):
            raise ValueError(
                "SCHEDULE_ENABLE entries must not carry a detail_value "
                "(the fixed 'enabled' semantic needs no value)."
            )


@dataclass(frozen=True, slots=True)
class VerifiedActionContext:
    """The bounded, deterministic result of one context build (Section
    12A.4).

    Attributes:
        entries: Up to five VerifiedActionEntry objects, already
            ordered and bounded (Section 12A.7).
        truncated: True if any eligible entry was omitted purely to
            stay within the total-entry bound.
        notes: Zero or more short, honest, non-sensitive notes about a
            source that was unavailable - never a raw exception,
            filesystem path, or database string.
    """

    entries: tuple[VerifiedActionEntry, ...]
    truncated: bool
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An internal, pre-formatting candidate entry. Carries the source
    row's own primary key for deterministic tie-breaking; dropped
    before a public VerifiedActionEntry is constructed."""

    domain: VerifiedActionDomain
    target_id: str
    status: VerifiedActionStatus
    detail_value: str | None
    observed_at: datetime
    row_id: int


def _sanitize_detail_value(value: str) -> str:
    """Bound and neutralise one free-text, user-authored field so it
    can never be rendered as instructions, a section heading, or an
    unbounded blob (Section 12A.16's allowlist/sanitisation
    requirement for the one field this module renders that carries
    user-authored text).

    Args:
        value: The raw, already-durable approved_phase_value.

    Returns:
        The value with every ASCII control character (including
        newlines) collapsed to a single space, runs of whitespace
        collapsed, and length bounded to _MAX_DETAIL_VALUE_CHARS with a
        trailing marker if truncated.
    """
    collapsed = _CONTROL_CHAR_PATTERN.sub(" ", value)
    collapsed = " ".join(collapsed.split())
    if len(collapsed) > _MAX_DETAIL_VALUE_CHARS:
        return collapsed[:_MAX_DETAIL_VALUE_CHARS] + "..."
    return collapsed


def _classify_status(
    *,
    step_2_verification_outcome_value: str | None,
    overall_status_value: str,
    step_1_status_value: str,
    handoff_status: PendingApprovalHandoffStatus | None,
) -> VerifiedActionStatus | None:
    """Derive one row's VerifiedActionStatus using the exact
    source-of-truth precedence in Section 12A.5, failing closed
    (returning None, meaning "omit this row") whenever the evidence is
    missing or genuinely self-contradictory.

    Shared by both domains: the two compound progress record types use
    independent enum classes but an identical bounded vocabulary of
    `.value` strings, so this function is parameterised on those
    already-typed values rather than duplicated per domain.

    Args:
        step_2_verification_outcome_value: The row's own
            step_2_verification_outcome.value, or None if step 2 has
            not completed.
        overall_status_value: The row's own overall_status.value.
        step_1_status_value: The row's own step_1_status.value.
        handoff_status: The current PendingApprovalHandoffStatus for
            this row's request_id, or None if unknown/unavailable.

    Returns:
        The bounded VerifiedActionStatus this row represents, or None
        if the row is not eligible or its evidence cannot be resolved
        without guessing.
    """
    # Compound progress's own verification outcome is authoritative
    # whenever it exists, regardless of overall_status (Section 12A.5) -
    # a verified/mismatched/unavailable fact is true independent of
    # whether the trailing confirmation-read step afterward succeeded.
    if step_2_verification_outcome_value is not None:
        return _STEP2_OUTCOME_TO_STATUS.get(step_2_verification_outcome_value)

    if overall_status_value == "not_executed":
        if handoff_status is PendingApprovalHandoffStatus.DECLINED:
            return VerifiedActionStatus.DECLINED
        if handoff_status is PendingApprovalHandoffStatus.EXPIRED:
            return VerifiedActionStatus.EXPIRED
        # NOT_EXECUTED with no corroborating declined/expired handoff
        # evidence is a genuine disagreement - omit rather than guess.
        return None

    if overall_status_value == "needs_reconciliation":
        return VerifiedActionStatus.INTERRUPTED

    if overall_status_value in ("pending", "in_progress"):
        if handoff_status in (
            PendingApprovalHandoffStatus.PENDING,
            PendingApprovalHandoffStatus.APPROVED_UNCONSUMED,
        ):
            return VerifiedActionStatus.AWAITING_APPROVAL
        if handoff_status is PendingApprovalHandoffStatus.CLAIMED:
            if step_1_status_value == "pending":
                # Claimed for resume, but nothing was ever durably
                # attempted yet (Section 12A.5, row 2).
                return VerifiedActionStatus.AWAITING_APPROVAL
            # Claimed, and something was durably attempted, but the
            # row is still non-terminal - an incomplete checkpoint
            # (Section 12A.5, row 4).
            return VerifiedActionStatus.INTERRUPTED
        # No handoff evidence, or a handoff status that contradicts a
        # non-terminal progress row - omit rather than guess.
        return None

    # overall_status is COMPLETED or FAILED here, but
    # step_2_verification_outcome is None. COMPLETED/FAILED-from-step-2
    # always sets an outcome via the store's own CAS transitions, so
    # this is either a structurally-impossible row (a malformed/
    # inconsistent test construction) or a bare step-1 write failure -
    # neither has a corresponding member in the accepted status
    # vocabulary (Section 12A.6's eligible event set only names
    # verified/mismatch/unavailable/pending/interrupted/declined/
    # expired) - omitted, never guessed as success or failure.
    return None


def _fetch_bounded_candidate_rows(store: object) -> list[object]:
    """Fetch this build's entire bounded row set from one progress
    store, using its four category-specific, hard-limited read
    methods instead of list_all() (Phase 100, Batch 1 bounded-read
    correction).

    Each category query is independently bounded to
    _MAX_CANDIDATES_PER_CATEGORY_QUERY (itself hard-capped again inside
    the store), so the total number of rows fetched from one store is
    never more than four times that constant, regardless of how much
    history the table holds. The four WHERE clauses are mutually
    exclusive by construction (Section 8 of the bounded-read audit), so
    a row is never returned by more than one call here.

    Args:
        store: A CompoundWorkflowProgressStore or
            ScheduleCompoundWorkflowProgressStore instance - both
            expose an identical four-method bounded-read surface.

    Returns:
        The concatenation of all four category reads' own records.
    """
    return [
        *store.list_recent_pending_verification(
            limit=_MAX_CANDIDATES_PER_CATEGORY_QUERY
        ),
        *store.list_recent_verification_problems(
            limit=_MAX_CANDIDATES_PER_CATEGORY_QUERY
        ),
        *store.list_recent_verified(limit=_MAX_CANDIDATES_PER_CATEGORY_QUERY),
        *store.list_recent_not_executed(limit=_MAX_CANDIDATES_PER_CATEGORY_QUERY),
    ]


def _project_state_candidates(
    store: CompoundWorkflowProgressStore,
    pending_approval_store: PendingApprovalStore | None,
    handoff_failures: list[bool],
) -> list[_Candidate]:
    """Build every eligible ProjectState-domain candidate from a
    bounded read of durable progress rows.

    Args:
        store: The real CompoundWorkflowProgressStore to read.
        pending_approval_store: Used only to resolve handoff_status for
            rows whose evidence needs it; None if unavailable.
        handoff_failures: Mutated (appended to) if any individual
            handoff lookup raises, so the caller can add one honest,
            deduplicated note.

    Returns:
        A list of _Candidate objects for every row an eligible status
        could be derived for.
    """
    candidates: list[_Candidate] = []
    for record in _fetch_bounded_candidate_rows(store):
        outcome_value = (
            record.step_2_verification_outcome.value
            if record.step_2_verification_outcome is not None
            else None
        )
        # _classify_status() never consults handoff_status once an
        # outcome is already set (Section 12A.5: the verification
        # outcome is authoritative and decisive on its own) - skip the
        # lookup entirely rather than performing one it can't use.
        handoff = (
            _lookup_handoff_status(
                pending_approval_store, record.request_id, handoff_failures
            )
            if outcome_value is None
            else None
        )
        status = _classify_status(
            step_2_verification_outcome_value=outcome_value,
            overall_status_value=record.overall_status.value,
            step_1_status_value=record.step_1_status.value,
            handoff_status=handoff,
        )
        if status is None:
            continue
        candidates.append(
            _Candidate(
                domain=VerifiedActionDomain.PROJECT_STATE_PHASE,
                target_id=_PROJECT_STATE_TARGET_ID,
                status=status,
                detail_value=_sanitize_detail_value(record.approved_phase_value),
                observed_at=record.updated_at,
                row_id=record.id,
            )
        )
    return candidates


def _schedule_candidates(
    store: ScheduleCompoundWorkflowProgressStore,
    pending_approval_store: PendingApprovalStore | None,
    handoff_failures: list[bool],
) -> list[_Candidate]:
    """Build every eligible schedule-domain candidate from a bounded
    read of durable progress rows. Mirrors _project_state_candidates
    exactly, using the trusted integer schedule_id as target identity
    and no detail_value (Section 12A.8).

    Args:
        store: The real ScheduleCompoundWorkflowProgressStore to read.
        pending_approval_store: Used only to resolve handoff_status;
            None if unavailable.
        handoff_failures: Mutated (appended to) if any individual
            handoff lookup raises.

    Returns:
        A list of _Candidate objects for every row an eligible status
        could be derived for.
    """
    candidates: list[_Candidate] = []
    for record in _fetch_bounded_candidate_rows(store):
        outcome_value = (
            record.step_2_verification_outcome.value
            if record.step_2_verification_outcome is not None
            else None
        )
        # _classify_status() never consults handoff_status once an
        # outcome is already set (Section 12A.5: the verification
        # outcome is authoritative and decisive on its own) - skip the
        # lookup entirely rather than performing one it can't use.
        handoff = (
            _lookup_handoff_status(
                pending_approval_store, record.request_id, handoff_failures
            )
            if outcome_value is None
            else None
        )
        status = _classify_status(
            step_2_verification_outcome_value=outcome_value,
            overall_status_value=record.overall_status.value,
            step_1_status_value=record.step_1_status.value,
            handoff_status=handoff,
        )
        if status is None:
            continue
        candidates.append(
            _Candidate(
                domain=VerifiedActionDomain.SCHEDULE_ENABLE,
                target_id=str(record.schedule_id),
                status=status,
                detail_value=None,
                observed_at=record.updated_at,
                row_id=record.id,
            )
        )
    return candidates


def _lookup_handoff_status(
    pending_approval_store: PendingApprovalStore | None,
    request_id: str | None,
    handoff_failures: list[bool],
) -> PendingApprovalHandoffStatus | None:
    """Resolve one row's current handoff status, isolating any failure.

    Args:
        pending_approval_store: The store to query, or None if
            unavailable (never attempted).
        request_id: The progress row's own request_id, or None if it
            never carried one.
        handoff_failures: Appended to (once) if the lookup itself
            raises, so the caller can surface one honest note.

    Returns:
        The PendingApprovalHandoffStatus, or None if unavailable,
        unknown, or the lookup failed.
    """
    if pending_approval_store is None or request_id is None:
        return None
    try:
        return pending_approval_store.get_handoff_status(request_id)
    except Exception:
        handoff_failures.append(True)
        return None


def _deduplicate(candidates: list[_Candidate]) -> list[_Candidate]:
    """Collapse same-target, same-status candidates to the newest one
    (Section 12A.8).

    Different statuses for the same target are never collapsed against
    each other - a declined request never suppresses an earlier
    verified success, and an interrupted attempt coexists with the
    last verified fact - only repeated rows carrying the *same* status
    for the *same* target (e.g. two historical verified-enable rows for
    the same schedule) collapse to the newest.

    Args:
        candidates: Every eligible candidate from every domain.

    Returns:
        One candidate per distinct (domain, target_id, status) triple -
        the one with the greatest (observed_at, row_id).
    """
    groups: dict[
        tuple[VerifiedActionDomain, str, VerifiedActionStatus], list[_Candidate]
    ] = {}
    for candidate in candidates:
        key = (candidate.domain, candidate.target_id, candidate.status)
        groups.setdefault(key, []).append(candidate)
    return [
        max(items, key=lambda c: (c.observed_at, c.row_id))
        for items in groups.values()
    ]


def _sort_and_bound(
    candidates: list[_Candidate],
) -> tuple[list[_Candidate], bool]:
    """Apply Section 12A.7's exact deterministic ordering and total
    bound.

    Sorts newest-first (by observed_at, then row_id as the tie-break)
    first, then stable-sorts by priority tier - Python's sort stability
    guarantees the newest-first order survives within each tier.

    Args:
        candidates: Every deduplicated candidate.

    Returns:
        A tuple of (bounded, truncated): the first _MAX_TOTAL_ENTRIES
        candidates in final order, and whether any were dropped purely
        to stay within that bound.
    """
    recency_ordered = sorted(
        candidates, key=lambda c: (c.observed_at, c.row_id), reverse=True
    )
    tier_ordered = sorted(
        recency_ordered, key=lambda c: _STATUS_PRIORITY_TIER[c.status]
    )
    truncated = len(tier_ordered) > _MAX_TOTAL_ENTRIES
    return tier_ordered[:_MAX_TOTAL_ENTRIES], truncated


def _format_timestamp(value: datetime) -> str:
    """Render a timestamp using the same convention already established
    by intelligence/context.py's own _format_last_updated().

    Args:
        value: The real, already-durable timestamp.

    Returns:
        A "YYYY-MM-DD HH:MM:SS UTC" string.
    """
    return f"{value.strftime('%Y-%m-%d %H:%M:%S')} UTC"


#: Section 12A.9's exact deterministic wording, keyed by status. Every
#: template embeds detail_value/timestamp only via safe, sanitised,
#: already-bounded fields - never raw stored text, never an internal
#: enum/table/checkpoint name.
_PROJECT_STATE_TEMPLATES: dict[VerifiedActionStatus, str] = {
    VerifiedActionStatus.VERIFIED_SUCCESS: (
        'The project phase was verified set to "{detail}" at {timestamp}.'
    ),
    VerifiedActionStatus.AWAITING_APPROVAL: (
        'A request to update the project phase to "{detail}" is awaiting '
        "approval and has not executed."
    ),
    VerifiedActionStatus.INTERRUPTED: (
        'Updating the project phase to "{detail}" was interrupted after '
        "its last durable checkpoint; completion is not confirmed."
    ),
    VerifiedActionStatus.VERIFICATION_MISMATCH: (
        'The phase update to "{detail}" ran, but the project phase was '
        "not verified set to that value."
    ),
    VerifiedActionStatus.VERIFICATION_UNAVAILABLE: (
        "Jarvis could not verify the persisted project phase after a "
        'request to set it to "{detail}".'
    ),
    VerifiedActionStatus.DECLINED: (
        'A request to update the project phase to "{detail}" was declined '
        "and was not executed."
    ),
    VerifiedActionStatus.EXPIRED: (
        'A request to update the project phase to "{detail}" expired and '
        "was not executed."
    ),
}

_SCHEDULE_TEMPLATES: dict[VerifiedActionStatus, str] = {
    VerifiedActionStatus.VERIFIED_SUCCESS: (
        "Schedule {schedule_id} was verified enabled at {timestamp}."
    ),
    VerifiedActionStatus.AWAITING_APPROVAL: (
        "A request to enable schedule {schedule_id} is awaiting approval "
        "and has not executed."
    ),
    VerifiedActionStatus.INTERRUPTED: (
        "Enabling schedule {schedule_id} was interrupted after its last "
        "durable checkpoint; completion is not confirmed."
    ),
    VerifiedActionStatus.VERIFICATION_MISMATCH: (
        "The enable action for schedule {schedule_id} ran, but it was not "
        "verified enabled."
    ),
    VerifiedActionStatus.VERIFICATION_UNAVAILABLE: (
        "Jarvis could not verify the persisted enabled state of schedule "
        "{schedule_id}."
    ),
    VerifiedActionStatus.DECLINED: (
        "A request to enable schedule {schedule_id} was declined and was "
        "not executed."
    ),
    VerifiedActionStatus.EXPIRED: (
        "A request to enable schedule {schedule_id} expired and was not "
        "executed."
    ),
}


def _format_entry_text(candidate: _Candidate) -> str:
    """Render one candidate's deterministic sentence (Section 12A.9).

    Args:
        candidate: The candidate to render.

    Returns:
        The fixed-template sentence for this candidate's domain and
        status, with its own timestamp always embedded (Section
        12A.10 - never a current-state claim from historical
        evidence).
    """
    timestamp = _format_timestamp(candidate.observed_at)
    if candidate.domain is VerifiedActionDomain.PROJECT_STATE_PHASE:
        return _PROJECT_STATE_TEMPLATES[candidate.status].format(
            detail=candidate.detail_value, timestamp=timestamp
        )
    return _SCHEDULE_TEMPLATES[candidate.status].format(
        schedule_id=candidate.target_id, timestamp=timestamp
    )


def build_verified_action_context(
    *,
    project_state_progress_store: CompoundWorkflowProgressStore | None,
    schedule_progress_store: ScheduleCompoundWorkflowProgressStore | None,
    pending_approval_store: PendingApprovalStore | None,
) -> VerifiedActionContext:
    """Build the bounded, deterministic VerifiedActionContext for one
    read.

    Every source is isolated in its own try/except (mirroring
    ContextAssembler's own established per-source isolation pattern in
    intelligence/context.py) - a failure in one store never prevents
    the other's valid evidence from being included, and never raises
    out of this function. Not called by any live path in Batch 1; only
    this module's own dedicated tests invoke it directly.

    Args:
        project_state_progress_store: The real
            CompoundWorkflowProgressStore, or None to omit this domain
            entirely (contributes nothing, no note).
        schedule_progress_store: The real
            ScheduleCompoundWorkflowProgressStore, or None to omit this
            domain entirely.
        pending_approval_store: The real PendingApprovalStore, used
            only to resolve current handoff status; None disables
            handoff-dependent statuses (AWAITING_APPROVAL, INTERRUPTED,
            DECLINED, EXPIRED) but never affects
            VERIFIED_SUCCESS/VERIFICATION_MISMATCH/
            VERIFICATION_UNAVAILABLE, which need no handoff evidence.

    Returns:
        A VerifiedActionContext with up to five entries, in
        deterministic order, plus any honest, bounded notes about
        unavailable sources.
    """
    notes: list[str] = []
    candidates: list[_Candidate] = []
    handoff_failures: list[bool] = []

    if project_state_progress_store is not None:
        try:
            candidates.extend(
                _project_state_candidates(
                    project_state_progress_store,
                    pending_approval_store,
                    handoff_failures,
                )
            )
        except Exception:
            notes.append(_PROJECT_STATE_STORE_UNAVAILABLE_NOTE)

    if schedule_progress_store is not None:
        try:
            candidates.extend(
                _schedule_candidates(
                    schedule_progress_store,
                    pending_approval_store,
                    handoff_failures,
                )
            )
        except Exception:
            notes.append(_SCHEDULE_STORE_UNAVAILABLE_NOTE)

    if handoff_failures:
        notes.append(_HANDOFF_LOOKUP_FAILED_NOTE)

    deduplicated = _deduplicate(candidates)
    bounded, truncated = _sort_and_bound(deduplicated)

    entries = tuple(
        VerifiedActionEntry(
            domain=candidate.domain,
            target_id=candidate.target_id,
            status=candidate.status,
            detail_value=candidate.detail_value,
            observed_at=candidate.observed_at,
            text=_format_entry_text(candidate),
        )
        for candidate in bounded
    )

    return VerifiedActionContext(
        entries=entries, truncated=truncated, notes=tuple(notes)
    )
