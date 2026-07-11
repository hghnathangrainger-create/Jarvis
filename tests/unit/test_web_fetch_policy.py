"""
test_web_fetch_policy.py

Unit tests for WebFetchPolicy (Phase 32, Batch 1: Webpage Fetch/Read
Safety Foundation).

Every test here exercises pure, in-process validation only - no
network, no DNS resolution, no mocked transport. These are the tests
Nathan's plan calls "the single most important test file" for this
phase: every scheme/host/IP/credential rule must be proven correct in
isolation before any network layer is built on top of it (Batch 2).

Run with:
    pytest tests/unit/test_web_fetch_policy.py
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from web.fetch_policy import (
    FetchRejectionReason,
    RedirectPolicy,
    RejectedTarget,
    SizeLimitPolicy,
    TimeoutPolicy,
    ValidatedTarget,
    WebFetchPolicy,
)


@pytest.fixture
def policy() -> WebFetchPolicy:
    return WebFetchPolicy()


# ---------------------------------------------------------------------------
# Valid targets
# ---------------------------------------------------------------------------


def test_valid_http_url_is_approved(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://example.com")
    assert isinstance(result, ValidatedTarget)
    assert result.scheme == "http"
    assert result.hostname == "example.com"


def test_valid_https_url_is_approved(policy: WebFetchPolicy) -> None:
    result = policy.validate("https://example.com")
    assert isinstance(result, ValidatedTarget)
    assert result.scheme == "https"
    assert result.hostname == "example.com"


def test_uppercase_scheme_and_host_are_normalized_to_lowercase(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("HTTP://EXAMPLE.COM")
    assert isinstance(result, ValidatedTarget)
    assert result.scheme == "http"
    assert result.hostname == "example.com"


def test_url_with_path_and_query_is_allowed(policy: WebFetchPolicy) -> None:
    result = policy.validate("https://example.com/articles/one?ref=jarvis")
    assert isinstance(result, ValidatedTarget)
    assert result.path == "/articles/one"
    assert result.query == "ref=jarvis"


def test_fragment_is_intentionally_stripped_from_the_validated_target(
    policy: WebFetchPolicy,
) -> None:
    """Fragments are never sent to a server, so they are dropped.

    This is the "clearly tested decision" the phase plan calls for:
    ValidatedTarget has no fragment field at all, so a fragment can
    never leak into anything a future fetch layer sends over the wire.
    """
    result = policy.validate("https://example.com/path?q=1#section")
    assert isinstance(result, ValidatedTarget)
    assert result.path == "/path"
    assert result.query == "q=1"
    assert not hasattr(result, "fragment")


def test_ordinary_domain_hostname_is_approved_without_resolution(
    policy: WebFetchPolicy,
) -> None:
    """A plain domain name is validated by shape only in Batch 1.

    Resolving it to a real IP address happens in Batch 2, immediately
    before the actual connection - this batch performs no DNS lookup
    at all, so an ordinary domain is approved purely on scheme/
    credential/localhost-name shape.
    """
    result = policy.validate("https://a-domain-that-is-never-resolved.example")
    assert isinstance(result, ValidatedTarget)


def test_explicit_normal_port_is_preserved_and_allowed(
    policy: WebFetchPolicy,
) -> None:
    """Port restriction is deferred to a later, explicit allowance.

    Per the Phase 32 plan (Section 7, rule 4), port policy is "not part
    of this phase's default policy" - Batch 1 records the port but does
    not reject non-80/443 ports.
    """
    result = policy.validate("https://example.com:8443/path")
    assert isinstance(result, ValidatedTarget)
    assert result.port == 8443


def test_url_with_no_explicit_port_has_none_port(policy: WebFetchPolicy) -> None:
    result = policy.validate("https://example.com")
    assert isinstance(result, ValidatedTarget)
    assert result.port is None


# ---------------------------------------------------------------------------
# Malformed URLs
# ---------------------------------------------------------------------------


def test_empty_string_is_rejected_as_malformed(policy: WebFetchPolicy) -> None:
    result = policy.validate("")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MALFORMED_URL


def test_whitespace_only_string_is_rejected_as_malformed(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("   ")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MALFORMED_URL


def test_unparseable_ipv6_bracket_url_is_rejected_as_malformed(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("http://[::1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MALFORMED_URL


def test_non_string_input_is_rejected_as_malformed(policy: WebFetchPolicy) -> None:
    result = policy.validate(None)  # type: ignore[arg-type]
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MALFORMED_URL


# ---------------------------------------------------------------------------
# Scheme checks
# ---------------------------------------------------------------------------


def test_missing_scheme_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("example.com/path")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MISSING_SCHEME


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
        "data:text/html;base64,QQ==",
        "javascript:alert(1)",
        "mailto:someone@example.com",
        "about:blank",
        "chrome://settings",
        "ws://example.com/socket",
        "wss://example.com/socket",
        "gopher://example.com",
        "blob:https://example.com/uuid",
    ],
)
def test_unsupported_scheme_is_rejected(policy: WebFetchPolicy, url: str) -> None:
    result = policy.validate(url)
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_SCHEME


# ---------------------------------------------------------------------------
# Hostname checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://", "http:///path"])
def test_missing_hostname_is_rejected(policy: WebFetchPolicy, url: str) -> None:
    result = policy.validate(url)
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.MISSING_HOSTNAME


# ---------------------------------------------------------------------------
# Embedded credentials
# ---------------------------------------------------------------------------


def test_embedded_username_and_password_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://user:pass@example.com")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.EMBEDDED_CREDENTIALS


def test_embedded_token_only_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://token@example.com")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.EMBEDDED_CREDENTIALS


def test_rejected_credentials_detail_never_contains_the_actual_secret(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("http://admin:super-secret-password@example.com")
    assert isinstance(result, RejectedTarget)
    assert "super-secret-password" not in result.detail
    assert "admin" not in result.detail


# ---------------------------------------------------------------------------
# Localhost naming
# ---------------------------------------------------------------------------


def test_localhost_hostname_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://localhost")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.LOCALHOST_HOSTNAME


def test_localhost_with_port_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://localhost:8080/admin")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.LOCALHOST_HOSTNAME


def test_uppercase_localhost_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://LOCALHOST")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.LOCALHOST_HOSTNAME


# ---------------------------------------------------------------------------
# IPv4 literal blocking
# ---------------------------------------------------------------------------


def test_ipv4_loopback_127_0_0_1_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://127.0.0.1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv4_unspecified_0_0_0_0_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://0.0.0.0")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv4_private_10_range_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://10.0.0.1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv4_private_172_16_range_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://172.16.0.1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv4_private_192_168_range_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://192.168.0.1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv4_cloud_metadata_address_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://169.254.169.254")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_another_ipv4_link_local_address_is_rejected(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("http://169.254.1.1")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


# ---------------------------------------------------------------------------
# IPv6 literal blocking
# ---------------------------------------------------------------------------


def test_ipv6_loopback_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://[::1]")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv6_link_local_is_rejected(policy: WebFetchPolicy) -> None:
    result = policy.validate("http://[fe80::1]")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv6_unique_local_private_address_is_rejected(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("http://[fc00::1]")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv6_unique_local_fd_prefix_is_also_rejected(
    policy: WebFetchPolicy,
) -> None:
    result = policy.validate("http://[fd12:3456:789a::1]")
    assert isinstance(result, RejectedTarget)
    assert result.reason == FetchRejectionReason.DISALLOWED_IP_LITERAL


def test_ipv6_global_looking_address_is_approved(policy: WebFetchPolicy) -> None:
    """A public-range IPv6 literal is not blocked by this batch's rules.

    Confirms the IP-range check is precise (blocking only the named
    ranges), not an overbroad "reject all IP literals" shortcut.
    """
    result = policy.validate("http://[2001:4860:4860::8888]")
    assert isinstance(result, ValidatedTarget)


# ---------------------------------------------------------------------------
# Future-batch policy value objects
# ---------------------------------------------------------------------------


def test_redirect_policy_has_a_small_positive_default_hop_cap() -> None:
    redirect_policy = RedirectPolicy()
    assert redirect_policy.max_hops == 3


def test_timeout_policy_has_a_conservative_positive_default() -> None:
    timeout_policy = TimeoutPolicy()
    assert timeout_policy.total_seconds > 0
    assert timeout_policy.total_seconds <= 30


def test_size_limit_policy_has_a_positive_default_cap() -> None:
    size_limit_policy = SizeLimitPolicy()
    assert size_limit_policy.max_bytes > 0


def test_web_fetch_policy_accepts_and_stores_the_future_batch_policies() -> None:
    custom_redirects = RedirectPolicy(max_hops=1)
    custom_timeout = TimeoutPolicy(total_seconds=5.0)
    custom_size_limit = SizeLimitPolicy(max_bytes=1_000)

    policy = WebFetchPolicy(
        redirect_policy=custom_redirects,
        timeout_policy=custom_timeout,
        size_limit_policy=custom_size_limit,
    )

    assert policy.redirect_policy is custom_redirects
    assert policy.timeout_policy is custom_timeout
    assert policy.size_limit_policy is custom_size_limit


def test_web_fetch_policy_defaults_when_no_policies_given() -> None:
    policy = WebFetchPolicy()
    assert policy.redirect_policy == RedirectPolicy()
    assert policy.timeout_policy == TimeoutPolicy()
    assert policy.size_limit_policy == SizeLimitPolicy()


# ---------------------------------------------------------------------------
# Adversarial sweep (Batch 1 scope only - no network, no redirects yet)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(document.cookie)",
        "http://localhost/admin",
        "http://127.0.0.1:8080/internal",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/admin",
        "http://admin:password@10.0.0.1/",
    ],
)
def test_adversarial_targets_are_all_cleanly_rejected(
    policy: WebFetchPolicy, url: str
) -> None:
    """Every classic SSRF/scheme-confusion shape is a clean rejection.

    None of these raise an exception - every failure mode is data (a
    RejectedTarget), matching the phase plan's error-handling policy.
    """
    result = policy.validate(url)
    assert isinstance(result, RejectedTarget)


# ---------------------------------------------------------------------------
# Structural proofs: no network I/O anywhere in this module
# ---------------------------------------------------------------------------


def test_fetch_policy_module_imports_no_networking_library() -> None:
    """AST-based proof that fetch_policy.py performs no network I/O.

    Mirrors ConfigTool's own structural test convention (Phase 31):
    prove the absence of a capability by inspecting the module's own
    import statements, rather than trusting a docstring's claim.
    """
    source = Path("web/fetch_policy.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    forbidden = {"socket", "httpx", "requests", "urllib3", "http", "ssl"}
    assert not (imported_names & forbidden), imported_names
