"""
schedule_compound_grounding.py

An isolated, non-live-wired, deterministic grounding function for
exactly one trusted, hand-authored two-capability compound request
template - the second one this codebase ever defines (Phase 99, Batch
1 - docs/phase_99_second_compound_template_planning.md):
SCHEDULE_ENABLE -> SCHEDULE_SHOW_ENABLED_STATE.

Mirrors intelligence.compound_grounding.ground_compound_decision()'s
exact shape, and reuses its own generic, already-accepted building
blocks directly (CompoundTemplate, CompoundGroundingResult,
CompoundUngroundedReason, and its private clause-splitting/signature-
grounding helpers) - but is deliberately never added to that module's
own live _ALLOWED_COMPOUND_TEMPLATES tuple, and never imported by
intelligence/planning.py's own live _select_compound_tool_sequence()
dispatch. Adding this template to the shared, already-live allowlist
would immediately make it a real, selectable "execute_sequence" pair
for the model - a dormant plan builder/recognizer existing elsewhere is
not, by itself, a live-activation boundary; only this module's own
isolation from every live call site is (see
docs/phase_99_second_compound_template_planning.md's own Batch 1/2/3
split, and tests/unit/test_phase99_batch1_isolation.py's own
confinement proofs).

Responsibilities:
    - Define this one, separate, single-entry compound-template
      allowlist (_ALLOWED_SCHEDULE_COMPOUND_TEMPLATES) - never merged
      into, or read by, intelligence.compound_grounding's own allowlist.
    - Split the live request into exactly two ordered clauses on the
      one fixed connector " and then " (reusing
      intelligence.compound_grounding's own _split_clauses() and
      intelligence.grounding's own signature-matching machinery
      unchanged), independently ground each clause's own capability
      signature, and independently ground each clause's own declared
      "schedule_id" argument against that clause's own text via a new,
      narrow numeric-argument clause grounder (Section below) -
      intelligence.compound_grounding._ground_clause_argument() cannot
      be reused here: it is hardcoded to intelligence.grounding's own
      *string*-argument marker table ("value"), never consulting the
      separate numeric-argument marker table SCHEDULE_ENABLE/
      SCHEDULE_DISABLE/SCHEDULE_SHOW_ENABLED_STATE all use.
    - Additionally require the two steps' own declared "schedule_id"
      values to agree exactly - the model must name the same schedule
      in both steps. A mismatch is refused outright, never resolved by
      preferring one value, inferring a pronoun reference, or any
      general variable-passing/result-propagation mechanism: this is a
      single, narrow, hardcoded equality check between two already-
      parsed, already-validated integers, scoped to this one template
      only.
    - Report one of the *existing*, shared CompoundUngroundedReason
      values on any failure - never a new, tenth reason
      (CompoundUngroundedReason is closed at exactly nine members by
      its own docstring; reusing CLAUSE_ARGUMENT_MISMATCH for every
      numeric-argument failure mode here, mirroring how it already
      covers every string-argument failure mode for the ProjectState
      template, keeps that invariant intact).

Does NOT:
    - Get imported by intelligence/planning.py, core/orchestrator.py,
      main.py, or any other live runtime module. Only this module's own
      dedicated tests import it in Batch 1.
    - Modify, extend, or get merged into
      intelligence.compound_grounding._ALLOWED_COMPOUND_TEMPLATES - a
      wholly separate, parallel allowlist of its own.
    - Accept a third step, a differing pair, a reversed order, or any
      capability outside this one hand-authored entry.
    - Call SecurityManager, ApprovalManager, ToolExecutor, or any
      verification code, or execute/approve/persist anything - a pure
      function of (already-real strings and data) to a
      CompoundGroundingResult, exactly like its ProjectState sibling.
"""

from __future__ import annotations

import intelligence.grounding as _live_grounding
from intelligence.capability_catalog import CapabilityId
from intelligence.compound_grounding import (
    CompoundGroundingResult,
    CompoundTemplate,
    CompoundUngroundedReason,
    _ground_clause_signature,
    _reject,
    _split_clauses,
)
from intelligence.compound_structured_output import ParsedCompoundToolSelection

#: The one fixed connector this template uses too - identical to the
#: ProjectState template's own, declared independently here (never
#: imported from intelligence.compound_grounding) so this module has no
#: import-time dependency on that module's own private connector
#: constant.
_SCHEDULE_COMPOUND_CONNECTOR = " and then "

