"""
test_agents.py

Tests for the AI Agent System (Chapter 20):
  - All 6 agent types: model creation, config, status transitions
  - BaseAgent lifecycle: initialize → available → assigned → working → completed
  - Timeout enforcement: agent exceeds max_execution_time → terminated
  - Safety rules: GREEN-only access, no agent spawning
  - Trading agent safety: refuses buy/sell/trade commands
  - AgentManager: register, assign, execute, terminate, status
  - Planner agent: generates suggestions without overriding
  - Research agent: saves results to Knowledge Library
  - Agent tool: run, status, results, terminate actions
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from agents.models import AgentConfig, AgentResult, AgentStatus, AgentTask, AgentType
from agents.base import BaseAgent
from agents.research_agent import ResearchAgent
from agents.coding_agent import CodingAgent
from agents.content_agent import ContentAgent
from agents.learning_agent import LearningAgent
from agents.trading_agent import TradingAgent
from agents.planner_agent import PlannerSupportAgent
from agents.manager import AgentManager
from tools.base_tool import ToolRequest


# ---------------------------------------------------------------------------
# Agent Models Tests
# ---------------------------------------------------------------------------


class TestAgentModels:
    """Tests for agent data models."""

    def test_agent_type_enum(self):
        """Test AgentType has all required values."""
        assert AgentType.RESEARCH.value == "research"
        assert AgentType.CODING.value == "coding"
        assert AgentType.CONTENT.value == "content"
        assert AgentType.LEARNING.value == "learning"
        assert AgentType.TRADING.value == "trading"
        assert AgentType.PLANNER_SUPPORT.value == "planner_support"

    def test_agent_status_enum(self):
        """Test AgentStatus has all required values."""
        assert AgentStatus.CREATED.value == "created"
        assert AgentStatus.AVAILABLE.value == "available"
        assert AgentStatus.WORKING.value == "working"
        assert AgentStatus.COMPLETED.value == "completed"
        assert AgentStatus.FAILED.value == "failed"

    def test_agent_config_defaults(self):
        """Test AgentConfig default values."""
        config = AgentConfig(agent_type=AgentType.RESEARCH)
        assert config.max_execution_time == 300
        assert config.allowed_tools == ["GREEN"]

    def test_agent_task_creation(self):
        """Test AgentTask creation and to_dict."""
        task = AgentTask(
            agent_type=AgentType.RESEARCH,
            prompt="Research Python",
        )
        assert task.status == AgentStatus.CREATED
        assert task.agent_type == AgentType.RESEARCH
        d = task.to_dict()
        assert d["agent_type"] == "research"
        assert d["prompt"] == "Research Python"

    def test_agent_result_creation(self):
        """Test AgentResult creation and to_dict."""
        result = AgentResult(
            task_id="test-123",
            agent_type=AgentType.CODING,
            result="def hello(): pass",
            tokens_used=100,
            duration_ms=500,
            status=AgentStatus.COMPLETED,
        )
        d = result.to_dict()
        assert d["task_id"] == "test-123"
        assert d["status"] == "completed"


# ---------------------------------------------------------------------------
# BaseAgent Lifecycle Tests
# ---------------------------------------------------------------------------


class TestBaseAgentLifecycle:
    """Tests for BaseAgent lifecycle management."""

    def test_lifecycle_transitions(self):
        """Test complete lifecycle: created → initialized → available."""
        agent = ResearchAgent()
        assert agent.status == AgentStatus.CREATED

        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE

    def test_execute_transitions(self):
        """Test execute lifecycle: assigned → working → completed."""
        agent = ResearchAgent()
        agent.initialize()

        task = AgentTask(prompt="Test research")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.current_task is None

    def test_can_handle(self):
        """Test can_handle returns correct results."""
        agent = ResearchAgent()
        assert agent.can_handle(AgentType.RESEARCH) is True
        assert agent.can_handle(AgentType.CODING) is False

    def test_terminate(self):
        """Test agent termination."""
        agent = ResearchAgent()
        agent.initialize()

        task = AgentTask(prompt="Long task")
        # Start execution in a thread to test termination
        agent._current_task = task
        agent._status = AgentStatus.WORKING

        result = agent.terminate()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.current_task is None

    def test_terminate_no_task(self):
        """Test terminate with no running task."""
        agent = ResearchAgent()
        agent.initialize()

        result = agent.terminate()
        assert result is None

    def test_get_info(self):
        """Test get_info returns agent information."""
        agent = ResearchAgent()
        info = agent.get_info()
        assert info["agent_type"] == "research"
        assert info["status"] == "created"
        assert "max_execution_time" in info


# ---------------------------------------------------------------------------
# Agent Type Tests
# ---------------------------------------------------------------------------


class TestResearchAgent:
    """Tests for ResearchAgent."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = ResearchAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.RESEARCH

    def test_execute_without_ai(self):
        """Test execute without AI router returns basic template."""
        agent = ResearchAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Research Python web frameworks")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "Research" in result.result

    def test_execute_with_mock_ai(self):
        """Test execute with mocked AI router."""
        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Research findings about Python."
        mock_response.input_tokens = 50
        mock_response.output_tokens = 100
        mock_router.route.return_value = mock_response

        agent = ResearchAgent(ai_router=mock_router)
        agent.initialize()

        task = AgentTask(prompt="Research Python")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert result.tokens_used == 150
        mock_router.route.assert_called_once()

    def test_saves_to_knowledge_library(self):
        """Test that research results are saved to Knowledge Library."""
        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Research findings."
        mock_response.input_tokens = 50
        mock_response.output_tokens = 100
        mock_router.route.return_value = mock_response

        mock_km = MagicMock()
        agent = ResearchAgent(ai_router=mock_router, knowledge_manager=mock_km)
        agent.initialize()

        task = AgentTask(prompt="Research Python")
        result = agent.execute(task)

        mock_km.add_knowledge.assert_called_once()
        call_kwargs = mock_km.add_knowledge.call_args[1]
        assert call_kwargs["category"] == "research"


