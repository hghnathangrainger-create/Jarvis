"""
test_safe_web_fetcher.py

Unit tests for SafeWebFetcher (Phase 32, Batch 2: Webpage Fetch/Read
Safety Foundation).

Every test uses httpx.MockTransport and an injected DNS resolver - no
real network call and no real DNS lookup is ever made, matching this
project's established discipline of never depending on a real external
service in tests (WebSearchProvider's own tests likewise never hit the
real DuckDuckGo API).

Run with:
    pytest tests/unit/test_safe_web_fetcher.py
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path
from typing import Callable

import httpx
import pytest

from web.fetch_policy import RedirectPolicy, SizeLimitPolicy, TimeoutPolicy, WebFetchPolicy
from web.safe_web_fetcher import (
    SafeWebFetcher,
    WebFetchFailure,
    WebFetchFailureReason,
    WebFetchSuccess,
)

_PUBLIC_IP = "93.184.216.34"


def _resolver_for(mapping: dict[str, list[str]]) -> Callable[[str], list[str]]:
    """Build a fake resolver from a hostname -> [ip, ...] mapping."""

    def resolver(hostname: str) -> list[str]:
        if hostname not in mapping:
            raise OSError(f"simulated resolution failure for '{hostname}'")
        return mapping[hostname]

    return resolver


def _html_response(body: bytes = b"<html><body>hi</body></html>") -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/html; charset=utf-8"}, content=body
    )


# ---------------------------------------------------------------------------
# Policy rejection never reaches the network
# ---------------------------------------------------------------------------


def test_rejected_url_never_triggers_a_network_call() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _html_response()

    fetcher = SafeWebFetcher(transport=httpx.MockTransport(handler))
    result = fetcher.fetch("http://localhost/admin")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.REJECTED_BY_POLICY
    assert calls == []


# ---------------------------------------------------------------------------
# A valid URL performs exactly one controlled GET
# ---------------------------------------------------------------------------


def test_valid_url_triggers_exactly_one_get_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _html_response()

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/article")

    assert isinstance(result, WebFetchSuccess)
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert result.page.status_code == 200
    assert result.page.content_type == "text/html"
    assert result.page.charset == "utf-8"


def test_connection_is_pinned_to_the_resolved_ip_not_the_hostname() -> None:
    """The single most important design point in this batch.

    Proves the outgoing request's actual connection target (url.host)
    is the DNS-resolved, already-validated IP address - never the
    original hostname string - while the Host header and TLS SNI
    extension still carry the real hostname, so certificate
    verification (in real TLS, not exercised by this mocked test)
    still checks the correct name.
    """
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        captured["header_host"] = request.headers.get("host")
        captured["sni_hostname"] = request.extensions.get("sni_hostname")
        return _html_response()

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchSuccess)
    assert captured["host"] == _PUBLIC_IP
    assert captured["header_host"] == "example.com"
    assert captured["sni_hostname"] == "example.com"


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------


def test_timeout_configuration_from_policy_is_applied() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions.get("timeout")
        return _html_response()

    policy = WebFetchPolicy(timeout_policy=TimeoutPolicy(total_seconds=2.5))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    fetcher.fetch("https://example.com/")

    assert captured["timeout"] == {
        "connect": 2.5,
        "read": 2.5,
        "write": 2.5,
        "pool": 2.5,
    }


# ---------------------------------------------------------------------------
# Size limit enforcement
# ---------------------------------------------------------------------------


def test_oversized_response_fails_safely_while_streaming() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _html_response(body=b"x" * 1_000)

    policy = WebFetchPolicy(size_limit_policy=SizeLimitPolicy(max_bytes=10))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.OVERSIZED_RESPONSE


def test_declared_content_length_over_cap_is_rejected_before_reading_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "999999"},
            content=b"small body, lying content-length header",
        )

    policy = WebFetchPolicy(size_limit_policy=SizeLimitPolicy(max_bytes=100))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.OVERSIZED_RESPONSE
    assert "Content-Length" in result.detail


def test_response_within_size_limit_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _html_response(body=b"short body")

    policy = WebFetchPolicy(size_limit_policy=SizeLimitPolicy(max_bytes=1_000))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchSuccess)
    assert result.page.byte_count == len(b"short body")


# ---------------------------------------------------------------------------
# Content-Type gating
# ---------------------------------------------------------------------------


def test_acceptable_content_type_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"plain text"
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchSuccess)
    assert result.page.content_type == "text/plain"


def test_missing_content_type_is_an_explicit_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"no content-type header at all")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.MISSING_CONTENT_TYPE


@pytest.mark.parametrize(
    "content_type",
    [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "video/mp4",
        "audio/mpeg",
        "application/octet-stream",
        "application/zip",
        "application/x-msdownload",
        "application/json",
    ],
)
def test_disallowed_content_types_are_rejected(content_type: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": content_type}, content=b"binary-ish"
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.DISALLOWED_CONTENT_TYPE


# ---------------------------------------------------------------------------
# Redirect handling
# ---------------------------------------------------------------------------


def test_redirect_following_is_disabled_on_the_underlying_client() -> None:
    """Confirms the raw httpx.Client never auto-follows a redirect.

    If this were True, a redirect target would reach the real
    connection layer before this module's own policy re-validation
    ever saw it - the exact bypass the manual redirect loop exists to
    prevent.
    """
    fetcher = SafeWebFetcher()
    assert fetcher._client.follow_redirects is False


def test_manual_redirect_within_limit_succeeds_when_every_hop_validates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        if host == "start.example":
            return httpx.Response(
                302, headers={"location": "https://final.example/landing"}
            )
        if host == "final.example":
            return _html_response(body=b"final page content")
        raise AssertionError(f"unexpected host: {host}")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for(
            {"start.example": [_PUBLIC_IP], "final.example": ["93.184.216.35"]}
        ),
    )
    result = fetcher.fetch("https://start.example/")

    assert isinstance(result, WebFetchSuccess)
    assert result.page.body == b"final page content"


def test_redirect_limit_exceeded_fails_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "https://loop.example/next"}
        )

    policy = WebFetchPolicy(redirect_policy=RedirectPolicy(max_hops=2))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"loop.example": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://loop.example/start")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.TOO_MANY_REDIRECTS


@pytest.mark.parametrize(
    "redirect_target",
    [
        "http://localhost/admin",
        "http://127.0.0.1/internal",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/file",
        "http://user:pass@example.com/",
        "javascript:alert(1)",
    ],
)
def test_redirect_to_a_rejected_target_is_refused(redirect_target: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": redirect_target})

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"start.example": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://start.example/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.REDIRECT_TARGET_REJECTED


def test_redirect_to_private_ip_literal_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://10.0.0.5/"})

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"start.example": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://start.example/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.REDIRECT_TARGET_REJECTED


# ---------------------------------------------------------------------------
# Network/HTTP error handling
# ---------------------------------------------------------------------------


def test_connection_error_returns_structured_failure_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused", request=request)

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.CONNECTION_ERROR


def test_unexpected_non_httpx_exception_returns_structured_failure_not_a_crash() -> None:
    """Even a bug-like, non-httpx exception must never escape fetch().

    Proves the last-resort safety net: every failure mode is data, per
    the Phase 32 plan's error-handling policy, not only the httpx-
    specific exception types anticipated above.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("simulated unexpected bug")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.UNEXPECTED_ERROR


