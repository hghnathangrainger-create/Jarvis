"""
html_text_extractor.py

Deterministic, standard-library-only webpage text extraction (Phase 32,
Batch 3: Webpage Fetch/Read Safety Foundation).

Responsibilities:
    - Define extract_text_from_page()/extract_text_from_fetched_page(),
      which convert a SafeWebFetcher-fetched page's raw bytes into
      plain text, dispatching on the page's own Content-Type: HTML/
      XHTML is parsed and stripped to visible text, text/plain is
      passed through with only light normalisation.
    - Define ExtractedText/TextExtractionSuccess/TextExtractionFailure/
      TextExtractionFailureReason: the only shapes a caller ever sees.

Does NOT:
    - Execute scripts, evaluate CSS, fetch subresources (images,
      stylesheets, iframes), follow links, or interpret JavaScript in
      any way. This module only ever calls the standard library's
      html.parser.HTMLParser, which does none of those things - it is
      a tokeniser, not a browser or a renderer.
    - Preserve script/style/noscript/template content as if it were
      page text: the content of those elements is discarded entirely
      (see _SKIP_CONTENT_TAGS below), so text that was only ever meant
      to be executed, styled, or shown to non-JS clients can never be
      mistaken for the page's real visible content - or, later, for an
      instruction to an AI reading this output.
    - Treat its own output as trusted. Every ExtractedText this module
      returns is exactly as untrusted as the raw bytes SafeWebFetcher
      fetched - it is Jarvis's own cleaned-up rendering of *someone
      else's* content, not something Jarvis has verified or authored.
      A future ai/webpage_ingestion.py module (not built in this phase)
      must wrap this output in ai.context_models.AIContextBlock.
      from_untrusted(...), exactly like ai/web_search_ingestion.py
      already does for search results - never construct or imply
      ContentTrust.JARVIS_TRUSTED for anything this module returns.
    - Register a tool, a CommandRouter command, or a SecurityManager
      rule; integrate with AI, workflow, scheduler, dashboard, or
      Inbox; or write extracted text to a file or the database.

Design decisions (documented so a later batch does not need to re-derive them):
    - script/style/noscript/template content is skipped by tag name,
      not by trying to detect "is this code" - a small, fixed,
      by-name skip-list, matching this project's general preference
      for explicit allow/skip-lists over heuristic detection.
    - If a skip-tag is never closed (malformed HTML), every subsequent
      character is conservatively treated as still inside that tag -
      the skip zone can only ever grow from unmatched markup, never
      shrink. This means malformed HTML fails safe by excluding more
      text than a perfect parser would, never by leaking script/style
      content into the output.
    - HTML comments are ignored (HTMLParser never calls handle_data for
      comment bodies at all, so no special handling is required).
    - Character references/entities (e.g. "&amp;") are decoded safely
      via HTMLParser's own convert_charrefs=True default - the standard
      library's own decoder, not a hand-rolled one.
    - HTML-extracted whitespace is fully collapsed to single spaces:
      indentation and line breaks in markup carry no meaning, so
      "collapse whitespace" (the Phase 32 plan's own wording) means
      exactly that here - no paragraph/heading structure is preserved.
      This is a deliberate simplification: this module is a text
      extractor, not a layout-preserving renderer. The one exception:
      a fixed set of block-level tags (p, div, li, br, headings, etc.)
      insert a single word-boundary space at their start/end, so two
      adjacent block elements with no whitespace between them in the
      source (common in minified HTML, e.g.
      "<p>Hello</p><p>World</p>") do not collapse into one glued word
      ("HelloWorld") - this is a correctness fix, not structure
      preservation; the boundary is still just a plain space once
      whitespace is collapsed, never a newline or paragraph marker.
    - text/plain content is treated differently: its whitespace *is*
      part of the content (line breaks, indentation, code-like
      formatting), so it is passed through with only line-ending
      normalisation and trimming - never whitespace-collapsed like
      HTML is. This is the "clearly tested decision" the batch's own
      scope calls for.
    - Malformed HTML never raises: HTMLParser is already tolerant of
      real-world malformed markup, and any parser call is additionally
      wrapped so a truly pathological input degrades to whatever text
      had already been accumulated, rather than propagating an
      exception to the caller.
    - Output is hard-capped at _MAX_OUTPUT_CHARS characters, with the
      result honestly reporting whether truncation occurred - never a
      silent partial fill, mirroring ai/web_search_ingestion.py's own
      size-budget disclosure convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser

from web.safe_web_fetcher import FetchedPage

#: Hard cap on characters returned by this module. Chosen to comfortably
#: hold a long article's worth of text while remaining bounded, mirroring
#: FileReadTool's own max_chars discipline.
_MAX_OUTPUT_CHARS = 200_000

#: Tags whose entire content (including any nested markup) is discarded,
#: never appearing in extracted text - see the module docstring's design
#: decision on why a skip-tag that is never closed extends the skip zone
#: rather than shrinking it.
_SKIP_CONTENT_TAGS = frozenset({"script", "style", "noscript", "template"})

_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_PLAIN_TEXT_CONTENT_TYPE = "text/plain"

#: Tags whose start/end marks a word-boundary in extracted text. Without
#: this, adjacent block elements with no whitespace between them in the
#: source (e.g. "<p>Hello</p><p>World</p>", common in minified HTML)
#: would collapse into one glued word ("HelloWorld") once whitespace is
#: collapsed - a real correctness problem, not merely cosmetic. A single
#: space is inserted at each boundary; the final whitespace-collapse
#: step reduces any resulting run of spaces back to exactly one.
_BLOCK_BOUNDARY_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "td",
        "th",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "header",
        "footer",
        "ul",
        "ol",
        "table",
        "pre",
        "hr",
    }
)


class TextExtractionFailureReason(str, Enum):
    """Fixed, stable reason codes for a failed text extraction.

    A str Enum so values compare equal to plain strings, mirroring
    web.fetch_policy.FetchRejectionReason's and
    web.safe_web_fetcher.WebFetchFailureReason's own convention.
    """

    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Bounded, plain-text extraction output.

    Attributes:
        text: The extracted (or passed-through) plain text, always at
            or under _MAX_OUTPUT_CHARS characters.
        character_count: len(text), provided directly for convenient
            audit logging without re-measuring the text.
        truncated: Whether the extracted text was longer than
            _MAX_OUTPUT_CHARS and was cut - never a silent partial
            fill; callers can always tell.
    """

    text: str
    character_count: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class TextExtractionSuccess:
    """A successful extraction outcome, wrapping the extracted text."""

    extracted: ExtractedText