#: Exactly one entry. A second schedule-paired template (e.g.
#: SCHEDULE_DISABLE -> SCHEDULE_SHOW_ENABLED_STATE) requires its own
#: fresh, explicit, separately-approved planning decision - never a
#: runtime discovery, a model-provided ordering, or a dynamically
#: registered template.
_ALLOWED_SCHEDULE_COMPOUND_TEMPLATES: tuple[CompoundTemplate, ...] = (
    CompoundTemplate(
        template_id="schedule_enable_then_show_enabled_state",
        steps=(
            CapabilityId.SCHEDULE_ENABLE,
            CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
        ),
        connector=_SCHEDULE_COMPOUND_CONNECTOR,
    ),
)


def _matching_schedule_template(
    declared_pair: tuple[CapabilityId, CapabilityId],
) -> CompoundTemplate | None:
    """Return the one allowlisted schedule template whose ordered steps
    exactly equal declared_pair, or None.

    Args:
        declared_pair: The parsed decision's own declared, ordered
            (step 1, step 2) capability ids.

    Returns:
        The matching CompoundTemplate, or None if declared_pair is not
        a member of _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES.
    """
    for template in _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES:
        if template.steps == declared_pair:
            return template
    return None


def _ground_schedule_clause_argument(
    clause_text: str,
    capability_id: CapabilityId,
    declared_arguments: dict[str, object],
) -> CompoundUngroundedReason | None:
    """Require capability_id's own declared "schedule_id" argument (if
    any) to be exactly attributable to clause_text's own text alone,
    via the numeric marker + exact-integer-equality technique
    intelligence.grounding.ground_decision() already uses for the
    single-decision path - never intelligence.compound_grounding's own
    _ground_clause_argument(), which only ever consults the *string*-
    argument marker table.

    Args:
        clause_text: One already-split, normalized, trimmed clause -
            only this clause's own text is ever consulted.
        capability_id: The capability this clause's own template
            position expects.
        declared_arguments: The structured step's own already-validated
            arguments dict for this same capability.

    Returns:
        None if there is no numeric argument to attribute, or the one
        real argument is exactly attributable. Otherwise
        CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH - reused for
        every numeric-argument failure mode (missing marker, ambiguous
        span, or a real mismatch), mirroring how the same reason
        already covers every string-argument failure mode for the
        ProjectState template.
    """
    marker = _live_grounding._NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY.get(capability_id)
    if marker is None:
        return None

    normalized_clause = _live_grounding._normalize(clause_text)
    span_outcome = _live_grounding._extract_numeric_argument_span(
        normalized_clause, marker
    )
    if not isinstance(span_outcome, int):
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH
    candidate_id = span_outcome

    declared_value = declared_arguments.get(_live_grounding._NUMERIC_ARGUMENT_NAME)
    if not isinstance(declared_value, int) or isinstance(declared_value, bool):
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    if candidate_id != declared_value:
        return CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH
    return None


def ground_schedule_compound_decision(
    *, request_text: str, parsed: ParsedCompoundToolSelection
) -> CompoundGroundingResult:
    """The single, deny-only, pure grounding gate for the second
    trusted compound template (Phase 99, Batch 1).

    Never called by any live code path in Batch 1 - only this module's
    own dedicated tests exercise it.

    Args:
        request_text: The live, verbatim request text.
        parsed: An already-parsed ParsedCompoundToolSelection (from
            intelligence.compound_structured_output.parse_compound_tool_selection()).

    Returns:
        CompoundGroundingResult(grounded=True) if every applicable
        check passes, including the cross-step schedule_id identity
        check. CompoundGroundingResult(grounded=False, reason=...) with
        the single, first-failing, bounded CompoundUngroundedReason
        otherwise - never a raw request fragment, candidate span,
        rejected value, or any other sensitive detail.
    """
    if _live_grounding._contains_negation_marker(request_text):
        return _reject(CompoundUngroundedReason.NEGATED_OR_CONFLICTING_REQUEST)

    declared_pair = (parsed.steps[0].capability_id, parsed.steps[1].capability_id)
    template = _matching_schedule_template(declared_pair)
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
        argument_failure = _ground_schedule_clause_argument(
            clause_texts[index],
            template.steps[index],
            parsed.steps[index].arguments,
        )
        if argument_failure is not None:
            return _reject(argument_failure)

    # Phase 99, Batch 1's own additional requirement, unique to this
    # template (the ProjectState template's own second step takes no
    # arguments at all, so no such check was ever needed there): the
    # two steps' own already-validated, already-per-clause-grounded
    # schedule_id values must also agree with *each other* exactly.
    # Narrow, hardcoded, single-purpose equality check between two
    # already-real integers - never a general variable-passing/result-
    # propagation mechanism, and never resolved by inferring which one
    # was "meant": a disagreement is refused outright.
    first_schedule_id = parsed.steps[0].arguments.get("schedule_id")
    second_schedule_id = parsed.steps[1].arguments.get("schedule_id")
    if first_schedule_id != second_schedule_id:
        return _reject(CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH)

    return CompoundGroundingResult(grounded=True)