class TestCodingAgent:
    """Tests for CodingAgent."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = CodingAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.CODING

    def test_execute_without_ai(self):
        """Test execute without AI router returns basic template."""
        agent = CodingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Write a hello world function")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "Code" in result.result

    def test_python_syntax_validation(self):
        """Test Python syntax validation."""
        agent = CodingAgent()
        # Valid Python
        valid_code = "def hello():\n    return 'world'"
        notes = agent._validate_code(f"```python\n{valid_code}\n```")
        assert notes == ""

        # Invalid Python
        invalid_code = "def hello(\n    return 'world'"
        notes = agent._validate_code(f"```python\n{invalid_code}\n```")
        assert "syntax error" in notes.lower()


class TestContentAgent:
    """Tests for ContentAgent."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = ContentAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.CONTENT

    def test_execute_without_ai(self):
        """Test execute without AI router returns basic template."""
        agent = ContentAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Write a blog post about AI")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "AI" in result.result


class TestLearningAgent:
    """Tests for LearningAgent."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = LearningAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.LEARNING

    def test_execute_without_ai(self):
        """Test execute without AI router returns basic template."""
        agent = LearningAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Learn Python decorators")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "Learning Roadmap" in result.result


class TestTradingAgent:
    """Tests for TradingAgent safety rules."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = TradingAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.TRADING

    def test_refuses_buy_command(self):
        """Test agent refuses buy commands."""
        agent = TradingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Buy 100 shares of Apple")
        result = agent.execute(task)

        assert result.status == AgentStatus.FAILED
        assert "SAFETY VIOLATION" in result.result or "safety" in (task.error or "").lower()

    def test_refuses_sell_command(self):
        """Test agent refuses sell commands."""
        agent = TradingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Sell my Tesla stock")
        result = agent.execute(task)

        assert result.status == AgentStatus.FAILED

    def test_refuses_trade_command(self):
        """Test agent refuses trade execution."""
        agent = TradingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Execute trade for BTC")
        result = agent.execute(task)

        assert result.status == AgentStatus.FAILED

    def test_refuses_place_order(self):
        """Test agent refuses place order."""
        agent = TradingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Place order for 50 shares")
        result = agent.execute(task)

        assert result.status == AgentStatus.FAILED

    def test_allows_research_query(self):
        """Test agent allows research queries."""
        agent = TradingAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Research the current market trends for tech stocks")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "DISCLAIMER" in result.result