@dataclass(frozen=True, slots=True)
class TextExtractionFailure:
    """A failed extraction outcome - always data, never a raised exception.

    Attributes:
        reason: The TextExtractionFailureReason identifying why
            extraction could not proceed.
        detail: A short, human-readable explanation, safe to display
            or log.
    """

    reason: TextExtractionFailureReason
    detail: str


TextExtractionResult = TextExtractionSuccess | TextExtractionFailure


class _VisibleTextHTMLParser(HTMLParser):
    """Accumulates visible text, skipping script/style/noscript/template.

    Uses a single depth counter across all skip-tags rather than one
    per tag name: any skip-tag start increments it, any skip-tag end
    decrements it (never below zero), so nested or malformed skip-tag
    markup can only ever widen the skipped region, never narrow it
    prematurely - see the module docstring's design-decision note.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_BOUNDARY_TAGS and self._skip_depth == 0:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_BOUNDARY_TAGS and self._skip_depth == 0:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _apply_length_cap(text: str) -> ExtractedText:
    """Enforce _MAX_OUTPUT_CHARS, honestly reporting any truncation.

    Args:
        text: The already-normalised text to bound.

    Returns:
        An ExtractedText with text truncated if necessary and
        truncated set accordingly.
    """
    truncated = len(text) > _MAX_OUTPUT_CHARS
    bounded = text[:_MAX_OUTPUT_CHARS] if truncated else text
    return ExtractedText(
        text=bounded, character_count=len(bounded), truncated=truncated
    )


def extract_html_text(html_source: str) -> ExtractedText:
    """Extract visible plain text from an HTML/XHTML document string.

    Never raises: HTMLParser already tolerates real-world malformed
    markup, and any unexpected parsing error is caught so the function
    still returns whatever text had already been accumulated, rather
    than propagating an exception.

    Args:
        html_source: The already-decoded HTML/XHTML source text.

    Returns:
        An ExtractedText with all HTML markup, scripts, styles,
        noscript/template content, and comments removed, and all
        whitespace collapsed to single spaces.
    """
    parser = _VisibleTextHTMLParser()
    try:
        parser.feed(html_source)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed-input safety net
        pass

    collapsed = re.sub(r"\s+", " ", parser.get_text()).strip()
    return _apply_length_cap(collapsed)


def extract_plain_text(text_source: str) -> ExtractedText:
    """Pass through already-plain text, safely bounded.

    Unlike extract_html_text, whitespace is not collapsed: for
    text/plain content, whitespace (line breaks, indentation) is part
    of the content itself, not markup noise. Only line-ending
    normalisation and outer trimming are applied.

    Args:
        text_source: The already-decoded plain-text source.

    Returns:
        An ExtractedText with normalised line endings and outer
        whitespace trimmed, bounded to _MAX_OUTPUT_CHARS.
    """
    normalized = text_source.replace("\r\n", "\n").replace("\r", "\n").strip()
    return _apply_length_cap(normalized)


def extract_text_from_page(
    content_type: str, body: bytes, *, charset: str | None = None
) -> TextExtractionResult:
    """Decode and extract text from a fetched page's raw content-type/body.

    Args:
        content_type: The page's Content-Type value (with or without a
            "; charset=..." parameter - only the type/subtype prefix is
            used for dispatch).
        body: The page's raw response bytes.
        charset: The charset to decode body with, if known. Falls back
            to UTF-8 with errors="replace" if None, unrecognised, or if
            decoding otherwise fails - mirroring FileReadTool's/
            FileSearchTool's own established decoding convention.

    Returns:
        A TextExtractionSuccess wrapping the extracted text, or a
        TextExtractionFailure if content_type/body are not a supported,
        well-formed combination. Never raises.
    """
    if not isinstance(content_type, str) or not isinstance(body, (bytes, bytearray)):
        return TextExtractionFailure(
            reason=TextExtractionFailureReason.INVALID_INPUT,
            detail="content_type must be a string and body must be bytes.",
        )

    normalized_type = content_type.split(";")[0].strip().lower()

    try:
        decoded = bytes(body).decode(charset or "utf-8", errors="replace")
    except (LookupError, TypeError):
        decoded = bytes(body).decode("utf-8", errors="replace")

    if normalized_type in _HTML_CONTENT_TYPES:
        extracted = extract_html_text(decoded)
    elif normalized_type == _PLAIN_TEXT_CONTENT_TYPE:
        extracted = extract_plain_text(decoded)
    else:
        return TextExtractionFailure(
            reason=TextExtractionFailureReason.UNSUPPORTED_CONTENT_TYPE,
            detail=f"Cannot extract text from content type '{normalized_type}'.",
        )

    return TextExtractionSuccess(extracted=extracted)


def extract_text_from_fetched_page(page: FetchedPage) -> TextExtractionResult:
    """Convenience wrapper: extract text directly from a FetchedPage.

    Args:
        page: A page previously fetched by SafeWebFetcher.

    Returns:
        The same result extract_text_from_page() would return for
        page's own content_type/body/charset fields.
    """
    return extract_text_from_page(page.content_type, page.body, charset=page.charset)
