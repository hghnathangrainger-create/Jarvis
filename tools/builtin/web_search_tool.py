"""
web_search_tool.py

A deterministic, read-only web-search tool (Phase 16, Batch 2: Read-Only
Tool, Command Routing, Composition Wiring).

WebSearchTool is a GREEN tool. It performs exactly one external-network
read - a search - and returns the provider's title/URL/snippet metadata
directly to Nathan. It has no operation beyond "search", creates,
modifies, deletes, installs, approves, and executes nothing, and never
fetches, renders, or follows a URL.

WebSearchTool depends only on the WebSearchProvider abstraction (never a
concrete search vendor's dict or SDK type directly), so a future provider
can be substituted without changing this tool, CommandRouter,
ToolExecutor, or SecurityManager.

Security note: action_for() always returns the same fixed string,
regardless of the query's content. This guarantees a search query - no
matter what words it contains - can never influence this tool's own
security classification; SecurityManager.classify_action() is called
exactly once, before the search runs, against that fixed string, never
again and never against the query or the results.

All search results are untrusted external content: titles, URLs, and
snippets are displayed as data only. They are never interpreted as a
command, never fetched or opened automatically, and never enter an AI
reasoning path in this phase.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.web_search_provider import SearchResult, WebSearchProvider, WebSearchProviderError

_ACTION = "search the web"
_DEFAULT_MAX_RESULTS = 5


class WebSearchTool(BaseTool):
    """Performs a live web search and returns results directly to Nathan.

    Attributes:
        _provider: The WebSearchProvider used to perform the search.
    """

    def __init__(self, provider: WebSearchProvider) -> None:
        """Initialise the tool with a WebSearchProvider.

        Args:
            provider: The search provider to use. Injected, never
                constructed here - this tool never imports a concrete
                search vendor's client directly.
        """
        self._provider = provider

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "web_search".
        """
        return "web_search"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description, explicit that only search-result
            metadata (not full webpage content) is ever returned.
        """
        return (
            "Searches the live web and returns titles, URLs, and short "
            "snippets - not full webpage content. Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the fixed action string used for security classification.

        Always the same string, regardless of the query's content - see
        the module docstring for why this is a deliberate security
        decision, not an oversight.

        Args:
            request: The request being handled (its content is never
                inspected here).

        Returns:
            The fixed string "search the web".
        """
        return _ACTION

    def run(self, request: ToolRequest) -> ToolResult:
        """Perform a web search and return the results.

        Args:
            request: The request. Recognised input key:
                query: the search query text.

        Returns:
            A ToolResult containing the formatted results, an honest
            "no results found" message, or a failure for an empty query
            or a provider error. Never raises.
        """
        raw_query = request.input_data.get("query", "")
        query = str(raw_query).strip()
        if not query:
            return self.fail("A web search requires a non-empty query.")

        try:
            results = self._provider.search(query, max_results=_DEFAULT_MAX_RESULTS)
        except WebSearchProviderError as exc:
            return self.fail(f"Web search failed: {exc}")

        if not results:
            return self.ok(f"No web results were found for '{query}'.")

        return self.ok(self._format_results(query, results))

    @staticmethod
    def _format_results(query: str, results: list[SearchResult]) -> str:
        """Format search results as readable, clearly-labelled text.

        Never claims a webpage was read - only that these are search
        results (titles, URLs, and snippets), consistent with what the
        provider actually returned.

        Args:
            query: The search query, for the header line.
            results: The results to format, in provider order.

        Returns:
            A formatted, multi-line string.
        """
        lines = [
            f"Web search results for \"{query}\" "
            "(titles, URLs, and short snippets - not full webpage content):"
        ]
        for index, result in enumerate(results, start=1):
            lines.append(f"  {index}. {result.title}")
            lines.append(f"     {result.url}")
            lines.append(f"     {result.snippet}")
        return "\n".join(lines)
