"""
webpage_read_tool.py

Reads one webpage and returns its extracted, bounded plain text
(Phase 33, Batch 1: Webpage Read Command).

WebpageReadTool is the first tool built on Phase 32's webpage fetch/
read safety foundation. It wraps exactly two Phase 32 components -
web.safe_web_fetcher.SafeWebFetcher and
web.html_text_extractor.extract_text_from_fetched_page - and adds
nothing of its own except input validation, error formatting, and a
small terminal-output sanitizer (see sanitize_terminal_text below).

WebpageReadTool is a YELLOW tool: unlike WebSearchTool (which only ever
calls one fixed, vetted search provider), this tool sends a network
request to an arbitrary, Nathan-supplied target. That is a materially
different risk shape - closer to the existing (currently unused)
"download" rule in security/security_manager.py than to any read-only
GREEN tool - so it always requires approval before it runs, even though
Phase 32's own safety layers have already validated the target and
guarded the fetch itself.

Does NOT:
    - Summarise, interpret, or reason about the fetched content in any
      way - the extracted text is returned to Nathan exactly as Phase
      32 produced it (after sanitization), never rewritten or
      condensed.
    - Call an AI provider, construct an AIContextBlock, or otherwise
      treat fetched content as anything but display text for Nathan.
    - Write the fetched content to a file or the database, or persist
      it anywhere - each call is a fresh fetch with no memory of past
      calls.
    - Bypass, duplicate, or reimplement any of WebFetchPolicy's or
      SafeWebFetcher's own safety checks - every rejection or failure
      Phase 32 already defines is surfaced here as a plain, honest
      ToolResult failure, never retried or worked around.
    - Import anything from ai/, workflow/, scheduler.py, ui/dashboard,
      or inbox/ - this tool's only non-stdlib, non-tools/ dependency is
      the web/ package itself.
"""

from __future__ import annotations

import re
import unicodedata

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from web.html_text_extractor import TextExtractionFailure, extract_text_from_fetched_page
from web.safe_web_fetcher import SafeWebFetcher, WebFetchFailure

_ACTION = "read webpage"

#: ANSI CSI sequences (e.g. "\x1b[31m" for coloured text, cursor
#: movement) - the most common terminal-escape shape a malicious page's
#: text content could contain.
_ANSI_CSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

#: ANSI OSC sequences (e.g. terminal title changes, OSC 8 hyperlinks,
#: OSC 52 clipboard writes) - terminated by BEL or the two-byte ST
#: ("\x1b\\"). A real, documented terminal-injection vector distinct
#: from CSI sequences, so it is matched and removed separately.
_ANSI_OSC_PATTERN = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

#: Control characters that carry meaning in ordinary extracted text and
#: are always preserved. Every other Unicode "Cc" (control) character -
#: including a lone ESC that survived the two patterns above, BEL,
#: backspace, and any other C0/C1 control byte - is removed.
_ALLOWED_CONTROL_CHARS = frozenset({"\n", "\t"})


def sanitize_terminal_text(text: str) -> str:
    """Remove ANSI escape sequences and dangerous control characters.

    Webpage text is untrusted external content, and by the time it
    reaches this function it is about to be printed directly to
    Nathan's terminal. Ordinary text formatting (newlines, tabs) is
    preserved; anything else in the Unicode "control character"
    category is removed, including any ANSI/VT100 escape sequence a
    page's raw text could contain.

    Not addressed here (a disclosed, out-of-scope non-goal, not an
    oversight): Unicode bidirectional/format-control characters (e.g.
    right-to-left override, category "Cf"), which are a related but
    distinct text-spoofing concern from terminal control sequences and
    were judged out of scope for this small, focused sanitizer.

    Args:
        text: The already-extracted plain text to sanitize.

    Returns:
        The same text with ANSI escape sequences and control
        characters (other than newline/tab) removed.
    """
    without_csi = _ANSI_CSI_PATTERN.sub("", text)
    without_osc = _ANSI_OSC_PATTERN.sub("", without_csi)
    return "".join(
        ch
        for ch in without_osc
        if ch in _ALLOWED_CONTROL_CHARS or unicodedata.category(ch) != "Cc"
    )


class WebpageReadTool(BaseTool):
    """Fetches one webpage and returns its extracted, sanitized text.

    Attributes:
        _fetcher: The SafeWebFetcher used to perform every fetch.
    """

    def __init__(self, fetcher: SafeWebFetcher) -> None:
        """Initialise the tool with a SafeWebFetcher.

        Args:
            fetcher: The fetcher to use. Injected, never constructed
                here, mirroring WebSearchTool's own provider-injection
                pattern.
        """
        self._fetcher = fetcher

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "webpage_read".
        """
        return "webpage_read"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description, explicit that no summarization
            happens.
        """
        return (
            "Fetches one webpage and returns its extracted plain text - "
            "not a summary. Requires approval."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the fixed action string used for security classification.

        Always the same string, regardless of the requested URL, so a
        URL's content can never influence this tool's own security
        classification.

        Args:
            request: The request being handled (its content is never
                inspected here).

        Returns:
            The fixed string "read webpage".
        """
        return _ACTION

    def run(self, request: ToolRequest) -> ToolResult:
        """Fetch the requested webpage and return its extracted text.

        Args:
            request: The request. Recognised input key:
                url: the webpage address to read (required).

        Returns:
            A successful ToolResult with the extracted, sanitized text
            when the fetch and extraction both succeed, or a failed
            result naming the Phase 32 failure reason otherwise. Never
            raises.
        """
        raw_url = request.input_data.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            return self.fail(
                "Missing required input: 'url' (the webpage address to read)."
            )
        url = raw_url.strip()

        fetch_result = self._fetcher.fetch(url)
        if isinstance(fetch_result, WebFetchFailure):
            return self.fail(
                f"Could not read webpage '{url}': [{fetch_result.reason.value}] "
                f"{fetch_result.detail}"
            )

        page = fetch_result.page
        extraction_result = extract_text_from_fetched_page(page)
        if isinstance(extraction_result, TextExtractionFailure):
            return self.fail(
                f"Fetched '{url}' but could not extract its text: "
                f"[{extraction_result.reason.value}] {extraction_result.detail}"
            )

        extracted = extraction_result.extracted
        sanitized = sanitize_terminal_text(extracted.text)

        body = sanitized
        if extracted.truncated:
            body += (
                "\n\n[... truncated: the extracted text exceeded the safety "
                "limit and was cut off.]"
            )

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Webpage content from {url}:\n{body}",
            metadata={
                "url": url,
                "status_code": str(page.status_code),
                "content_type": page.content_type,
                "byte_count": str(page.byte_count),
                "truncated": str(extracted.truncated),
                # Phase 34, Batch 2: the clean, sanitized text (without the
                # "Webpage content from <url>:" display header or the
                # truncation-notice line appended to `output` above), so a
                # caller that needs the raw text for a further purpose
                # (AI summarization ingestion) never has to parse this
                # tool's own display-formatted output string - mirroring
                # ai/web_search_ingestion.py's own explicit precedent
                # against coupling AI ingestion to presentation formatting.
                "extracted_text": sanitized,
            },
        )
