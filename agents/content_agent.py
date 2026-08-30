"""
content_agent.py

Content Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take a content request and generate formatted content via AI.
    - Return formatted text with optional markdown.

Safety:
    - GREEN-only tool access by default.
    - Cannot spawn other agents.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentConfig, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a content creation assistant. Your job is to:
1. Understand the content request.
2. Create well-structured, engaging content.
3. Use appropriate formatting (headers, lists, emphasis).
4. Maintain a consistent tone and style.

Format your output with proper markdown for readability."""


class ContentAgent(BaseAgent):
    """Agent specialising in content creation and formatting.

    Takes a content request, generates content via AI, and returns
    formatted text with optional markdown.

    Attributes:
        _ai_router: The AI router for generating responses.
    """

    def __init__(
        self,
        ai_router: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the content agent.

        Args:
            ai_router: The AI router for generating responses.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.CONTENT,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Content creation and formatting agent",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a content creation task.

        Args:
            task: The content task.

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
                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for content task: %s", exc)

        # Fallback: basic content template
        result = self._generate_basic_content(prompt)
        return result, tokens_used

    def _generate_basic_content(self, prompt: str) -> str:
        """Generate a basic content template without AI.

        Args:
            prompt: The content request.

        Returns:
            A content template.
        """
        return f"""## {prompt}

### Introduction
[Introduction content would be generated here]

### Main Content
[Main content body would be generated here]

### Conclusion
[Conclusion content would be generated here]

---
*Note: This is a basic template. For actual content generation,
ensure the AI router is configured and available.*
"""
