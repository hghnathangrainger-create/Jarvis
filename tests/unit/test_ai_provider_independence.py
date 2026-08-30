"""
test_ai_provider_independence.py

Tests for AI Provider Independence (Chapter 24):
  - OllamaProvider with mocked HTTP calls
  - CostTracker: record, daily/monthly aggregation, provider breakdown, history
  - Budget checking (over budget = switch to Ollama)
  - Router fallback including Ollama as last resort
  - Cost tracking tool queries
  - AIResponse includes cost_usd
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai.cost_tracker import CostTracker, estimate_cost
from ai.providers.base import AIProviderError, AIResponse, AIRequest, AIMessage
from tools.base_tool import ToolRequest


# ---------------------------------------------------------------------------
# CostTracker Tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    """Tests for CostTracker cost recording and aggregation."""

    def setup_method(self):
        """Set up a cost tracker for each test."""
        self.tracker = CostTracker()

    def test_record_call(self):
        """Test recording a single API call."""
        record = self.tracker.record_call(
            provider="claude",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.005,
        )

        daily = self.tracker.get_daily_cost()
        assert daily == pytest.approx(0.005, abs=0.001)
        assert record.provider == "claude"

    def test_record_multiple_calls(self):
        """Test recording multiple API calls and aggregating."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)
        self.tracker.record_call("openai", "gpt-4o", 200, 100, cost_usd=0.01)
        self.tracker.record_call("claude", "claude-3-haiku", 50, 25, cost_usd=0.001)

        daily = self.tracker.get_daily_cost()
        assert daily == pytest.approx(0.016, abs=0.001)

    def test_monthly_cost(self):
        """Test monthly cost aggregation."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)
        self.tracker.record_call("openai", "gpt-4o", 200, 100, cost_usd=0.01)

        monthly = self.tracker.get_monthly_cost()
        assert monthly == pytest.approx(0.015, abs=0.001)

    def test_cost_by_provider(self):
        """Test cost breakdown by provider."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)
        self.tracker.record_call("claude", "claude-3-haiku", 50, 25, cost_usd=0.001)
        self.tracker.record_call("openai", "gpt-4o", 200, 100, cost_usd=0.01)

        by_provider = self.tracker.get_cost_by_provider()
        assert by_provider["claude"] == pytest.approx(0.006, abs=0.001)
        assert by_provider["openai"] == pytest.approx(0.01, abs=0.001)

    def test_cost_history(self):
        """Test cost history retrieval."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        history = self.tracker.get_cost_history(days=7)
        assert isinstance(history, list)
        assert len(history) >= 1

    def test_budget_daily(self):
        """Test daily budget checking."""
        self.tracker._daily_budget = 0.01
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        is_over, reason = self.tracker.is_over_budget()
        assert not is_over

        # Exceed daily budget
        self.tracker.record_call("openai", "gpt-4o", 200, 100, cost_usd=0.01)
        is_over, reason = self.tracker.is_over_budget()
        assert is_over
        assert "Daily budget exceeded" in reason

    def test_budget_monthly(self):
        """Test monthly budget checking."""
        self.tracker._monthly_budget = 0.02
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        is_over, _ = self.tracker.is_over_budget()
        assert not is_over

        # Exceed monthly budget
        self.tracker.record_call("openai", "gpt-4o", 200, 100, cost_usd=0.03)
        is_over, reason = self.tracker.is_over_budget()
        assert is_over
        assert "Monthly budget exceeded" in reason

    def test_no_budget_set(self):
        """Test that no budget means never over budget."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=100.0)
        is_over, _ = self.tracker.is_over_budget()
        assert not is_over

    def test_ollama_zero_cost(self):
        """Test that Ollama calls record zero cost."""
        record = self.tracker.record_call("ollama", "llama3", 100, 50, cost_usd=0.0)

        daily = self.tracker.get_daily_cost()
        assert daily == 0.0

    def test_budget_status(self):
        """Test budget status reporting."""
        self.tracker._daily_budget = 10.0
        self.tracker._monthly_budget = 100.0
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        status = self.tracker.get_budget_status()
        assert status["daily_budget_usd"] == 10.0
        assert status["monthly_budget_usd"] == 100.0
        assert status["is_over_budget"] is False
        assert status["daily_remaining_usd"] > 0

    def test_set_budget(self):
        """Test setting budget limits."""
        self.tracker.set_budget(daily=5.0, monthly=50.0)
        assert self.tracker._daily_budget == 5.0
        assert self.tracker._monthly_budget == 50.0

    def test_get_budget_status_no_cost(self):
        """Test budget status with no costs recorded."""
        status = self.tracker.get_budget_status()
        assert status["daily_cost_usd"] == 0.0
        assert status["monthly_cost_usd"] == 0.0
        assert status["is_over_budget"] is False


