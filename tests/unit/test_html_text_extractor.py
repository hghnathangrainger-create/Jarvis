"""
test_html_text_extractor.py

Unit tests for the deterministic HTML/plain-text extractor (Phase 32,
Batch 3: Webpage Fetch/Read Safety Foundation).

Run with:
    pytest tests/unit/test_html_text_extractor.py
"""

from __future__ import annotations

import ast
from pathlib import Path

from web.html_text_extractor import (
    TextExtractionFailure,
    TextExtractionFailureReason,
    TextExtractionSuccess,
    extract_html_text,
    extract_text_from_fetched_page,
    extract_text_from_page,
)
from web.safe_web_fetcher import FetchedPage


# ---------------------------------------------------------------------------
# text/plain pass-through
# ---------------------------------------------------------------------------


def test_plain_text_passes_through_with_line_breaks_preserved() -> None:
    result = extract_text_from_page("text/plain", b"Line one\nLine two\n  indented")
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Line one\nLine two\n  indented"


def test_plain_text_normalizes_windows_line_endings() -> None:
    result = extract_text_from_page("text/plain", b"a\r\nb\r\nc")
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "a\nb\nc"


# ---------------------------------------------------------------------------
# Simple HTML extraction
# ---------------------------------------------------------------------------


def test_simple_html_extracts_visible_text() -> None:
    html = "<html><body><p>Hello</p><p>World</p></body></html>"
    result = extract_text_from_page("text/html", html.encode("utf-8"))
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Hello World"


def test_xhtml_content_type_is_also_extracted_as_html() -> None:
    html = "<html><body><p>Hi</p></body></html>"
    result = extract_text_from_page(
        "application/xhtml+xml", html.encode("utf-8")
    )
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Hi"


def test_content_type_with_charset_parameter_dispatches_correctly() -> None:
    result = extract_text_from_page(
        "text/html; charset=utf-8", b"<p>Hello</p>"
    )
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Hello"


# ---------------------------------------------------------------------------
# Malformed HTML never crashes
# ---------------------------------------------------------------------------


def test_malformed_unclosed_tags_do_not_raise() -> None:
    html = "<div><p>Unclosed paragraph<div>Another <b>bold"
    extracted = extract_html_text(html)
    assert "Unclosed paragraph" in extracted.text
    assert "Another" in extracted.text


def test_severely_broken_markup_does_not_raise() -> None:
    html = "<<<>>> not <valid html at all <<< <script"
    extracted = extract_html_text(html)
    assert isinstance(extracted.text, str)


def test_unclosed_script_tag_conservatively_swallows_the_rest_of_the_page() -> None:
    """Documents the deliberate fail-safe skip-zone-only-grows behaviour.

    An unclosed <script> means everything after it is treated as still
    inside the script (never leaked as if it were real page text) -
    the extractor loses information rather than risking script content
    being mistaken for visible text.
    """
    html = "<p>Before</p><script>var x = 1; <p>Never shown</p>"
    extracted = extract_html_text(html)
    assert "Before" in extracted.text
    assert "Never shown" not in extracted.text
    assert "var x" not in extracted.text


# ---------------------------------------------------------------------------
# script/style/noscript/template content removed
# ---------------------------------------------------------------------------


def test_script_content_is_removed() -> None:
    html = "<p>Before</p><script>alert('x');</script><p>After</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "Before After"


def test_style_content_is_removed() -> None:
    html = "<style>body { color: red; }</style><p>Visible</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "Visible"


def test_noscript_content_is_removed() -> None:
    """Clearly tested decision: noscript is treated like script/style.

    Jarvis never executes JavaScript, but noscript fallback content is
    still excluded for consistency and simplicity - it is not treated
    as the page's real visible text.
    """
    html = "<noscript>Enable JavaScript to continue</noscript><p>Real content</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "Real content"
    assert "Enable JavaScript" not in extracted.text


def test_template_content_is_removed() -> None:
    html = "<template><p>Not rendered by any browser</p></template><p>Shown</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "Shown"
    assert "Not rendered" not in extracted.text


def test_nested_skip_tags_are_handled_by_the_shared_depth_counter() -> None:
    html = "<script>var s = '<style>fake</style>';</script><p>After</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "After"


# ---------------------------------------------------------------------------
# Comments ignored
# ---------------------------------------------------------------------------


def test_html_comments_are_ignored() -> None:
    html = "<p>Hello<!-- this is a hidden comment --> World</p>"
    extracted = extract_html_text(html)
    assert "hidden comment" not in extracted.text
    assert "Hello" in extracted.text
    assert "World" in extracted.text


