"""
injection_detector.py

Standalone prompt injection detection engine for the Jarvis AI Operating System.

Responsibilities:
    - Detect known injection patterns via regex matching.
    - Perform structural analysis of input text.
    - Compute confidence scores based on multiple signals.
    - Support configurable sensitivity levels (low/medium/high).

Does NOT:
    - Block or modify any input (detection only).
    - Implement security manager logic (see security_manager.py).
    - Make AI calls or use external services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from security.models import InjectionResult


# ---------------------------------------------------------------------------
# Detection sensitivity thresholds
# ---------------------------------------------------------------------------

_SENSITIVITY_THRESHOLDS: Final[dict[str, float]] = {
    "low": 0.9,      # Only flag very high confidence
    "medium": 0.7,   # Flag likely injections
    "high": 0.5,     # Flag anything suspicious
}


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InjectionPattern:
    """A named injection detection pattern.

    Attributes:
        label: Short identifier for this pattern.
        regex: Compiled case-insensitive regex.
        weight: Contribution to confidence score (0.0-1.0).
        category: Category for grouping (imperative, role_override, encoding, structural).
    """

    label: str
    regex: re.Pattern[str]
    weight: float
    category: str


def _compile(text: str) -> re.Pattern[str]:
    return re.compile(text, re.IGNORECASE)


# Pattern table: each entry contributes independently to the confidence score.
_INJECTION_PATTERNS: Final[tuple[InjectionPattern, ...]] = (
    # ----- Imperatives directed at an AI -----
    InjectionPattern(
        "ignore_previous_instructions",
        _compile(r"ignore (all |any )?(the )?previous instructions"),
        0.9,
        "imperative",
    ),
    InjectionPattern(
        "ignore_above_instructions",
        _compile(r"ignore (all |any )?(the )?(above|prior) instructions"),
        0.9,
        "imperative",
    ),
    InjectionPattern(
        "disregard_instructions",
        _compile(r"disregard (the )?(above|prior|previous)( instructions)?"),
        0.85,
        "imperative",
    ),
    InjectionPattern(
        "forget_your_instructions",
        _compile(r"forget (your|all|these) (previous )?instructions"),
        0.85,
        "imperative",
    ),
    InjectionPattern(
        "override_instructions",
        _compile(r"\boverride (your|the|all) (previous )?instructions"),
        0.9,
        "imperative",
    ),
    InjectionPattern(
        "new_system_prompt",
        _compile(r"\bnew system prompt\s*:"),
        0.85,
        "imperative",
    ),
    # ----- Role / system-override phrasing -----
    InjectionPattern(
        "you_are_now",
        _compile(r"\byou are now\b"),
        0.8,
        "role_override",
    ),
    InjectionPattern(
        "system_instruction_override",
        _compile(r"system instruction\s*:"),
        0.85,
        "role_override",
    ),
    InjectionPattern(
        "new_instructions_override",
        _compile(r"\bnew instructions\s*:"),
        0.8,
        "role_override",
    ),
    InjectionPattern(
        "pretend_you_are",
        _compile(r"\bpretend (that )?you('re| are)\b"),
        0.75,
        "role_override",
    ),
    InjectionPattern(
        "act_as_system",
        _compile(r"\bact as (the )?system\b"),
        0.8,
        "role_override",
    ),
    InjectionPattern(
        "you_are_an_ai",
        _compile(r"\byou are an? (ai|assistant|language model)\b(?!.*\bthat\b)"),
        0.6,
        "role_override",
    ),
    # ----- XML/JSON role injection -----
    InjectionPattern(
        "xml_system_tag",
        _compile(r"<\s*system\s*>"),
        0.8,
        "role_override",
    ),
    InjectionPattern(
        "xml_system_close",
        _compile(r"</\s*system\s*>"),
        0.7,
        "role_override",
    ),
    InjectionPattern(
        "json_role_injection",
        _compile(r'["\']?role["\']?\s*:\s*["\']?system["\']?'),
        0.8,
        "role_override",
    ),
    InjectionPattern(
        "tool_call_tag",
        _compile(r"<\s*/?\s*tool_call\s*>"),
        0.75,
        "role_override",
    ),
    InjectionPattern(
        "function_call_syntax",
        _compile(r"\bfunction_call\s*:"),
        0.7,
        "role_override",
    ),
    # ----- Markdown injection -----
    InjectionPattern(
        "markdown_end_override",
        _compile(r"---END---"),
        0.7,
        "encoding",
    ),
    InjectionPattern(
        "backtick_override",
        _compile(r"```(system|assistant|user)"),
        0.65,
        "encoding",
    ),
    # ----- Jailbreak phrasing -----
    InjectionPattern(
        "dan_mode",
        _compile(r"\bDAN mode\b"),
        0.9,
        "imperative",
    ),
    InjectionPattern(
        "jailbreak_phrase",
        _compile(r"\bjailbreak\b"),
        0.85,
        "imperative",
    ),
    InjectionPattern(
        "do_anything_now",
        _compile(r"\bdo anything now\b"),
        0.85,
        "imperative",
    ),
    InjectionPattern(
        "no_restrictions",
        _compile(r"\bwithout any (restrictions|limitations|rules)\b"),
        0.8,
        "imperative",
    ),
    InjectionPattern(
        "developer_mode",
        _compile(r"\bdeveloper mode\b"),
        0.8,
        "imperative",
    ),
    InjectionPattern(
        "ignore_safety",
        _compile(r"\bignore (all )?(safety|content) (policy|policies|guidelines)\b"),
        0.9,
        "imperative",
    ),
)


class InjectionDetector:
    """Standalone injection detection engine with configurable sensitivity.

    Performs pattern-based and structural analysis to detect prompt injection
    attempts. Returns confidence scores and matched technique descriptions.

    Attributes:
        sensitivity: Detection threshold level (low/medium/high).
    """

    def __init__(self, sensitivity: str = "medium") -> None:
        """Initialise the detector.

        Args:
            sensitivity: One of "low", "medium", or "high".
        """
        if sensitivity not in _SENSITIVITY_THRESHOLDS:
            sensitivity = "medium"
        self.sensitivity = sensitivity
        self._threshold = _SENSITIVITY_THRESHOLDS[sensitivity]

    def detect(self, text: str) -> InjectionResult:
        """Analyze text for prompt injection patterns.

        Args:
            text: The input text to analyze.

        Returns:
            InjectionResult with confidence score and detected techniques.
        """
        if not text or not text.strip():
            return InjectionResult(
                is_injection=False,
                confidence=0.0,
                technique="none",
                patterns=[],
                details="Empty input.",
            )

        signals: list[tuple[str, float]] = []

        # 1. Pattern matching
        pattern_matches = self._check_patterns(text)
        signals.extend(pattern_matches)

        # 2. Structural analysis
        structural_signals = self._check_structural(text)
        signals.extend(structural_signals)

        # 3. Compute combined confidence
        confidence = self._compute_confidence(signals)
        is_injection = confidence >= self._threshold

        # Build technique description
        technique = self._describe_technique(pattern_matches, structural_signals)
        matched_patterns = [label for label, _ in pattern_matches]

        details = self._build_details(confidence, is_injection, technique, matched_patterns)

        return InjectionResult(
            is_injection=is_injection,
            confidence=round(confidence, 4),
            technique=technique,
            patterns=matched_patterns,
            details=details,
        )

    def _check_patterns(self, text: str) -> list[tuple[str, float]]:
        """Check text against known injection patterns."""
        matches = []
        for pattern in _INJECTION_PATTERNS:
            if pattern.regex.search(text):
                matches.append((pattern.label, pattern.weight))
        return matches

    def _check_structural(self, text: str) -> list[tuple[str, float]]:
        """Perform structural analysis of the input."""
        signals = []

        # Very long inputs are suspicious
        if len(text) > 5000:
            signals.append(("excessive_length", 0.3))

        # Repeated token detection
        repeated = self._detect_repetition(text)
        if repeated:
            signals.append(("repeated_tokens", 0.4))

        # Unusual delimiter usage
        delimiter_count = sum(1 for marker in ["SYSTEM:", "USER:", "ASSISTANT:", "Human:", "AI:"]
                            if marker in text)
        if delimiter_count >= 2:
            signals.append(("multiple_delimiters", 0.5))

        # Instruction hierarchy violations (user trying to set system prompt)
        if re.search(r"\b(system|assistant)\s*:", text, re.IGNORECASE):
            # Only suspicious if combined with imperative language
            if re.search(r"\b(ignore|override|disregard|forget|new)\b", text, re.IGNORECASE):
                signals.append(("instruction_hierarchy_violation", 0.6))

        # Base64/hex encoded content (rough heuristic)
        if re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text):
            signals.append(("possible_encoded_content", 0.3))

        return signals

    def _detect_repetition(self, text: str) -> bool:
        """Detect repeated phrases in the text."""
        words = text.split()
        if len(words) < 10:
            return False

        # Check for repeated 3-gram sequences
        from collections import Counter
        trigrams = [tuple(words[i:i+3]) for i in range(len(words) - 2)]
        counts = Counter(trigrams)
        return any(count > 10 for count in counts.values())

    def _compute_confidence(self, signals: list[tuple[str, float]]) -> float:
        """Compute combined confidence from multiple signals.

        Uses a noisy-OR model: each signal independently contributes
        to the overall confidence.
        """
        if not signals:
            return 0.0

        # Noisy-OR: P(at least one true) = 1 - prod(1 - p_i)
        combined = 1.0
        for _, weight in signals:
            combined *= (1.0 - weight)

        return 1.0 - combined

    def _describe_technique(
        self,
        pattern_matches: list[tuple[str, float]],
        structural_signals: list[tuple[str, float]],
    ) -> str:
        """Describe the detected technique in human-readable form."""
        categories = set()
        for label, _ in pattern_matches:
            for p in _INJECTION_PATTERNS:
                if p.label == label:
                    categories.add(p.category)

        if structural_signals:
            categories.add("structural")

        if not categories:
            return "none"

        return ", ".join(sorted(categories))

    def _build_details(
        self,
        confidence: float,
        is_injection: bool,
        technique: str,
        matched_patterns: list[str],
    ) -> str:
        """Build human-readable details string."""
        if not is_injection:
            return f"Clean input (confidence: {confidence:.2f})."

        parts = [
            f"Injection detected (confidence: {confidence:.2f}).",
            f"Technique: {technique}.",
        ]
        if matched_patterns:
            parts.append(f"Matched patterns: {', '.join(matched_patterns)}.")
        return " ".join(parts)
