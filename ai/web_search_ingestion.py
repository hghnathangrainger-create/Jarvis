"""
web_search_ingestion.py

Web-search-result ingestion for the Jarvis AI Operating System (Phase 18,
Batch 1).

Responsibilities:
    - Acquire live web search results through the existing, unmodified
      WebSearchProvider abstraction (calling provider.search() directly,
      exactly once), and combine them into exactly one UNTRUSTED AI
      context, mirroring ai/memory_ingestion.py::ingest_memories_for_ai's
      own proven multi-item combination shape.
    - Represent every acquisition failure - a provider exception, or zero
      results - as data, never as a raised exception, matching both
      ai/file_ingestion.py's and ai/memory_ingestion.py's own established
      convention.
    - Frame every included result (title, URL, snippet) so its
      boundaries are obvious and it can never be mistaken for a Jarvis
      instruction, a trusted historical fact, or full webpage content.

Does NOT:
    - Call WebSearchTool or ToolExecutor. WebSearchTool's own run()
      returns a CLI-formatted display string; using it here would couple
      the AI ingestion boundary to presentation formatting, exactly the
      reason ai/memory_ingestion.py already gives for bypassing MemoryTool
      and calling MemoryManager.get() directly. WebSearchProvider.search()
      is the same kind of raw, already-safe, read-only dependency
      MemoryManager.get() already is - this module calls it the same way.
    - Import DDGS, duckduckgo_search, or any dependency-specific type.
      Only tools.web_search_provider.WebSearchProvider/SearchResult are
      ever touched here - the exact same Jarvis-owned boundary
      WebSearchTool itself already depends on.
    - Ever produce ContentTrust.JARVIS_TRUSTED - only
      AIContextBlock.from_untrusted() is ever used here, for every title,
      URL, and snippet, with no exception.
    - Rank, re-order, deduplicate, or otherwise reinterpret the results
      the provider returns. Results are combined in exactly the order
      provider.search() returned them.
    - Call the provider more than once. search() is invoked exactly one
      time per call to ingest_web_search_for_ai() - there is no code path
      here, or anywhere downstream of this module, that could trigger a
      second search.
    - Introduce a generic, multi-source ingestion framework. This module
      is deliberately web-search-specific, mirroring
      ai/file_ingestion.py's and ai/memory_ingestion.py's own explicit
      narrowness (both already anticipate a future source, such as a
      webpage, getting its own equally narrow module - this is that
      module, not a shared base class invented ahead of only its second
      real example).
    - Scan anything for injection patterns itself. The combined context
      still reaches PromptBuilder's existing, unmodified, automatic scan
      unchanged - this module never scans anything.
    - Claim its per-result delimiter framing or preamble sentence is a
      security boundary, a parser, or cryptographic isolation of any
      kind. It is structural serialization only - plain text embedded
      inside one UNTRUSTED block, exactly as untrusted as the search
      result content around it.

This is the only new production component Batch 1 adds.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.context_models import AIContextBlock
from tools.web_search_provider import SearchResult, WebSearchProvider, WebSearchProviderError

_DEFAULT_MAX_RESULTS = 5
_DEFAULT_MAX_CHARS_PER_RESULT = 500
_DEFAULT_MAX_TOTAL_CHARS = 4000

#: Fixed, Jarvis-authored preamble prepended to the combined context, ahead
#: of the actual results. Structural serialization only - it lives inside
#: the same UNTRUSTED block as the results themselves, but its own text is
#: entirely Jarvis-authored and fixed, never influenced by anything a
#: search result contains. Directly establishes, at the point the AI
#: actually reads the data, that these are snippets/metadata - not full
#: webpage content - and that Jarvis did not visit or read any page.
_PREAMBLE = (
    "The following are web search result snippets (titles, URLs, and "
    "short excerpts) - not full webpage content. They may be incomplete "
    "or inaccurate, and Jarvis did not visit or read the underlying "
    "pages."
)

#: Per-result framing. Structural serialization only - plain text embedded
#: inside one UNTRUSTED block, never a security boundary, never parsed
#: back out by any Jarvis code. {index} is the 1-based position among
#: *included* results, not the provider's original position, since a
#: SearchResult has no stable identity to number by.
_RESULT_DELIMITER_TEMPLATE = (
    "\n----- Search result {index} -----\n"
    "Title: {title}\n"
    "URL: {url}\n"
    "Snippet: {snippet}\n"
)


@dataclass(frozen=True, slots=True)
class WebSearchIngestionResult:
    """The result of ingesting live web search results for AI reasoning.

    Exactly one of `context`/`error` is populated, mirroring
    MemorySetIngestionResult's own success/error convention. Unlike
    MemorySetIngestionResult, outcomes are tracked as plain counts, not
    itemized ids - a SearchResult has no stable identity to itemize by.

    Attributes:
        context: A single UNTRUSTED AIContextBlock combining every
            included result, on success. None when no result could be
            included (total failure).
        error: A human-readable summary of why no result could be
            included (a provider failure, or zero results found). None
            on success.
        included_count: The number of results actually combined into
            `context`. Zero for a represented failure.
        omitted_for_size: The number of otherwise-valid results excluded
            because including them would have exceeded the combined
            total-size budget. Never partially included a second time to
            fill remaining space.
    """

    context: AIContextBlock | None = None
    error: str | None = None
    included_count: int = 0
    omitted_for_size: int = 0

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If both `context` and `error` are set, if neither
                is set, if `context` is set but `included_count` is zero,
                or if `context` is None but `included_count` is non-zero.
        """
        if self.context is not None and self.error is not None:
            raise ValueError(
                "WebSearchIngestionResult cannot carry both a context and "
                "an error - ingestion either succeeded (context) or "
                "failed (error), never both."
            )
        if self.context is None and self.error is None:
            raise ValueError(
                "WebSearchIngestionResult must carry either a context "
                "(success) or an error (failure) - it cannot represent "
                "neither."
            )
        if self.context is not None and self.included_count < 1:
            raise ValueError(
                "WebSearchIngestionResult cannot carry a context with "
                "included_count < 1 - a combined context implies at "
                "least one result was actually included."
            )
        if self.context is None and self.included_count != 0:
            raise ValueError(
                "WebSearchIngestionResult cannot report a non-zero "
                "included_count without a context - a represented "
                "failure never claims that any result was combined."
            )

    @property
    def success(self) -> bool:
        """Return whether ingestion produced usable, combined AI context.

        Returns:
            True if `context` is present, False otherwise.
        """
        return self.context is not None


