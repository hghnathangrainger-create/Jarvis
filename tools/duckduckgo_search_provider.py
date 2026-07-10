"""
duckduckgo_search_provider.py

DuckDuckGo implementation of the WebSearchProvider interface (Phase 16,
Batch 1: Search Provider Boundary).

Responsibilities:
    - Wrap the installed duckduckgo_search==8.1.1 package's DDGS.text()
      call behind the provider-neutral WebSearchProvider interface.
    - Translate DDGS.text()'s raw list[dict[str, str]] result shape into
      Jarvis-owned SearchResult objects - no raw provider dict ever
      crosses this boundary.
    - Surface every provider failure (network error, timeout, rate limit,
      or any other unexpected error) as WebSearchProviderError.

Does NOT:
    - Implement memory, planning, workflow, or tool logic.
    - Decide when it is called (that is WebSearchTool's responsibility).
    - Fetch, render, or summarise a webpage - only the three fields DDGS
      itself returns (title, href, body) are ever read.

This is the only module permitted to import duckduckgo_search. Keeping
this vendor dependency isolated here is what makes the rest of Jarvis
provider independent - a future migration to a different search vendor
(including the package's own documented successor, "ddgs" - see the
module-level note below) would only ever require a new adapter here,
never a change to WebSearchTool, CommandRouter, ToolExecutor, or
SecurityManager.

Known, disclosed dependency debt (verified directly against the
installed environment, not assumed): duckduckgo_search 8.1.1 emits a
RuntimeWarning on every call stating it has been renamed to "ddgs" and
recommending "pip install ddgs" instead. Phase 16 deliberately does not
migrate to "ddgs" - that package is not installed in this environment,
and switching dependencies was not part of the approved Phase 16 scope.
This adapter is exactly the boundary that would make such a migration
possible later without touching anything above it.
"""

from __future__ import annotations

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

from tools.web_search_provider import (
    SearchResult,
    WebSearchProvider,
    WebSearchProviderError,
)

_DEFAULT_TIMEOUT_SECONDS = 10

#: The exact three keys DDGS.text() returns per result, verified directly
#: against the installed package's own source
#: (duckduckgo_search/duckduckgo_search.py). A result missing any of these
#: keys, or whose value is not a string, is treated as malformed and
#: skipped - it never reaches the rest of Jarvis.
_REQUIRED_KEYS = ("title", "href", "body")


class DuckDuckGoSearchProvider(WebSearchProvider):
    """WebSearchProvider implementation backed by the DuckDuckGo API.

    Attributes:
        _client: The DDGS client used to make search requests.
    """

    def __init__(self, *, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        """Initialise the provider with a fixed, explicit request timeout.

        Args:
            timeout: Maximum seconds to wait for a search request before
                it is treated as a timeout failure. Defaults to the
                library's own documented default (10 seconds), made
                explicit here rather than left implicit.
        """
        self._client = DDGS(timeout=timeout)

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Perform a DuckDuckGo text search and return Jarvis-owned results.

        Args:
            query: The already-validated, non-empty search query text.
            max_results: The maximum number of results to request.

        Returns:
            A list of SearchResult objects. An empty list means the
            search completed but found no results.

        Raises:
            WebSearchProviderError: If the DuckDuckGo client raises any
                exception - a rate limit, a timeout, or any other
                unexpected error.
        """
        try:
            raw_results = self._client.text(query, max_results=max_results)
        except DuckDuckGoSearchException as exc:
            raise WebSearchProviderError(
                f"Web search request failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surface any client failure uniformly
            raise WebSearchProviderError(
                f"Unexpected error performing web search: {exc}"
            ) from exc

        if not raw_results:
            return []

        return [
            self._to_search_result(raw)
            for raw in raw_results
            if self._is_usable(raw)
        ]

    @staticmethod
    def _is_usable(raw: object) -> bool:
        """Report whether a raw provider result has every required field.

        A malformed individual result (missing a key, or a key whose value
        is not a string) is skipped rather than raised - one bad result
        must never discard the rest of an otherwise-usable result set.

        Args:
            raw: One raw result as returned by DDGS.text().

        Returns:
            True if the raw result is a dict containing non-empty string
            values for every key in _REQUIRED_KEYS.
        """
        if not isinstance(raw, dict):
            return False
        return all(isinstance(raw.get(key), str) for key in _REQUIRED_KEYS)

    @staticmethod
    def _to_search_result(raw: dict[str, str]) -> SearchResult:
        """Convert one verified-usable raw result dict into a SearchResult.

        Args:
            raw: A raw result dict already confirmed usable by _is_usable.

        Returns:
            The corresponding Jarvis-owned SearchResult.
        """
        return SearchResult(
            title=raw["title"],
            url=raw["href"],
            snippet=raw["body"],
        )
