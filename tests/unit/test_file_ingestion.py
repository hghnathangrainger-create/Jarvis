"""
test_file_ingestion.py

Unit tests for ai/file_ingestion.py (Phase 8, Batch 1).

These prove:
    - A successful acquisition returns an AIContextBlock: UNTRUSTED, carrying
      the file's actual content, labelled with the exact path that was read.
    - ingest_file_for_ai() itself is the caller of ToolExecutor.execute(
      "file_read", ...) - acquisition is not duplicated or bypassed.
    - The function's signature has no seam for supplying content and its
      source label independently, and no seam for handing it a pre-existing
      ToolResult to relabel - provenance is established by construction, not
      by caller discipline.
    - A failed acquisition (missing file, binary file, etc.) never produces
      a context block, and the failure text is returned as an error, never
      mistaken for real file content.
    - session_id and max_chars are forwarded to the real ToolExecutor/
      FileReadTool contract unchanged.

Run with:
    pytest tests/unit/test_file_ingestion.py
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ai.file_ingestion import FileIngestionResult, ingest_file_for_ai
from config.constants import ContentTrust, SecurityTier
from security.security_manager import SecurityManager
from tools.builtin import FileReadTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _RecordingLogger:
    """Stands in for the concrete EventLogger, recording every emit() call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


@pytest.fixture()
def logger() -> _RecordingLogger:
    return _RecordingLogger()


@pytest.fixture()
def executor(logger: _RecordingLogger) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register_tool(FileReadTool())
    return ToolExecutor(
        registry=registry,
        security_manager=SecurityManager(),
        logger=logger,  # type: ignore[arg-type]
    )


@pytest.fixture()
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "note.txt"
    path.write_text("Hello Jarvis! This is real file content.\n", encoding="utf-8")
    return path


# --- Successful acquisition ---------------------------------------------------


def test_successful_acquisition_returns_untrusted_context(
    executor: ToolExecutor, text_file: Path
) -> None:
    result = ingest_file_for_ai(executor, str(text_file))

    assert result.success is True
    assert result.error is None
    assert result.context is not None
    assert result.context.trust is ContentTrust.UNTRUSTED


def test_successful_acquisition_contains_the_actual_file_content(
    executor: ToolExecutor, text_file: Path
) -> None:
    result = ingest_file_for_ai(executor, str(text_file))

    assert result.context is not None
    assert "Hello Jarvis! This is real file content." in result.context.text


def test_source_label_identifies_the_exact_path_requested(
    executor: ToolExecutor, text_file: Path
) -> None:
    result = ingest_file_for_ai(executor, str(text_file))

    assert result.context is not None
    assert result.context.source == f"file:{text_file}"


def test_ingestion_never_produces_jarvis_trusted(
    executor: ToolExecutor, text_file: Path
) -> None:
    result = ingest_file_for_ai(executor, str(text_file))

    assert result.context is not None
    assert result.context.trust is not ContentTrust.JARVIS_TRUSTED


# --- The function itself performs acquisition (no bypass, no duplication) ---


