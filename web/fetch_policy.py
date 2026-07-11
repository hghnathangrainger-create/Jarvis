"""
fetch_policy.py

Pure, deterministic webpage-fetch target validation policy (Phase 32,
Batch 1: Webpage Fetch/Read Safety Foundation).

Responsibilities:
    - Define WebFetchPolicy.validate(url), which decides whether a URL
      is an allowed fetch target by scheme, hostname shape, embedded
      credentials, localhost naming, and - for IP-literal hosts only -
      private/loopback/link-local/multicast/reserved address ranges.
    - Define ValidatedTarget/RejectedTarget, the two possible outcomes
      of validation, and FetchRejectionReason, a small fixed set of
      reason codes suitable for tests and future audit logging.
    - Define RedirectPolicy, TimeoutPolicy, and SizeLimitPolicy: fixed,
      documented value objects that a future fetch layer (Batch 2) will
      consult. They are declared now, with real default values, so this
      module's shape does not need to change later - but nothing in
      this batch enforces them, since nothing in this batch performs a
      fetch.

Does NOT:
    - Perform any network I/O at all: no sockets, no DNS resolution, no
      HTTP requests. This module is pure and fully unit-testable
      without a network or even a mocked transport.
    - Resolve hostnames to IP addresses. A domain name (e.g.
      "example.com") is validated only for scheme/credential/localhost-
      name shape here. Resolving it to a real IP address and validating
      *that* address happens in Batch 2 (SafeWebFetcher), immediately
      before each actual connection - this is what defeats DNS
      rebinding (see docs/phase_32_implementation_plan.md, Section 8).
      Only IP-literal hosts (e.g. "http://127.0.0.1/") are checked
      against the private/reserved-range rules in this batch, since
      that check requires no resolution at all.
    - Follow redirects, enforce timeouts, enforce size limits, decode
      or extract any content - all Batch 2/3 work.
    - Register a tool, register a command, or integrate with AI,
      workflow, dashboard, or scheduler in any way.

This is Batch 1 of a very-risky, planning-plus-3-batch phase. Nothing
in the running system calls this module yet.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

#: Allow-list, not a block-list: an unrecognised future scheme is
#: rejected by default, never accidentally permitted.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Hostnames that refer to the local machine by name rather than by IP
#: literal. IP-literal loopback addresses (127.0.0.1, ::1) are caught
#: separately by the IP-range check below.
_LOCALHOST_HOSTNAMES = frozenset({"localhost"})


class FetchRejectionReason(str, Enum):
    """Fixed, stable reason codes for a rejected fetch target.

    A str Enum so values compare equal to plain strings (useful for
    tests and future audit-log serialisation) while remaining a closed,
    documented set - not a printf-style ad hoc message.
    """

    MALFORMED_URL = "malformed_url"
    MISSING_SCHEME = "missing_scheme"
    DISALLOWED_SCHEME = "disallowed_scheme"
    MISSING_HOSTNAME = "missing_hostname"
    EMBEDDED_CREDENTIALS = "embedded_credentials"
    LOCALHOST_HOSTNAME = "localhost_hostname"
    DISALLOWED_IP_LITERAL = "disallowed_ip_literal"


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    """A URL that has passed every Batch 1 syntactic validation check.

    This does NOT mean the URL is safe to fetch: a hostname (as opposed
    to an IP literal) has not yet been resolved, and the resolved-IP
    check - the single most important SSRF/DNS-rebinding defence -
    happens in Batch 2, immediately before the actual connection.

    The URL fragment (the "#section" part, if any) is intentionally
    discarded and has no field here: fragments are a client-side-only
    concept and are never transmitted to a server as part of an HTTP
    request, so they carry no meaning for a fetch target.

    Attributes:
        original_url: The exact URL string that was validated (as
            given, including any fragment - this is the input record,
            not the fetchable target shape).
        scheme: The lowercased scheme ("http" or "https").
        hostname: The lowercased hostname, with no credentials or port.
        port: The explicit port if present in the URL, else None.
        path: The URL's path component (empty string if none).
        query: The URL's query component (empty string if none).
    """

    original_url: str
    scheme: str
    hostname: str
    port: int | None
    path: str
    query: str


@dataclass(frozen=True, slots=True)
class RejectedTarget:
    """A URL that failed one or more Batch 1 validation checks.

    Attributes:
        original_url: The exact URL string that was rejected.
        reason: The FetchRejectionReason identifying which check failed.
        detail: A short, human-readable explanation, safe to display or
            log. Never includes credentials, even when the rejection
            reason is embedded credentials - the detail describes the
            problem, never the secret value itself.
    """

    original_url: str
    reason: FetchRejectionReason
    detail: str


@dataclass(frozen=True, slots=True)
class RedirectPolicy:
    """Fixed redirect-handling values for the future fetch layer (Batch 2).

    Not enforced by anything in Batch 1 - declared now so later batches
    do not need to change this module's shape. Redirects must be
    followed manually, one hop at a time, with this same validation
    policy re-applied to every hop's target - never delegated to an
    HTTP client's own automatic redirect-following.

    Attributes:
        max_hops: The maximum number of redirect hops to follow before
            failing cleanly.
    """

    max_hops: int = 3


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Fixed timeout values for the future fetch layer (Batch 2).

    Not enforced by anything in Batch 1. A single total timeout
    (connect + read combined), not two separately generous budgets that
    could sum to something large.

    Attributes:
        total_seconds: The total request timeout in seconds.
    """

    total_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class SizeLimitPolicy:
    """Fixed response-size values for the future fetch layer (Batch 2).

    Not enforced by anything in Batch 1. Must be enforced while
    streaming, closing the connection the moment the cap would be
    exceeded - never after buffering a full oversized body first.

    Attributes:
        max_bytes: The maximum number of response bytes to accept.
    """

    max_bytes: int = 5_000_000


