"""
test_phase32_pipeline_end_to_end.py

End-to-end internal pipeline tests for the complete Phase 32 webpage
fetch/read safety foundation: WebFetchPolicy -> SafeWebFetcher ->
html_text_extractor, chained exactly as a future integration would
chain them, but still entirely inside this test module - nothing in
the running system wires these together yet.

Every test uses httpx.MockTransport and an injected DNS resolver; no
real network call and no real DNS lookup is ever made, matching this
project's established discipline (WebSearchProvider's own tests
likewise never hit the real DuckDuckGo API).

Run with:
    pytest tests/integration/test_phase32_pipeline_end_to_end.py
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path
from typing import Callable

import httpx
import pytest

from web.fetch_policy import RedirectPolicy, SizeLimitPolicy, WebFetchPolicy
from web.html_text_extractor import TextExtractionSuccess, extract_text_from_fetched_page
from web.safe_web_fetcher import SafeWebFetcher, WebFetchFailure

_PUBLIC_IP = "93.184.216.34"


def _resolver_for(mapping: dict[str, list[str]]) -> Callable[[str], list[str]]:
    def resolver(hostname: str) -> list[str]:
        if hostname not in mapping:
            raise OSError(f"simulated resolution failure for '{hostname}'")
        return mapping[hostname]

    return resolver


def _fetch_and_extract(fetcher: SafeWebFetcher, url: str):
    """Chain fetch -> extract exactly as a future caller would."""
    fetch_result = fetcher.fetch(url)
    if isinstance(fetch_result, WebFetchFailure):
        return fetch_result
    return extract_text_from_fetched_page(fetch_result.page)


# ---------------------------------------------------------------------------
# Happy paths: valid HTML and plain text, fetched and extracted
# ---------------------------------------------------------------------------


def test_valid_html_page_is_fetched_and_extracted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body><h1>Title</h1><p>Body text.</p></body></html>",
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/article")

    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Title Body text."


def test_valid_plain_text_page_is_fetched_and_extracted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"Line one\nLine two",
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/notes.txt")

    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Line one\nLine two"


# ---------------------------------------------------------------------------
# Disallowed content type / oversized response never reach extraction
# ---------------------------------------------------------------------------


def test_disallowed_content_type_never_reaches_extraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4"
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/file.pdf")

    assert isinstance(result, WebFetchFailure)


def test_oversized_response_never_reaches_extraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>" + b"x" * 10_000 + b"</p>",
        )

    policy = WebFetchPolicy(size_limit_policy=SizeLimitPolicy(max_bytes=100))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/huge")

    assert isinstance(result, WebFetchFailure)


# ---------------------------------------------------------------------------
# Unsafe original URL / unsafe redirect never reach extraction
# ---------------------------------------------------------------------------


def test_unsafe_original_url_never_triggers_a_fetch_or_extraction() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    fetcher = SafeWebFetcher(transport=httpx.MockTransport(handler))
    result = _fetch_and_extract(fetcher, "http://169.254.169.254/latest/meta-data/")

    assert isinstance(result, WebFetchFailure)
    assert calls == []


def test_unsafe_redirect_target_never_reaches_extraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        if host == "start.example":
            return httpx.Response(
                302, headers={"location": "http://127.0.0.1/internal"}
            )
        raise AssertionError("the blocked redirect target must never be requested")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"start.example": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://start.example/")

    assert isinstance(result, WebFetchFailure)


# ---------------------------------------------------------------------------
# Redirect chains: within limit succeeds, over limit fails safely
# ---------------------------------------------------------------------------


def test_redirect_chain_within_limit_is_fetched_and_extracted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        if host == "hop1.example":
            return httpx.Response(
                302, headers={"location": "https://hop2.example/final"}
            )
        if host == "hop2.example":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<p>Landed safely</p>",
            )
        raise AssertionError(f"unexpected host: {host}")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for(
            {"hop1.example": [_PUBLIC_IP], "hop2.example": ["93.184.216.35"]}
        ),
    )
    result = _fetch_and_extract(fetcher, "https://hop1.example/start")

    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Landed safely"


def test_redirect_chain_over_limit_fails_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://loop.example/next"})

    policy = WebFetchPolicy(redirect_policy=RedirectPolicy(max_hops=1))
    fetcher = SafeWebFetcher(
        policy,
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"loop.example": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://loop.example/start")

    assert isinstance(result, WebFetchFailure)


# ---------------------------------------------------------------------------
# Network errors fail safely
# ---------------------------------------------------------------------------


def test_network_error_fails_safely_without_reaching_extraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure", request=request)

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/")

    assert isinstance(result, WebFetchFailure)


def test_dns_failure_fails_safely_without_reaching_extraction() -> None:
    def resolver(hostname: str) -> list[str]:
        raise socket.gaierror("simulated DNS failure")

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        resolver=resolver,
    )
    result = _fetch_and_extract(fetcher, "https://nowhere.example/")

    assert isinstance(result, WebFetchFailure)


# ---------------------------------------------------------------------------
# Malformed HTML from a genuinely valid, successful fetch
# ---------------------------------------------------------------------------


def test_malformed_html_from_a_valid_fetch_still_produces_a_safe_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<div><p>Unclosed <b>tags <div>everywhere",
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/broken")

    assert isinstance(result, TextExtractionSuccess)
    assert "Unclosed" in result.extracted.text


# ---------------------------------------------------------------------------
# No disk/database writes; no forbidden module coupling
# ---------------------------------------------------------------------------


def test_pipeline_never_writes_any_file_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<p>content</p>"
        )

    fetcher = SafeWebFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_resolver_for({"example.com": [_PUBLIC_IP]}),
    )
    result = _fetch_and_extract(fetcher, "https://example.com/")

    assert isinstance(result, TextExtractionSuccess)
    assert list(tmp_path.iterdir()) == []


def _collect_top_level_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    return imported_names


_FORBIDDEN_PACKAGES = {
    "ai",
    "workflow",
    "scheduler",
    "dashboard",
    "ui",
    "tools",
    "core",
    "security",
    "storage",
    "approval",
}


@pytest.mark.parametrize(
    "module_path",
    [
        "web/fetch_policy.py",
        "web/safe_web_fetcher.py",
        "web/html_text_extractor.py",
    ],
)
def test_no_phase32_module_imports_a_forbidden_package(module_path: str) -> None:
    """Structural proof: the entire web/ foundation stays fully isolated.

    None of the three Phase 32 modules import AI, workflow, scheduler,
    dashboard/ui, tool registration, CommandRouter/SecurityManager, or
    database/storage persistence modules - this is a safety layer
    nothing in the running system calls yet.
    """
    source = Path(module_path).read_text(encoding="utf-8")
    imported = _collect_top_level_imports(source)
    assert not (imported & _FORBIDDEN_PACKAGES), (module_path, imported)


def test_no_phase32_module_imports_the_database_module() -> None:
    """database.py holds the SQLAlchemy engine/session setup - Phase 32
    never persists anything, so none of its modules should import it."""
    for module_path in (
        "web/fetch_policy.py",
        "web/safe_web_fetcher.py",
        "web/html_text_extractor.py",
    ):
        source = Path(module_path).read_text(encoding="utf-8")
        imported = _collect_top_level_imports(source)
        assert "database" not in imported, module_path


def test_no_phase32_module_imports_command_router_or_security_manager() -> None:
    for module_path in (
        "web/fetch_policy.py",
        "web/safe_web_fetcher.py",
        "web/html_text_extractor.py",
    ):
        source = Path(module_path).read_text(encoding="utf-8")
        assert "command_router" not in source
        assert "security_manager" not in source


def test_only_the_webpage_read_tool_and_main_import_the_web_package() -> None:
    """Confirms Phase 32's foundation is consumed in exactly one place.

    Updated for Phase 33 (Batch 1): the foundation was deliberately
    "one-directional and unused" through the end of Phase 32, but
    Phase 33 exists specifically to consume it - via
    tools/builtin/webpage_read_tool.py and its registration in
    main.py, and nowhere else. This test now proves the narrower, still
    meaningful invariant: no AI, workflow, scheduler, dashboard/ui,
    approval, storage, or *other* tool module imports web/ - only the
    one tool built for this exact purpose, and the composition root
    that wires it in.
    """
    repo_root = Path(".")
    allowed_importers = {
        (repo_root / "tools" / "builtin" / "webpage_read_tool.py").resolve(),
        (repo_root / "main.py").resolve(),
    }
    production_dirs = ["tools", "core", "ai", "workflow", "ui", "approval", "storage"]
    offending: list[str] = []
    for directory in production_dirs:
        dir_path = repo_root / directory
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            source = py_file.read_text(encoding="utf-8")
            imported = _collect_top_level_imports(source)
            if "web" in imported and py_file.resolve() not in allowed_importers:
                offending.append(str(py_file))

    main_source = Path("main.py").read_text(encoding="utf-8")
    assert "web" in _collect_top_level_imports(main_source)

    tool_source = Path("tools/builtin/webpage_read_tool.py").read_text(encoding="utf-8")
    assert "web" in _collect_top_level_imports(tool_source)

    assert offending == []
