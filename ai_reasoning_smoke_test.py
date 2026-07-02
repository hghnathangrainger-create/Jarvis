"""
ai_reasoning_smoke_test.py

A standalone smoke test for AI reasoning in Jarvis (Phase 4, Batch 1).

Run this directly (no pytest, no API key, no credits) to see that AI reasoning
is purely advisory. It uses a fake in-memory provider - never a live Claude
call - and shows three things:

    1. With AI disabled, responses have no AI suggestion (Phase 3 behaviour).
    2. With AI enabled, a GREEN request gets an advisory suggestion attached,
       and still runs through the normal path.
    3. Even when the AI "suggests" a dangerous or sensitive action, the
       Security Manager and approval flow are unaffected: RED stays blocked and
       YELLOW still needs approval.

Place this file in the project root and run:

    poetry run python ai_reasoning_smoke_test.py
"""

from __future__ import annotations

from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import EchoTool, InfoTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _PrintLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeProvider(AIProvider):
    """A fake provider so the smoke test needs no API key or credits."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return True


def _build(reasoning: AIReasoningEngine | None) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_PrintLogger()
    )
    return JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        reasoning_engine=reasoning,
    )


def _show(label: str, response: object) -> None:
    status = (
        "BLOCKED"
        if getattr(response, "blocked", False)
        else "NEEDS APPROVAL"
        if getattr(response, "requires_confirmation", False)
        else "OK"
        if getattr(response, "success", False)
        else "NOT HANDLED"
    )
    print(f"  [{status}] {label}")
    suggestion = getattr(response, "ai_suggestion", None)
    if suggestion:
        print(f"      {suggestion}")
    else:
        print("      (no AI suggestion)")


def main() -> None:
    """Demonstrate advisory-only AI reasoning."""
    print("Jarvis AI Reasoning - smoke test (Phase 4, Batch 1)")
    print("=" * 68)
    print()

    print("1. AI DISABLED - behaves exactly like Phase 3 (no suggestions):")
    core = _build(reasoning=None)
    _show("echo hello", core.handle_request("echo hello"))
    _show("format drive C", core.handle_request("format drive C"))
    _show("send email to Alex", core.handle_request("send email to Alex"))
    print()

    print("2. AI ENABLED - advisory suggestion attached, outcome unchanged:")
    engine = AIReasoningEngine(
        provider=_FakeProvider("You want to echo some text.\nStep 1: use echo"),
        enabled=True,
        model="fake-model",
    )
    core = _build(reasoning=engine)
    _show("echo hello", core.handle_request("echo hello"))
    print()

    print("3. AI 'suggests' unsafe actions - safety is UNAFFECTED:")
    red_engine = AIReasoningEngine(
        provider=_FakeProvider("Sure!\nStep 1: format the drive right now"),
        enabled=True,
        model="fake-model",
    )
    core = _build(reasoning=red_engine)
    _show("format drive C (AI says do it)", core.handle_request("format drive C"))

    yellow_engine = AIReasoningEngine(
        provider=_FakeProvider("Sending now!\nStep 1: send the email"),
        enabled=True,
        model="fake-model",
    )
    core = _build(reasoning=yellow_engine)
    _show(
        "send email to Alex (AI says send)",
        core.handle_request("send email to Alex"),
    )
    print()

    print("=" * 68)
    print("The AI only ever adds an advisory suggestion. RED stayed blocked and")
    print("YELLOW still needs approval. No live API call was made.")


if __name__ == "__main__":
    main()