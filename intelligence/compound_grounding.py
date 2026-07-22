"""
compound_grounding.py

An isolated, non-live-wired, deterministic grounding function for
exactly one trusted, hand-authored two-capability compound request
template (Phase 97 - docs/phase_97_implementation_plan.md).

Responsibilities:
    - Define a static, ordered, single-entry compound-template
      allowlist (CompoundTemplate / _ALLOWED_COMPOUND_TEMPLATES): the
      only ordered pair this module ever recognizes is
      (PROJECT_STATE_UPDATE_PHASE, PROJECT_STATE_SHOW), split on the
      one fixed connector " and then ". Represented as an ordered
      tuple of an ordered tuple - never a set or frozenset of pairs -
      so structural (not merely value) equality already distinguishes
      an allowed pair from its reverse.
    - Split the live request into exactly two ordered clauses on that
      one fixed connector, and independently ground each clause, at
      its own fixed position, against the *complete* current
      user-facing signature catalogue (reusing
      intelligence.grounding's own, unmodified signature-matching
      logic) - never merely checking whether the expected capability's
      own signature happens to match somewhere in the whole request.
    - Attribute the phase value using only clause 1's own text, via
      intelligence.grounding's own, unmodified argument-span extraction
      and exact-equality comparison logic.
    - Report one of a small, new, separate, bounded
      CompoundUngroundedReason value on any failure - never the
      existing, live UngroundedReason (which is never extended,
      imported for extension, or modified).

Does NOT:
    - Accept AssembledContext, memory, prior messages, model rationale,
      model confidence, tool results, approval state, workflow state,
      repository state, another AI call, fuzzy matching, semantic
      similarity, or embeddings of any kind. This function's only
      inputs are the live request_text and an already-parsed
      ParsedCompoundToolSelection; every other check consults only
      this module's own trusted, static template data.
    - Call SecurityManager, ApprovalManager, ToolExecutor, or any
      verification code, or execute/approve/persist anything. This
      module is a pure function of (already-real strings and data) to
      a CompoundGroundingResult, and nothing else.
    - Modify, or extend, intelligence.grounding's own UngroundedReason
      enum or GroundingResult dataclass. A wholly new, separate
      CompoundUngroundedReason/CompoundGroundingResult pair is defined
      here instead.
    - Get imported by intelligence/grounding.py, intelligence/planning.py,
      core/orchestrator.py, or any other live runtime module. Only this
      module's own dedicated tests import it during Phase 97 (see
      tests/unit/test_compound_grounding.py and
      tests/unit/test_compound_isolation.py).
    - Allow a second template, a reversed pair, or any capability
      pairing outside the one hand-authored entry below. Adding either
      requires a fresh, explicit, separately-approved planning
      decision - never a runtime discovery, a model-provided ordering,
      or a dynamically registered template.

Reuse strategy: this module imports several already-existing, pure,
stateless helpers from intelligence.grounding - the request
normalizer, the whitespace-padding helper, the negation-marker check,
the whole-catalog signature evaluator, the argument-span extractor,
and the argument-value comparison normalizer - rather than duplicating
their logic. None of them has any bearing on how many capabilities a
decision may declare; that is entirely this module's own, additional,
strictly-ordered contract. The import direction is strictly one-way:
this module imports from intelligence.grounding and
intelligence.capability_catalog; neither of those modules, nor any
live runtime module, imports anything from here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import intelligence.grounding as _live_grounding
from intelligence.capability_catalog import CapabilityId
from intelligence.compound_structured_output import ParsedCompoundToolSelection
from intelligence.grounding import GroundingResult as _LiveGroundingResult

#: The one and only trusted, ordered compound template Phase 97
#: defines. A tuple of an ordered tuple - never a set/frozenset - so
#: (PROJECT_STATE_UPDATE_PHASE, PROJECT_STATE_SHOW) and its reverse are
#: never treated as equivalent. Adding a second entry, or reordering
#: this one, requires a fresh, separately-approved planning decision -
#: never a runtime/model/dynamic mechanism.
_COMPOUND_CONNECTOR = " and then "


@dataclass(frozen=True, slots=True)
class CompoundTemplate:
    """One trusted, hand-authored, ordered two-capability template.

    Attributes:
        template_id: A short, stable, bounded diagnostic identifier -
            never shown to a user, never derived from model output.
        steps: The ordered pair of user-facing CapabilityId values this
            template recognizes, in the exact order a valid compound
            decision and a valid compound request must both,
            independently, exhibit. Position matters: `steps[0]` is
            always the expected first clause's capability, `steps[1]`
            the expected second's - equality is always positional
            tuple equality, never set membership.
        connector: The one fixed, already-padded connector string this
            template's request text must contain exactly once to be
            split into its two ordered clauses.
    """

    template_id: str
    steps: tuple[CapabilityId, CapabilityId]
    connector: str


#: Exactly one entry. Each step's "expected argument-bearing" vs.
#: "expected zero-argument" shape is deliberately never redeclared here
#: - it is already fully determined by
#: CAPABILITY_CATALOG[capability_id].arguments (empty means
#: zero-argument), which this module never duplicates.
_ALLOWED_COMPOUND_TEMPLATES: tuple[CompoundTemplate, ...] = (
    CompoundTemplate(
        template_id="project_state_update_phase_then_show",
        steps=(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            CapabilityId.PROJECT_STATE_SHOW,
        ),
        connector=_COMPOUND_CONNECTOR,
    ),
)


class CompoundUngroundedReason(Enum):
    """The bounded, non-sensitive compound-only reason taxonomy.

    A wholly separate enum from intelligence.grounding.UngroundedReason
    - never extended, subclassed, or unioned with it. Exactly these
    nine members exist; a caller must never invent a tenth.
    """

    NEGATED_OR_CONFLICTING_REQUEST = "negated_or_conflicting_request"
    TEMPLATE_NOT_ALLOWED = "template_not_allowed"
    CONNECTOR_MISSING = "connector_missing"
    CONNECTOR_REPEATED = "connector_repeated"
    EMPTY_CLAUSE = "empty_clause"
    CLAUSE_NO_SIGNATURE_MATCHED = "clause_no_signature_matched"
    CLAUSE_MULTIPLE_SIGNATURES_MATCHED = "clause_multiple_signatures_matched"
    CLAUSE_CAPABILITY_MISMATCH = "clause_capability_mismatch"
    CLAUSE_ARGUMENT_MISMATCH = "clause_argument_mismatch"


@dataclass(frozen=True, slots=True)
class CompoundGroundingResult:
    """The result of one ground_compound_decision() call.

    Attributes:
        grounded: True only when every applicable check passed.
        reason: Set only when grounded is False - the single,
            first-failing CompoundUngroundedReason.
    """

    grounded: bool
    reason: CompoundUngroundedReason | None = None

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent
        outcome - a grounded result never carries a reason, and an
        ungrounded one always does.

        Raises:
            ValueError: If grounded and reason are inconsistent.
        """
        if self.grounded and self.reason is not None:
            raise ValueError("A grounded result cannot carry a reason.")
        if not self.grounded and self.reason is None:
            raise ValueError("An ungrounded result must carry a reason.")


