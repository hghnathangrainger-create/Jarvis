"""
compound_structured_output.py

An isolated, non-live-wired compound decision model and parser (Phase
97 - docs/phase_97_implementation_plan.md). Proves that exactly one
trusted, hand-authored two-capability request template can be parsed
deterministically, without touching the existing, live, single-
capability decision path in any way.

Responsibilities:
    - Define a wholly separate compound decision vocabulary:
      CompoundToolSelectionDecision (one member, "execute_sequence"),
      CompoundToolSelectionStep, ParsedCompoundToolSelection, and
      CompoundToolSelectionParseError - none of which is the same
      Python type as, or shares any class relationship with,
      intelligence.structured_output's own ToolSelectionDecision /
      ParsedToolSelection / ToolSelectionParseError.
    - Parse and strictly validate exactly the two-step compound schema
      (Section 7 of the Phase 97 plan): an exact two-key top level
      ({"decision", "steps"}), "decision" equal to exactly
      "execute_sequence", "steps" a JSON array of exactly two objects,
      each with exactly {"capability_id", "arguments"}, both
      capability ids real and not internal_only, no duplicate
      capability id, and each step's own "arguments" validated against
      that capability's own declared CapabilityArgumentSpec tuple.

Does NOT:
    - Add "execute_sequence" to intelligence.structured_output's own
      ToolSelectionDecision enum, or to parse_tool_selection()'s own
      accepted decision literals in any way. That existing, live parser
      is never imported for its decision-handling logic here, and
      continues to reject "execute_sequence" today exactly as it did
      before this module existed - via its own unmodified "unknown
      decision value" branch, requiring no change to keep doing so.
    - Perform any grounding, template-allowlist, or request-text
      evaluation - that is intelligence.compound_grounding's own,
      separate responsibility. This module only ever validates JSON
      shape and catalog/argument-spec conformance.
    - Call any AI provider, SecurityManager, ApprovalManager,
      ToolExecutor, or verification code, or execute/approve/persist
      anything. This module is a pure function of (raw text, capability
      catalog) to a validated ParsedCompoundToolSelection, or a raised
      CompoundToolSelectionParseError, and nothing else.
    - Get imported by intelligence/structured_output.py,
      intelligence/planning.py, core/orchestrator.py, or any other live
      runtime module. Only this module's own dedicated tests import it
      during Phase 97 (see tests/unit/test_compound_structured_output.py
      and tests/unit/test_compound_isolation.py).

Reuse strategy: this module imports three already-existing, pure,
stateless helpers from intelligence.structured_output - the strict
JSON-object duplicate-key hook, the single-outer-fence stripper, and
the per-capability argument validator - rather than duplicating their
logic. None of the three has any bearing on which top-level decision
literals the live parser accepts; that acceptance is governed solely
by parse_tool_selection()'s own explicit `decision_raw == "execute"`/
`"unsupported"` check, which this module never touches, imports the
inverse of, or influences. The import direction is strictly one-way:
this module imports from intelligence.structured_output; that module
never imports anything from here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from intelligence.capability_catalog import CapabilityAdapter, CapabilityId
from intelligence.structured_output import (
    ToolSelectionParseError as _LiveToolSelectionParseError,
)
from intelligence.structured_output import _reject_duplicate_keys as _live_reject_duplicate_keys
from intelligence.structured_output import (
    _strip_single_outer_fence as _live_strip_single_outer_fence,
)
from intelligence.structured_output import _validate_arguments as _live_validate_arguments

#: Kept deliberately equal to intelligence.structured_output's own
#: _MAX_RAW_OUTPUT_CHARS value, but declared independently here rather
#: than imported - a single integer literal is simpler and safer to
#: duplicate than to import purely for its value, and carries no
#: decision-literal coupling either way.
_MAX_RAW_OUTPUT_CHARS = 2000

#: The exact, and only, top-level shape this parser accepts - a wholly
#: different key set from intelligence.structured_output's own
#: {"decision", "capability_id", "arguments"}, so the two schemas can
#: never be confused with one another.
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"decision", "steps"})

#: The exact, and only, per-step shape this parser accepts.
_ALLOWED_STEP_KEYS = frozenset({"capability_id", "arguments"})

#: The one and only decision literal this parser ever accepts. Never
#: added to intelligence.structured_output.ToolSelectionDecision.
_EXECUTE_SEQUENCE_LITERAL = "execute_sequence"

#: The exact number of steps every compound decision this parser
#: accepts must declare (Phase 97: bounded to exactly two, never more,
#: never fewer, never a variable-length sequence).
_REQUIRED_STEP_COUNT = 2


class CompoundToolSelectionDecision(Enum):
    """The one valid compound decision literal (Phase 97).

    A wholly distinct Python type from
    intelligence.structured_output.ToolSelectionDecision - the two
    share no base class beyond Enum itself, and no instance of one is
    ever compared with, or substituted for, the other.
    """

    EXECUTE_SEQUENCE = "execute_sequence"


@dataclass(frozen=True, slots=True)
class CompoundToolSelectionStep:
    """One already-validated step of a parsed compound decision.

    Attributes:
        capability_id: The selected capability for this step - a real,
            non-internal_only CAPABILITY_CATALOG member.
        arguments: A freshly-built dict of validated arguments for this
            step's own capability, produced by
            intelligence.structured_output's own, unmodified
            _validate_arguments() - never a reference to any
            decoder-owned or otherwise externally-held dict.
    """

    capability_id: CapabilityId
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ParsedCompoundToolSelection:
    """A fully parsed and validated compound model response.

    Only ever constructed after every JSON, duplicate-key, key-set,
    type, catalog-membership, internal_only, duplicate-capability, and
    per-step argument rule has passed.

    Attributes:
        decision: Always CompoundToolSelectionDecision.EXECUTE_SEQUENCE
            - this parser accepts no other decision value.
        steps: Exactly two CompoundToolSelectionStep entries, in the
            same order the raw "steps" array declared them. Order is
            never reinterpreted, reordered, or inferred here - this
            module only ever preserves declaration order; whether that
            order is an *allowed* order is
            intelligence.compound_grounding's own, separate concern.
    """

    decision: CompoundToolSelectionDecision
    steps: tuple[CompoundToolSelectionStep, CompoundToolSelectionStep]


class CompoundToolSelectionParseError(Exception):
    """Raised for any compound parsing or validation failure.

    A wholly separate exception type from
    intelligence.structured_output.ToolSelectionParseError - it does
    not subclass it, so a caller's `except ToolSelectionParseError`
    can never accidentally also catch a compound parse failure, and
    vice versa.

    Attributes:
        reason: A short, fixed, non-sensitive description of which
            rule failed - never the raw model output, a raw internal
            exception, or any live request/context/memory content.
    """

    def __init__(self, reason: str) -> None:
        """Initialise the error with its bounded reason.

        Args:
            reason: A short, fixed, non-sensitive failure description.
        """
        super().__init__(reason)
        self.reason = reason


def _parse_json_object(text: str) -> dict[str, object]:
    """Strictly parse `text` as a single JSON object, rejecting any
    duplicate key at any nesting depth (reusing
    intelligence.structured_output's own, unmodified duplicate-key
    hook).

    Args:
        text: The already fence-stripped candidate JSON text.

    Returns:
        The decoded top-level JSON object.

    Raises:
        CompoundToolSelectionParseError: If the text is not valid JSON,
            is not a JSON object, or contains a duplicate key anywhere.
    """
    try:
        parsed_json = json.loads(text, object_pairs_hook=_live_reject_duplicate_keys)
    except _LiveToolSelectionParseError as exc:
        raise CompoundToolSelectionParseError(exc.reason) from exc
    except json.JSONDecodeError as exc:
        raise CompoundToolSelectionParseError("malformed JSON in model output") from exc

    if not isinstance(parsed_json, dict):
        raise CompoundToolSelectionParseError("model output must be a JSON object")
    return parsed_json


def _parse_step(
    step_raw: object, catalog: Mapping[CapabilityId, CapabilityAdapter]
) -> CompoundToolSelectionStep:
    """Validate and build one CompoundToolSelectionStep from a raw step
    entry.

    Args:
        step_raw: One raw entry from the "steps" array.
        catalog: The capability catalog to validate against.

    Returns:
        A validated CompoundToolSelectionStep.

    Raises:
        CompoundToolSelectionParseError: For any per-step validation
            failure (non-object step, wrong key set, unknown/internal-
            only/unsupported capability, malformed or invalid
            arguments).
    """
    if not isinstance(step_raw, dict):
        raise CompoundToolSelectionParseError("each compound step must be a JSON object")
    if set(step_raw) != _ALLOWED_STEP_KEYS:
        raise CompoundToolSelectionParseError(
            "unexpected or missing keys in a compound step"
        )

    capability_id_raw = step_raw["capability_id"]
    if not isinstance(capability_id_raw, str):
        raise CompoundToolSelectionParseError("capability_id must be a string")
    try:
        capability_id = CapabilityId(capability_id_raw)
    except ValueError as exc:
        raise CompoundToolSelectionParseError("unknown capability id") from exc

    adapter = catalog.get(capability_id)
    if adapter is None:
        raise CompoundToolSelectionParseError("capability id not present in catalog")
    if adapter.internal_only:
        raise CompoundToolSelectionParseError(
            "capability is internal-only and cannot be selected"
        )

    arguments_raw = step_raw["arguments"]
    if not isinstance(arguments_raw, dict):
        raise CompoundToolSelectionParseError("arguments must be a JSON object")

    try:
        validated_arguments = _live_validate_arguments(adapter, arguments_raw)
    except _LiveToolSelectionParseError as exc:
        raise CompoundToolSelectionParseError(exc.reason) from exc

    return CompoundToolSelectionStep(
        capability_id=capability_id, arguments=validated_arguments
    )


def parse_compound_tool_selection(
    raw_text: str, catalog: Mapping[CapabilityId, CapabilityAdapter]
) -> ParsedCompoundToolSelection:
    """Strictly parse and validate one compound model response.

    Never called by any live code path in Phase 97 - only this
    module's own dedicated tests exercise it.

    Args:
        raw_text: The raw, untrimmed candidate text.
        catalog: The capability catalog to validate each declared
            capability_id and its arguments against
            (intelligence.capability_catalog.CAPABILITY_CATALOG in
            production, though production never calls this function
            this phase).

    Returns:
        A validated ParsedCompoundToolSelection.

    Raises:
        CompoundToolSelectionParseError: For any parsing or validation
            failure, with a short, bounded, non-sensitive .reason.
    """
    if len(raw_text) > _MAX_RAW_OUTPUT_CHARS:
        raise CompoundToolSelectionParseError("model output too long")

    try:
        text = _live_strip_single_outer_fence(raw_text)
    except _LiveToolSelectionParseError as exc:
        raise CompoundToolSelectionParseError(exc.reason) from exc
    if not text:
        raise CompoundToolSelectionParseError("empty model output")

    parsed_json = _parse_json_object(text)

    if set(parsed_json) != _ALLOWED_TOP_LEVEL_KEYS:
        raise CompoundToolSelectionParseError(
            "unexpected or missing top-level keys"
        )

    decision_raw = parsed_json["decision"]
    if decision_raw != _EXECUTE_SEQUENCE_LITERAL:
        raise CompoundToolSelectionParseError("unknown or missing compound decision value")

    steps_raw = parsed_json["steps"]
    if not isinstance(steps_raw, list):
        raise CompoundToolSelectionParseError("steps must be a JSON array")
    if len(steps_raw) != _REQUIRED_STEP_COUNT:
        raise CompoundToolSelectionParseError(
            "steps must contain exactly two entries"
        )

    parsed_steps: list[CompoundToolSelectionStep] = []
    seen_capability_ids: set[CapabilityId] = set()
    for step_raw in steps_raw:
        step = _parse_step(step_raw, catalog)
        if step.capability_id in seen_capability_ids:
            raise CompoundToolSelectionParseError(
                "duplicate capability id in compound steps"
            )
        seen_capability_ids.add(step.capability_id)
        parsed_steps.append(step)

    return ParsedCompoundToolSelection(
        decision=CompoundToolSelectionDecision.EXECUTE_SEQUENCE,
        steps=(parsed_steps[0], parsed_steps[1]),
    )
