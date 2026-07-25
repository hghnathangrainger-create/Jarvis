"""
actionable_decision_issue.py

Phase 101, Batch 1 (dormant foundation) -
docs/phase_101_actionable_ambiguity_planning.md: a narrow, deterministic
typed model for exactly one class of "ask jarvis to:" failure - a
required argument that is absent or invalid - for a small, explicit,
five-capability allowlist, plus a pure formatter rendering it as
concise, non-technical retry guidance.

Responsibilities:
    - Define the bounded ActionableIssueKind vocabulary (exactly two
      members: MISSING_REQUIRED_ARGUMENT, INVALID_ARGUMENT_FORMAT) and
      the ActionableDecisionIssue dataclass, validated at construction.
    - Define the fixed, hand-maintained Phase 101 guidance
      specification for exactly five capabilities
      (SCHEDULE_ENABLE/SCHEDULE_DISABLE/SCHEDULE_SHOW_ENABLED_STATE/
      MEMORY_SEARCH/PROJECT_STATE_UPDATE_PHASE) - never every capability
      in the catalog automatically.
    - Classify an eligible failure into an ActionableDecisionIssue using
      only already-trusted evidence:
        * classify_actionable_issue_from_ungrounded_selection() reuses
          a live ground_decision() call's own already-computed
          capability_id/UngroundedReason directly - no new grounding
          call.
        * classify_actionable_issue_from_invalid_output() independently
          peeks the model's own claimed capability_id from the raw
          provider text (never trusting it alone), then calls the
          real, unmodified intelligence.grounding.ground_decision()
          with that capability_id and a fixed, never-real sentinel
          argument value, so grounding's own existing negation/
          signature-uniqueness/model-agreement checks decide - on any
          disagreement, remain fail-closed.
        * classify_actionable_issue_from_unsupported() has no model
          capability_id to start from at all (a valid "unsupported"
          decision carries none) - it instead probes each of the five
          allowlisted capabilities through the same real
          ground_decision() call, and only proceeds if exactly one
          probe reaches the argument-extraction stage (i.e. request
          text alone, independent of any model output, uniquely and
          unambiguously identifies it against the *entire* catalog's
          signature space, not merely against the allowlist).
    - Render a fixed, deterministic, four-part message via
      format_actionable_decision_issue() - never an AI call, never
      capability ids/enum names/parser terminology, never a guessed
      value.

Does NOT:
    - Change intelligence.grounding.ground_decision()'s signature,
      return shape, or internal logic in any way. Every classifier
      here calls it completely unmodified, exactly as any other caller
      would.
    - Change intelligence.structured_output.py at all. The one new
      peek helper re-parses raw text using that module's own already-
      private fence-stripping/duplicate-key-safe JSON decoding
      (imported, not reimplemented) - mirroring
      intelligence.compound_structured_output.peek_compound_decision()'s
      own established cross-module reuse convention exactly.
    - Read Verified Action Context, memory, ProjectState, or any other
      historical or retrieved content. Every classifier's only inputs
      are the live request text and/or the live raw provider text -
      never anything stored.
    - Wire into any live user-facing response path. Nothing in
      core/orchestrator.py references this module in Batch 1; the
      field this module's callers populate on PlanningOutcome is
      inspected only by this feature's own dedicated tests.
    - Create an approval, a workflow, a progress row, or execute a
      tool. Every function here is a pure, side-effect-free read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from intelligence.grounding import UngroundedReason, ground_decision
from intelligence.structured_output import ToolSelectionParseError as _LiveToolSelectionParseError
from intelligence.structured_output import (
    _reject_duplicate_keys as _live_reject_duplicate_keys,
)
from intelligence.structured_output import (
    _strip_single_outer_fence as _live_strip_single_outer_fence,
)

#: Mirrors intelligence.structured_output._MAX_RAW_OUTPUT_CHARS's own
#: value, declared independently here rather than imported - matching
#: intelligence.compound_structured_output.py's own established
#: precedent for this exact constant.
_MAX_RAW_OUTPUT_CHARS = 2000

#: Fixed, never-realistic sentinel values used only to probe whether a
#: capability's own declared argument is extractable from request text
#: at all - never stored, never shown to a user, never compared against
#: anything but the request text itself by the real, unmodified
#: ground_decision(). Chosen so an accidental real collision is
#: effectively impossible; even a collision would only ever suppress an
#: issue (grounded=True is never treated as an issue), never fabricate
#: one.
_SENTINEL_INT_VALUE = -987654321
_SENTINEL_STR_VALUE = "￾__phase_101_actionable_issue_probe_sentinel__￾"

#: The bounded reasons that legitimately currently map to an eligible
#: issue kind (Section 6 of the accepted planning amendment). Every
#: other UngroundedReason - negation/conflict, no/multiple signature
#: matches, model/independent disagreement, or a genuine value
#: mismatch - deliberately produces no issue at all.
_MISSING_REASONS = frozenset({UngroundedReason.MISSING_ARGUMENT_SPAN})
_INVALID_REASONS = frozenset({UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN})

#: The exact, closed set of intelligence.structured_output.
#: ToolSelectionParseError.reason strings that describe the required
#: argument itself being absent or invalid - and nothing else. Every
#: other reason (malformed JSON, an unknown decision value, an unknown
#: or non-catalog capability id, an internal-only capability, an
#: unexpected top-level key set, an unknown argument *name*, a NUL/
#: control character, an oversized string, or oversized raw output) is
#: a genuinely different, non-argument-content defect and must never be
#: reinterpreted as "the argument was missing/invalid" merely because a
#: capability_id also happens to be peekable from the same raw text.
_ELIGIBLE_INVALID_OUTPUT_REASONS = frozenset(
    {
        "missing required argument",
        "invalid argument type",
        # Section 6 of the accepted planning amendment: a whitespace-
        # only string value should normally count as missing - this is
        # still an argument-content defect on the one declared
        # argument, so it is eligible for the same independent-
        # evidence probe as the two reasons above; the probe's own
        # fresh ground_decision() call (never this string) decides the
        # final MISSING-vs-INVALID classification.
        "empty or whitespace-only string argument",
    }
)


class ActionableIssueKind(Enum):
    """The bounded, non-speculative Phase 101 Batch 1 issue vocabulary.
    Exactly these two members exist - no collision, compound,
    negation, or unsupported-request kind is added in this batch."""

    MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
    INVALID_ARGUMENT_FORMAT = "invalid_argument_format"


@dataclass(frozen=True, slots=True)
class _GuidanceSpec:
    """One capability's fixed, hand-maintained Phase 101 guidance
    metadata. Never derived from model output; never touched by
    Verified Action Context.

    Attributes:
        action_label: A short, user-facing name for the missing/invalid
            value (never the raw catalog argument name, e.g.
            "schedule_id").
        retry_template: The exact, already-supported command grammar,
            with a bracketed placeholder where the value is unknown -
            never a real value.
        approval_clause: The exact sentence to append when a valid
            retry would still require approval, or None for a GREEN
            capability.
    """

    action_label: str
    retry_template: str
    approval_clause: str | None


#: The complete, closed Phase 101 Batch 1 allowlist (Section 8 of the
#: accepted planning document) - exactly five capabilities. No other
#: capability may receive actionable retry guidance in this phase.
_GUIDANCE_SPEC_BY_CAPABILITY: dict[CapabilityId, _GuidanceSpec] = {
    CapabilityId.SCHEDULE_ENABLE: _GuidanceSpec(
        action_label="schedule ID",
        retry_template="ask jarvis to: enable schedule <schedule id>",
        approval_clause="Enabling a schedule will still require approval.",
    ),
    CapabilityId.SCHEDULE_DISABLE: _GuidanceSpec(
        action_label="schedule ID",
        retry_template="ask jarvis to: disable schedule <schedule id>",
        approval_clause="Disabling a schedule will still require approval.",
    ),
    CapabilityId.SCHEDULE_SHOW_ENABLED_STATE: _GuidanceSpec(
        action_label="schedule ID",
        retry_template="ask jarvis to: check the enabled state of schedule <schedule id>",
        approval_clause=None,
    ),
    CapabilityId.MEMORY_SEARCH: _GuidanceSpec(
        action_label="search text",
        retry_template="ask jarvis to: search memories for <search text>",
        approval_clause=None,
    ),
    CapabilityId.PROJECT_STATE_UPDATE_PHASE: _GuidanceSpec(
        action_label="phase value",
        retry_template="ask jarvis to: update my project phase to <phase value>",
        approval_clause="Updating the project phase will still require approval.",
    ),
}

#: The same five capabilities, as a frozenset - used for O(1) allowlist
#: membership checks. A dedicated test proves this equals
#: _GUIDANCE_SPEC_BY_CAPABILITY's own key set exactly.
ACTIONABLE_GUIDANCE_ALLOWLIST: frozenset[CapabilityId] = frozenset(
    _GUIDANCE_SPEC_BY_CAPABILITY
)


@dataclass(frozen=True, slots=True)
class ActionableDecisionIssue:
    """One bounded, fully-trusted description of a missing/invalid
    required-argument failure for an allowlisted capability.

    Every field is either a fixed catalog/specification fact or the
    bounded classification itself - never a guessed, historical, or
    model-authored value.

    Attributes:
        kind: Which of the two bounded issue kinds this is.
        capability_id: The allowlisted capability this issue concerns.
        argument_name: The capability's own declared argument name
            (from CapabilityArgumentSpec.name - e.g. "schedule_id").
        argument_type_name: The capability's own declared argument type
            ("int" or "str").
        action_label: The fixed, user-facing label for the value.
        retry_example: The fixed, already-supported retry command, with
            a placeholder - never a real value.
        requires_approval: Whether a valid retry would still require
            approval (a trusted fact from the guidance specification).
    """

    kind: ActionableIssueKind
    capability_id: CapabilityId
    argument_name: str
    argument_type_name: str
    action_label: str
    retry_example: str
    requires_approval: bool

    def __post_init__(self) -> None:
        """Reject any construction outside the closed Phase 101 Batch 1
        allowlist/vocabulary.

        Raises:
            ValueError: If capability_id is not allowlisted, or any
                bounded string field is empty.
        """
        if self.capability_id not in ACTIONABLE_GUIDANCE_ALLOWLIST:
            raise ValueError(
                f"{self.capability_id!r} is not in the Phase 101 Batch 1 "
                "actionable-guidance allowlist."
            )
        if self.argument_type_name not in ("int", "str"):
            raise ValueError(
                f"Unsupported argument_type_name: {self.argument_type_name!r}."
            )
        if not self.argument_name or not self.action_label or not self.retry_example:
            raise ValueError(
                "argument_name, action_label, and retry_example must all be "
                "non-empty."
            )


def _sentinel_arguments_for(capability_id: CapabilityId) -> dict[str, object]:
    """Build the one-key probe arguments dict for a real ground_decision()
    call, using the capability's own declared argument name/type.

    Args:
        capability_id: An allowlisted capability id.

    Returns:
        A dict of exactly one key -> a fixed, never-real sentinel value
        of the correct declared type.
    """
    spec = CAPABILITY_CATALOG[capability_id].arguments[0]
    sentinel: object = (
        _SENTINEL_INT_VALUE if spec.type_name == "int" else _SENTINEL_STR_VALUE
    )
    return {spec.name: sentinel}


def _issue_kind_for_reason(
    reason: UngroundedReason,
) -> ActionableIssueKind | None:
    """Map a bounded UngroundedReason to a bounded ActionableIssueKind,
    or None if that reason is not eligible for guidance in Batch 1.

    Args:
        reason: The real UngroundedReason a ground_decision() call
            returned.

    Returns:
        The corresponding ActionableIssueKind, or None for every
        reason outside the two eligible ones (negation/conflict, no/
        multiple signature match, model/independent disagreement, and
        genuine value mismatch all return None).
    """
    if reason in _MISSING_REASONS:
        return ActionableIssueKind.MISSING_REQUIRED_ARGUMENT
    if reason in _INVALID_REASONS:
        return ActionableIssueKind.INVALID_ARGUMENT_FORMAT
    return None


def _build_issue(
    capability_id: CapabilityId, kind: ActionableIssueKind
) -> ActionableDecisionIssue:
    """Construct the one ActionableDecisionIssue for an allowlisted
    capability and an already-determined eligible kind.

    Args:
        capability_id: An allowlisted capability id.
        kind: The already-determined eligible issue kind.

    Returns:
        A fully-populated ActionableDecisionIssue.
    """
    spec = _GUIDANCE_SPEC_BY_CAPABILITY[capability_id]
    argument_spec = CAPABILITY_CATALOG[capability_id].arguments[0]
    return ActionableDecisionIssue(
        kind=kind,
        capability_id=capability_id,
        argument_name=argument_spec.name,
        argument_type_name=argument_spec.type_name,
        action_label=spec.action_label,
        retry_example=spec.retry_template,
        requires_approval=spec.approval_clause is not None,
    )


def classify_actionable_issue_from_ungrounded_selection(
    *, capability_id: CapabilityId, reason: UngroundedReason
) -> ActionableDecisionIssue | None:
    """Classify an already-computed, real UNGROUNDED_SELECTION outcome.

    Reuses the live ground_decision() call's own already-established
    result directly - by the time that call reached argument-span
    extraction (the only place MISSING_ARGUMENT_SPAN/
    AMBIGUOUS_ARGUMENT_SPAN can occur), it had already independently
    confirmed the request text matches exactly one capability signature
    and that the model's own selected capability_id agrees with it -
    no new grounding call, no new evidence collection.

    Args:
        capability_id: The capability select_tool() already grounded
            against (the model's own selection, already confirmed to
            be the request text's unique match).
        reason: The real UngroundedReason ground_decision() returned.

    Returns:
        An ActionableDecisionIssue if capability_id is allowlisted and
        reason is one of the two eligible reasons; otherwise None.
    """
    if capability_id not in ACTIONABLE_GUIDANCE_ALLOWLIST:
        return None
    kind = _issue_kind_for_reason(reason)
    if kind is None:
        return None
    return _build_issue(capability_id, kind)


def _peek_allowlisted_capability_id(raw_text: str) -> CapabilityId | None:
    """Narrow, read-only peek: does raw_text parse as a JSON object
    whose own "capability_id" names a real, catalog-known, non-
    internal, Phase 101-allowlisted capability?

    Never validates "arguments", never raises, never trusted alone -
    only ever used as one input to a real ground_decision() call, which
    independently re-confirms it against the live request text.

    Args:
        raw_text: The raw, untrimmed text the AI provider returned.

    Returns:
        The allowlisted CapabilityId if one is safely identifiable;
        None for malformed JSON, an unexpected shape, an unknown or
        non-allowlisted capability, or any other defect.
    """
    if len(raw_text) > _MAX_RAW_OUTPUT_CHARS:
        return None
    try:
        text = _live_strip_single_outer_fence(raw_text)
    except _LiveToolSelectionParseError:
        return None
    if not text:
        return None
    try:
        parsed_json = json.loads(text, object_pairs_hook=_live_reject_duplicate_keys)
    except (_LiveToolSelectionParseError, json.JSONDecodeError):
        return None
    if not isinstance(parsed_json, dict):
        return None
    capability_id_raw = parsed_json.get("capability_id")
    if not isinstance(capability_id_raw, str):
        return None
    try:
        capability_id = CapabilityId(capability_id_raw)
    except ValueError:
        return None
    if capability_id not in ACTIONABLE_GUIDANCE_ALLOWLIST:
        return None
    return capability_id


def classify_actionable_issue_from_invalid_output(
    *, raw_text: str, request_text: str, reason: str
) -> ActionableDecisionIssue | None:
    """Classify an INVALID_OUTPUT failure that may still have a
    trustworthy capability identity.

    Gates on `reason` first: only the closed set of
    ToolSelectionParseError.reason strings that describe the required
    argument itself being absent/invalid are eligible at all
    (_ELIGIBLE_INVALID_OUTPUT_REASONS) - a genuinely unrelated schema
    defect (malformed JSON, an unknown decision value, an unknown
    capability id, an unexpected key set, ...) must never be
    reinterpreted as user ambiguity merely because a capability_id
    also happens to be peekable from the same raw text.

    Never trusts the model's own claimed capability_id alone: after
    peeking it (read-only, never validated), this calls the real,
    unmodified ground_decision() with that exact capability_id and a
    fixed sentinel argument value, so grounding's own existing
    negation/signature-uniqueness/model-agreement checks are the sole
    authority. Any disagreement (ambiguous signature, model capability
    id differing from the request text's own unique match, negation)
    yields the same real UngroundedReason values that already exist for
    exactly this purpose - and this function returns None for every one
    of them.

    Args:
        raw_text: The raw, untrimmed provider text that failed
            intelligence.structured_output.parse_tool_selection().
        request_text: The live, verbatim request text.
        reason: The real ToolSelectionParseError.reason string that
            was raised.

    Returns:
        An ActionableDecisionIssue only when reason is one of the
        eligible argument-content strings, the peeked capability id is
        allowlisted, and the real ground_decision() call - probed with
        a sentinel argument - reaches exactly a missing or invalid-
        format argument span. None for every other case, including
        malformed JSON with no trustworthy capability identity at all.
    """
    if reason not in _ELIGIBLE_INVALID_OUTPUT_REASONS:
        return None
    capability_id = _peek_allowlisted_capability_id(raw_text)
    if capability_id is None:
        return None
    return _classify_via_probe(capability_id=capability_id, request_text=request_text)


def classify_actionable_issue_from_unsupported(
    *, request_text: str
) -> ActionableDecisionIssue | None:
    """Classify a valid "unsupported" decision that may still describe
    one deterministically identifiable, allowlisted missing/invalid
    argument.

    A valid "unsupported" decision carries no capability_id at all
    (intelligence.structured_output.ParsedToolSelection.capability_id
    is None) - the model's own response is never used as a source of
    capability identity here. Instead, each of the five allowlisted
    capabilities is probed in turn through the real, unmodified
    ground_decision(); because that function's own signature-matching
    step always scans the *entire* capability catalog regardless of
    which capability_id is passed in, at most one probe can ever reach
    the argument-extraction stage - every other probe necessarily
    receives NO_SIGNATURE_MATCHED, MULTIPLE_SIGNATURES_MATCHED,
    SELECTED_CAPABILITY_NOT_UNIQUE_MATCH, or
    NEGATED_OR_CONFLICTING_REQUEST, all of which classify to None.

    Args:
        request_text: The live, verbatim request text - the only
            evidence this function ever consults.

    Returns:
        An ActionableDecisionIssue only when request text alone,
        independent of any model output, uniquely identifies one
        allowlisted capability with a missing/invalid argument. None
        otherwise (including a genuinely vague or unrelated request).
    """
    for capability_id in ACTIONABLE_GUIDANCE_ALLOWLIST:
        issue = _classify_via_probe(
            capability_id=capability_id, request_text=request_text
        )
        if issue is not None:
            return issue
    return None


def _classify_via_probe(
    *, capability_id: CapabilityId, request_text: str
) -> ActionableDecisionIssue | None:
    """Shared probe: call the real ground_decision() with a fixed
    sentinel argument value for one allowlisted capability, and
    classify the result.

    Args:
        capability_id: An allowlisted capability id to probe.
        request_text: The live, verbatim request text.

    Returns:
        An ActionableDecisionIssue if the probe reaches exactly a
        missing/invalid argument span; None for every other grounding
        outcome (including a fully grounded result, which can only mean
        the sentinel coincidentally matched a real, present value - a
        genuine value exists, so this is not a missing/invalid case).
    """
    result = ground_decision(
        request_text=request_text,
        capability_id=capability_id,
        arguments=_sentinel_arguments_for(capability_id),
    )
    if result.grounded or result.reason is None:
        return None
    kind = _issue_kind_for_reason(result.reason)
    if kind is None:
        return None
    return _build_issue(capability_id, kind)


def format_actionable_decision_issue(issue: ActionableDecisionIssue) -> str:
    """Render one ActionableDecisionIssue as a fixed, deterministic,
    non-technical retry message.

    Pure and deterministic: the same issue always renders identical
    text. Never calls an AI model, never mentions a capability id, enum
    name, or parser/grounding term, and never includes a guessed value
    - every word beyond the issue's own bounded fields is a fixed
    literal.

    Args:
        issue: The ActionableDecisionIssue to render.

    Returns:
        A three- or four-sentence message: what is missing/invalid,
        what Jarvis needs, one exact supported retry example, and (only
        for a capability that requires approval) one fixed approval
        notice.
    """
    if issue.kind is ActionableIssueKind.MISSING_REQUIRED_ARGUMENT:
        opening = (
            f"I need the {issue.action_label} before I can prepare this action."
        )
    else:
        if issue.argument_type_name == "int":
            opening = f"The {issue.action_label} must be a whole number."
        else:
            opening = f"The {issue.action_label} isn't in a format Jarvis can use."

    parts = [opening, f"Try: {issue.retry_example}."]
    if issue.requires_approval:
        spec = _GUIDANCE_SPEC_BY_CAPABILITY[issue.capability_id]
        assert spec.approval_clause is not None
        parts.append(spec.approval_clause)
    return " ".join(parts)
