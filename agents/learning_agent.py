"""
learning_agent.py

Learning Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take a learning topic and generate a study roadmap.
    - Organize concepts hierarchically.
    - Optionally save to Knowledge Library as learning materials.

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

_SYSTEM_PROMPT = """You are a learning assistant. Your job is to:
1. Analyze the learning topic.
2. Create a structured study roadmap.
3. Organize concepts from basic to advanced.
4. Include practice exercises and resources.
5. Estimate time requirements for each section.

Use clear headings, bullet points, and progress indicators.
Make the learning path logical and achievable."""


class LearningAgent(BaseAgent):
    """Agent specialising in educational content and study plans.

    Takes a learning topic, generates a study roadmap, organizes concepts
    hierarchically, and optionally saves to Knowledge Library.

    Attributes:
        _ai_router: The AI router for generating responses.
        _knowledge_manager: Optional knowledge manager for saving materials.
    """

    def __init__(
        self,
        ai_router: Any = None,
        knowledge_manager: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the learning agent.

        Args:
            ai_router: The AI router for generating responses.
            knowledge_manager: Optional knowledge manager for saving materials.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.LEARNING,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Educational content and study plans agent",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router
        self._knowledge_manager = knowledge_manager

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a learning task.

        Args:
            task: The learning task.

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
                            title=f"Learning: {prompt[:100]}",
                            content=result,
                            category="learning",
                            tags=["agent", "learning", "education"],
                            source="learning_agent",
                        )
                    except Exception as exc:
                        logger.warning("Failed to save learning materials: %s", exc)

                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for learning task: %s", exc)

        # Fallback: basic learning template
        result = self._generate_basic_roadmap(prompt)
        return result, tokens_used

    def _generate_basic_roadmap(self, topic: str) -> str:
        """Generate a basic learning roadmap without AI.

        Args:
            topic: The learning topic.

        Returns:
            A learning roadmap template.
        """
        return f"""## Learning Roadmap: {topic}

### 🎯 Learning Objectives
- Understand the fundamentals of {topic}
- Apply key concepts in practical scenarios
- Build a solid foundation for advanced topics

### 📚 Study Plan

#### Week 1-2: Fundamentals
- [ ] Core concepts and terminology
- [ ] Basic principles
- [ ] Introduction tutorials

#### Week 3-4: Intermediate
- [ ] Advanced concepts
- [ ] Hands-on exercises
- [ ] Real-world examples

#### Week 5-6: Advanced
- [ ] Complex topics
- [ ] Best practices
- [ ] Project work

### 📖 Recommended Resources
- [Resource list would be populated here]

### ✅ Practice Exercises
- [Exercise list would be populated here]

---
*Note: This is a basic template. For a detailed learning path,
ensure the AI router is configured and available.*
"""
