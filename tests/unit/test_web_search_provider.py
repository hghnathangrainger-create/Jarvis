"""
test_web_search_provider.py

Unit tests for the WebSearchProvider abstraction and SearchResult model
(Phase 16, Batch 1: Search Provider Boundary).

These tests exercise only the provider-neutral interface - no concrete
provider, no network call, no dependency-specific behaviour. See
test_duckduckgo_search_provider.py for the concrete adapter's own tests.

Run with:
    pytest tests/unit/test_web_search_provider.py
"""

from __future__ import annotations

import pytest

from tools.web_search_provider import (
    SearchResult,
    WebSearchProvider,
    WebSearchProviderError,
)


# --- SearchResult -------------------------------------------------------------


def test_search_result_holds_title_url_snippet() -> None:
    result = SearchResult(title="A title", url="https://example.com", snippet="A snippet.")
    assert result.title == "A title"
    assert result.url == "https://example.com"
    assert result.snippet == "A snippet."


def test_search_result_is_frozen() -> None:
    result = SearchResult(title="t", url="u", snippet="s")
    with pytest.raises(Exception):
        result.title = "changed"  # type: ignore[misc]


def test_search_result_has_no_extra_fields() -> None:
    """Structural guarantee: SearchResult carries only display data - no
    raw provider dict, no execution-adjacent field of any kind."""
    result = SearchResult(title="t", url="u", snippet="s")
    assert not hasattr(result, "raw")
    assert not hasattr(result, "tool_input")
    assert not hasattr(result, "html")
    assert not hasattr(result, "content")


# --- WebSearchProvider (ABC contract) ------------------------------------------


def test_web_search_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        WebSearchProvider()  # type: ignore[abstract]


def test_a_concrete_subclass_must_implement_search() -> None:
    class _Incomplete(WebSearchProvider):
        pass

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


def test_a_concrete_subclass_implementing_search_can_be_instantiated() -> None:
    class _Fake(WebSearchProvider):
        def search(self, query: str, *, max_results: int) -> list[SearchResult]:
            return []

    provider = _Fake()
    assert provider.search("anything", max_results=5) == []


# --- WebSearchProviderError -----------------------------------------------------


def test_web_search_provider_error_is_a_plain_exception() -> None:
    error = WebSearchProviderError("something went wrong")
    assert isinstance(error, Exception)
    assert str(error) == "something went wrong"


def test_web_search_provider_error_is_the_single_failure_type() -> None:
    """Any concrete provider is expected to translate every one of its own
    failure modes into this one exception type - proven structurally here
    by confirming it is a plain, unparameterised Exception subclass any
    caller can catch with a single except clause."""
    assert issubclass(WebSearchProviderError, Exception)
    assert WebSearchProviderError.__bases__ == (Exception,)