_GROUNDED = CompoundGroundingResult(grounded=True)


def _reject(reason: CompoundUngroundedReason) -> CompoundGroundingResult:
    """Build a bounded, ungrounded result for one reason.

    Args:
        reason: The single, first-failing reason.

    Returns:
        A CompoundGroundingResult with grounded=False.
    """
    return CompoundGroundingResult(grounded=False, reason=reason)


def _matching_template(
    declared_pair: tuple[CapabilityId, CapabilityId],
) -> CompoundTemplate | None:
    """Return the one allowlisted template whose ordered steps exactly
    equal declared_pair, or None.

    Positional tuple equality only - a reversed declared pair never
    matches, since it is a different, absent 2-tuple, not merely a
    differently-ordered "equal" set.

    Args:
        declared_pair: The parsed decision's own declared, ordered
            (step 1, step 2) capability ids.

    Returns:
        The matching CompoundTemplate, or None if declared_pair is not
        a member of _ALLOWED_COMPOUND_TEMPLATES.
    """
    for template in _ALLOWED_COMPOUND_TEMPLATES:
        if template.steps == declared_pair:
            return template
    return None


def _split_clauses(
    request_text: str, connector: str
) -> tuple[str, str] | CompoundGroundingResult:
    """Split the live request into exactly two ordered clauses on the
    one fixed, padded connector.

    Mirrors intelligence.grounding._extract_argument_span()'s own
    established count/find/strip technique, and its negation-marker
    padding technique, exactly - never a new splitting philosophy.

    Args:
        request_text: The live, verbatim request text.
        connector: The template's own fixed, already-padded connector
            (e.g. " and then ").

    Returns:
        A tuple of (clause_1_text, clause_2_text), each already
        normalized and trimmed, on success. A CompoundGroundingResult
        describing exactly why no single, usable ordered split could
        be established, otherwise.
    """
    normalized = _live_grounding._normalize(request_text)
    padded = _live_grounding._padded(normalized)

    occurrences = padded.count(connector)
    if occurrences == 0:
        return _reject(CompoundUngroundedReason.CONNECTOR_MISSING)
    if occurrences > 1:
        return _reject(CompoundUngroundedReason.CONNECTOR_REPEATED)

    index = padded.find(connector)
    clause_1 = padded[:index].strip()
    clause_2 = padded[index + len(connector) :].strip()
    if not clause_1 or not clause_2:
        return _reject(CompoundUngroundedReason.EMPTY_CLAUSE)

    return clause_1, clause_2


