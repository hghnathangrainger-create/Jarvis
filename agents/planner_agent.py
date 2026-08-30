"""
planner_agent.py

Planner Support Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take a complex goal and generate workflow suggestions.
    - Break down tasks into steps with dependencies.
    - Estimate complexity and time requirements.
    - Final planning decisions always remain with the Planner subsystem.

Safety:
    - GREEN-only tool access by default.
    - Cannot spawn other agents.
    - Only suggests — never overrides the Planner.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentConfig, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a workflow planning assistant. Your job is to:
1. Analyze complex goals and break them into steps.
2. Identify dependencies between steps.
3. Estimate complexity and time for each step.
4. Suggest the most efficient workflow.

IMPORTANT: You only SUGGEST workflows. Final planning decisions
are made by the Planner subsystem. Your output is advisory only.

Format your suggestions with clear step numbers, dependencies,
and estimated time/complexity."""


class PlannerSupportAgent(BaseAgent):
    """Agent that suggests workflows without overriding the Planner.

    Takes a complex goal, generates workflow suggestions with step
    breakdowns, estimates complexity and dependencies. Final planning
    decisions always remain with the Planner subsystem.

    Attributes:
        _ai_router: The AI router for generating responses.
    """

    def __init__(
        self,
        ai_router: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the planner support agent.

        Args:
            ai_router: The AI router for generating responses.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.PLANNER_SUPPORT,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Workflow planning suggestions agent",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a planning suggestion task.

        Args:
            task: The planning task.

        Returns:
            Tuple of (result_text, tokens_used).
        """
        prompt = task.prompt
        tokens_used = 0

        # Use AI router if available
        if self._ai_router is not None:
            try:
                response = self._ai_router.route(
                    system_instruction=self._config.system_prompt,
                    user_message=prompt,
                )
                result = response.text
                tokens_used = (response.input_tokens or 0) + (response.output_tokens or 0)

                # Add advisory note
                result += "\n\n---\n📋 *This is a workflow suggestion. Final planning decisions are made by the Planner subsystem.*"

                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for planning task: %s", exc)

        # Fallback: basic planning template
        result = self._generate_basic_plan(prompt)
        return result, tokens_used

    def _generate_basic_plan(self, goal: str) -> str:
        """Generate a basic planning template without AI.

        Args:
            goal: The goal to plan for.

        Returns:
            A planning template.
        """
        return f"""## Workflow Suggestion: {goal}

### Step Breakdown

| Step | Description | Dependencies | Complexity | Est. Time |
|------|-------------|--------------|------------|-----------|
| 1 | [First step] | None | Low | 15 min |
| 2 | [Second step] | Step 1 | Medium | 30 min |
| 3 | [Third step] | Steps 1, 2 | High | 45 min |

### Dependencies Graph
```
Step 1 --> Step 2 --> Step 3
Step 1 ---------> Step 3
```

### Risk Assessment
- **Low Risk**: [Steps with low risk]
- **Medium Risk**: [Steps with medium risk]
- **High Risk**: [Steps with high risk]

### Recommendations
1. [Recommendation 1]
2. [Recommendation 2]
3. [Recommendation 3]

---
📋 *This is a workflow suggestion. Final planning decisions are made by the Planner subsystem.*

*Note: This is a basic template. For detailed planning suggestions,
ensure the AI router is configured and available.*
"""