def ingest_web_search_for_ai(
    provider: WebSearchProvider,
    query: str,
    *,
    max_results: int = _DEFAULT_MAX_RESULTS,
    max_chars_per_result: int = _DEFAULT_MAX_CHARS_PER_RESULT,
    max_total_chars: int = _DEFAULT_MAX_TOTAL_CHARS,
) -> WebSearchIngestionResult:
    """Perform exactly one web search and combine its results into one AI context.

    This function performs exactly one acquisition: it calls
    provider.search(query, max_results=max_results) itself, once, and
    combines whatever results come back. There is no parameter, loop, or
    retry through which a second search could occur.

    The exact size-budget sequence (mirroring
    ai/memory_ingestion.py::ingest_memories_for_ai's own proven sequence):
    results in provider-returned order -> a per-result snippet truncation
    -> a running total-size check. A result that does not fit within the
    remaining total budget is never truncated further to fit - it is
    wholly omitted and counted in `omitted_for_size`.

    WebSearchProvider.search() is already read-only and side-effect-free;
    this function adds no new security tier, approval requirement, or
    execution path, and never goes through ToolExecutor or WebSearchTool,
    exactly like ai/memory_ingestion.py's own functions never go through
    ToolExecutor or MemoryTool.

    Args:
        provider: The WebSearchProvider used to perform the search.
        query: Nathan's own, already-parsed search query text.
        max_results: The maximum number of results to request from the
            provider. Defaults to 5, matching WebSearchTool's own fixed
            default.
        max_chars_per_result: The maximum number of characters of each
            individual result's snippet to include. Title and URL are
            never truncated - they are naturally short, and truncating a
            URL would make it useless. Defaults to 500.
        max_total_chars: The maximum combined number of characters across
            every included result's own framed contribution (its
            delimiter, title, URL, and truncated snippet). Defaults to
            4000.

    Returns:
        A WebSearchIngestionResult. On success (at least one result
        included), `context` is a single
        AIContextBlock.from_untrusted(...) - never JARVIS_TRUSTED -
        combining the fixed preamble and every included result's own
        delimited contribution, labelled source=f"web-search:{query!r}".
        On total failure (a provider exception, or zero results found),
        `context` is None and `error` honestly explains why - and no
        result is ever presented as if it were usable context.

    Raises:
        ValueError: If max_chars_per_result or max_total_chars is not a
            positive integer.
    """
    if max_chars_per_result < 1:
        raise ValueError(
            f"max_chars_per_result must be a positive integer, got "
            f"{max_chars_per_result}."
        )
    if max_total_chars < 1:
        raise ValueError(
            f"max_total_chars must be a positive integer, got {max_total_chars}."
        )

    try:
        results: list[SearchResult] = provider.search(query, max_results=max_results)
    except WebSearchProviderError as exc:
        return WebSearchIngestionResult(
            error=f"Web search failed: {exc}"
        )

    if not results:
        return WebSearchIngestionResult(
            error=f"No web results were found for '{query}'."
        )

    included_count = 0
    omitted_for_size = 0
    contributions: list[str] = []
    running_total = len(_PREAMBLE)

    for result in results:
        text, _truncated = _truncate(result.snippet, max_chars_per_result)
        contribution = _RESULT_DELIMITER_TEMPLATE.format(
            index=included_count + omitted_for_size + 1,
            title=result.title,
            url=result.url,
            snippet=text,
        )

        if running_total + len(contribution) > max_total_chars:
            omitted_for_size += 1
            continue

        running_total += len(contribution)
        included_count += 1
        contributions.append(contribution)

    if included_count == 0:
        return WebSearchIngestionResult(
            error=(
                f"Web results for '{query}' could not be included within "
                "the size limit."
            ),
            omitted_for_size=omitted_for_size,
        )

    combined_text = (_PREAMBLE + "".join(contributions)).strip()

    return WebSearchIngestionResult(
        context=AIContextBlock.from_untrusted(
            combined_text, source=f"web-search:{query!r}"
        ),
        included_count=included_count,
        omitted_for_size=omitted_for_size,
    )


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Shorten a snippet to max_chars, with an honest truncation notice.

    Args:
        text: The result's raw snippet text.
        max_chars: The maximum number of characters of text to keep.

    Returns:
        A tuple of (text, truncated). When text already fits within
        max_chars, it is returned unchanged and truncated is False.
        Otherwise, the first max_chars characters are kept, followed by
        an explicit truncation notice, and truncated is True.
    """
    if len(text) <= max_chars:
        return text, False

    notice = f" [... truncated: showing the first {max_chars} characters.]"
    return f"{text[:max_chars]}{notice}", True
