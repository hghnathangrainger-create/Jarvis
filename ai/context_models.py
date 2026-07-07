"""
context_models.py

Trust-tagged AI context blocks for the Jarvis AI Operating System
(Phase 7, Batch 2).

Responsibilities:
    - Define AIContextBlock: a piece of text destined for an AI prompt,
      carrying its trust origin as a structural property rather than as a
      convention a caller could forget or misapply.
    - Provide the only approved construction paths: from_system(),
      from_live_user_input(), and from_untrusted(). No other way to produce
      an AIContextBlock exists.
    - Enforce, at construction, that ContentTrust.JARVIS_TRUSTED can only be
      produced by the two named trusted factories - never by direct
      construction, regardless of what source string a caller supplies.

Does NOT:
    - Decide what content is fed into a prompt (see ai/reasoning_engine.py)
      or how a block is rendered into prompt text (see ai/prompt_builder.py).
    - Scan content for suspicious patterns (Phase 7, Batch 3).
    - Call any AI provider.

Conservative trust rule: JARVIS_TRUSTED is reserved for text Jarvis's own
code authored (source="system") or the user's literal current-turn typed
input (source="user_live_input"). Everything else - stored memory, file
contents, web/network content, tool output, AI-generated content, external
memory, and historical conversation text - is UNTRUSTED, even though a
person originally wrote some of it, because it was not authored live, in
this turn, by the user currently in control. Nothing about this rule may be
relaxed by adding a new source string to the trusted set; only a separate,
explicit, and documented security decision (not this module) may ever
change it.

Construction guard, precisely: a source string alone is never sufficient
proof of origin - "system" or "user_live_input" are just labels a caller
could type without ever having gone through the approved factories. The
guard below therefore does not check the source string; it checks for
possession of a private, unexported sentinel object that only from_system()
and from_live_user_input() ever pass. Direct construction of AIContextBlock
with trust=ContentTrust.JARVIS_TRUSTED - even with an approved-looking
source - fails, because the sentinel is never supplied. Reaching that
sentinel from outside this module requires deliberately importing a
private, undocumented name and reproducing the exact singleton instance;
that is a fundamentally different act from supplying a plausible string,
and is the accepted boundary of what "cannot be produced" means for a
runtime, non-cryptographic guard in a single-process Python application.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config.constants import ContentTrust

#: The only two source labels ever permitted to carry JARVIS_TRUSTED. Used
#: only for documentation and readability in error messages; membership in
#: this set is NOT what grants trust - see _TRUSTED_ORIGIN_KEY below.
_JARVIS_TRUSTED_SOURCES = frozenset({"system", "user_live_input"})

#: An unforgeable, unexported sentinel. Only from_system() and
#: from_live_user_input() ever pass this to the constructor. A caller
#: constructing AIContextBlock directly - even with trust=JARVIS_TRUSTED and
#: source="system" - leaves _origin_key at its default of None, which fails
#: the identity check in __post_init__. This module never exports this name;
#: __all__ deliberately omits it.
_TRUSTED_ORIGIN_KEY = object()

__all__ = ["AIContextBlock"]


@dataclass(frozen=True, slots=True)
class AIContextBlock:
    """A single piece of context destined for an AI prompt, with its trust
    origin attached structurally.

    Instances must be created only through from_system(),
    from_live_user_input(), or from_untrusted(). Constructing one directly
    with trust=ContentTrust.JARVIS_TRUSTED always raises ValueError,
    regardless of what source string is supplied - trusted authority can
    never be claimed by typing the right label, only by having actually gone
    through one of the two approved trusted factories.

    Attributes:
        text: The context text itself.
        trust: Whether this text is JARVIS_TRUSTED or UNTRUSTED.
        source: A short label identifying where this text came from - one of
            "system" or "user_live_input" for JARVIS_TRUSTED text, or any
            other descriptive label (for example "memory", "file", "web",
            "tool_output", "ai_generated", "conversation_history") for
            UNTRUSTED text. Purely descriptive; it never grants trust.
    """

    text: str
    trust: ContentTrust
    source: str
    _origin_key: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Reject any attempt to claim JARVIS_TRUSTED without the factory key.

        Raises:
            ValueError: If trust is ContentTrust.JARVIS_TRUSTED but this
                instance was not constructed via from_system() or
                from_live_user_input().
        """
        if self.trust is not ContentTrust.JARVIS_TRUSTED:
            return

        if self._origin_key is not _TRUSTED_ORIGIN_KEY:
            raise ValueError(
                "ContentTrust.JARVIS_TRUSTED can only be produced by "
                "AIContextBlock.from_system() or "
                "AIContextBlock.from_live_user_input(). Direct construction "
                "cannot claim trusted authority, even with an approved-"
                f"looking source such as {sorted(_JARVIS_TRUSTED_SOURCES)!r} "
                "- a source label is descriptive only and is never proof of "
                "origin. Use AIContextBlock.from_untrusted(...) for any "
                "content that did not come from one of the two named "
                "trusted factories."
            )

        if self.source not in _JARVIS_TRUSTED_SOURCES:
            # Unreachable through the public factories (they always pass a
            # matching source alongside the key), but kept as a second,
            # independent check so the two trusted factories can never drift
            # out of sync with this guard by accident.
            raise ValueError(
                "ContentTrust.JARVIS_TRUSTED may only be paired with "
                f"source in {sorted(_JARVIS_TRUSTED_SOURCES)!r}, got "
                f"source={self.source!r}."
            )

    @classmethod
    def from_system(cls, text: str) -> "AIContextBlock":
        """Build a JARVIS_TRUSTED block for text Jarvis's own code authored.

        Args:
            text: The system-authored text (for example, a system
                instruction fragment).

        Returns:
            An AIContextBlock with trust=JARVIS_TRUSTED, source="system".
        """
        return cls(
            text=text,
            trust=ContentTrust.JARVIS_TRUSTED,
            source="system",
            _origin_key=_TRUSTED_ORIGIN_KEY,
        )

    @classmethod
    def from_live_user_input(cls, text: str) -> "AIContextBlock":
        """Build a JARVIS_TRUSTED block for the user's literal current-turn input.

        Args:
            text: The user's own typed request text for the current turn
                only. Never a stored or historical copy of past input.

        Returns:
            An AIContextBlock with trust=JARVIS_TRUSTED,
            source="user_live_input".
        """
        return cls(
            text=text,
            trust=ContentTrust.JARVIS_TRUSTED,
            source="user_live_input",
            _origin_key=_TRUSTED_ORIGIN_KEY,
        )

    @classmethod
    def from_untrusted(cls, text: str, *, source: str) -> "AIContextBlock":
        """Build an UNTRUSTED block for any non-live, non-Jarvis-authored text.

        Use this for stored memory, file contents, web/network content, tool
        output, AI-generated content, external memory, and historical
        conversation text - anything that is not Jarvis's own authored text
        or the user's literal current-turn input.

        Args:
            text: The untrusted text.
            source: A required, descriptive label for where this text came
                from (for example "memory", "file", "web", "tool_output",
                "ai_generated", "conversation_history"). Never grants trust;
                UNTRUSTED blocks require no key regardless of this label.

        Returns:
            An AIContextBlock with trust=ContentTrust.UNTRUSTED.
        """
        return cls(text=text, trust=ContentTrust.UNTRUSTED, source=source)