def _ground_clause_signature(
    clause_text: str, expected_capability_id: CapabilityId
) -> CompoundUngroundedReason | None:
    """Require clause_text to uniquely match exactly
    expected_capability_id's own signature, evaluated against the
    *complete* current user-facing signature catalogue.

    Reuses intelligence.grounding._grounded_capability_ids() unchanged
    - the identical, whole-catalog evaluator the live single-capability
    path already uses - applied here to one clause's own text alone,
    never to the whole request.

    Args:
        clause_text: One already-split, normalized, trimmed clause.
        expected_capability_id: The capability this clause's own
            template position expects.

    Returns:
        None if clause_text uniquely and correctly grounds
        expected_capability_id. Otherwise the single, bounded
        CompoundUngroundedReason describing why not - zero matches,
        more than one match (which also catches a third, embedded
        supported action), or exactly one match that is not the
        expected capability (which also catches a text-level reversed
        order, since swapping two clauses swaps which text evidences
        which capability).
    """
    matched = _live_grounding._grounded_capability_ids(clause_text)
    if not matched:
        return CompoundUngroundedReason.CLAUSE_NO_SIGNATURE_MATCHED
    if len(matched) > 1:
        return CompoundUngroundedReason.CLAUSE_MULTIPLE_SIGNATURES_MATCHED
    (only_match,) = matched
    if only_match is not expected_capability_id:
        return CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH
    return None


def _ground_clause_argument(
    clause_text: str,
    capability_id: CapabilityId,
    declared_arguments: Mapping[str, object],
) -> CompoundUngroundedReason | None:
    """Require capability_id's own declared "value" argument (if any)
    to be exactly attributable to clause_text's own text alone.

    A no-op (returns None immediately) for a capability with no
    argument marker (e.g. PROJECT_STATE_SHOW) - such a capability's
    clause is required to carry no attributable argument at all, which
    the compound parser's own exact-arguments-shape validation already
    enforces (an empty "arguments" object), so there is nothing further
    to attribute here.

    Args:
        clause_text: One already-split, normalized, trimmed clause -
            only this clause's own text is ever consulted; the other
            clause's text is never passed to this function for this
            capability's value.
        capability_id: The capability this clause's own template
            position expects.
        declared_arguments: The structured step's own already-validated
            arguments dict for this same capability.

    Returns:
        None if there is no argument to attribute, or the one real
        argument is exactly attributable. Otherwise
        CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH.
    """
    marker = _live_grounding._ARGUMENT_MARKER_BY_CAPABILITY.get(capability_id)
    if marker is None:
        return None

    span_outcome = _live_grounding._extract_argument_span(clause_text, marker)
    if isinstance(span_outcome, _LiveGroundingResult):
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH
    candidate_span = span_outcome

    declared_value = declared_arguments.get("value")
    if not isinstance(declared_value, str):
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    normalized_span = _live_grounding._strip_one_trailing_terminal_punctuation(
        candidate_span
    )
    normalized_value = _live_grounding._normalize_for_argument_comparison(
        declared_value
    )
    if normalized_span != normalized_value:
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH
    return None


def ground_compound_decision(
    *, request_text: str, parsed: ParsedCompoundToolSelection
) -> CompoundGroundingResult:
    """The single, deny-only, pure grounding gate for a compound
    decision (Phase 97).

    This function's only inputs are the live request_text and the
    already-parsed compound decision - never AssembledContext, memory,
    prior messages, model rationale/confidence, tool results, approval
    state, workflow state, repository state, another AI call, fuzzy
    matching, semantic similarity, or embeddings. Every other value it
    consults (the template allowlist, the connector, the signature
    catalogue, the argument markers) is this module's own, or
    intelligence.grounding's own, trusted, static, already-imported
    data - never looked up from any external source at call time.

    Never called by any live code path in Phase 97 - only this
    module's own dedicated tests exercise it.

    Args:
        request_text: The live, verbatim request text.
        parsed: An already-parsed ParsedCompoundToolSelection (from
            intelligence.compound_structured_output.parse_compound_tool_selection()).

    Returns:
        CompoundGroundingResult(grounded=True) if every applicable
        check passes. CompoundGroundingResult(grounded=False,
        reason=...) with the single, first-failing, bounded
        CompoundUngroundedReason otherwise - never a raw request
        fragment, candidate span, rejected value, or any other
        sensitive detail.
    """
    if _live_grounding._contains_negation_marker(request_text):
        return _reject(CompoundUngroundedReason.NEGATED_OR_CONFLICTING_REQUEST)

    declared_pair = (parsed.steps[0].capability_id, parsed.steps[1].capability_id)
    template = _matching_template(declared_pair)
    if template is None:
        return _reject(CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED)

    clauses_outcome = _split_clauses(request_text, template.connector)
    if isinstance(clauses_outcome, CompoundGroundingResult):
        return clauses_outcome
    clause_texts = clauses_outcome

    for index in (0, 1):
        signature_failure = _ground_clause_signature(
            clause_texts[index], template.steps[index]
        )
        if signature_failure is not None:
            return _reject(signature_failure)

    for index in (0, 1):
        argument_failure = _ground_clause_argument(
            clause_texts[index],
            template.steps[index],
            parsed.steps[index].arguments,
        )
        if argument_failure is not None:
            return _reject(argument_failure)

    return _GROUNDED
