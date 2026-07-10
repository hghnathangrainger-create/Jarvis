"""
test_duckduckgo_search_provider.py

Unit tests for DuckDuckGoSearchProvider (Phase 16, Batch 1: Search
Provider Boundary).

No test in this file makes a real network call. A fake, injected
DDGS-shaped stub stands in for the real duckduckgo_search.DDGS client,
exactly matching the "every test uses a fake provider" discipline already
established for ClaudeProvider (see test_main_ai_wiring.py).

Run with:
    pytest tests/unit/test_duckduckgo_search_provider.py
"""

from __future__ import annotations

import pytest
from duckduckgo_search.exceptions import (
    DuckDuckGoSearchException,
    RatelimitException,
    TimeoutException,
)

import tools.duckduckgo_search_provider as module
from tools.duckduckgo_search_provider import DuckDuckGoSearchProvider
from tools.web_search_provider import SearchResult, WebSearchProviderError


class _FakeDDGS:
    """A fake stand-in for duckduckgo_search.DDGS.

    Records the constructor's timeout and every call's query/max_results,
    and returns (or raises) whatever the test configured - never touches
    the real network.
    """

    last_instance: "_FakeDDGS | None" = None

    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout
        self.calls: list[tuple[str, int]] = []
        self._results: list[dict[str, str]] | None = None
        self._raise: Exception | None = None
        _FakeDDGS.last_instance = self

    def configure(
        self,
        *,
        results: list[dict[str, str]] | None = None,
        raise_: Exception | None = None,
    ) -> None:
        self._results = results
        self._raise = raise_

    def text(self, keywords: str, max_results: int | None = None) -> list[dict[str, str]]:
        self.calls.append((keywords, max_results))
        if self._raise is not None:
            raise self._raise
        return self._results if self._results is not None else []


@pytest.fixture()
def fake_ddgs(monkeypatch: pytest.MonkeyPatch) -> type[_FakeDDGS]:
    monkeypatch.setattr(module, "DDGS", _FakeDDGS)
    return _FakeDDGS


# --- Successful mapping ---------------------------------------------------------


def test_search_maps_all_three_verified_keys(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(
        results=[{"title": "A Title", "href": "https://example.com/a", "body": "A snippet."}]
    )

    results = provider.search("jarvis ai", max_results=5)

    assert results == [
        SearchResult(title="A Title", url="https://example.com/a", snippet="A snippet.")
    ]


def test_search_returns_multiple_results_in_order(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(
        results=[
            {"title": "First", "href": "https://a", "body": "one"},
            {"title": "Second", "href": "https://b", "body": "two"},
        ]
    )

    results = provider.search("query", max_results=5)

    assert [r.title for r in results] == ["First", "Second"]


def test_search_passes_query_and_max_results_through(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(results=[])

    provider.search("distinctive query text", max_results=7)

    assert _FakeDDGS.last_instance.calls == [("distinctive query text", 7)]


def test_constructor_passes_explicit_timeout_through(fake_ddgs: type[_FakeDDGS]) -> None:
    DuckDuckGoSearchProvider(timeout=3)
    assert _FakeDDGS.last_instance.timeout == 3


def test_constructor_default_timeout_is_ten_seconds(fake_ddgs: type[_FakeDDGS]) -> None:
    DuckDuckGoSearchProvider()
    assert _FakeDDGS.last_instance.timeout == 10


# --- Zero results ---------------------------------------------------------------


def test_zero_results_returns_empty_list_not_an_error(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(results=[])

    assert provider.search("nothing found for this", max_results=5) == []


# --- Malformed individual results ------------------------------------------------


def test_malformed_result_missing_a_key_is_skipped(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(
        results=[
            {"title": "Good", "href": "https://good", "body": "fine"},
            {"title": "Missing body", "href": "https://bad"},
        ]
    )

    results = provider.search("query", max_results=5)

    assert len(results) == 1
    assert results[0].title == "Good"


def test_malformed_result_with_non_string_value_is_skipped(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(
        results=[
            {"title": "Good", "href": "https://good", "body": "fine"},
            {"title": None, "href": "https://bad", "body": "bad"},
        ]
    )

    results = provider.search("query", max_results=5)

    assert len(results) == 1
    assert results[0].title == "Good"


def test_non_dict_result_entry_is_skipped(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(results=[{"title": "Good", "href": "https://good", "body": "fine"}])
    # Simulate a provider returning something unexpected mixed into the list.
    _FakeDDGS.last_instance._results.append("not a dict")  # type: ignore[union-attr]

    results = provider.search("query", max_results=5)

    assert len(results) == 1


def test_all_malformed_results_yields_empty_list_not_an_error(
    fake_ddgs: type[_FakeDDGS],
) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(results=[{"title": "only title"}])

    assert provider.search("query", max_results=5) == []


# --- Exception translation -------------------------------------------------------


def test_duckduckgo_search_exception_becomes_provider_error(
    fake_ddgs: type[_FakeDDGS],
) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(raise_=DuckDuckGoSearchException("boom"))

    with pytest.raises(WebSearchProviderError):
        provider.search("query", max_results=5)


def test_ratelimit_exception_becomes_provider_error(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(raise_=RatelimitException("too many requests"))

    with pytest.raises(WebSearchProviderError):
        provider.search("query", max_results=5)


def test_timeout_exception_becomes_provider_error(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(raise_=TimeoutException("timed out"))

    with pytest.raises(WebSearchProviderError):
        provider.search("query", max_results=5)


def test_unexpected_exception_also_becomes_provider_error(
    fake_ddgs: type[_FakeDDGS],
) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(raise_=ValueError("something else broke"))

    with pytest.raises(WebSearchProviderError):
        provider.search("query", max_results=5)


def test_provider_error_never_leaks_the_original_exception_type(
    fake_ddgs: type[_FakeDDGS],
) -> None:
    """Callers only ever need to catch one exception type."""
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(raise_=RatelimitException("too many requests"))

    try:
        provider.search("query", max_results=5)
        pytest.fail("expected WebSearchProviderError")
    except WebSearchProviderError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"leaked raw provider exception type: {type(exc)}")


# --- No raw provider dict escapes ------------------------------------------------


def test_no_raw_dict_appears_in_results(fake_ddgs: type[_FakeDDGS]) -> None:
    provider = DuckDuckGoSearchProvider()
    _FakeDDGS.last_instance.configure(
        results=[{"title": "T", "href": "https://x", "body": "s"}]
    )

    results = provider.search("query", max_results=5)

    for result in results:
        assert isinstance(result, SearchResult)
        assert not isinstance(result, dict)
