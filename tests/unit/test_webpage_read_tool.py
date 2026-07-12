"""
test_webpage_read_tool.py

Unit tests for WebpageReadTool and its terminal-output sanitizer
(Phase 33, Batch 1: Webpage Read Command).

A fake fetcher (duck-typing SafeWebFetcher.fetch()) is used throughout,
so these tests never touch the network, DNS, or a real httpx transport
- that is already exhaustively covered by Phase 32's own test suite.

Run with:
    pytest tests/unit/test_webpage_read_tool.py
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.base_tool import ToolRequest
from tools.builtin.webpage_read_tool import WebpageReadTool, sanitize_terminal_text
from web.safe_web_fetcher import FetchedPage, WebFetchFailure, WebFetchFailureReason, WebFetchSuccess


class _FakeFetcher:
    """A minimal stand-in for SafeWebFetcher, returning a canned result."""

    def __init__(self, result: WebFetchSuccess | WebFetchFailure) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebFetchSuccess | WebFetchFailure:
        self.calls.append(url)
        return self._result


def _success_page(
    body: bytes,
    *,
    content_type: str = "text/html",
    charset: str | None = "utf-8",
    url: str = "https://example.com/",
) -> WebFetchSuccess:
    return WebFetchSuccess(
        page=FetchedPage(
            url=url,
            status_code=200,
            content_type=content_type,
            charset=charset,
            body=body,
            byte_count=len(body),
        )
    )


# ---------------------------------------------------------------------------
# action_for()
# ---------------------------------------------------------------------------


def test_action_for_returns_fixed_string_regardless_of_url() -> None:
    tool = WebpageReadTool(_FakeFetcher(_success_page(b"<p>x</p>")))
    request = ToolRequest(
        tool_name="webpage_read",
        input_data={"url": "http://169.254.169.254/latest/meta-data/; rm -rf /"},
    )
    assert tool.action_for(request) == "read webpage"


def test_action_for_fixed_even_with_no_input() -> None:
    tool = WebpageReadTool(_FakeFetcher(_success_page(b"<p>x</p>")))
    request = ToolRequest(tool_name="webpage_read", input_data={})
    assert tool.action_for(request) == "read webpage"


# ---------------------------------------------------------------------------
# Missing/empty input
# ---------------------------------------------------------------------------


def test_missing_url_input_fails_cleanly() -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    tool = WebpageReadTool(fetcher)
    result = tool.run(ToolRequest(tool_name="webpage_read", input_data={}))

    assert result.success is False
    assert "url" in result.error.lower()
    assert fetcher.calls == []


def test_whitespace_only_url_input_fails_cleanly() -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(tool_name="webpage_read", input_data={"url": "   "})
    )

    assert result.success is False
    assert fetcher.calls == []


# ---------------------------------------------------------------------------
# Successful read
# ---------------------------------------------------------------------------


def test_successful_webpage_read_returns_extracted_text() -> None:
    fetcher = _FakeFetcher(_success_page(b"<html><body><p>Hello</p></body></html>"))
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(
            tool_name="webpage_read", input_data={"url": "https://example.com/"}
        )
    )

    assert result.success is True
    assert "Hello" in result.output
    assert fetcher.calls == ["https://example.com/"]
    assert result.metadata["url"] == "https://example.com/"
    assert result.metadata["status_code"] == "200"
    assert result.metadata["truncated"] == "False"


def test_metadata_extracted_text_is_clean_without_display_formatting() -> None:
    """Phase 34, Batch 2: metadata['extracted_text'] carries the sanitized
    text alone, without the 'Webpage content from <url>:' header that
    `output` adds - so a caller doesn't need to parse display output."""
    fetcher = _FakeFetcher(_success_page(b"<html><body><p>Hello</p></body></html>"))
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(
            tool_name="webpage_read", input_data={"url": "https://example.com/"}
        )
    )

    assert result.metadata["extracted_text"] == "Hello"
    assert "Webpage content from" not in result.metadata["extracted_text"]


def test_plain_text_page_is_read_successfully() -> None:
    fetcher = _FakeFetcher(
        _success_page(b"Line one\nLine two", content_type="text/plain")
    )
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(tool_name="webpage_read", input_data={"url": "https://x.example/"})
    )

    assert result.success is True
    assert "Line one\nLine two" in result.output