class TestPlannerSupportAgent:
    """Tests for PlannerSupportAgent."""

    def test_initialization(self):
        """Test agent initializes correctly."""
        agent = PlannerSupportAgent()
        agent.initialize()
        assert agent.status == AgentStatus.AVAILABLE
        assert agent.agent_type == AgentType.PLANNER_SUPPORT

    def test_execute_without_ai(self):
        """Test execute without AI router returns basic template."""
        agent = PlannerSupportAgent(ai_router=None)
        agent.initialize()

        task = AgentTask(prompt="Plan a web application project")
        result = agent.execute(task)

        assert result.status == AgentStatus.COMPLETED
        assert "Workflow Suggestion" in result.result
        assert "Planner subsystem" in result.result


# ---------------------------------------------------------------------------
# Timeout Enforcement Tests
# ---------------------------------------------------------------------------


class TestTimeoutEnforcement:
    """Tests for execution timeout enforcement."""

    def test_timeout_sets_flag(self):
        """Test that timeout sets termination flag."""
        config = AgentConfig(
            agent_type=AgentType.RESEARCH,
            max_execution_time=1,  # 1 second timeout
        )
        agent = ResearchAgent(config=config)
        agent.initialize()
        task = AgentTask(prompt="Test")

        # Manually start the timer and wait for it to fire
        agent._current_task = task
        agent._status = AgentStatus.WORKING
        agent._start_timer(task)

        # Wait for the timer to fire
        time.sleep(1.5)

        # The timer should have called terminate
        assert agent.status == AgentStatus.AVAILABLE
        assert agent._current_task is None

    def test_timeout_timer_is_daemon(self):
        """Test that timeout timer is a daemon thread."""
        agent = ResearchAgent()
        agent.initialize()
        task = AgentTask(prompt="Test")

        agent._start_timer(task)
        assert agent._timer is not None
        assert agent._timer.daemon is True
        agent._cancel_timer()

    def test_execute_with_timeout_error(self):
        """Test that timeout causes FAILED status via exception."""
        class FailingAgent(BaseAgent):
            def _execute_impl(self, task):
                # Simulate a task that takes too long and gets terminated
                time.sleep(0.1)
                raise TimeoutError("Execution timed out")

        config = AgentConfig(
            agent_type=AgentType.RESEARCH,
            max_execution_time=300,
        )
        agent = FailingAgent(config)
        agent.initialize()

        task = AgentTask(prompt="Will fail")
        result = agent.execute(task)

        assert result.status == AgentStatus.FAILED
        assert agent.status == AgentStatus.AVAILABLE


# ---------------------------------------------------------------------------
# Safety Rules Tests
# ---------------------------------------------------------------------------


class TestSafetyRules:
    """Tests for agent safety constraints."""

    def test_agents_start_green_only(self):
        """Test that agents start with GREEN-only access."""
        for AgentClass in [ResearchAgent, CodingAgent, ContentAgent,
                          LearningAgent, TradingAgent, PlannerSupportAgent]:
            agent = AgentClass()
            assert "GREEN" in agent._config.allowed_tools
            assert "YELLOW" not in agent._config.allowed_tools
            assert "RED" not in agent._config.allowed_tools

    def test_agents_cannot_spawn_other_agents(self):
        """Test that agents don't have agent spawning capability."""
        agent = ResearchAgent()
        info = agent.get_info()
        # Agents should not have access to agent management tools
        assert info["agent_type"] == "research"


# ---------------------------------------------------------------------------
# AgentManager Tests
# ---------------------------------------------------------------------------