# ---------------------------------------------------------------------------
# Cost Estimation Tests
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """Tests for the estimate_cost function."""

    def test_claude_sonnet_cost(self):
        """Test Claude Sonnet cost estimation."""
        cost = estimate_cost("claude", "claude-sonnet-4-6", 1000, 500)
        # Claude Sonnet: $3/$15 per 1M tokens
        expected = (1000 / 1_000_000 * 3) + (500 / 1_000_000 * 15)
        assert cost == pytest.approx(expected, rel=0.01)

    def test_claude_haiku_cost(self):
        """Test Claude Haiku cost estimation."""
        cost = estimate_cost("claude", "claude-3-haiku", 1000, 500)
        # Claude Haiku: $0.25/$1.25 per 1M tokens
        expected = (1000 / 1_000_000 * 0.25) + (500 / 1_000_000 * 1.25)
        assert cost == pytest.approx(expected, rel=0.01)

    def test_gpt4o_cost(self):
        """Test GPT-4o cost estimation."""
        cost = estimate_cost("openai", "gpt-4o", 1000, 500)
        # GPT-4o: $2.50/$10 per 1M tokens
        expected = (1000 / 1_000_000 * 2.50) + (500 / 1_000_000 * 10)
        assert cost == pytest.approx(expected, rel=0.01)

    def test_gpt4o_mini_cost(self):
        """Test GPT-4o-mini cost estimation."""
        cost = estimate_cost("openai", "gpt-4o-mini", 1000, 500)
        # GPT-4o-mini: $0.15/$0.60 per 1M tokens
        expected = (1000 / 1_000_000 * 0.15) + (500 / 1_000_000 * 0.60)
        assert cost == pytest.approx(expected, rel=0.01)

    def test_gemini_flash_cost(self):
        """Test Gemini Flash cost estimation."""
        cost = estimate_cost("gemini", "gemini-2.0-flash", 1000, 500)
        # Gemini Flash: $0.075/$0.30 per 1M tokens
        expected = (1000 / 1_000_000 * 0.075) + (500 / 1_000_000 * 0.30)
        assert cost == pytest.approx(expected, rel=0.01)

    def test_ollama_zero_cost(self):
        """Test Ollama has zero cost."""
        cost = estimate_cost("ollama", "llama3", 1000, 500)
        assert cost == 0.0

    def test_unknown_provider_fallback(self):
        """Test unknown provider defaults to GPT-4o rates."""
        cost = estimate_cost("unknown", "mystery-model", 1000, 500)
        # Should use GPT-4o rates as fallback
        expected = (1000 / 1_000_000 * 2.50) + (500 / 1_000_000 * 10)
        assert cost == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# AIResponse Cost Field Tests
# ---------------------------------------------------------------------------


class TestAIResponseCostField:
    """Tests that AIResponse includes cost_usd field."""

    def test_response_includes_cost(self):
        """Test that AIResponse can include cost_usd."""
        response = AIResponse(
            text="Hello",
            model="claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=5,
            provider="claude",
            cost_usd=0.001,
        )
        assert response.cost_usd == 0.001

    def test_response_cost_default_zero(self):
        """Test that AIResponse cost_usd defaults to 0.0."""
        response = AIResponse(
            text="Hello",
            model="test",
            input_tokens=10,
            output_tokens=5,
        )
        assert response.cost_usd == 0.0


