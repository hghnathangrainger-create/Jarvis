"""
grounding.py

Deterministic, deny-only attribution of a valid "ask jarvis to:"
structured decision to the live user request (Phase 92, Batch 1;
contracts fixed by docs/phase_92_implementation_plan.md, Section 20 -
the final accepted grounding contract, itself preceded by Sections
18/19's superseded designs).

Responsibilities:
    - Detect a small, fixed set of negation/conflict markers in the
      live request (Section 20.6) and refuse before any other check
      runs - a negated or contrasted request ("do not update the focus
      to X", "search for A, not B") is never safely actionable by a
      deterministic checker that does not attempt real natural-language
      understanding.
    - Evaluate the live request_text against every model-selectable
      capability's own fixed action-and-domain (and, for
      memory_list_recent, recency-qualifier) intent signature (Section
      20.2), and require the request to uniquely match exactly the
      model-selected capability among the *whole* catalog (Section
      20.3) - never merely check the selected capability's own
      signature in isolation, since that alone cannot detect an
      ambiguous request that also happens to satisfy a different
      capability's signature.
    - For the two capabilities with a model-supplied string argument
      (project_state_update_focus, memory_search), extract the single
      candidate argument span from the live request using a fixed,
      per-capability marker (Section 20.4), and require the model's
      already-validated value to equal that span exactly, under a
      narrow, documented normalization (Section 20.5).
    - For the one capability with a model-supplied integer argument
      (schedule_enable, Phase 94, Batch 2), extract the single
      candidate numeric span from the live request using its own
      fixed marker, and require the model's already-validated integer
      to equal that span's parsed value exactly - the same marker +
      single-occurrence + exact-equality technique as the string
      extractors, applied to a second value type, never a new
      attribution philosophy (docs/phase_94_implementation_plan.md,
      Section 6).

Does NOT:
    - Call an AI provider, compute a similarity score, or retain state
      between calls. Every function here is a pure function of
      already-real strings - no embeddings, no learned classification,
      no confidence score of any kind.
    - Read AssembledContext, memory, ProjectState, or any other
      retrieved/assembled context. Grounding evidence comes only from
      the live request_text parameter and the already-validated
      argument value passed to ground_decision() - nothing else is
      even in scope to consult.
    - Modify, coerce, trim, reorder, or otherwise alter the
      model-supplied argument value. This module only ever decides
      accept/reject; the original, already-validated value passed to
      build_tool_input() afterward is untouched either way.
    - Widen an outcome. ground_decision() can only cause select_tool()
      to refuse a decision that would otherwise have proceeded; it can
      never cause an otherwise-invalid decision (a malformed structured
      output, an unsupported decision, a hygiene-failing argument) to
      become valid.
    - Attempt quotation parsing, sentiment analysis, or general
      natural-language negation understanding. The negation gate is a
      small, fixed substring/whole-word check only (Section 20.6) - a
      legitimate literal memory-search value that itself contains one
      of the fixed markers may be refused in this V1 and require
      simpler restatement; this is a deliberate, documented limitation,
      not an oversight.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from intelligence.capability_catalog import CapabilityId

#: The one model-supplied argument name every string argument-bearing
#: capability in this catalog uses (Phase 90 Batch 3, Phase 91 Batch 2).
_ARGUMENT_NAME = "value"

#: The one model-supplied integer argument name SCHEDULE_ENABLE uses
#: (Phase 94, Batch 2) - a distinct name and attribution mechanism from
#: _ARGUMENT_NAME's string capabilities, since a schedule id is
#: attributed via marker + exact integer equality, never marker +
#: string equality.
_NUMERIC_ARGUMENT_NAME = "schedule_id"

_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")

_TERMINAL_PUNCTUATION = (".", "!", "?")


class UngroundedReason(Enum):
    """The bounded, non-sensitive internal reason taxonomy (Section
    20.9) - never the raw request, the candidate span, the rejected
    value, retrieved context, or model reasoning. Exactly these seven
    members exist; a caller must never invent an eighth."""

    NEGATED_OR_CONFLICTING_REQUEST = "negated_or_conflicting_request"
    NO_SIGNATURE_MATCHED = "no_signature_matched"
    MULTIPLE_SIGNATURES_MATCHED = "multiple_signatures_matched"
    SELECTED_CAPABILITY_NOT_UNIQUE_MATCH = "selected_capability_not_unique_match"
    MISSING_ARGUMENT_SPAN = "missing_argument_span"
    AMBIGUOUS_ARGUMENT_SPAN = "ambiguous_argument_span"
    ARGUMENT_VALUE_MISMATCH = "argument_value_mismatch"


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """The result of one ground_decision() call.

    Attributes:
        grounded: True only when every applicable check passed.
        reason: Set only when grounded is False - the single,
            first-failing UngroundedReason.
    """

    grounded: bool
    reason: UngroundedReason | None = None

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


_GROUNDED = GroundingResult(grounded=True)


def _reject(reason: UngroundedReason) -> GroundingResult:
    """Build a bounded, ungrounded result for one reason.

    Args:
        reason: The single, first-failing reason.

    Returns:
        A GroundingResult with grounded=False.
    """
    return GroundingResult(grounded=False, reason=reason)


def _normalize(text: str) -> str:
    """Casefold, normalize curly apostrophes to straight, and collapse
    whitespace - the one shared normalization step every check below
    reuses (Section 20 "Request normalization").

    Args:
        text: The raw text to normalize.

    Returns:
        The casefolded, apostrophe-normalized, whitespace-collapsed,
        trimmed text.
    """
    folded = text.casefold().replace("’", "'")
    return re.sub(r"\s+", " ", folded).strip()


def _tokenize(normalized_text: str) -> frozenset[str]:
    """Split already-normalized text into plain alphanumeric tokens.

    Deliberately a separate, simpler tokenizer than
    intelligence.context.derive_query_terms(): that function is tuned
    for memory-search relevance (a 4-character minimum, a general
    English stopword list) - neither tuning is appropriate here, where
    even a short token (e.g. "to") must remain a real, distinct token
    for exact action/domain matching, and no stopword filtering is
    wanted at all (grounding matches specific, hand-chosen tokens only,
    never ranks by informativeness).

    Args:
        normalized_text: Text already passed through _normalize().

    Returns:
        The set of non-empty tokens.
    """
    return frozenset(token for token in _TOKEN_PATTERN.split(normalized_text) if token)


def _padded(normalized_text: str) -> str:
    """Wrap already-normalized text with one leading and trailing
    space, so a whole-word substring search can never match a word
    that merely contains the same letters without a space boundary on
    both sides (e.g. "not" inside "notebook").

    Args:
        normalized_text: Text already passed through _normalize().

    Returns:
        The text padded with a single leading and trailing space.
    """
    return f" {normalized_text} "


# ---------------------------------------------------------------------------
# Request-level negation / conflict gate (Section 20.6)
# ---------------------------------------------------------------------------

#: Matched as the padded substring " <word> " - safe from matching
#: inside "notebook"/"notice" (no space follows "not") or
#: "whenever"/"nevertheless" (no space surrounds "never" in either
#: word). " not " alone already catches every "<word> not" construction
#: ("do not", "does not", "is not", "will not", "should not", ...)
#: since each contains the standalone word "not".
_WHOLE_WORD_NEGATION_MARKERS: tuple[str, ...] = (" not ", " never ")

#: Matched as a direct substring of the apostrophe-normalized text -
#: safe without padding, since the apostrophe itself is a sufficiently
#: distinctive boundary no ordinary word shares.
_CONTRACTION_NEGATION_MARKERS: tuple[str, ...] = (
    "don't",
    "doesn't",
    "isn't",
    "won't",
    "can't",
)

#: Matched as a direct substring - "cannot" has no internal space, so
#: it is not already covered by " not "; the remaining three are
#: multi-word, space-delimited phrases with no false-positive risk.
_PHRASE_NEGATION_MARKERS: tuple[str, ...] = (
    "cannot",
    "instead of",
    "rather than",
    "but not",
)


def _contains_negation_marker(request_text: str) -> bool:
    """Detect the fixed, small set of negation/conflict markers in the
    live request (Section 20.6).

    A deliberately conservative, fixed substring/whole-word check only
    - never quotation parsing, sentiment analysis, or general
    negation understanding. Applied to the whole request, independent
    of which capability was selected, since a negated or contrasted
    request is unsafe to act on for any capability.

    Args:
        request_text: The live, verbatim request text.

    Returns:
        True if any fixed marker is present.
    """
    normalized = _normalize(request_text)
    padded = _padded(normalized)
    if any(marker in padded for marker in _WHOLE_WORD_NEGATION_MARKERS):
        return True
    if any(marker in normalized for marker in _CONTRACTION_NEGATION_MARKERS):
        return True
    return any(marker in normalized for marker in _PHRASE_NEGATION_MARKERS)


# ---------------------------------------------------------------------------
# Capability intent signatures (Section 20.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _IntentSignature:
    """One capability's fixed, hand-maintained action-and-domain
    signature.

    Every dimension is required independently - action, domain, and
    (when declared) qualifier - never substituting for one another.
    Every token/phrase in every signature below is traceable to either
    a real, currently-passing test's literal request_text, or the
    real, already-shipped _TRUSTED_PLANNING_INSTRUCTION text in
    intelligence/planning.py (see docs/phase_92_implementation_plan.md,
    Section 20.2.1 for the exact source of each).

    Attributes:
        action_tokens: At least one must be present as a token.
        domain_tokens: At least one must be present as a token (used
            together with domain_phrases - either satisfies the domain
            requirement; a signature declares whichever is real).
        domain_phrases: At least one must be present as an adjacent
            substring of the normalized text (never decomposed into
            its individual words) - used for "project state", which
            must never be satisfied by "project" or "state" alone.
        qualifier_tokens: If non-empty, at least one must also be
            present as a token, in addition to (never instead of)
            action and domain evidence. Empty for every capability
            except memory_list_recent.
    """

    action_tokens: tuple[str, ...]
    domain_tokens: tuple[str, ...] = ()
    domain_phrases: tuple[str, ...] = ()
    qualifier_tokens: tuple[str, ...] = ()


#: Exactly the twelve model-selectable capabilities (Section 20.2's
#: final table for the original six; docs/phase_93_implementation_plan.md
#: for APPROVAL_HISTORY/WORKFLOW_HISTORY, added Phase 93, Batch 1;
#: docs/phase_94_implementation_plan.md, Section 6, for SCHEDULE_ENABLE,
#: added Phase 94, Batch 2; docs/phase_95_implementation_plan.md for
#: SCHEDULE_DISABLE, added Phase 95; docs/phase_96_implementation_plan.md
#: for PROJECT_STATE_UPDATE_PHASE, added Phase 96;
#: docs/phase_99_second_compound_template_planning.md for
#: SCHEDULE_SHOW_ENABLED_STATE, added Phase 99, Batch 1). project_state_verify_focus
#: and schedule_verify_enabled_state are both deliberately absent - both
#: are internal_only and can never be a parsed EXECUTE decision's
#: capability_id (intelligence/structured_output.py already rejects
#: either before ground_decision() could ever be called with it).
_SIGNATURES: dict[CapabilityId, _IntentSignature] = {
    CapabilityId.PROJECT_STATE_SHOW: _IntentSignature(
        action_tokens=("show",),
        domain_phrases=("project state",),
    ),
    CapabilityId.PROJECT_STATE_UPDATE_FOCUS: _IntentSignature(
        action_tokens=("update",),
        domain_tokens=("focus",),
    ),
    CapabilityId.PROJECT_STATE_UPDATE_PHASE: _IntentSignature(
        action_tokens=("update",),
        domain_tokens=("phase",),
        # Phase 96: no qualifier needed - "phase" is not a domain token
        # of any other signature (including PROJECT_STATE_UPDATE_FOCUS's
        # own "focus"), so no collision requires a third dimension.
    ),
    CapabilityId.HEALTH_CHECK: _IntentSignature(
        action_tokens=("check",),
        # Deliberately "health" only - not the shipped instruction
        # text's own "or status" alternative. A bare "status" token is
        # too generic (project status, schedule status, approval
        # status, and workflow status are all real, unrelated Jarvis
        # concepts) to serve as this capability's sole domain evidence;
        # no currently-accepted request or test relies on "status"
        # alone, so narrowing to "health" costs nothing against real
        # evidence while closing a real collision risk.
        domain_tokens=("health",),
    ),
    CapabilityId.SCHEDULE_LIST: _IntentSignature(
        action_tokens=("show", "list"),
        domain_tokens=("schedule", "schedules"),
    ),
    CapabilityId.MEMORY_LIST_RECENT: _IntentSignature(
        action_tokens=("show", "list"),
        domain_tokens=("memory", "memories", "remember", "remembered"),
        # The corrected dimension (Section 20.1): recency is required,
        # separate, evidence - never a substitute for the action tokens
        # above, and never sufficient by itself.
        qualifier_tokens=("recent", "recently"),
    ),
    CapabilityId.MEMORY_SEARCH: _IntentSignature(
        action_tokens=("search", "find"),
        domain_tokens=("memory", "memories"),
    ),
    CapabilityId.APPROVAL_HISTORY: _IntentSignature(
        action_tokens=("show", "list"),
        domain_tokens=("approval", "approvals"),
        # Phase 93, Batch 1: "history" is required, separate qualifier
        # evidence - never action or domain evidence by itself, exactly
        # mirroring memory_list_recent's own corrected "recent"/
        # "recently" qualifier (Section 20.1). "approval"/"approvals"
        # alone, or "history" alone, or a generic action word alone,
        # must never be sufficient.
        qualifier_tokens=("history",),
    ),
    CapabilityId.WORKFLOW_HISTORY: _IntentSignature(
        action_tokens=("show", "list"),
        domain_tokens=("workflow", "workflows"),
        qualifier_tokens=("history",),
    ),
    CapabilityId.SCHEDULE_ENABLE: _IntentSignature(
        action_tokens=("enable",),
        domain_tokens=("schedule", "schedules"),
        # Phase 94, Batch 2: no qualifier needed - "enable" is not an
        # action token of any other signature, so no collision requires
        # a third, disambiguating dimension the way memory_list_recent/
        # approval_history/workflow_history each need "recent"/"history".
    ),
    CapabilityId.SCHEDULE_DISABLE: _IntentSignature(
        action_tokens=("disable",),
        domain_tokens=("schedule", "schedules"),
        # Phase 95: no qualifier needed - "disable" is not an action
        # token of any other signature (including SCHEDULE_ENABLE's own
        # "enable"), so no collision requires a third dimension.
    ),
    CapabilityId.SCHEDULE_SHOW_ENABLED_STATE: _IntentSignature(
        action_tokens=("check",),
        domain_tokens=("schedule", "schedules"),
        # Phase 99, Batch 1: deliberately "check", never "show"/"list" -
        # both of those are already SCHEDULE_LIST's own action tokens,
        # and SCHEDULE_LIST's own signature has no qualifier requirement
        # at all (domain: "schedule"/"schedules" alone already
        # satisfies it). Reusing "show"/"list" here would make any
        # request mentioning both an action word and "schedule" satisfy
        # *both* signatures at once - an unresolvable
        # MULTIPLE_SIGNATURES_MATCHED ambiguity for every phrase this
        # capability needs, since SCHEDULE_LIST's own existing behavior
        # must never be narrowed to accommodate this addition. "check"
        # collides with no other action token except HEALTH_CHECK's own
        # - safe, since that capability's distinct "health" domain never
        # co-occurs with "schedule" in a real request.
    ),
}


def _signature_matches(
    signature: _IntentSignature, normalized_text: str, tokens: frozenset[str]
) -> bool:
    """Check one capability's signature against an already-normalized,
    already-tokenized request.

    Args:
        signature: The capability's fixed signature.
        normalized_text: The request, already passed through
            _normalize() - used only for domain_phrases' adjacent-
            substring check.
        tokens: The request's own tokens, already passed through
            _tokenize().

    Returns:
        True only if action evidence, domain evidence, and (if
        declared) qualifier evidence are all independently present.
    """
    if not any(token in tokens for token in signature.action_tokens):
        return False

    domain_ok = any(token in tokens for token in signature.domain_tokens) or any(
        phrase in normalized_text for phrase in signature.domain_phrases
    )
    if not domain_ok:
        return False

    if signature.qualifier_tokens and not any(
        token in tokens for token in signature.qualifier_tokens
    ):
        return False

    return True


def _grounded_capability_ids(request_text: str) -> frozenset[CapabilityId]:
    """Evaluate the live request against every one of the eleven
    catalogue signatures (Section 20.3's catalogue-wide rule) - never
    only the model-selected capability's own signature in isolation.

    Args:
        request_text: The live, verbatim request text.

    Returns:
        The set of capability ids whose full signature is satisfied -
        may be empty, exactly one, or more than one.
    """
    normalized = _normalize(request_text)
    tokens = _tokenize(normalized)
    return frozenset(
        capability_id
        for capability_id, signature in _SIGNATURES.items()
        if _signature_matches(signature, normalized, tokens)
    )


# ---------------------------------------------------------------------------
# Argument-span extraction and attribution (Section 20.4/20.5)
# ---------------------------------------------------------------------------

#: The one fixed, per-capability marker whose text-after-marker is the
#: single candidate argument span - real, currently-tested language for
#: both (memory_search: "search my memories **for** X"; project_state_
#: update_focus: "update my focus **to** X"). Every other capability
#: has no entry - argument-span logic never runs for a zero-argument
#: capability.
_ARGUMENT_MARKER_BY_CAPABILITY: dict[CapabilityId, str] = {
    CapabilityId.PROJECT_STATE_UPDATE_FOCUS: " to ",
    # Phase 96: shared verbatim with PROJECT_STATE_UPDATE_FOCUS - safe
    # because ground_decision() resolves a unique matching *signature*
    # first (disambiguated by domain_tokens: "focus" vs "phase"), and
    # only then extracts the value using that one matched capability's
    # own marker, exactly mirroring how SCHEDULE_ENABLE/SCHEDULE_DISABLE
    # already safely share " schedule ".
    CapabilityId.PROJECT_STATE_UPDATE_PHASE: " to ",
    CapabilityId.MEMORY_SEARCH: " for ",
}

#: The one fixed, per-capability marker for a model-supplied *integer*
#: argument (Phase 94, Batch 2) - real, currently-tested language
#: ("enable **schedule** 5", matching core/command_router.py's own
#: _SCHEDULE_ENABLE_PREFIXES grammar). Kept in its own dict, distinct
#: from _ARGUMENT_MARKER_BY_CAPABILITY, since the extracted span is
#: parsed and compared as an int, never as a string.
_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY: dict[CapabilityId, str] = {
    CapabilityId.SCHEDULE_ENABLE: " schedule ",
    # Phase 95: shared verbatim with SCHEDULE_ENABLE - safe because
    # ground_decision() resolves a unique matching *signature* first
    # (disambiguated by action_tokens: "enable" vs "disable"), and only
    # then extracts the argument using that one matched capability's
    # own marker. "enable schedule 5" and "disable schedule 5" are
    # never ambiguous with each other.
    CapabilityId.SCHEDULE_DISABLE: " schedule ",
    # Phase 99, Batch 1: shared verbatim too - safe for the identical
    # reason, disambiguated by action_tokens ("check" vs "enable"/
    # "disable").
    CapabilityId.SCHEDULE_SHOW_ENABLED_STATE: " schedule ",
}


def _strip_one_trailing_terminal_punctuation(text: str) -> str:
    """Remove at most one trailing '.', '!', or '?' - never any other
    character, never more than one, never anything not at the very end
    (Section 20.5's exact, narrow terminal-punctuation policy).

    Args:
        text: Already-normalized (casefolded, whitespace-collapsed,
            trimmed) text.

    Returns:
        text with its single trailing terminal-punctuation character
        removed, or text unchanged if it does not end with one.
    """
    if text and text[-1] in _TERMINAL_PUNCTUATION:
        return text[:-1]
    return text


def _normalize_for_argument_comparison(text: str) -> str:
    """The exact, narrow normalization used only to decide argument
    attribution - never applied to the executable value itself.

    Args:
        text: The raw candidate span or raw model-supplied value.

    Returns:
        The casefolded, apostrophe-normalized, whitespace-collapsed
        text with at most one trailing terminal-punctuation character
        removed.
    """
    return _strip_one_trailing_terminal_punctuation(_normalize(text))


def _extract_argument_span(
    normalized_request: str, marker: str
) -> GroundingResult | str:
    """Extract the single candidate argument span from an
    already-normalized request, or return the exact bounded refusal.

    Args:
        normalized_request: The request, already passed through
            _normalize().
        marker: The capability's fixed marker (" to " or " for ").

    Returns:
        The trimmed candidate span (a str) on success, or a
        GroundingResult(grounded=False, ...) describing exactly why no
        single, usable span could be established.
    """
    occurrences = normalized_request.count(marker)
    if occurrences == 0:
        return _reject(UngroundedReason.MISSING_ARGUMENT_SPAN)
    if occurrences > 1:
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)

    index = normalized_request.find(marker)
    span = normalized_request[index + len(marker) :].strip()
    if not span:
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)
    if " or " in _padded(span):
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)

    return span


def _extract_numeric_argument_span(
    normalized_request: str, marker: str
) -> GroundingResult | int:
    """Extract the single candidate integer argument (a schedule id)
    from an already-normalized request, or return the exact bounded
    refusal (Phase 94, Batch 2 - the numeric analogue of
    _extract_argument_span, docs/phase_94_implementation_plan.md,
    Section 6).

    Applies the identical marker + single-occurrence discipline as
    _extract_argument_span, but the candidate must additionally be
    entirely decimal digits (str.isdigit()) once at most one trailing
    terminal-punctuation character is stripped - no sign, no embedded
    or trailing whitespace-separated extra token, no second numeric
    target. Anything else is ambiguous, never guessed at.

    Args:
        normalized_request: The request, already passed through
            _normalize().
        marker: The capability's fixed marker (" schedule ").

    Returns:
        The parsed candidate integer on success, or a
        GroundingResult(grounded=False, ...) describing exactly why no
        single, usable numeric span could be established.
    """
    occurrences = normalized_request.count(marker)
    if occurrences == 0:
        return _reject(UngroundedReason.MISSING_ARGUMENT_SPAN)
    if occurrences > 1:
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)

    index = normalized_request.find(marker)
    span = normalized_request[index + len(marker) :].strip()
    span = _strip_one_trailing_terminal_punctuation(span)
    if not span:
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)
    if not span.isdigit():
        # Anything not entirely decimal digits - a sign, a second
        # whitespace-separated token, trailing non-numeric text, or
        # any other shape - is ambiguous, never guessed at (no sign
        # guessing, no number-word conversion, no fuzzy extraction).
        return _reject(UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN)

    return int(span)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ground_decision(
    *,
    request_text: str,
    capability_id: CapabilityId,
    arguments: Mapping[str, object],
) -> GroundingResult:
    """The single, deny-only grounding gate intelligence.planning.select_tool()
    calls for every valid "execute" decision, after structured-output
    parsing and argument validation and before _preflight_capability()
    (Section 20's exact execution-order requirement - see also
    core/orchestrator.py, which never calls SecurityManager, approval,
    ToolExecutor, or the verifier before this gate has already
    returned).

    This function's only inputs are the live request_text and the
    already-validated arguments for the already-parsed decision -
    never AssembledContext, memory, ProjectState, or any other
    retrieved or assembled content, so no adversarial or injected
    context can ever influence its outcome.

    Args:
        request_text: The live, verbatim request text (already
            stripped of the "ask jarvis to:" prefix and surrounding
            whitespace) - the only source of grounding evidence.
        capability_id: The model-selected capability id, already
            confirmed present in CAPABILITY_CATALOG and not
            internal_only by intelligence/structured_output.py.
        arguments: The already-validated arguments dict for this
            capability (empty for a zero-argument capability).

    Returns:
        GroundingResult(grounded=True) if every applicable check
        passes. GroundingResult(grounded=False, reason=...) with the
        single, first-failing, bounded UngroundedReason otherwise -
        never a raw request fragment, candidate span, rejected value,
        or any other sensitive detail.
    """
    if _contains_negation_marker(request_text):
        return _reject(UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST)

    matched = _grounded_capability_ids(request_text)

    if not matched:
        return _reject(UngroundedReason.NO_SIGNATURE_MATCHED)
    if len(matched) > 1:
        return _reject(UngroundedReason.MULTIPLE_SIGNATURES_MATCHED)
    (unique_match,) = matched
    if unique_match is not capability_id:
        return _reject(UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH)

    marker = _ARGUMENT_MARKER_BY_CAPABILITY.get(capability_id)
    if marker is not None:
        normalized_request = _normalize(request_text)
        span_outcome = _extract_argument_span(normalized_request, marker)
        if isinstance(span_outcome, GroundingResult):
            return span_outcome
        candidate_span = span_outcome

        value = arguments[_ARGUMENT_NAME]
        assert isinstance(value, str)  # guaranteed by structured_output.py's own validation

        normalized_span = _strip_one_trailing_terminal_punctuation(candidate_span)
        normalized_value = _normalize_for_argument_comparison(value)

        if normalized_span != normalized_value:
            return _reject(UngroundedReason.ARGUMENT_VALUE_MISMATCH)

        return _GROUNDED

    numeric_marker = _NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY.get(capability_id)
    if numeric_marker is not None:
        normalized_request = _normalize(request_text)
        numeric_outcome = _extract_numeric_argument_span(normalized_request, numeric_marker)
        if isinstance(numeric_outcome, GroundingResult):
            return numeric_outcome
        candidate_id = numeric_outcome

        value = arguments[_NUMERIC_ARGUMENT_NAME]
        # guaranteed by structured_output.py's own validation: a real
        # int, never a bool (bool is explicitly excluded there since it
        # is a Python int subclass).
        assert isinstance(value, int) and not isinstance(value, bool)

        if candidate_id != value:
            return _reject(UngroundedReason.ARGUMENT_VALUE_MISMATCH)

        return _GROUNDED

    # Zero-argument capability - capability-selection grounding is the
    # entire check (Section 20: "Zero-argument capabilities require
    # capability-selection grounding only").
    return _GROUNDED
