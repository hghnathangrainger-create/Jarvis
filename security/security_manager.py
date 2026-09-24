"""
security_manager.py

Rule-based action classification for the Jarvis AI Operating System.

Responsibilities:
    - Classify a requested action as GREEN, YELLOW, or RED.
    - Return a clear, human-readable reason alongside every classification.
    - Apply a safe default (YELLOW) to actions that match no known rule.
    - Scan untrusted text for prompt-injection patterns before it reaches an
      AI provider (Phase 7, Batch 3) - detection only, never enforcement.
    - Decide the unexpected-action verdict (FLAG/ESCALATE/BLOCK) for an
      AI-suggested action that falls outside a plan's expected scope (Phase 7,
      Batch 4) - policy only; it does not itself log, execute, or approve
      anything.

Does NOT:
    - Execute, approve, or block actions itself (it only classifies them).
    - Use AI calls or any external security service.
    - Connect to the Planner or Workflow Engine.
    - Implement permissions, roles, or credential handling.
    - Decide what happens when injection is detected (Batch 4), or treat a
      scan result as any kind of user approval - scan_for_injection only
      reports what it found.
    - Convert an unexpected-action verdict into an execution path, an
      approval, or a Plan change - evaluate_unexpected_action only reports a
      verdict; the caller (JarvisOrchestrator) decides what, if anything, to
      do with it, and Batch 4 uses it purely for observability.

The classification is deliberately simple and rule-based for Phase 1: an
ordered list of keyword rules, checked most-dangerous-first, so that the most
severe matching tier always wins. Every rule carries its own explanation, so
the result is always understandable and auditable. The injection scanner
added in Phase 7, Batch 3 follows the same philosophy: a small, explicit,
inspectable pattern list, not a machine-learned or remotely-updated one. The
unexpected-action policy added in Phase 7, Batch 4 reuses classify_action's
existing tier decision rather than duplicating or replacing it; it only adds
a mapping from (tier, in-scope?) to a verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from config.constants import SecurityTier


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    """The result of classifying a requested action.

    Attributes:
        action: The original action text that was classified.
        tier: The assigned security tier (GREEN, YELLOW, or RED).
        reason: A human-readable explanation of why this tier was assigned.
        matched_keyword: The keyword that triggered the classification, or None
            when the action matched no rule and the default tier was applied.
    """

    action: str
    tier: SecurityTier
    reason: str
    matched_keyword: str | None = None

    @property
    def is_allowed_automatically(self) -> bool:
        """Whether the action may proceed without user confirmation.

        Returns:
            True only for GREEN actions.
        """
        return self.tier is SecurityTier.GREEN

    @property
    def requires_confirmation(self) -> bool:
        """Whether the action requires user confirmation before proceeding.

        Returns:
            True only for YELLOW actions.
        """
        return self.tier is SecurityTier.YELLOW

    @property
    def is_blocked(self) -> bool:
        """Whether the action is blocked by default.

        Returns:
            True only for RED actions.
        """
        return self.tier is SecurityTier.RED


@dataclass(frozen=True, slots=True)
class InjectionScanResult:
    """The result of scanning a piece of untrusted text for injection patterns.

    This is a detection report only. Phase 7, Batch 3 defines no enforcement
    behaviour: a suspicious result does not block, rewrite, or remove
    anything, and it is never treated as any form of user approval. Whether
    - and how - a suspicious finding changes what happens next is deferred to
    Batch 4.

    Attributes:
        suspicious: True if at least one instruction-like pattern matched.
        matched_patterns: The labels of every pattern that matched, in the
            fixed order the pattern table declares them. Empty when nothing
            matched.
        text: The original text that was scanned, unchanged, so a caller or
            audit record can see exactly what was evaluated.
    """

    suspicious: bool
    matched_patterns: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class _Rule:
    """A single keyword-based classification rule.

    Attributes:
        keyword: The lowercase keyword to look for within the action text.
        tier: The tier to assign when the keyword is present.
        reason: The explanation to attach to a matching decision.
    """

    keyword: str
    tier: SecurityTier
    reason: str


# Rules are evaluated in order. RED rules are listed first so that the most
# dangerous matching tier always wins, even if a less severe keyword also
# appears in the action text. Within a tier, more specific phrases are listed
# before more general ones.
_RULES: tuple[_Rule, ...] = (
    # ----- RED: dangerous, blocked by default -----
    _Rule("format drive", SecurityTier.RED, "Formatting a drive destroys all data on it."),
    _Rule("format disk", SecurityTier.RED, "Formatting a disk destroys all data on it."),
    _Rule("wipe drive", SecurityTier.RED, "Wiping a drive permanently destroys data."),
    _Rule("disable antivirus", SecurityTier.RED, "Disabling antivirus removes a core protection."),
    _Rule("disable firewall", SecurityTier.RED, "Disabling the firewall exposes the system to attack."),
    _Rule("disable security", SecurityTier.RED, "Disabling security controls is dangerous."),
    _Rule("steal", SecurityTier.RED, "Stealing credentials or data is malicious and prohibited."),
    _Rule("exfiltrate", SecurityTier.RED, "Exfiltrating data is malicious and prohibited."),
    _Rule("ransomware", SecurityTier.RED, "Ransomware is malicious software and prohibited."),
    _Rule("keylogger", SecurityTier.RED, "Keyloggers capture private input and are prohibited."),
    _Rule("delete all", SecurityTier.RED, "Bulk deletion is irreversible and high risk."),
    _Rule("forget all memories", SecurityTier.RED, "Forgetting all memories is an irreversible bulk wipe and is not allowed."),
    _Rule("forget all", SecurityTier.RED, "Bulk forgetting is irreversible and high risk."),
    _Rule("rm -rf", SecurityTier.RED, "Recursive force-delete is irreversible and high risk."),
    _Rule("drop database", SecurityTier.RED, "Dropping a database destroys all of its data."),
    _Rule("modify registry", SecurityTier.RED, "Editing the registry can break the operating system."),
    _Rule("edit registry", SecurityTier.RED, "Editing the registry can break the operating system."),
    # ----- YELLOW: sensitive, requires confirmation -----
    # ----- YELLOW: sensitive, requires approval -----
    # Memory changes are state-changing and must be confirmed. These are listed
    # first so they are matched before any read-only GREEN rule. In particular
    # they must win over the GREEN "get" rule, because the word "forget"
    # contains the substring "get"; without these, "forget memory" would be
    # misclassified as a safe retrieval.
    _Rule("forget memory", SecurityTier.YELLOW, "Forgetting a memory removes it and must be confirmed."),
    _Rule("update memory", SecurityTier.YELLOW, "Updating a memory changes stored content and must be confirmed."),
    _Rule("move memory", SecurityTier.YELLOW, "Moving a memory to another category changes it and must be confirmed."),
    # Phase 89, Batch 1: updating the manually-maintained project-state
    # record changes stored content, just like "update memory" above -
    # an explicit rule is added rather than relying on the default
    # YELLOW fallback, so the reason is always specific and auditable.
    # Does not collide with "update memory" (a different, longer
    # keyword phrase) or any other existing rule.
    _Rule("update jarvis project state", SecurityTier.YELLOW, "Updating the project-state record changes stored content and must be confirmed."),
    # Markdown brain writes: creating or replacing an external Markdown
    # note changes state, exactly like "update memory" above - explicit
    # rules are added rather than relying on the default YELLOW fallback,
    # so the reason is always specific and auditable. Both action strings
    # are fixed and input-independent (BrainWriteTool.action_for derives
    # them from the fixed sub-command only), so a note title, path, or
    # content can never influence classification. Checked directly against
    # every existing rule: neither phrase contains, nor is contained by,
    # "write file"/"edit file"/"update memory"/"delete" (the classification
    # walks this ordered table, and both phrases diverge from each of those
    # at or before their second word) - confirmed by direct comparison,
    # not assumed.
    _Rule("write brain note", SecurityTier.YELLOW, "Creating a Markdown brain note changes external state and must be confirmed."),
    _Rule("update brain note", SecurityTier.YELLOW, "Replacing a Markdown brain note changes external state and must be confirmed."),
    _Rule("delete file", SecurityTier.YELLOW, "Deleting a file changes state and should be confirmed."),
    _Rule("delete folder", SecurityTier.YELLOW, "Deleting a folder changes state and should be confirmed."),
    # Phase 38: restoring a quarantined file changes the filesystem (a
    # new file appears at its original path, and the quarantine copy
    # disappears), so it needs its own dedicated, reason-bearing rule -
    # matching how "copy file"/"move file" each got their own entry
    # rather than relying on the generic YELLOW default fallback.
    _Rule("restore file", SecurityTier.YELLOW, "Restoring a quarantined file changes the filesystem and should be confirmed."),
    _Rule("delete", SecurityTier.YELLOW, "Deletion changes state and should be confirmed."),
    _Rule("remove", SecurityTier.YELLOW, "Removing data changes state and should be confirmed."),
    _Rule("send email", SecurityTier.YELLOW, "Sending an email communicates on your behalf."),
    _Rule("send message", SecurityTier.YELLOW, "Sending a message communicates on your behalf."),
    _Rule("install software", SecurityTier.YELLOW, "Installing software changes the system."),
    _Rule("install", SecurityTier.YELLOW, "Installing changes the system and should be confirmed."),
    _Rule("uninstall", SecurityTier.YELLOW, "Uninstalling changes the system and should be confirmed."),
    _Rule("write file", SecurityTier.YELLOW, "Writing a file changes state and should be confirmed."),
    _Rule("modify file", SecurityTier.YELLOW, "Modifying a file changes state and should be confirmed."),
    _Rule("edit file", SecurityTier.YELLOW, "Editing a file changes state and should be confirmed."),
    # Phase 25: already covered by the generic "write file"-adjacent
    # default-YELLOW fallback without this entry (no existing rule
    # contains "copy"), but listed explicitly, matching every other
    # command family's own tailored reason rather than the generic
    # fallback wording.
    _Rule("copy file", SecurityTier.YELLOW, "Copying a file creates new state and should be confirmed."),
    _Rule("move file", SecurityTier.YELLOW, "Moving a file changes its location and should be confirmed."),
    _Rule("rename", SecurityTier.YELLOW, "Renaming changes state and should be confirmed."),
    _Rule("download", SecurityTier.YELLOW, "Downloading brings external content onto the system."),
    # Phase 33: without this explicit rule, "read webpage" would fall
    # through to the generic GREEN "read" rule below (it contains "read"
    # as a substring) and be misclassified as safe automatic read-only
    # access - but unlike "read file" (local, no external target),
    # reading a webpage sends a network request to an arbitrary,
    # Nathan-supplied target and displays external content, which is
    # exactly the "download" rule's own reasoning above. Listed here,
    # before any GREEN rule, so it is always matched first.
    _Rule("read webpage", SecurityTier.YELLOW, "Reading a webpage brings external network content onto the system and displays it to you, so approval is required."),
    _Rule("run command", SecurityTier.YELLOW, "Running a command can change the system."),
    _Rule("execute", SecurityTier.YELLOW, "Executing code can change the system."),
    _Rule("purchase", SecurityTier.YELLOW, "Spending money should always be confirmed."),
    _Rule("pay", SecurityTier.YELLOW, "Spending money should always be confirmed."),
    # Phase 21: schedule management. None of these three keywords appear
    # anywhere else in this table; without them, all three would already
    # fall through to the cautious YELLOW default - these rules exist
    # only to give each one its own specific, honest reason, matching
    # every other explicit rule's own tailored wording rather than the
    # generic fallback message. Listed before the GREEN "search" rule
    # below so "schedule web search" is never misclassified as a plain,
    # automatically-allowed search.
    _Rule("schedule web search", SecurityTier.YELLOW, "Creating a scheduled action commits Jarvis to run it unattended and should be confirmed."),
    _Rule("enable schedule", SecurityTier.YELLOW, "Re-enabling a scheduled action resumes unattended runs and should be confirmed."),
    _Rule("disable schedule", SecurityTier.YELLOW, "Disabling a scheduled action changes state and should be confirmed."),
    # ----- GREEN: safe, allowed automatically -----
    # A manual, user-requested memory save is read-only from the system's point
    # of view: the user has explicitly asked Jarvis to remember this exact text,
    # nothing is overwritten or removed, and the "do not remember" rule still
    # applies. These phrases are specific to memory so they never green-light a
    # file write, which remains YELLOW via the "write file" rule above.
    _Rule("save memory", SecurityTier.GREEN, "Saving a memory the user explicitly asked to store is safe."),
    _Rule("remember memory", SecurityTier.GREEN, "Remembering text the user explicitly provided is safe."),
    _Rule("search memories", SecurityTier.GREEN, "Searching memory is read-only and safe."),
    _Rule("search memory", SecurityTier.GREEN, "Searching memory is read-only and safe."),
    _Rule("list memories", SecurityTier.GREEN, "Listing memory is read-only and safe."),
    # Phase 24: file search. Already covered by the generic "search" rule
    # below without this entry, but listed explicitly, matching every
    # other command family's own tailored reason rather than the
    # generic fallback wording.
    _Rule("search files", SecurityTier.GREEN, "Searching files by name or content is read-only and safe."),
    # Phase 31: configuration status. Already covered by the generic
    # "show" rule below without this entry, but listed explicitly for
    # the same reason as "search files" above.
    _Rule("show configuration", SecurityTier.GREEN, "Showing configuration status is read-only and never exposes secret values."),
    # Phase 43: command discoverability. Already covered by the generic
    # "show" rule below without this entry, but listed explicitly for
    # the same reason as "search files"/"show configuration" above.
    _Rule("show available commands", SecurityTier.GREEN, "Listing available commands is read-only and safe."),
    # Phase 57, Batch 1: system health check. Already covered by the
    # generic "show" rule below without this entry, but listed
    # explicitly for the same reason as "show available commands" above.
    _Rule("show system health", SecurityTier.GREEN, "Showing system health status is read-only and safe."),
    # Markdown brain reads: already covered by the generic
    # "search"/"read"/"show" rules below without these entries, but listed
    # explicitly for the same reason as "search files" above - each command
    # family's own tailored, auditable reason. Listed before their generic
    # counterparts so the tailored reason always wins. Checked directly
    # against every YELLOW/RED rule above: no rule's keyword appears in
    # any of these three strings (in particular none contains "read
    # webpage", the one YELLOW rule that also starts with "read") -
    # confirmed by direct comparison, not assumed.
    _Rule("search brain notes", SecurityTier.GREEN, "Searching brain notes is read-only and safe."),
    _Rule("read brain note", SecurityTier.GREEN, "Reading a brain note does not change anything."),
    _Rule("show brain status", SecurityTier.GREEN, "Showing brain configuration status is read-only and never exposes secret values."),
    _Rule("search", SecurityTier.GREEN, "Searching is read-only and safe."),
    _Rule("read file", SecurityTier.GREEN, "Reading a file does not change anything."),
    _Rule("read", SecurityTier.GREEN, "Reading does not change anything."),
    _Rule("list", SecurityTier.GREEN, "Listing information is read-only and safe."),
    _Rule("show", SecurityTier.GREEN, "Showing information is read-only and safe."),
    _Rule("view", SecurityTier.GREEN, "Viewing information is read-only and safe."),
    _Rule("get", SecurityTier.GREEN, "Retrieving information is read-only and safe."),
    _Rule("open application", SecurityTier.GREEN, "Opening an application is low risk."),
    _Rule("summarize", SecurityTier.GREEN, "Summarising is read-only and safe."),
    _Rule("summarise", SecurityTier.GREEN, "Summarising is read-only and safe."),
    _Rule("calculate", SecurityTier.GREEN, "Calculating does not change anything."),
)

# Applied when no rule matches: cautious but not blocking. An unrecognised
# action is treated as sensitive and routed for confirmation rather than being
# allowed silently or blocked outright.
_DEFAULT_TIER = SecurityTier.YELLOW
_DEFAULT_REASON = (
    "Action did not match any known rule. Treated as sensitive and routed "
    "for confirmation as a precaution."
)


# ---------------------------------------------------------------------------
# Prompt-injection pattern detection (Phase 7, Batch 3)
#
# A small, explicit, hand-maintained table - deliberately not ML-based, not
# semantic, and not remotely updated (the Master Specification names an
# "advanced injection pattern library" as explicit Future Expansion, not this
# batch). Every pattern is a plain, readable regex covering one of the four
# categories the specification requires: imperatives directed at an AI,
# role/system-override phrasing, tool-call-like syntax embedded in prose, and
# jailbreak phrasing. Patterns are checked in this fixed order, and every
# match is reported - there is no most-severe-wins short-circuit here, unlike
# _RULES, because detection is a report, not a classification decision.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _InjectionPattern:
    """A single named prompt-injection detection pattern.

    Attributes:
        label: A short, stable identifier for this pattern, used in
            InjectionScanResult.matched_patterns and in audit records.
        pattern: The compiled, case-insensitive regex to search for.
    """

    label: str
    pattern: re.Pattern[str]


def _pattern(text: str) -> re.Pattern[str]:
    """Compile a case-insensitive regex for the injection pattern table.

    Args:
        text: The regular expression source.

    Returns:
        The compiled, case-insensitive pattern.
    """
    return re.compile(text, re.IGNORECASE)


_INJECTION_PATTERNS: tuple[_InjectionPattern, ...] = (
    # ----- Imperatives directed at an AI -----
    _InjectionPattern(
        "ignore_previous_instructions",
        _pattern(r"ignore (all |any )?(the )?previous instructions"),
    ),
    _InjectionPattern(
        "ignore_above_instructions",
        _pattern(r"ignore (all |any )?(the )?(above|prior) instructions"),
    ),
    _InjectionPattern(
        "disregard_instructions",
        _pattern(r"disregard (the )?(above|prior|previous)( instructions)?"),
    ),
    _InjectionPattern(
        "forget_your_instructions",
        _pattern(r"forget (your|all|these) (previous )?instructions"),
    ),
    # ----- Role / system-override phrasing -----
    _InjectionPattern(
        "system_instruction_override",
        _pattern(r"system instruction\s*:"),
    ),
    _InjectionPattern(
        "you_are_now_override",
        _pattern(r"\byou are now\b"),
    ),
    _InjectionPattern(
        "new_instructions_override",
        _pattern(r"\bnew instructions\s*:"),
    ),
    _InjectionPattern(
        "pretend_you_are_override",
        _pattern(r"\bpretend (that )?you('re| are)\b"),
    ),
    # ----- Tool-call-like syntax embedded in prose -----
    _InjectionPattern(
        "tool_call_tag",
        _pattern(r"<\s*/?\s*tool_call\s*>"),
    ),
    _InjectionPattern(
        "function_call_syntax",
        _pattern(r"\bfunction_call\s*:"),
    ),
    _InjectionPattern(
        "json_tool_invocation",
        _pattern(r'["\']?tool_name["\']?\s*:\s*["\']'),
    ),
    # ----- Jailbreak phrasing -----
    _InjectionPattern(
        "dan_mode",
        _pattern(r"\bDAN mode\b"),
    ),
    _InjectionPattern(
        "jailbreak_phrase",
        _pattern(r"\bjailbreak\b"),
    ),
    _InjectionPattern(
        "do_anything_now",
        _pattern(r"\bdo anything now\b"),
    ),
    _InjectionPattern(
        "no_restrictions_phrase",
        _pattern(r"\bwithout any (restrictions|limitations|rules)\b"),
    ),
)


# ---------------------------------------------------------------------------
# Unexpected AI action escalation (Phase 7, Batch 4)
#
# Policy only: this section decides what verdict an AI-suggested action
# outside a plan's expected scope should receive. It never executes, approves,
# or reclassifies anything, and it reuses classify_action's existing tier
# decision rather than duplicating it. Whether, and how, a caller acts on the
# verdict is entirely up to that caller - JarvisOrchestrator uses it purely
# for observability in this batch, since nothing yet lets an AI suggestion
# execute at all.
# ---------------------------------------------------------------------------


class UnexpectedActionVerdict(Enum):
    """The verdict for an AI-suggested action outside a plan's expected scope.

    Mirrors the Master Specification's per-tier rule for an unexpected action:
    GREEN is flagged but not obstructed, YELLOW is escalated to approval
    (never granted automatically), and RED is blocked immediately.

    Attributes:
        FLAG: The action is GREEN tier; record the anomaly, do not obstruct.
        ESCALATE: The action is YELLOW tier; require user approval, never
            grant it automatically.
        BLOCK: The action is RED tier; block it immediately.
    """

    FLAG = "flag"
    ESCALATE = "escalate"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class UnexpectedActionDecision:
    """The verdict for one AI-suggested action found outside the expected scope.

    Only produced when the action is not in the caller-supplied set of
    expected actions; classify_action is always the source of the tier.

    Attributes:
        action: The AI-suggested action text that was evaluated.
        tier: The tier classify_action assigned to this action.
        verdict: The unexpected-action verdict derived from that tier.
        reason: A human-readable explanation, combining classify_action's own
            reason with the fact that this action was unexpected.
    """

    action: str
    tier: SecurityTier
    verdict: UnexpectedActionVerdict
    reason: str


_UNEXPECTED_ACTION_VERDICT_BY_TIER: dict[SecurityTier, UnexpectedActionVerdict] = {
    SecurityTier.GREEN: UnexpectedActionVerdict.FLAG,
    SecurityTier.YELLOW: UnexpectedActionVerdict.ESCALATE,
    SecurityTier.RED: UnexpectedActionVerdict.BLOCK,
}


class SecurityManager:
    """Classifies requested actions into security tiers using simple rules.

    The manager is stateless; a single instance can be shared across the
    application. It makes no network calls and uses no AI.
    """

    def classify_action(self, action: str) -> SecurityDecision:
        """Classify a requested action into a security tier.

        The action text is matched case-insensitively against an ordered list
        of keyword rules. RED rules are evaluated before YELLOW, which are
        evaluated before GREEN, so the most severe matching tier always wins.
        Actions that match no rule receive the cautious default tier.

        Args:
            action: A human-readable description of the action to classify
                (e.g. "delete file report.txt", "search memories").

        Returns:
            A SecurityDecision containing the tier, a reason, and the keyword
            that matched (or None when the default was applied).

        Raises:
            ValueError: If the action text is empty or whitespace-only.
        """
        text = action.strip()
        if not text:
            raise ValueError("action must not be empty.")

        haystack = text.casefold()
        for rule in _RULES:
            if rule.keyword in haystack:
                return SecurityDecision(
                    action=text,
                    tier=rule.tier,
                    reason=rule.reason,
                    matched_keyword=rule.keyword,
                )

        return SecurityDecision(
            action=text,
            tier=_DEFAULT_TIER,
            reason=_DEFAULT_REASON,
            matched_keyword=None,
        )

    def scan_for_injection(self, text: str) -> InjectionScanResult:
        """Scan untrusted text for instruction-like prompt-injection patterns.

        This is detection only. It never blocks, rewrites, or removes
        anything, and a suspicious result must never be treated as any form
        of user approval - it is a report for audit and, from Phase 7 Batch 4
        onward, for an escalation policy layered separately on top. Every
        matching pattern is reported; there is no most-severe-wins
        short-circuit, unlike classify_action.

        Args:
            text: The untrusted text to scan (for example, the contents of
                an AIContextBlock with trust=ContentTrust.UNTRUSTED). Trusted
                text - Jarvis's own instructions, or the user's live
                current-turn input - should never be passed here; there is
                nothing external in it to scan for.

        Returns:
            An InjectionScanResult recording whether anything suspicious was
            found, which named patterns matched (in a fixed, deterministic
            order), and the original text.
        """
        matches = tuple(
            entry.label for entry in _INJECTION_PATTERNS if entry.pattern.search(text)
        )
        return InjectionScanResult(
            suspicious=bool(matches),
            matched_patterns=matches,
            text=text,
        )

    def evaluate_unexpected_action(
        self, action: str, expected_actions: frozenset[str]
    ) -> UnexpectedActionDecision | None:
        """Decide the verdict for an action outside a plan's expected scope.

        This reuses classify_action for the tier decision - it is never
        duplicated or reimplemented here. A verdict is only returned when
        action is not a member of expected_actions; an expected action is not
        unexpected, so there is nothing to flag, escalate, or block.

        This method only returns a verdict; it never executes the action,
        never approves it, and never changes classify_action's tier or any
        Plan. What a caller does with the verdict - if anything - is entirely
        up to that caller.

        Args:
            action: The AI-suggested action text to evaluate (for example, an
                AISuggestedAction's description).
            expected_actions: The set of action strings the Planner already
                produced for this request, e.g.
                frozenset(step.action for step in plan.steps).

        Returns:
            None if action is a member of expected_actions. Otherwise, an
            UnexpectedActionDecision carrying classify_action's tier and the
            corresponding verdict: FLAG for GREEN, ESCALATE for YELLOW, BLOCK
            for RED.

        Raises:
            ValueError: If the action text is empty or whitespace-only (the
                same validation classify_action performs).
        """
        if action in expected_actions:
            return None

        classification = self.classify_action(action)
        verdict = _UNEXPECTED_ACTION_VERDICT_BY_TIER[classification.tier]
        return UnexpectedActionDecision(
            action=classification.action,
            tier=classification.tier,
            verdict=verdict,
            reason=(
                "This action was not part of the plan's expected scope. "
                f"{classification.reason}"
            ),
        )