# ---------------------------------------------------------------------------
# OllamaProvider Tests (with mocked HTTP)
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    """Tests for OllamaProvider with mocked HTTP calls."""

    def test_provider_name(self):
        """Test provider name is 'ollama'."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()
        assert provider.name == "ollama"

    def test_provider_custom_config(self):
        """Test provider with custom base_url and model."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            base_url="http://custom-host:11434",
            default_model="mistral",
        )
        assert provider._base_url == "http://custom-host:11434"
        assert provider._default_model == "mistral"

    def test_is_available_when_server_running(self):
        """Test is_available returns True when Ollama server is running."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert provider.is_available() is True

    def test_is_available_when_server_down(self):
        """Test is_available returns False when Ollama server is not running."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()

        with patch("httpx.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            assert provider.is_available() is False

    def test_generate_request_format(self):
        """Test that generate sends correct request format."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(default_model="llama3")

        request = AIRequest(
            system="You are a helpful assistant.",
            messages=(AIMessage(role="user", content="Hello"),),
            model="llama3",
            max_tokens=100,
        )

        # Mock the client directly since ollama may not be installed
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "Hi there!"},
            "eval_count": 10,
            "prompt_eval_count": 5,
        }
        provider._client = mock_client

        response = provider.generate(request)
        assert response.text == "Hi there!"
        assert response.provider == "ollama"
        assert response.model == "llama3"
        assert response.cost_usd == 0.0

    def test_cost_properties(self):
        """Test that cost properties return zero."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()
        assert provider.cost_per_input_token == 0.0
        assert provider.cost_per_output_token == 0.0

    def test_generate_failure(self):
        """Test that generate raises AIProviderError on failure."""
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()

        # Mock the client directly since ollama may not be installed
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("Server error")
        provider._client = mock_client

        request = AIRequest(
            system="test",
            messages=(AIMessage(role="user", content="Hello"),),
            model="llama3",
            max_tokens=100,
        )

        with pytest.raises(AIProviderError, match="Ollama request failed"):
            provider.generate(request)


# ---------------------------------------------------------------------------
# CostTrackingTool Tests
# ---------------------------------------------------------------------------


class TestCostTrackingTool:
    """Tests for the CostTrackingTool."""

    def setup_method(self):
        """Set up the tool with a temporary tracker."""
        from tools.builtin.cost_tracking_tool import CostTrackingTool

        self.tracker = CostTracker()
        self.tool = CostTrackingTool(cost_tracker=self.tracker)

    def test_tool_name(self):
        """Test tool name."""
        assert self.tool.name == "cost_tracking"

    def test_tool_tier(self):
        """Test tool tier is GREEN."""
        assert self.tool.tier == "GREEN"

    def test_summary_action(self):
        """Test summary action returns cost data."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "summary"})
        result = self.tool.run(request)
        assert result.success is True
        assert "Cost Summary" in result.output
        assert "claude" in result.output

    def test_history_action(self):
        """Test history action returns cost history."""
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "history", "days": 7})
        result = self.tool.run(request)
        assert result.success is True
        assert "Cost History" in result.output

    def test_budget_action_no_budget(self):
        """Test budget action with no budget set."""
        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "budget"})
        result = self.tool.run(request)
        assert result.success is True
        assert "Budget Status" in result.output
        assert "no budget set" in result.output

    def test_budget_action_with_budget(self):
        """Test budget action with budget set."""
        self.tracker._daily_budget = 10.0
        self.tracker.record_call("claude", "claude-sonnet-4-6", 100, 50, cost_usd=0.005)

        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "budget"})
        result = self.tool.run(request)
        assert result.success is True
        assert "$10.00" in result.output

    def test_set_budget_action(self):
        """Test set_budget action updates budget."""
        request = ToolRequest(
            tool_name="cost_tracking",
            input_data={"action": "set_budget", "daily_budget": 5.0, "monthly_budget": 100.0},
        )
        result = self.tool.run(request)
        assert result.success is True
        assert "Budget updated" in result.output
        assert "$5.00" in result.output
        assert "$100.00" in result.output

    def test_no_tracker_returns_failure(self):
        """Test that tool returns failure when no tracker is available."""
        from tools.builtin.cost_tracking_tool import CostTrackingTool

        tool = CostTrackingTool(cost_tracker=None)
        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "summary"})
        result = tool.run(request)
        assert result.success is False

    def test_unknown_action_returns_failure(self):
        """Test that unknown action returns failure."""
        request = ToolRequest(tool_name="cost_tracking", input_data={"action": "unknown"})
        result = self.tool.run(request)
        assert result.success is False


# ---------------------------------------------------------------------------
# Router Fallback Tests (including Ollama)
# ---------------------------------------------------------------------------


class TestRouterFallback:
    """Tests for AI router fallback including Ollama."""

    def test_parse_ollama_model_string(self):
        """Test parsing ollama:llama3 model string."""
        from ai.router import parse_model_string

        mock_provider = MagicMock()
        mock_provider.name = "ollama"

        claude_provider = MagicMock()
        claude_provider.name = "claude"

        providers = (claude_provider, mock_provider)
        provider, model = parse_model_string("ollama:llama3", providers)

        assert provider.name == "ollama"
        assert model == "llama3"

    def test_parse_auto_model_string(self):
        """Test parsing auto model string returns first provider."""
        from ai.router import parse_model_string

        claude_provider = MagicMock()
        claude_provider.name = "claude"
        ollama_provider = MagicMock()
        ollama_provider.name = "ollama"

        providers = (claude_provider, ollama_provider)
        provider, model = parse_model_string("auto", providers)

        assert provider.name == "claude"

    def test_parse_plain_model_string(self):
        """Test parsing plain model string uses first provider."""
        from ai.router import parse_model_string

        claude_provider = MagicMock()
        claude_provider.name = "claude"
        ollama_provider = MagicMock()
        ollama_provider.name = "ollama"

        providers = (claude_provider, ollama_provider)
        provider, model = parse_model_string("my-model", providers)

        assert provider.name == "claude"
        assert model == "my-model"
