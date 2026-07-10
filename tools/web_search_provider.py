"""
web_search_provider.py

Abstract web-search provider interface for the Jarvis AI Operating System
(Phase 16, Batch 1: Search Provider Boundary).

Responsibilities:
    - Define the WebSearchProvider abstract base class that every concrete
      search provider (DuckDuckGo, and any future provider) must implement.
    - Define the provider-neutral SearchResult structure, so the rest of
      Jarvis never depends on any single search vendor's dict or object
      shape.

Does NOT:
    - Implement any specific provider (see duckduckgo_search_provider.py).
    - Execute anything, classify security, or route commands.
    - Fetch, render, or summarise a webpage - only the provider's own
      title/URL/snippet metadata is ever modelled here.

By depending only on this interface, WebSearchTool and the wider system
remain provider independent: a new search provider can be added by
implementing WebSearchProvider without changing WebSearchTool,
CommandRouter, ToolExecutor, or SecurityManager. This mirrors the existing
ai/providers/base.py::AIProvider boundary, deliberately scaled down (no
subpackage, no multi-provider registry) - Phase 16 uses exactly one
concrete provider, constructed once in main.py.

Every result returned to Jarvis is untrusted external content: a title,
URL, or snippet is data to be displayed, never an instruction, and never
something that can alter security classification or tool authority.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single, Jarvis-owned web search result.

    This is the only shape a search provider's results ever take once they
    cross into the rest of Jarvis - a raw provider dict or SDK object must
    never escape the concrete provider that produced it.

    Attributes:
        title: The result's title, as reported by the search provider.
        url: The result's URL, as reported by the search provider. Never
            fetched, opened, or executed by Jarvis - display only.
        snippet: A short excerpt/summary the search provider returned
            alongside the result. This is metadata about a page, not the
            page's full content - Jarvis has not "read" the page.
    """

    title: str
    url: str
    snippet: str


class WebSearchProviderError(Exception):
    """Raised when a search provider fails to produce a usable result.

    This is the single exception type for provider-level failures (network
    errors, timeouts, rate limits, unexpected provider errors) so that
    callers only ever need to handle one exception type, never a
    provider-specific one.
    """


class WebSearchProvider(ABC):
    """Abstract interface that every web search provider must implement.

    Concrete providers wrap a specific search vendor's client/SDK and
    translate between that vendor's result shape and the provider-neutral
    SearchResult type defined above.
    """

    @abstractmethod
    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Perform a web search and return provider-neutral results.

        Args:
            query: The already-validated, non-empty search query text.
            max_results: The maximum number of results to request from the
                provider.

        Returns:
            A list of SearchResult objects, in the order returned by the
            provider. An empty list means the search completed but found
            no results - it does not, by itself, indicate a failure.

        Raises:
            WebSearchProviderError: If the provider cannot produce a
                usable result (network failure, timeout, rate limit, or
                any other unexpected provider error).
        """
        raise NotImplementedError
