"""
security_manager.py

Rule-based action classification for the Jarvis AI Operating System.

Responsibilities:
    - Classify a requested action as GREEN, YELLOW, or RED.
    - Return a clear, human-readable reason alongside every classification.
    - Apply a safe default (YELLOW) to actions that match no known rule.

Does NOT:
    - Execute, approve, or block actions itself (it only classifies them).
    - Use AI calls or any external security service.
    - Connect to the Planner or Workflow Engine.
    - Implement permissions, roles, or credential handling.

The classification is deliberately simple and rule-based for Phase 1: an
ordered list of keyword rules, checked most-dangerous-first, so that the most
severe matching tier always wins. Every rule carries its own explanation, so
the result is always understandable and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    _Rule("delete file", SecurityTier.YELLOW, "Deleting a file changes state and should be confirmed."),
    _Rule("delete folder", SecurityTier.YELLOW, "Deleting a folder changes state and should be confirmed."),
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
    _Rule("move file", SecurityTier.YELLOW, "Moving a file changes its location and should be confirmed."),
    _Rule("rename", SecurityTier.YELLOW, "Renaming changes state and should be confirmed."),
    _Rule("download", SecurityTier.YELLOW, "Downloading brings external content onto the system."),
    _Rule("run command", SecurityTier.YELLOW, "Running a command can change the system."),
    _Rule("execute", SecurityTier.YELLOW, "Executing code can change the system."),
    _Rule("purchase", SecurityTier.YELLOW, "Spending money should always be confirmed."),
    _Rule("pay", SecurityTier.YELLOW, "Spending money should always be confirmed."),
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