# ---------------------------------------------------------------------------
# Entities decoded safely
# ---------------------------------------------------------------------------


def test_named_entities_are_decoded() -> None:
    extracted = extract_html_text("<p>Tom &amp; Jerry</p>")
    assert extracted.text == "Tom & Jerry"


def test_numeric_entities_are_decoded() -> None:
    extracted = extract_html_text("<p>Caf&#233;</p>")
    assert extracted.text == "Café"


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------


def test_html_whitespace_is_collapsed_to_single_spaces() -> None:
    html = "<p>Hello \n\n   World  \t again</p>"
    extracted = extract_html_text(html)
    assert extracted.text == "Hello World again"


# ---------------------------------------------------------------------------
# Output character limit
# ---------------------------------------------------------------------------


def test_output_character_limit_is_enforced_and_disclosed() -> None:
    long_html = "<p>" + ("a" * 300_000) + "</p>"
    extracted = extract_html_text(long_html)
    assert extracted.truncated is True
    assert extracted.character_count == 200_000
    assert len(extracted.text) == 200_000


def test_short_content_is_not_marked_truncated() -> None:
    extracted = extract_html_text("<p>short</p>")
    assert extracted.truncated is False
    assert extracted.character_count == len("short")


# ---------------------------------------------------------------------------
# Empty/blank content behavior
# ---------------------------------------------------------------------------


def test_empty_html_content_is_a_success_with_empty_text() -> None:
    result = extract_text_from_page("text/html", b"")
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == ""
    assert result.extracted.character_count == 0
    assert result.extracted.truncated is False


def test_whitespace_only_html_content_reduces_to_empty_text() -> None:
    extracted = extract_html_text("   \n\n\t  ")
    assert extracted.text == ""


def test_empty_plain_text_content_is_a_success_with_empty_text() -> None:
    result = extract_text_from_page("text/plain", b"")
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == ""


# ---------------------------------------------------------------------------
# Non-string / invalid content and unsupported content types
# ---------------------------------------------------------------------------


def test_non_bytes_body_is_an_explicit_invalid_input_failure() -> None:
    result = extract_text_from_page("text/html", "not bytes")  # type: ignore[arg-type]
    assert isinstance(result, TextExtractionFailure)
    assert result.reason == TextExtractionFailureReason.INVALID_INPUT


def test_non_string_content_type_is_an_explicit_invalid_input_failure() -> None:
    result = extract_text_from_page(None, b"data")  # type: ignore[arg-type]
    assert isinstance(result, TextExtractionFailure)
    assert result.reason == TextExtractionFailureReason.INVALID_INPUT


def test_unsupported_content_type_is_an_explicit_failure() -> None:
    result = extract_text_from_page("application/pdf", b"%PDF-1.4 binary data")
    assert isinstance(result, TextExtractionFailure)
    assert result.reason == TextExtractionFailureReason.UNSUPPORTED_CONTENT_TYPE


def test_unrecognised_charset_falls_back_to_utf8() -> None:
    result = extract_text_from_page(
        "text/html", "<p>café</p>".encode("utf-8"), charset="not-a-real-charset"
    )
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "café"


def test_declared_charset_is_honoured() -> None:
    body = "<p>café</p>".encode("latin-1")
    result = extract_text_from_page("text/html", body, charset="latin-1")
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "café"


# ---------------------------------------------------------------------------
# FetchedPage convenience wrapper
# ---------------------------------------------------------------------------


def test_extract_text_from_fetched_page_wraps_the_same_logic() -> None:
    page = FetchedPage(
        url="https://example.com/",
        status_code=200,
        content_type="text/html",
        charset="utf-8",
        body=b"<p>Wrapped</p>",
        byte_count=len(b"<p>Wrapped</p>"),
    )
    result = extract_text_from_fetched_page(page)
    assert isinstance(result, TextExtractionSuccess)
    assert result.extracted.text == "Wrapped"


# ---------------------------------------------------------------------------
# Structural proofs
# ---------------------------------------------------------------------------


def test_extractor_module_imports_no_forbidden_packages() -> None:
    source = Path("web/html_text_extractor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    forbidden = {
        "ai",
        "workflow",
        "scheduler",
        "dashboard",
        "tools",
        "core",
        "requests",
        "httpx",
        "socket",
    }
    assert not (imported_names & forbidden), imported_names


def test_extractor_module_never_calls_open() -> None:
    source = Path("web/html_text_extractor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open"