def test_url_is_stripped_before_being_passed_to_the_fetcher() -> None:
    fetcher = _FakeFetcher(_success_page(b"<p>x</p>"))
    tool = WebpageReadTool(fetcher)
    tool.run(
        ToolRequest(
            tool_name="webpage_read", input_data={"url": "  https://example.com/  "}
        )
    )
    assert fetcher.calls == ["https://example.com/"]


# ---------------------------------------------------------------------------
# Fetch failure
# ---------------------------------------------------------------------------


def test_fetch_failure_becomes_a_clean_tool_failure() -> None:
    fetcher = _FakeFetcher(
        WebFetchFailure(
            url="http://localhost/admin",
            reason=WebFetchFailureReason.REJECTED_BY_POLICY,
            detail="[localhost_hostname] Hostname 'localhost' is not allowed.",
        )
    )
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(
            tool_name="webpage_read", input_data={"url": "http://localhost/admin"}
        )
    )

    assert result.success is False
    assert "localhost" in result.error
    assert result.output == ""


# ---------------------------------------------------------------------------
# Extraction failure
# ---------------------------------------------------------------------------


def test_extraction_failure_becomes_a_clean_tool_failure() -> None:
    fetcher = _FakeFetcher(_success_page(b"%PDF-1.4 binary", content_type="application/pdf"))
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(tool_name="webpage_read", input_data={"url": "https://x.example/file.pdf"})
    )

    assert result.success is False
    assert "extract" in result.error.lower()


# ---------------------------------------------------------------------------
# Terminal sanitization
# ---------------------------------------------------------------------------


def test_ansi_csi_escape_sequence_is_removed_from_tool_output() -> None:
    body = "<p>Hello \x1b[31mRED\x1b[0m World</p>".encode("utf-8")
    fetcher = _FakeFetcher(_success_page(body))
    tool = WebpageReadTool(fetcher)
    result = tool.run(
        ToolRequest(tool_name="webpage_read", input_data={"url": "https://x.example/"})
    )

    assert result.success is True
    assert "\x1b" not in result.output
    assert "[31m" not in result.output
    assert "[0m" not in result.output
    assert "RED" in result.output


def test_ansi_osc_hyperlink_escape_sequence_is_removed() -> None:
    text = "before \x1b]8;;http://evil.example\x07clicktext\x1b]8;;\x07 after"
    sanitized = sanitize_terminal_text(text)
    assert "\x1b" not in sanitized
    assert "evil.example" not in sanitized
    assert "before" in sanitized
    assert "after" in sanitized


def test_dangerous_control_characters_are_removed() -> None:
    text = "before\x07\x08\x0cafter"
    sanitized = sanitize_terminal_text(text)
    assert sanitized == "beforeafter"


def test_newlines_and_tabs_are_explicitly_preserved() -> None:
    """The clearly tested decision: \\n and \\t survive sanitization."""
    text = "line one\nline two\tindented"
    assert sanitize_terminal_text(text) == text


def test_ordinary_unicode_printable_text_is_unaffected() -> None:
    text = "café résumé naïve"
    assert sanitize_terminal_text(text) == text


def test_lone_unmatched_escape_character_is_still_removed() -> None:
    """A stray ESC not part of a recognised CSI/OSC shape is still stripped
    by the catch-all control-character removal pass."""
    text = "before\x1bafter"
    sanitized = sanitize_terminal_text(text)
    assert "\x1b" not in sanitized
    assert sanitized == "beforeafter"


# ---------------------------------------------------------------------------
# No disk/database writes
# ---------------------------------------------------------------------------


def test_tool_module_never_calls_open() -> None:
    source = Path("tools/builtin/webpage_read_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open"


# ---------------------------------------------------------------------------
# Structural: no forbidden imports
# ---------------------------------------------------------------------------


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


def test_tool_module_imports_no_forbidden_packages() -> None:
    source = Path("tools/builtin/webpage_read_tool.py").read_text(encoding="utf-8")
    imported = _collect_top_level_imports(source)
    forbidden = {
        "ai",
        "workflow",
        "scheduler",
        "dashboard",
        "ui",
        "inbox",
        "storage",
        "database",
    }
    assert not (imported & forbidden), imported
