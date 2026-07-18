"""
structured_output.py

The strict, deterministic parser for Jarvis's "ask jarvis to: <request>"
model output (Phase 90, Batch 2; contracts fixed by
docs/phase_90_implementation_plan.md, Sections 25.B and 26.A/B/D).

Responsibilities:
    - Reject raw model output over 2,000 characters before any other
      processing (Section 26.D).
    - Strip exactly one optional outer triple-backtick fence (no
      language tag, or "json") - the parser's one narrow leniency.
    - Parse the fenced/unfenced text as JSON, rejecting any duplicate
      key at any nesting depth (top level or inside "arguments") via a
      strict object_pairs_hook - json.loads() never runs with its
      default, silently-overwriting duplicate-key behaviour.
    - Validate the exact three-key {decision, capability_id, arguments}
      schema and its cross-field rules for both the "execute" and
      "unsupported" decisions (Section 26.A).
    - For an "execute" decision, validate "arguments" against the
      selected capability's own declared CapabilityArgumentSpec tuple
      from intelligence/capability_catalog.py - unknown keys, missing
      required keys, wrong types, and oversized strings are all
      rejected here, before any ToolRegistry/SecurityManager involvement.

Does NOT:
    - Call any AI provider, or know anything about AIRouter/PromptBuilder.
      This module is a pure function of (raw text, capability catalog)
      to a validated ParsedToolSelection - or a raised
      ToolSelectionParseError - and nothing else.
    - Check ToolRegistry for whether a capability's real tool is still
      registered. That is intelligence/planning.py's own preflight
      responsibility (Section 25.C: catalog membership and registry
      membership are two independent checks).
    - Repair, guess, coerce, extract, or normalize anything beyond the
      one permitted fence-stripping leniency. Any other malformed
      input is rejected outright - never a "best guess" repaired
      request.
    - Expose the raw, as-received model text in any exception message.
      Every ToolSelectionParseError.reason is a short, fixed,
      non-sensitive description of which rule failed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from intelligence.capability_catalog import CapabilityAdapter, CapabilityId

#: Section 26.D: applied to the raw, untrimmed provider output, before
#: any fence stripping or JSON parsing.
_MAX_RAW_OUTPUT_CHARS = 2000

#: Reuses the same 500-character ceiling the original plan (Section
#: 24.B.10) fixed for a single string argument - Batch 2's one
#: capability takes no arguments at all, so this only ever applies to
#: a future capability, but the limit is enforced here now so it is
#: never silently absent.
_MAX_STRING_ARGUMENT_CHARS = 500

_ALLOWED_TOP_LEVEL_KEYS = frozenset({"decision", "capability_id", "arguments"})

_PYTHON_TYPE_BY_NAME: dict[str, type] = {"str": str, "int": int, "bool": bool}


class ToolSelectionDecision(Enum):
    """The two valid outcomes a "ask jarvis to:" model response may
    express (Section 26.A/B)."""

    EXECUTE = "execute"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ParsedToolSelection:
    """A fully parsed and validated model tool-selection response.

    Only ever constructed after every JSON, duplicate-key, key-set,
    type, cross-field, size, catalog, and argument rule has passed.

    Attributes:
        decision: EXECUTE or UNSUPPORTED.
        capability_id: The selected capability, or None for UNSUPPORTED.
        arguments: A freshly-built dict of validated arguments - never
            a reference to any decoder-owned or otherwise externally-
            held dict.
    """

    decision: ToolSelectionDecision
    capability_id: CapabilityId | None
    arguments: dict[str, object]


class ToolSelectionParseError(Exception):
    """Raised for any parsing or validation failure.

    Attributes:
        reason: A short, fixed, non-sensitive description of which
            rule failed - safe to show a user, never the raw model
            output or an exception's own internal text.
    """

    def __init__(self, reason: str) -> None:
        """Initialise the error with its bounded reason.

        Args:
            reason: A short, fixed, non-sensitive failure description.
        """
        super().__init__(reason)
        self.reason = reason


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A strict object_pairs_hook rejecting any repeated key.

    Invoked by json.loads() for every JSON object it decodes - top
    level and nested alike - so a single hook rejects a duplicate key
    at any depth, with no separate recursive check needed.

    Args:
        pairs: The ordered (key, value) pairs json.loads() decoded for
            one JSON object.

    Returns:
        A new dict built from pairs, if every key was unique.

    Raises:
        ToolSelectionParseError: If any key appears more than once.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ToolSelectionParseError("duplicate key in model output")
        result[key] = value
    return result


def _strip_single_outer_fence(text: str) -> str:
    """Strip exactly one optional outer triple-backtick fence.

    Permits only a fence with no language tag or the "json" tag,
    appearing as the first and last non-whitespace content. Anything
    else fence-shaped (multiple fences, nested fences, an unterminated
    fence, an unsupported language tag, or a fence not wrapping the
    entire trimmed text) is rejected outright.

    Args:
        text: The raw model text, not yet trimmed.

    Returns:
        The text with its one permitted outer fence removed, or the
        trimmed text unchanged if no fence was present.

    Raises:
        ToolSelectionParseError: If a fence-shaped construct is present
            but does not conform to the one permitted shape.
    """
    stripped = text.strip()

    if not stripped.startswith("```"):
        if "```" in stripped:
            raise ToolSelectionParseError("unexpected code fence in model output")
        return stripped

    if not stripped.endswith("```") or len(stripped) < 6:
        raise ToolSelectionParseError("unterminated code fence in model output")

    first_newline = stripped.find("\n")
    if first_newline == -1:
        raise ToolSelectionParseError("malformed code fence in model output")

    language_tag = stripped[3:first_newline].strip()
    if language_tag not in ("", "json"):
        raise ToolSelectionParseError("unsupported code fence language")

    inner = stripped[first_newline + 1 : -3]
    if "```" in inner:
        raise ToolSelectionParseError("multiple or nested code fences")

    return inner.strip()


def _is_control_char(character: str) -> bool:
    """Return whether a single character is a C0 control character or DEL.

    Args:
        character: A single character.

    Returns:
        True if character's code point is a C0 control (0x00-0x1F) or
        DEL (0x7F) - this deliberately does not flag an ordinary
        printable space (0x20).
    """
    code_point = ord(character)
    return code_point < 0x20 or code_point == 0x7F


def _validate_string_argument(value: str) -> None:
    """Apply the fixed string-argument hygiene rules to any string
    argument (Section 26/Batch 3 planning prompt).

    Applied generically to every string-typed argument this parser
    ever validates - not special-cased to any one argument name - since
    there is no reason a different string argument would need laxer
    rules.

    Args:
        value: The already-type-checked string value.

    Raises:
        ToolSelectionParseError: If value is empty or whitespace-only,
            exceeds the fixed maximum length, contains a NUL character,
            or has a leading/trailing control character.
    """
    if len(value) > _MAX_STRING_ARGUMENT_CHARS:
        raise ToolSelectionParseError("oversized string argument")
    if not value.strip():
        raise ToolSelectionParseError("empty or whitespace-only string argument")
    if "\x00" in value:
        raise ToolSelectionParseError("string argument contains a NUL character")
    if _is_control_char(value[0]) or _is_control_char(value[-1]):
        raise ToolSelectionParseError(
            "string argument has a leading or trailing control character"
        )


def _validate_arguments(
    adapter: CapabilityAdapter, arguments: dict[str, object]
) -> dict[str, object]:
    """Validate a raw "arguments" object against one capability's spec.

    Args:
        adapter: The selected capability's catalog entry.
        arguments: The raw, decoded "arguments" object.

    Returns:
        A freshly-built dict containing only the capability's own
        declared argument names.

    Raises:
        ToolSelectionParseError: For an unknown argument name, a
            missing required argument, a wrong argument type, or an
            oversized string argument.
    """
    declared = {spec.name: spec for spec in adapter.arguments}

    unknown = set(arguments) - set(declared)
    if unknown:
        raise ToolSelectionParseError("unknown argument name in model output")

    validated: dict[str, object] = {}
    for spec in adapter.arguments:
        if spec.name not in arguments:
            if spec.required:
                raise ToolSelectionParseError("missing required argument")
            continue

        value = arguments[spec.name]
        expected_type = _PYTHON_TYPE_BY_NAME[spec.type_name]

        # bool is a subclass of int in Python, so an explicit isinstance
        # check against bool is required first to keep the two types
        # from being silently interchangeable (no coercion of any kind).
        if expected_type is bool:
            if not isinstance(value, bool):
                raise ToolSelectionParseError("invalid argument type")
        elif isinstance(value, bool) or not isinstance(value, expected_type):
            raise ToolSelectionParseError("invalid argument type")

        if expected_type is str:
            _validate_string_argument(value)

        validated[spec.name] = value

    return validated


def parse_tool_selection(
    raw_text: str, catalog: Mapping[CapabilityId, CapabilityAdapter]
) -> ParsedToolSelection:
    """Strictly parse and validate one model response.

    Args:
        raw_text: The raw, untrimmed text the AI provider returned.
        catalog: The capability catalog to validate a selected
            "execute" capability_id and its arguments against
            (intelligence.capability_catalog.CAPABILITY_CATALOG in
            production).

    Returns:
        A validated ParsedToolSelection.

    Raises:
        ToolSelectionParseError: For any parsing or validation failure,
            with a short, bounded, non-sensitive .reason.
    """
    if len(raw_text) > _MAX_RAW_OUTPUT_CHARS:
        raise ToolSelectionParseError("model output too long")

    text = _strip_single_outer_fence(raw_text)
    if not text:
        raise ToolSelectionParseError("empty model output")

    try:
        parsed_json = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ToolSelectionParseError:
        raise
    except json.JSONDecodeError as exc:
        raise ToolSelectionParseError("malformed JSON in model output") from exc

    if not isinstance(parsed_json, dict):
        raise ToolSelectionParseError("model output must be a JSON object")

    if set(parsed_json) != _ALLOWED_TOP_LEVEL_KEYS:
        raise ToolSelectionParseError("unexpected or missing top-level keys")

    decision_raw = parsed_json["decision"]
    if decision_raw == "execute":
        decision = ToolSelectionDecision.EXECUTE
    elif decision_raw == "unsupported":
        decision = ToolSelectionDecision.UNSUPPORTED
    else:
        raise ToolSelectionParseError("unknown decision value")

    capability_id_raw = parsed_json["capability_id"]
    arguments_raw = parsed_json["arguments"]
    if not isinstance(arguments_raw, dict):
        raise ToolSelectionParseError("arguments must be a JSON object")

    if decision is ToolSelectionDecision.UNSUPPORTED:
        if capability_id_raw is not None:
            raise ToolSelectionParseError(
                "unsupported decision must have a null capability_id"
            )
        if arguments_raw:
            raise ToolSelectionParseError(
                "unsupported decision must have empty arguments"
            )
        return ParsedToolSelection(
            decision=decision, capability_id=None, arguments={}
        )

    # decision is EXECUTE from here on.
    if not isinstance(capability_id_raw, str):
        raise ToolSelectionParseError("capability_id must be a string")

    try:
        capability_id = CapabilityId(capability_id_raw)
    except ValueError as exc:
        raise ToolSelectionParseError("unknown capability id") from exc

    adapter = catalog.get(capability_id)
    if adapter is None:
        raise ToolSelectionParseError("capability id not present in catalog")
    if adapter.internal_only:
        raise ToolSelectionParseError(
            "capability is internal-only and cannot be selected"
        )

    validated_arguments = _validate_arguments(adapter, arguments_raw)

    return ParsedToolSelection(
        decision=decision, capability_id=capability_id, arguments=validated_arguments
    )