def test_timeout_exception_returns_structured_failure_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.TIMEOUT


@pytest.mark.parametrize("status_code", [404, 403, 500, 503])
def test_http_4xx_5xx_status_is_an_explicit_failure(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers={"content-type": "text/html"})

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.HTTP_ERROR
    assert str(status_code) in result.detail


# ---------------------------------------------------------------------------
# DNS / resolved-IP protection
# ---------------------------------------------------------------------------


def test_hostname_resolving_to_public_ip_is_allowed() -> None:
    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(lambda r: _html_response()),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")
    assert isinstance(result, WebFetchSuccess)


@pytest.mark.parametrize(
    "resolved_ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_hostname_resolving_to_a_blocked_ip_is_rejected(resolved_ip: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _html_response()

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"evil.example": [resolved_ip]}),
    )
    result = fetcher.fetch("https://evil.example/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.DNS_RESOLVED_BLOCKED_IP
    assert calls == [], "a blocked resolved IP must never reach the network"


def test_any_blocked_address_among_multiple_resolved_addresses_fails_closed() -> None:
    """DNS returning one safe and one unsafe address is a full rejection.

    A real client can't guarantee which of several returned addresses
    it will actually connect to - refusing whenever any candidate is
    unsafe is the only fail-closed choice.
    """
    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(lambda r: _html_response()),
        resolver=_resolver_for({"mixed.example": [_PUBLIC_IP, "127.0.0.1"]}),
    )
    result = fetcher.fetch("https://mixed.example/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.DNS_RESOLVED_BLOCKED_IP


def test_dns_resolution_failure_returns_structured_failure() -> None:
    def resolver(hostname: str) -> list[str]:
        raise socket.gaierror("simulated: name or service not known")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(lambda r: _html_response()),
        resolver=resolver,
    )
    result = fetcher.fetch("https://nowhere.example/")

    assert isinstance(result, WebFetchFailure)
    assert result.reason == WebFetchFailureReason.DNS_RESOLUTION_FAILED


# ---------------------------------------------------------------------------
# No disk writes; no forbidden module coupling
# ---------------------------------------------------------------------------


def test_fetching_never_writes_any_file_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(lambda r: _html_response()),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = fetcher.fetch("https://example.com/")

    assert isinstance(result, WebFetchSuccess)
    assert list(tmp_path.iterdir()) == []


def test_safe_web_fetcher_module_imports_no_forbidden_packages() -> None:
    """AST-based proof: no AI/workflow/scheduler/dashboard/tool coupling.

    Mirrors the same structural-proof convention used for ConfigTool
    (Phase 31) and WebFetchPolicy (Phase 32 Batch 1).
    """
    source = Path("web/safe_web_fetcher.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    forbidden = {"ai", "workflow", "scheduler", "dashboard", "tools", "core", "requests"}
    assert not (imported_names & forbidden), imported_names


def test_safe_web_fetcher_module_never_calls_open() -> None:
    """AST-based proof that this module never opens a local file."""
    source = Path("web/safe_web_fetcher.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", "SafeWebFetcher must never open a file"


def test_safe_web_fetcher_uses_only_httpx_for_networking() -> None:
    """The only networking import beyond the standard library is httpx."""
    source = Path("web/safe_web_fetcher.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    assert "requests" not in imported_names
    assert "urllib3" not in imported_names
    assert "httpx" in imported_names
