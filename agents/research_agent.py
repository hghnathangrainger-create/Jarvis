"""
research_agent.py

Research Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take a research prompt and generate structured findings.
    - Use AI to generate research queries and summaries.
    - Optionally save results to the Knowledge Library.

Safety:
    - GREEN-only tool access by default.
    - Cannot spawn other agents.
    - Cannot access memory outside assigned scope.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentConfig, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a research assistant. Your job is to:
1. Analyze the research topic provided.
2. Generate key research questions.
3. Provide a structured summary of findings.
4. Organize information with clear sections.

Always cite sources when possible. Be thorough but concise.
Format your response with clear headings and bullet points."""


class ResearchAgent(BaseAgent):
    """Agent specialising in research and information gathering.

    Takes a research prompt, uses AI to generate research queries,
    structures findings into a summary, and optionally saves results
    to the Knowledge Library.

    Attributes:
        _ai_router: The AI router for generating responses.
        _knowledge_manager: Optional knowledge manager for saving results.
    """

    def __init__(
        self,
        ai_router: Any = None,
        knowledge_manager: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the research agent.

        Args:
            ai_router: The AI router for generating responses.
            knowledge_manager: Optional knowledge manager for saving results.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.RESEARCH,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Research and information gathering agent",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router
        self._knowledge_manager = knowledge_manager

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a research task.

        Args:
            task: The research task.

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

                # Save to knowledge library if available
                if self._knowledge_manager is not None:
                    try:
                        self._knowledge_manager.add_knowledge(
                            title=f"Research: {prompt[:100]}",
                            content=result,
                            category="research",
                            tags=["agent", "research"],
                            source="research_agent",
                        )
                    except Exception as exc:
                        logger.warning("Failed to save research to knowledge library: %s", exc)

                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for research task: %s", exc)
                # Fall through to basic response

        # Fallback: basic research framework
        result = self._generate_basic_research(prompt)
        return result, tokens_used

    def _generate_basic_research(self, prompt: str) -> str:
        """Generate a basic research framework without AI.

        Args:
            prompt: The research topic.

        Returns:
            A structured research template.
        """
        return f"""## Research Summary: {prompt}

### Key Questions
- What are the main concepts related to this topic?
- What are the current trends or developments?
- What are the practical applications?

### Findings
[Research findings would be populated here based on available data sources]

### Sources
[Sources would be listed here]

### Recommendations
[Based on the research, recommendations would be provided here]

---
*Note: This is a basic research template. For more detailed analysis,
ensure the AI router is configured and available.*
"""