def test_ingestion_itself_invokes_file_read(
    executor: ToolExecutor, text_file: Path, logger: _RecordingLogger
) -> None:
    """Acquisition goes through the real, already-secured file_read tool -
    proven by the real tool_call/SUCCESS audit event it always produces."""
    ingest_file_for_ai(executor, str(text_file))

    tool_calls = [c for c in logger.calls if c.get("action_type") == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["security_tier"] is SecurityTier.GREEN


def test_a_nonexistent_path_still_goes_through_the_real_tool(
    executor: ToolExecutor, logger: _RecordingLogger, tmp_path: Path
) -> None:
    ingest_file_for_ai(executor, str(tmp_path / "does_not_exist.txt"))

    tool_calls = [c for c in logger.calls if c.get("action_type") == "tool_call"]
    assert len(tool_calls) == 1


# --- Provenance established by construction, not by caller discipline -------


def test_signature_has_no_seam_for_independent_content_and_source() -> None:
    """The only external content-location input is `path`. There is no
    parameter through which a caller could supply file text and a source
    label independently, so the two can never describe different things."""
    params = set(inspect.signature(ingest_file_for_ai).parameters)
    assert params == {"executor", "path", "session_id", "max_chars"}
    assert "text" not in params
    assert "source" not in params
    assert "content" not in params


def test_signature_does_not_accept_a_pre_existing_tool_result() -> None:
    """The function cannot be used to relabel arbitrary pre-existing
    ToolResult content as file provenance, because it never accepts a
    ToolResult at all - only a path it reads itself."""
    params = inspect.signature(ingest_file_for_ai).parameters
    assert "tool_result" not in params
    assert "result" not in params


def test_same_path_always_produces_the_same_source_label(
    executor: ToolExecutor, text_file: Path
) -> None:
    first = ingest_file_for_ai(executor, str(text_file))
    second = ingest_file_for_ai(executor, str(text_file))
    assert first.context is not None
    assert second.context is not None
    assert first.context.source == second.context.source == f"file:{text_file}"


# --- Failure is represented as data, never as a raised exception ------------


def test_missing_file_does_not_raise_and_produces_no_context(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    result = ingest_file_for_ai(executor, str(tmp_path / "missing.txt"))

    assert result.success is False
    assert result.context is None
    assert result.error is not None
    assert "does not exist" in result.error


def test_binary_file_produces_no_context(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    path = tmp_path / "image.bin"
    path.write_bytes(b"\x89PNG\r\n\x00\x00\x00binary\x00stuff")

    result = ingest_file_for_ai(executor, str(path))

    assert result.success is False
    assert result.context is None
    assert result.error is not None
    assert "binary" in result.error.lower()


def test_directory_path_produces_no_context(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    result = ingest_file_for_ai(executor, str(tmp_path))

    assert result.success is False
    assert result.context is None


def test_failure_text_is_never_mistaken_for_file_content(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    """The error string belongs in FileIngestionResult.error, never wrapped
    into an AIContextBlock as if it were the file's own content."""
    result = ingest_file_for_ai(executor, str(tmp_path / "missing.txt"))

    assert result.context is None
    assert isinstance(result.error, str)


def test_missing_path_does_not_raise(executor: ToolExecutor) -> None:
    result = ingest_file_for_ai(executor, "")
    assert result.success is False
    assert result.context is None
    assert result.error is not None


# --- session_id / max_chars forwarding ---------------------------------------


def test_session_id_is_forwarded_to_the_real_executor(
    executor: ToolExecutor, text_file: Path, logger: _RecordingLogger
) -> None:
    ingest_file_for_ai(executor, str(text_file), session_id=99)

    tool_calls = [c for c in logger.calls if c.get("action_type") == "tool_call"]
    assert tool_calls[0]["session_id"] == 99


def test_max_chars_is_forwarded_and_truncation_is_preserved(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    path = tmp_path / "big.txt"
    path.write_text("A" * 10_000, encoding="utf-8")

    result = ingest_file_for_ai(executor, str(path), max_chars=100)

    assert result.context is not None
    # Split off the "Contents of <path>:" header, since the temp path itself
    # (e.g. AppData) may contain the letter being counted.
    body = result.context.text.split("\n", 1)[1]
    assert body.count("A") == 100
    assert "truncated" in result.context.text.lower()


def test_default_max_chars_matches_file_read_tool_default(
    executor: ToolExecutor, tmp_path: Path
) -> None:
    path = tmp_path / "big.txt"
    path.write_text("A" * 10_000, encoding="utf-8")

    result = ingest_file_for_ai(executor, str(path))

    assert result.context is not None
    body = result.context.text.split("\n", 1)[1]
    assert body.count("A") == 4000


# --- FileIngestionResult itself ------------------------------------------------


def test_result_is_frozen() -> None:
    import dataclasses

    result = FileIngestionResult(error="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.error = "y"  # type: ignore[misc]


def test_result_success_property_reflects_context_presence() -> None:
    from ai.context_models import AIContextBlock

    assert FileIngestionResult(context=None, error="x").success is False
    block = AIContextBlock.from_untrusted("text", source="file:x.txt")
    assert FileIngestionResult(context=block).success is True


# --- FileIngestionResult cannot represent a contradictory outcome -----------


def test_result_rejects_both_context_and_error_set() -> None:
    from ai.context_models import AIContextBlock

    block = AIContextBlock.from_untrusted("text", source="file:x.txt")
    with pytest.raises(ValueError, match="cannot carry both"):
        FileIngestionResult(context=block, error="also failed")


def test_result_rejects_neither_context_nor_error_set() -> None:
    with pytest.raises(ValueError, match="cannot represent neither"):
        FileIngestionResult()


def test_ingest_file_for_ai_never_produces_a_contradictory_result(
    executor: ToolExecutor, text_file: Path, tmp_path: Path
) -> None:
    """Both real code paths (success and failure) always satisfy the
    invariant - proven end to end, not just at the type level."""
    success = ingest_file_for_ai(executor, str(text_file))
    assert (success.context is None) != (success.error is None)

    failure = ingest_file_for_ai(executor, str(tmp_path / "missing.txt"))
    assert (failure.context is None) != (failure.error is None)