class WebFetchPolicy:
    """Pure, deterministic decision of whether a URL is a fetchable target.

    No network I/O. Hostnames that are not IP literals are validated by
    shape only (scheme, credentials, localhost naming) - see the module
    docstring for what resolved-IP validation (Batch 2) adds on top of
    this.
    """

    def __init__(
        self,
        *,
        redirect_policy: RedirectPolicy | None = None,
        timeout_policy: TimeoutPolicy | None = None,
        size_limit_policy: SizeLimitPolicy | None = None,
    ) -> None:
        """Construct a policy, optionally overriding the future-batch defaults.

        Args:
            redirect_policy: Redirect-handling values for a future fetch
                layer. Defaults to RedirectPolicy() if not given.
            timeout_policy: Timeout values for a future fetch layer.
                Defaults to TimeoutPolicy() if not given.
            size_limit_policy: Response-size values for a future fetch
                layer. Defaults to SizeLimitPolicy() if not given.
        """
        self.redirect_policy = redirect_policy or RedirectPolicy()
        self.timeout_policy = timeout_policy or TimeoutPolicy()
        self.size_limit_policy = size_limit_policy or SizeLimitPolicy()

    def validate(self, url: str) -> ValidatedTarget | RejectedTarget:
        """Validate a URL against every Batch 1 syntactic safety rule.

        Checked in order, each a hard failure: well-formed URL, allowed
        scheme, non-empty hostname, no embedded credentials, not a
        localhost name, and - only for IP-literal hosts - not a
        private/loopback/link-local/multicast/reserved/unspecified
        address.

        Args:
            url: The URL string to validate.

        Returns:
            A ValidatedTarget if every check passes, otherwise a
            RejectedTarget naming the first check that failed.
        """
        if not isinstance(url, str) or not url.strip():
            return RejectedTarget(
                original_url=url if isinstance(url, str) else "",
                reason=FetchRejectionReason.MALFORMED_URL,
                detail="URL must be a non-empty string.",
            )

        candidate = url.strip()

        try:
            parts = urlsplit(candidate)
            scheme = parts.scheme.lower()
            username = parts.username
            password = parts.password
            hostname = parts.hostname
            port = parts.port
        except ValueError as exc:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.MALFORMED_URL,
                detail=f"URL could not be parsed: {exc}",
            )

        if not scheme:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.MISSING_SCHEME,
                detail="URL has no scheme (expected 'http' or 'https').",
            )

        if scheme not in _ALLOWED_SCHEMES:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.DISALLOWED_SCHEME,
                detail=(
                    f"Scheme '{scheme}' is not allowed; only 'http' and "
                    "'https' are permitted."
                ),
            )

        if username is not None or password is not None:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.EMBEDDED_CREDENTIALS,
                detail=(
                    "URL must not contain embedded credentials (e.g. "
                    "'user:pass@host' or 'token@host')."
                ),
            )

        if not hostname:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.MISSING_HOSTNAME,
                detail="URL has no hostname.",
            )

        hostname = hostname.lower()

        if hostname in _LOCALHOST_HOSTNAMES:
            return RejectedTarget(
                original_url=candidate,
                reason=FetchRejectionReason.LOCALHOST_HOSTNAME,
                detail=(
                    f"Hostname '{hostname}' refers to the local machine "
                    "and is not allowed."
                ),
            )

        ip_literal = _parse_ip_literal(hostname)
        if ip_literal is not None:
            blocked_reason = _blocked_ip_reason(ip_literal)
            if blocked_reason is not None:
                return RejectedTarget(
                    original_url=candidate,
                    reason=FetchRejectionReason.DISALLOWED_IP_LITERAL,
                    detail=(
                        f"IP address '{hostname}' is {blocked_reason} and "
                        "is not allowed."
                    ),
                )

        return ValidatedTarget(
            original_url=candidate,
            scheme=scheme,
            hostname=hostname,
            port=port,
            path=parts.path,
            query=parts.query,
        )


def _parse_ip_literal(
    hostname: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a hostname as an IP literal, without any DNS resolution.

    Args:
        hostname: The lowercased hostname component from the URL.

    Returns:
        The parsed IPv4Address/IPv6Address if the hostname is an IP
        literal, otherwise None (meaning it is an ordinary domain name,
        which this batch does not resolve or otherwise validate).
    """
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _blocked_ip_reason(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str | None:
    """Decide whether a resolved-or-literal IP address must be blocked.

    Uses the standard library's own ipaddress predicates directly
    rather than hand-rolled CIDR math, per the Phase 32 plan's explicit
    Batch 1 risk mitigation.

    Args:
        ip: The IP address to check.

    Returns:
        A short human-readable reason string if the address is blocked,
        otherwise None.
    """
    if ip.is_unspecified:
        return "an unspecified address"
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address"
    if ip.is_multicast:
        return "a multicast address"
    if ip.is_private:
        return "a private-range address"
    if ip.is_reserved:
        return "a reserved address"
    return None
