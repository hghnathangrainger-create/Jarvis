"""
safe_web_fetcher.py

The low-level, network-capable webpage fetch service (Phase 32, Batch 2:
Webpage Fetch/Read Safety Foundation).

Responsibilities:
    - Define SafeWebFetcher, the one place an HTTP request is actually
      made. Every fetch is validated by WebFetchPolicy (Batch 1) before
      any network access, and every DNS-resolved IP address is
      validated again, immediately before the actual connection.
    - Define WebFetchSuccess/WebFetchFailure/FetchedPage/
      WebFetchFailureReason: the only shapes a caller ever sees. A raw
      httpx.Response, exception, or resolved socket address never
      escapes this module.
    - Isolate the one new runtime dependency, httpx, to exactly this
      module - mirroring tools/duckduckgo_search_provider.py's own
      "only module permitted to import the vendor package" discipline.

Does NOT:
    - Register a tool, a CommandRouter command, or a SecurityManager
      rule.
    - Integrate with AI, workflow, scheduler, dashboard, or Inbox.
    - Summarise, extract, or clean fetched text (see Batch 3).
    - Write fetched content to a file or the database.
    - Perform more than one logical fetch per call, or anything beyond
      a single GET request per (re-)validated target.

Connect-time DNS-rebinding defence (the hardest problem in this batch):
    A hostname is resolved to its candidate IP address(es) with
    socket.getaddrinfo() (or an injected resolver, for tests). Every
    resolved address is checked with the exact same
    web.fetch_policy.blocked_ip_reason() predicate Batch 1 already uses
    for IP literals typed directly into a URL - if ANY resolved address
    is private/loopback/link-local/multicast/reserved/unspecified, the
    entire request is refused, even if another resolved address would
    have been safe (fail closed, not "pick the safe one and hope").

    If every resolved address passes, the connection is then pinned:
    the actual TCP/TLS connection target is httpx's URL rewritten to
    the first resolved address, with the original hostname preserved as
    the Host header and (for https) as the "sni_hostname" transport
    extension, which httpx/httpcore use as the TLS server_hostname for
    both SNI and certificate hostname verification
    (httpcore._sync.connection.HTTPConnection._connect reads this
    extension directly). Because the connection itself is opened
    against the IP address already validated - not against the
    hostname string - there is no window between "resolve" and
    "connect" in which a second, different DNS answer (a rebinding
    attack) could substitute an unsafe address: httpx/httpcore never
    re-resolves a literal IP address. This is the standard "resolve
    once, pin the connection, keep hostname for TLS" mitigation and is
    fully exercised by this module's own tests via httpx.MockTransport,
    which captures the exact URL/headers/extensions that would be
    handed to the real connection layer - so the pinning behaviour
    itself is proven without a real network call.

    Residual, disclosed limitation: this defends the connection this
    module opens. It does not, and cannot, control any DNS caching or
    connection reuse inside the underlying OS resolver or connection
    pool across *separate* SafeWebFetcher calls; each call performs its
    own fresh resolve-validate-pin sequence, which is the granularity
    at which this defence is meaningful for a "fetch this URL" service.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import urljoin

import httpx

from web.fetch_policy import (
    RejectedTarget,
    ValidatedTarget,
    WebFetchPolicy,
    blocked_ip_reason,
    parse_ip_literal,
)

#: Allowed Content-Type values (the "type/subtype" portion only, any
#: "; charset=..." parameter is stripped before comparison). Allow-list,
#: not a block-list - an unrecognised or missing type is a rejection.
_ALLOWED_CONTENT_TYPES = frozenset(
    {"text/html", "text/plain", "application/xhtml+xml"}
)

#: Read the response body in bounded chunks rather than loading it into
#: memory in one call, mirroring FileCopyTool's own _CHUNK_SIZE
#: discipline.
_CHUNK_SIZE = 65_536

#: A byte string identifying this fetcher to servers. Deliberately
#: distinct from httpx's own default so a fetch attempt is identifiable
#: in third-party server logs as coming from Jarvis, not a generic
#: script.
_USER_AGENT = "Jarvis-SafeWebFetcher/1 (+https://github.com)"

#: A hostname resolver: given a hostname (or IP literal), return its
#: candidate IP address strings. Injectable so tests never perform a
#: real DNS lookup - see _default_resolver for the real implementation.
_Resolver = Callable[[str], list[str]]


class WebFetchFailureReason(str, Enum):
    """Fixed, stable reason codes for a failed fetch attempt.

    A str Enum so values compare equal to plain strings (useful for
    tests and future audit-log serialisation), mirroring
    web.fetch_policy.FetchRejectionReason's own convention.
    """

    REJECTED_BY_POLICY = "rejected_by_policy"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    DNS_RESOLVED_BLOCKED_IP = "dns_resolved_blocked_ip"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    OVERSIZED_RESPONSE = "oversized_response"
    MISSING_CONTENT_TYPE = "missing_content_type"
    DISALLOWED_CONTENT_TYPE = "disallowed_content_type"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    REDIRECT_TARGET_REJECTED = "redirect_target_rejected"
    HTTP_ERROR = "http_error"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """A successfully fetched webpage's safe, bounded content.

    Attributes:
        url: The final URL the content was fetched from (after any
            validated redirects - the original request URL if none).
        status_code: The HTTP status code (always 2xx; other statuses
            produce a WebFetchFailure instead, never a FetchedPage).
        content_type: The response's Content-Type value, without any
            "; charset=..." parameter (e.g. "text/html").
        charset: The charset parameter from Content-Type, lowercased,
            or None if not declared.
        body: The raw response bytes, always at or under
            WebFetchPolicy.size_limit_policy.max_bytes.
        byte_count: len(body), provided directly for convenient audit
            logging without re-measuring the body.
    """

    url: str
    status_code: int
    content_type: str
    charset: str | None
    body: bytes
    byte_count: int


@dataclass(frozen=True, slots=True)
class WebFetchSuccess:
    """A successful fetch outcome, wrapping the fetched page."""

    page: FetchedPage


@dataclass(frozen=True, slots=True)
class WebFetchFailure:
    """A failed fetch outcome - always data, never a raised exception.

    Attributes:
        url: The URL that failed (the original request URL, or the
            redirect target that failed, whichever step failed).
        reason: The WebFetchFailureReason identifying which check or
            error caused the failure.
        detail: A short, human-readable explanation, safe to display or
            log (never includes credentials or fetched page content).
    """

    url: str
    reason: WebFetchFailureReason
    detail: str


WebFetchResult = WebFetchSuccess | WebFetchFailure


class SafeWebFetcher:
    """Fetches a single webpage safely, enforcing WebFetchPolicy throughout.

    Every call to fetch() re-validates its target (and every redirect
    hop's target) against the given WebFetchPolicy, resolves and pins
    the DNS-resolved IP address before connecting, restricts the method
    to GET, disables automatic redirect-following in favour of manual,
    re-validated hops, enforces the policy's timeout and size limit, and
    checks Content-Type before any body bytes are read.
    """

    def __init__(
        self,
        policy: WebFetchPolicy | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: _Resolver | None = None,
    ) -> None:
        """Construct a fetcher.

        Args:
            policy: The WebFetchPolicy to enforce. Defaults to
                WebFetchPolicy() if not given.
            transport: An optional httpx transport override. Tests pass
                an httpx.MockTransport here so no real network call is
                ever made; production code leaves this as None to use
                httpx's real default transport.
            resolver: An optional hostname resolver override, used only
                for tests (see _default_resolver for the real, socket-
                based implementation used when this is None).
        """
        self._policy = policy or WebFetchPolicy()
        self._resolver: _Resolver = resolver or _default_resolver
        timeout = httpx.Timeout(self._policy.timeout_policy.total_seconds)
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> SafeWebFetcher:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def fetch(self, url: str) -> WebFetchResult:
        """Fetch a single webpage, following only validated redirects.

        Args:
            url: The URL to fetch.

        Returns:
            A WebFetchSuccess wrapping the fetched page, or a
            WebFetchFailure naming the first check or error that
            stopped the fetch. Never raises - every failure mode
            (policy rejection, DNS failure, blocked resolved IP,
            timeout, connection error, oversized response, wrong/
            missing content type, too many redirects, redirect to a
            rejected target, HTTP error status) is returned as data.
        """
        current_url = url
        hop = 0

        while True:
            validated = self._policy.validate(current_url)
            if isinstance(validated, RejectedTarget):
                reason = (
                    WebFetchFailureReason.REDIRECT_TARGET_REJECTED
                    if hop > 0
                    else WebFetchFailureReason.REJECTED_BY_POLICY
                )
                return WebFetchFailure(
                    url=current_url,
                    reason=reason,
                    detail=f"[{validated.reason.value}] {validated.detail}",
                )

            pinned = self._resolve_and_pin(validated)
            if isinstance(pinned, WebFetchFailure):
                return pinned
            request_url, host_header = pinned

            outcome = self._perform_single_request(request_url, host_header)
            if isinstance(outcome, _RedirectTo):
                hop += 1
                if hop > self._policy.redirect_policy.max_hops:
                    return WebFetchFailure(
                        url=current_url,
                        reason=WebFetchFailureReason.TOO_MANY_REDIRECTS,
                        detail=(
                            "Exceeded the redirect limit of "
                            f"{self._policy.redirect_policy.max_hops} hop(s)."
                        ),
                    )
                current_url = urljoin(current_url, outcome.next_url)
                continue

            return outcome

    def _resolve_and_pin(
        self, validated: ValidatedTarget
    ) -> tuple[httpx.URL, str] | WebFetchFailure:
        """Resolve validated's hostname and pin the request to one safe IP.

        Args:
            validated: The syntactically-validated target to resolve.

        Returns:
            A (request_url, host_header) pair, where request_url's host
            is a DNS-resolved-and-validated IP literal and host_header
            is the original hostname (for the Host header and TLS SNI),
            or a WebFetchFailure if resolution failed or every/any
            resolved address is blocked.
        """
        try:
            resolved_ips = self._resolver(validated.hostname)
        except OSError as exc:
            return WebFetchFailure(
                url=validated.original_url,
                reason=WebFetchFailureReason.DNS_RESOLUTION_FAILED,
                detail=f"Could not resolve '{validated.hostname}': {exc}",
            )

        if not resolved_ips:
            return WebFetchFailure(
                url=validated.original_url,
                reason=WebFetchFailureReason.DNS_RESOLUTION_FAILED,
                detail=f"'{validated.hostname}' resolved to no addresses.",
            )

        for ip_str in resolved_ips:
            ip = parse_ip_literal(ip_str)
            if ip is None:
                continue
            reason = blocked_ip_reason(ip)
            if reason is not None:
                return WebFetchFailure(
                    url=validated.original_url,
                    reason=WebFetchFailureReason.DNS_RESOLVED_BLOCKED_IP,
                    detail=(
                        f"'{validated.hostname}' resolved to '{ip_str}', "
                        f"which is {reason} and is not allowed."
                    ),
                )

        pin_ip = resolved_ips[0]
        try:
            target_url = httpx.URL(
                scheme=validated.scheme,
                host=validated.hostname,
                port=validated.port,
                path=validated.path or "/",
                query=validated.query.encode("utf-8") if validated.query else None,
            )
            pinned_url = target_url.copy_with(host=pin_ip)
        except httpx.InvalidURL as exc:
            return WebFetchFailure(
                url=validated.original_url,
                reason=WebFetchFailureReason.UNEXPECTED_ERROR,
                detail=f"Could not build a request URL: {exc}",
            )
        return pinned_url, validated.hostname

    def _perform_single_request(
        self, request_url: httpx.URL, host_header: str
    ) -> WebFetchSuccess | WebFetchFailure | _RedirectTo:
        """Perform exactly one GET request against an already-pinned URL.

        Args:
            request_url: The pinned URL (host already replaced with a
                validated resolved IP address).
            host_header: The original hostname, sent as the Host header
                and (for https) as the TLS "sni_hostname" extension so
                certificate hostname verification still checks the real
                hostname, not the pinned IP literal.

        Returns:
            A WebFetchSuccess, a WebFetchFailure, or a _RedirectTo
            naming the next hop's (unvalidated, relative-or-absolute)
            Location target for the caller to re-validate.
        """
        try:
            with self._client.stream(
                "GET",
                request_url,
                headers={"Host": host_header},
                extensions={"sni_hostname": host_header},
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        return WebFetchFailure(
                            url=str(request_url),
                            reason=WebFetchFailureReason.HTTP_ERROR,
                            detail=(
                                f"HTTP {response.status_code} redirect had "
                                "no Location header."
                            ),
                        )
                    return _RedirectTo(next_url=location)

                if not (200 <= response.status_code < 300):
                    return WebFetchFailure(
                        url=str(request_url),
                        reason=WebFetchFailureReason.HTTP_ERROR,
                        detail=f"Server returned HTTP {response.status_code}.",
                    )

                content_type_header = response.headers.get("content-type")
                if not content_type_header:
                    return WebFetchFailure(
                        url=str(request_url),
                        reason=WebFetchFailureReason.MISSING_CONTENT_TYPE,
                        detail="Response had no Content-Type header.",
                    )

                content_type, charset = _parse_content_type(content_type_header)
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    return WebFetchFailure(
                        url=str(request_url),
                        reason=WebFetchFailureReason.DISALLOWED_CONTENT_TYPE,
                        detail=(
                            f"Content-Type '{content_type}' is not allowed; "
                            "only text/html, text/plain, and "
                            "application/xhtml+xml are accepted."
                        ),
                    )

                max_bytes = self._policy.size_limit_policy.max_bytes
                declared_length = response.headers.get("content-length")
                if declared_length is not None:
                    try:
                        if int(declared_length) > max_bytes:
                            return WebFetchFailure(
                                url=str(request_url),
                                reason=WebFetchFailureReason.OVERSIZED_RESPONSE,
                                detail=(
                                    f"Declared Content-Length "
                                    f"{declared_length} exceeds the "
                                    f"{max_bytes}-byte limit."
                                ),
                            )
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        return WebFetchFailure(
                            url=str(request_url),
                            reason=WebFetchFailureReason.OVERSIZED_RESPONSE,
                            detail=(
                                f"Response exceeded the {max_bytes}-byte "
                                "limit while streaming; connection closed."
                            ),
                        )
                    chunks.append(chunk)

                body = b"".join(chunks)
                return WebFetchSuccess(
                    page=FetchedPage(
                        url=str(request_url),
                        status_code=response.status_code,
                        content_type=content_type,
                        charset=charset,
                        body=body,
                        byte_count=len(body),
                    )
                )
        except httpx.TimeoutException as exc:
            return WebFetchFailure(
                url=str(request_url),
                reason=WebFetchFailureReason.TIMEOUT,
                detail=f"Request timed out: {exc}",
            )
        except httpx.InvalidURL as exc:
            # httpx eagerly builds a "next_request" for any 3xx response
            # even when follow_redirects=False (so callers may choose to
            # follow manually) - this happens before our own code ever
            # sees the response, so a Location header httpx itself
            # cannot parse as a URL (e.g. "javascript:alert(1)", which
            # has no authority component) raises here rather than
            # returning a response. Treated identically to any other
            # redirect target our own policy would reject.
            return WebFetchFailure(
                url=str(request_url),
                reason=WebFetchFailureReason.REDIRECT_TARGET_REJECTED,
                detail=f"Redirect target was not a usable URL: {exc}",
            )
        except httpx.HTTPError as exc:
            return WebFetchFailure(
                url=str(request_url),
                reason=WebFetchFailureReason.CONNECTION_ERROR,
                detail=f"Network error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - last-resort safety boundary
            # A true I/O boundary: every failure mode must be data, never
            # an exception escaping to a caller (Phase 32 plan, error-
            # handling policy). Anything not already handled above by a
            # specific httpx exception type is reported honestly as
            # unexpected, rather than crashing the caller.
            return WebFetchFailure(
                url=str(request_url),
                reason=WebFetchFailureReason.UNEXPECTED_ERROR,
                detail=f"Unexpected error while fetching: {exc}",
            )


@dataclass(frozen=True, slots=True)
class _RedirectTo:
    """Internal signal: the response was a redirect to next_url.

    Never returned from SafeWebFetcher.fetch() itself - the fetch loop
    consumes this and re-validates next_url before following it.
    """

    next_url: str


def _parse_content_type(header_value: str) -> tuple[str, str | None]:
    """Split a Content-Type header into its type and optional charset.

    Args:
        header_value: The raw Content-Type header value, e.g.
            "text/html; charset=UTF-8".

    Returns:
        A (content_type, charset) pair; content_type is lowercased and
        stripped of any parameters, charset is lowercased or None if
        not declared.
    """
    parts = header_value.split(";")
    content_type = parts[0].strip().lower()
    charset: str | None = None
    for param in parts[1:]:
        param = param.strip()
        if param.lower().startswith("charset="):
            charset = param.split("=", 1)[1].strip().strip('"').lower()
            break
    return content_type, charset


def _default_resolver(hostname: str) -> list[str]:
    """Resolve hostname to its candidate IP addresses via the real OS resolver.

    An IP-literal hostname resolves to itself (getaddrinfo accepts IP
    literals directly, performing no actual DNS query), so this
    function is safe to call unconditionally for every validated
    target, whether it was originally a domain name or an IP literal.

    Args:
        hostname: The hostname (or IP literal) to resolve.

    Returns:
        A list of unique IP address strings, in the order returned by
        the operating system's resolver.

    Raises:
        OSError: If resolution fails (socket.gaierror, a subclass of
            OSError, is what the real resolver raises for an unknown
            host).
    """
    infos = socket.getaddrinfo(hostname, None)
    seen: set[str] = set()
    ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips
