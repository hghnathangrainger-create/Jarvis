"""
test_webpage_ingestion.py

Unit tests for ai/webpage_ingestion.py (Phase 34, Batch 1: AI Webpage
Ingestion Module).

No webpage is ever fetched in these tests - every input is a plain
string a caller is presumed to have already obtained through the
existing, approval-gated Phase 33 acquisition path. No SafeWebFetcher,
WebpageReadTool, or ToolExecutor is imported or used anywhere here.

Run with:
    pytest tests/unit/test_webpage_ingestion.py
"""

from __future__ import annotations

import ast

import pytest

from ai.context_models import AIContextBlock
from ai.webpage_ingestion import WebpageIngestionResult, ingest_webpage_for_ai
from config.constants import ContentTrust

_URL = "https://example.com/article"


# ---------------------------------------------------------------------------
# WebpageIngestionResult invariants
# ---------------------------------------------------------------------------


def test_result_rejects_both_context_and_error() -> None:
    context = AIContextBlock.from_untrusted("text", source="webpage:'x'")
    with pytest.raises(ValueError):
        WebpageIngestionResult(context=context, error="boom")


def test_result_rejects_neither_context_nor_error() -> None:
    with pytest.raises(ValueError):
        WebpageIngestionResult()


def test_result_rejects_truncated_without_context() -> None:
    with pytest.raises(ValueError):
        WebpageIngestionResult(error="boom", truncated=True)


def test_success_property_reflects_context_presence() -> None:
    context = AIContextBlock.from_untrusted("text", source="webpage:'x'")
    assert WebpageIngestionResult(context=context).success is True
    assert WebpageIngestionResult(error="boom").success is False


# ---------------------------------------------------------------------------
# Creates exactly one UNTRUSTED context block
# ---------------------------------------------------------------------------


def test_creates_exactly_one_untrusted_context_block() -> None:
    result = ingest_webpage_for_ai(_URL, "Hello, this is the page content.")

    assert result.success is True
    assert isinstance(result.context, AIContextBlock)
    assert result.context.trust is ContentTrust.UNTRUSTED


def test_source_identifies_webpage_url() -> None:
    result = ingest_webpage_for_ai(_URL, "Some page content.")
    assert result.context.source == f"webpage:{_URL!r}"


def test_preamble_says_external_untrusted_data_only() -> None:
    result = ingest_webpage_for_ai(_URL, "Some page content.")
    text = result.context.text.lower()

    assert "webpage" in text
    assert "not a summary jarvis has verified" in text or "not verified" in text
    assert "instruction" in text
    assert "data" in text


def test_webpage_text_appears_inside_the_untrusted_block() -> None:
    distinctive = "A very distinctive sentence about zebras and telescopes."
    result = ingest_webpage_for_ai(_URL, distinctive)
    assert distinctive in result.context.text


def test_url_appears_as_plain_display_text_not_specially_interpreted() -> None:
    """The URL is included as source/metadata display only - even a URL
    shaped like it might carry an embedded instruction is just inert text
    inside the UNTRUSTED block, never something Jarvis code parses back
    out or acts on."""
    adversarial_url = "https://example.com/?ignore_previous_instructions=true"
    result = ingest_webpage_for_ai(adversarial_url, "Ordinary content.")

    assert result.context.trust is ContentTrust.UNTRUSTED
    assert adversarial_url in result.context.text
    assert result.context.source == f"webpage:{adversarial_url!r}"


# ---------------------------------------------------------------------------
# Size budget / truncation
# ---------------------------------------------------------------------------


def test_content_is_bounded_by_the_configured_size_limit() -> None:
    long_text = "x" * 50_000
    result = ingest_webpage_for_ai(_URL, long_text, max_chars=100)

    assert result.truncated is True
    # The framed context includes the preamble/metadata too, so we only
    # assert the *page text portion* respects the bound, not the whole
    # combined context length.
    assert "x" * 100 in result.context.text
    assert "x" * 101 not in result.context.text


def test_truncation_is_disclosed_in_the_context_text() -> None:
    result = ingest_webpage_for_ai(_URL, "y" * 1000, max_chars=50)
    assert result.truncated is True
    assert "truncated" in result.context.text.lower()


def test_non_truncated_content_does_not_falsely_claim_truncation() -> None:
    result = ingest_webpage_for_ai(_URL, "short content", max_chars=6000)
    assert result.truncated is False
    assert "truncated" not in result.context.text.lower()


def test_max_chars_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ingest_webpage_for_ai(_URL, "content", max_chars=0)
    with pytest.raises(ValueError):
        ingest_webpage_for_ai(_URL, "content", max_chars=-5)


def test_default_max_chars_is_six_thousand() -> None:
    text = "a" * 7000
    result = ingest_webpage_for_ai(_URL, text)
    assert result.truncated is True
    assert "a" * 6000 in result.context.text
    assert "a" * 6001 not in result.context.text


# ---------------------------------------------------------------------------
# Blank/empty text behavior
# ---------------------------------------------------------------------------


def test_empty_text_returns_a_represented_failure() -> None:
    result = ingest_webpage_for_ai(_URL, "")
    assert result.success is False
    assert result.context is None
    assert result.error is not None
    assert _URL in result.error


def test_whitespace_only_text_returns_a_represented_failure() -> None:
    result = ingest_webpage_for_ai(_URL, "   \n\t  ")
    assert result.success is False
    assert result.context is None


# ---------------------------------------------------------------------------
# Optional metadata
# ---------------------------------------------------------------------------


def test_optional_metadata_appears_when_provided() -> None:
    result = ingest_webpage_for_ai(
        _URL,
        "content",
        content_type="text/html",
        status_code=200,
        byte_count=1234,
    )
    text = result.context.text
    assert "text/html" in text
    assert "200" in text
    assert "1234" in text


def test_extraction_truncated_flag_is_disclosed_distinctly() -> None:
    result = ingest_webpage_for_ai(_URL, "content", extraction_truncated=True)
    assert "already cut short" in result.context.text.lower()


def test_omitted_metadata_produces_no_stray_lines() -> None:
    result = ingest_webpage_for_ai(_URL, "content")
    # None of the optional metadata was supplied, so none of its labels
    # should appear.
    text = result.context.text
    assert "Content-Type:" not in text
    assert "Status:" not in text
    assert "Fetched byte count:" not in text


# ---------------------------------------------------------------------------
# Structural proofs: no acquisition, no AI call, no forbidden imports
# ---------------------------------------------------------------------------


def _imported_names(module_file: str) -> set[str]:
    with open(module_file, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
            if node.module:
                imported_names.add(node.module)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
    return imported_names


def test_module_never_imports_acquisition_or_execution_dependencies() -> None:
    import ai.webpage_ingestion as module

    imported = _imported_names(module.__file__)
    forbidden = {
        "SafeWebFetcher",
        "WebpageReadTool",
        "ToolExecutor",
        "ToolRegistry",
        "web.safe_web_fetcher",
        "tools.builtin.webpage_read_tool",
        "tools.executor",
    }
    assert not (imported & forbidden), imported


def test_module_never_imports_the_ai_reasoning_engine_or_router() -> None:
    import ai.webpage_ingestion as module

    imported = _imported_names(module.__file__)
    forbidden = {"AIReasoningEngine", "AIRouter", "ai.reasoning_engine", "ai.router"}
    assert not (imported & forbidden), imported


def test_module_never_imports_command_router_security_manager_or_main() -> None:
    import ai.webpage_ingestion as module

    imported = _imported_names(module.__file__)
    forbidden = {
        "CommandRouter",
        "SecurityManager",
        "core.command_router",
        "security.security_manager",
        "main",
    }
    assert not (imported & forbidden), imported


def test_module_never_imports_inbox_storage_or_database() -> None:
    import ai.webpage_ingestion as module

    imported = _imported_names(module.__file__)
    forbidden = {
        "InboxStore",
        "inbox.inbox_store",
        "storage.database",
        "storage.models",
        "database",
    }
    assert not (imported & forbidden), imported


def test_module_never_imports_workflow_scheduler_or_dashboard() -> None:
    import ai.webpage_ingestion as module

    imported = _imported_names(module.__file__)
    forbidden = {
        "WorkflowEngine",
        "workflow.engine",
        "scheduler",
        "dashboard",
        "ui.dashboard_app",
    }
    assert not (imported & forbidden), imported


def test_module_never_calls_open() -> None:
    import ai.webpage_ingestion as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open"