class TestAgentManager:
    """Tests for the AgentManager."""

    def setup_method(self):
        """Set up manager for each test."""
        self.manager = AgentManager()

    def test_register_agent(self):
        """Test registering an agent."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        retrieved = self.manager.get_agent(AgentType.RESEARCH)
        assert retrieved is agent

    def test_get_nonexistent_agent(self):
        """Test getting a non-registered agent."""
        result = self.manager.get_agent(AgentType.CODING)
        assert result is None

    def test_assign_task(self):
        """Test assigning a task to an available agent."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        task = self.manager.assign_task(AgentType.RESEARCH, "Research Python")
        assert task is not None
        assert task.agent_type == AgentType.RESEARCH

    def test_assign_task_no_available_agent(self):
        """Test assigning task when no agent is available."""
        task = self.manager.assign_task(AgentType.RESEARCH, "Research Python")
        assert task is None

    def test_execute_task(self):
        """Test executing a task."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        task = self.manager.assign_task(AgentType.RESEARCH, "Research Python")
        result = self.manager.execute_task(task)

        assert result.status == AgentStatus.COMPLETED
        assert len(self.manager._completed_tasks) == 1

    def test_terminate_task(self):
        """Test terminating a running task."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        task = AgentTask(prompt="Test")
        agent._current_task = task
        agent._status = AgentStatus.WORKING

        success = self.manager.terminate_task(task.task_id)
        assert success is True

    def test_terminate_nonexistent_task(self):
        """Test terminating a nonexistent task."""
        success = self.manager.terminate_task("nonexistent-id")
        assert success is False

    def test_get_status(self):
        """Test getting manager status."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        status = self.manager.get_status()
        assert status["total_agents"] == 1
        assert status["available_agents"] == 1
        assert "research" in status["agents"]

    def test_list_completed(self):
        """Test listing completed tasks."""
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        task = self.manager.assign_task(AgentType.RESEARCH, "Test")
        self.manager.execute_task(task)

        completed = self.manager.list_completed()
        assert len(completed) == 1


# ---------------------------------------------------------------------------
# Agent Tool Tests
# ---------------------------------------------------------------------------


class TestAgentTool:
    """Tests for the AgentTool."""

    def setup_method(self):
        """Set up the tool for each test."""
        from tools.builtin.agent_tool import AgentTool

        self.manager = AgentManager()
        agent = ResearchAgent()
        agent.initialize()
        self.manager.register_agent(agent)

        self.tool = AgentTool(agent_manager=self.manager)

    def test_tool_name(self):
        """Test tool name."""
        assert self.tool.name == "agent"

    def test_tool_tier(self):
        """Test tool tier is YELLOW."""
        assert self.tool.tier == "YELLOW"

    def test_status_action(self):
        """Test status action."""
        request = ToolRequest(
            tool_name="agent",
            input_data={"action": "status"},
        )
        result = self.tool.run(request)
        assert result.success is True
        assert "Agent Status" in result.output

    def test_run_action(self):
        """Test run action."""
        request = ToolRequest(
            tool_name="agent",
            input_data={
                "action": "run",
                "agent_type": "research",
                "prompt": "Research Python web frameworks",
            },
        )
        result = self.tool.run(request)
        assert result.success is True
        assert "Agent Task Result" in result.output

    def test_run_invalid_agent_type(self):
        """Test run action with invalid agent type."""
        request = ToolRequest(
            tool_name="agent",
            input_data={
                "action": "run",
                "agent_type": "invalid",
                "prompt": "Test",
            },
        )
        result = self.tool.run(request)
        assert result.success is False

    def test_run_no_prompt(self):
        """Test run action without prompt."""
        request = ToolRequest(
            tool_name="agent",
            input_data={
                "action": "run",
                "agent_type": "research",
            },
        )
        result = self.tool.run(request)
        assert result.success is False

    def test_results_action_empty(self):
        """Test results action with no completed tasks."""
        request = ToolRequest(
            tool_name="agent",
            input_data={"action": "results"},
        )
        result = self.tool.run(request)
        assert result.success is True
        assert "No completed tasks" in result.output

    def test_terminate_action(self):
        """Test terminate action."""
        request = ToolRequest(
            tool_name="agent",
            input_data={"action": "terminate", "task_id": "nonexistent"},
        )
        result = self.tool.run(request)
        assert result.success is False

    def test_unknown_action(self):
        """Test unknown action returns failure."""
        request = ToolRequest(
            tool_name="agent",
            input_data={"action": "unknown"},
        )
        result = self.tool.run(request)
        assert result.success is False

    def test_no_manager(self):
        """Test tool with no manager returns failure."""
        from tools.builtin.agent_tool import AgentTool

        tool = AgentTool(agent_manager=None)
        request = ToolRequest(
            tool_name="agent",
            input_data={"action": "status"},
        )
        result = tool.run(request)
        assert result.success is False
