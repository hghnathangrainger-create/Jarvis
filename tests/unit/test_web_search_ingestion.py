"""
test_web_search_ingestion.py

Unit tests for ai/web_search_ingestion.py (Phase 18, Batch 1: Web-Search
Ingestion Model and Combination Logic).

A fake WebSearchProvider is used throughout - no real network call, and
no dependency on the concrete DuckDuckGo adapter at all.

Run with:
    pytest tests/unit/test_web_search_ingestion.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

from ai.context_models import AIContextBlock
from ai.web_search_ingestion import (
    WebSearchIngestionResult,
    ingest_web_search_for_ai,
)
from config.constants import ContentTrust
from tools.web_search_provider import SearchResult, WebSearchProvider, WebSearchProviderError


class _FakeProvider(WebSearchProvider):
    """A fake WebSearchProvider recording every call it receives."""

    def __init__(
        self,
        *,
        results: list[SearchResult] | None = None,
        raise_: Exception | None = None,
    ) -> None:
        self._results = results if results is not None else []
        self._raise = raise_
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if self._raise is not None:
            raise self._raise
        return self._results


def _result(title: str = "A Title", url: str = "https://example.com", snippet: str = "A snippet.") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


# --- WebSearchIngestionResult invariants ---------------------------------------


def test_result_rejects_both_context_and_error() -> None:
    context = AIContextBlock.from_untrusted("text", source="web-search:'q'")
    with pytest.raises(ValueError):
        WebSearchIngestionResult(context=context, error="boom", included_count=1)


def test_result_rejects_neither_context_nor_error() -> None:
    with pytest.raises(ValueError):
        WebSearchIngestionResult()


def test_result_rejects_context_with_zero_included_count() -> None:
    context = AIContextBlock.from_untrusted("text", source="web-search:'q'")
    with pytest.raises(ValueError):
        WebSearchIngestionResult(context=context, included_count=0)


def test_result_rejects_error_with_nonzero_included_count() -> None:
    with pytest.raises(ValueError):
        WebSearchIngestionResult(error="boom", included_count=1)


def test_result_success_property() -> None:
    context = AIContextBlock.from_untrusted("text", source="web-search:'q'")
    ok = WebSearchIngestionResult(context=context, included_count=1)
    assert ok.success is True
    failed = WebSearchIngestionResult(error="boom")
    assert failed.success is False


# --- Successful ingestion -------------------------------------------------------


def test_ingest_combines_results_into_one_untrusted_context() -> None:
    provider = _FakeProvider(
        results=[_result(title="First", url="https://a", snippet="one")]
    )

    result = ingest_web_search_for_ai(provider, "jarvis ai")

    assert result.success is True
    assert result.context.trust is ContentTrust.UNTRUSTED
    assert result.included_count == 1


def test_ingest_calls_provider_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(results=[_result()])

    ingest_web_search_for_ai(provider, "distinctive query")

    assert len(provider.calls) == 1
    assert provider.calls[0] == ("distinctive query", 5)


def test_ingest_preserves_query_text_unchanged() -> None:
    provider = _FakeProvider(results=[_result()])

    ingest_web_search_for_ai(provider, "  a query with odd casing AND spacing  ")

    assert provider.calls[0][0] == "  a query with odd casing AND spacing  "


def test_ingest_preserves_result_order() -> None:
    provider = _FakeProvider(
        results=[
            _result(title="First", url="https://a", snippet="one"),
            _result(title="Second", url="https://b", snippet="two"),
            _result(title="Third", url="https://c", snippet="three"),
        ]
    )

    result = ingest_web_search_for_ai(provider, "query")

    text = result.context.text
    assert text.index("First") < text.index("Second") < text.index("Third")


def test_ingest_deterministic_result_labels() -> None:
    provider = _FakeProvider(
        results=[_result(title="First"), _result(title="Second")]
    )

    result = ingest_web_search_for_ai(provider, "query")

    assert "Search result 1" in result.context.text
    assert "Search result 2" in result.context.text


def test_ingest_preserves_title_url_snippet_boundaries() -> None:
    provider = _FakeProvider(
        results=[_result(title="My Title", url="https://example.com/page", snippet="My snippet text")]
    )

    result = ingest_web_search_for_ai(provider, "query")

    text = result.context.text
    assert "Title: My Title" in text
    assert "URL: https://example.com/page" in text
    assert "Snippet: My snippet text" in text


def test_ingest_includes_fixed_preamble_disclosure() -> None:
    provider = _FakeProvider(results=[_result()])

    result = ingest_web_search_for_ai(provider, "query")

    text = result.context.text
    assert "not full webpage content" in text
    assert "did not visit or read" in text


def test_ingest_source_label_includes_query() -> None:
    provider = _FakeProvider(results=[_result()])

    result = ingest_web_search_for_ai(provider, "my query")

    assert "web-search:" in result.context.source
    assert "my query" in result.context.source


# --- Zero results / provider failure ---------------------------------------------


def test_zero_results_is_a_total_failure_not_usable_context() -> None:
    provider = _FakeProvider(results=[])

    result = ingest_web_search_for_ai(provider, "nothing found for this")

    assert result.success is False
    assert result.context is None
    assert "No web results were found" in result.error
    assert "nothing found for this" in result.error


def test_provider_exception_is_a_total_failure() -> None:
    provider = _FakeProvider(raise_=WebSearchProviderError("network unavailable"))

    result = ingest_web_search_for_ai(provider, "query")

    assert result.success is False
    assert "network unavailable" in result.error


def test_provider_exception_never_propagates() -> None:
    provider = _FakeProvider(raise_=WebSearchProviderError("timed out"))

    # Must not raise.
    result = ingest_web_search_for_ai(provider, "query")
    assert result.success is False


# --- Budgets: per-result and total ------------------------------------------------


def test_per_result_snippet_truncation_is_deterministic() -> None:
    long_snippet = "x" * 1000
    provider = _FakeProvider(results=[_result(snippet=long_snippet)])

    result = ingest_web_search_for_ai(provider, "query", max_chars_per_result=50)

    text = result.context.text
    assert "x" * 50 in text
    assert "x" * 51 not in text
    assert "truncated" in text.lower()


def test_title_and_url_are_never_truncated() -> None:
    long_title = "T" * 1000
    long_url = "https://example.com/" + "u" * 1000
    provider = _FakeProvider(results=[_result(title=long_title, url=long_url, snippet="short")])

    result = ingest_web_search_for_ai(provider, "query", max_chars_per_result=50)

    text = result.context.text
    assert long_title in text
    assert long_url in text


def test_total_budget_wholly_omits_results_never_partially_reincludes() -> None:
    results = [_result(title=f"T{i}", snippet="y" * 200) for i in range(5)]
    provider = _FakeProvider(results=results)

    result = ingest_web_search_for_ai(
        provider, "query", max_chars_per_result=200, max_total_chars=500
    )

    assert result.success is True
    assert result.included_count < 5
    assert result.omitted_for_size == 5 - result.included_count
    # A later, omitted result's title must not appear at all - never
    # partially included.
    for i in range(result.included_count, 5):
        assert f"T{i}" not in result.context.text


def test_all_results_omitted_for_size_is_a_total_failure() -> None:
    provider = _FakeProvider(results=[_result(snippet="y" * 5000)])

    result = ingest_web_search_for_ai(
        provider, "query", max_chars_per_result=5000, max_total_chars=10
    )

    assert result.success is False
    assert result.omitted_for_size == 1


def test_max_results_is_forwarded_to_provider() -> None:
    provider = _FakeProvider(results=[_result()])

    ingest_web_search_for_ai(provider, "query", max_results=3)

    assert provider.calls[0][1] == 3


def test_default_max_results_is_five() -> None:
    provider = _FakeProvider(results=[_result()])

    ingest_web_search_for_ai(provider, "query")

    assert provider.calls[0][1] == 5


def test_invalid_max_chars_per_result_raises() -> None:
    provider = _FakeProvider(results=[_result()])
    with pytest.raises(ValueError):
        ingest_web_search_for_ai(provider, "query", max_chars_per_result=0)


def test_invalid_max_total_chars_raises() -> None:
    provider = _FakeProvider(results=[_result()])
    with pytest.raises(ValueError):
        ingest_web_search_for_ai(provider, "query", max_total_chars=0)


# --- No duplicate handling / no reordering (explicit, per plan) ------------------


def test_duplicate_results_are_not_deduplicated() -> None:
    """Explicit, deliberate design decision (docs/phase_18_implementation_plan.md,
    Section 5): results are combined in exactly the order and cardinality
    the provider returned, with no deduplication."""
    duplicate = _result(title="Same", url="https://same", snippet="same")
    provider = _FakeProvider(results=[duplicate, duplicate])

    result = ingest_web_search_for_ai(provider, "query")

    assert result.included_count == 2
    assert result.context.text.count("Same") >= 2


# --- Structural: no raw provider dict, no dependency-specific key ---------------


def test_no_raw_dict_or_provider_specific_keys_appear() -> None:
    provider = _FakeProvider(results=[_result(title="T", url="https://x", snippet="s")])

    result = ingest_web_search_for_ai(provider, "query")

    assert isinstance(result.context.text, str)
    for forbidden in ("href", "'body'", "DDGS", "duckduckgo_search"):
        assert forbidden not in result.context.text


def test_module_has_no_dependency_specific_imports() -> None:
    """Structural proof, via real AST import inspection: this module
    imports neither duckduckgo_search nor any dependency-specific name."""
    import ai.web_search_ingestion as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
            if node.module:
                imported_names.add(node.module)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    for forbidden in ("duckduckgo_search", "DDGS", "ddgs"):
        assert forbidden not in imported_names


def test_module_never_imports_tool_executor_or_web_search_tool() -> None:
    import ai.web_search_ingestion as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    for forbidden in ("ToolExecutor", "WebSearchTool", "ToolRegistry"):
        assert forbidden not in imported_names


def test_module_calls_provider_search_only_once_per_invocation() -> None:
    """Structural proof, via real AST call-site inspection (not a naive
    substring search, which would also match this function's own
    docstring prose): no loop or retry could ever call .search() more
    than once per ingest_web_search_for_ai() invocation."""
    import ai.web_search_ingestion as module

    source = inspect.getsource(module.ingest_web_search_for_ai)
    tree = ast.parse(source)
    search_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "search"
    ]
    assert len(search_calls) == 1
