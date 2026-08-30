"""
trading_agent.py

Trading Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take market research requests and generate educational analysis.
    - Compare strategies and explain concepts.
    - NEVER executes trades or makes financial decisions.
    - Only provides research and education.

Safety:
    - GREEN-only tool access by default.
    - Hardcoded safety check: refuses any prompt containing trade execution.
    - Cannot spawn other agents.
    - NEVER makes financial decisions — research and education only.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentConfig, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)

# Forbidden patterns — refuse any prompt containing trade execution
_FORBIDDEN_PATTERNS = re.compile(
    r"\b(buy|sell|trade|execute order|place order|submit order|"
    r"make trade|execute trade|submit trade|place trade|"
    r"open position|close position|enter trade|exit trade)\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = """You are a market research and education assistant. Your job is to:
1. Analyze market topics for educational purposes.
2. Explain trading concepts and strategies.
3. Compare different approaches objectively.
4. Provide historical context and analysis.

IMPORTANT: You are an EDUCATIONAL assistant only. You NEVER:
- Execute trades or orders
- Make buy/sell recommendations
- Provide financial advice
- Guarantee returns or outcomes

Always include disclaimers about financial risk.
Always frame analysis as educational, not advisory."""


class TradingAgent(BaseAgent):
    """Agent specialising in market research and education.

    Takes market research requests, generates educational analysis and
    strategy comparison. NEVER executes trades or makes financial decisions.

    Attributes:
        _ai_router: The AI router for generating responses.
    """

    def __init__(
        self,
        ai_router: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the trading agent.

        Args:
            ai_router: The AI router for generating responses.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.TRADING,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Market research and education agent (no trading)",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a trading research task.

        Args:
            task: The trading research task.

        Returns:
            Tuple of (result_text, tokens_used).

        Raises:
            ValueError: If the task contains forbidden trade execution patterns.
        """
        prompt = task.prompt
        tokens_used = 0

        # SAFETY CHECK: Refuse any prompt containing trade execution
        if _FORBIDDEN_PATTERNS.search(prompt):
            raise ValueError(
                "SAFETY VIOLATION: This agent only provides research and education. "
                "Trade execution, buy/sell orders, and financial advice are strictly "
                "forbidden. Please rephrase your request as a research question."
            )

        # Use AI router if available
        if self._ai_router is not None:
            try:
                response = self._ai_router.route(
                    system_instruction=self._config.system_prompt,
                    user_message=prompt,
                )
                result = response.text
                tokens_used = (response.input_tokens or 0) + (response.output_tokens or 0)

                # Add safety disclaimer
                result += self._get_disclaimer()

                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for trading task: %s", exc)

        # Fallback: basic research template
        result = self._generate_basic_research(prompt)
        return result, tokens_used

    def _get_disclaimer(self) -> str:
        """Return the standard trading education disclaimer."""
        return """

---
⚠️ **EDUCATIONAL DISCLAIMER**
This analysis is for educational purposes only. It does not constitute
financial advice, trading recommendations, or investment guidance.
Always consult with a qualified financial advisor before making any
investment decisions. Past performance does not guarantee future results.
Trading involves significant risk of loss.
"""

    def _generate_basic_research(self, prompt: str) -> str:
        """Generate a basic research template without AI.

        Args:
            prompt: The research topic.

        Returns:
            A research template.
        """
        return f"""## Market Research: {prompt}

### Overview
[Market overview would be generated here]

### Key Concepts
- [Concept 1 would be explained here]
- [Concept 2 would be explained here]
- [Concept 3 would be explained here]

### Strategy Comparison
| Strategy | Pros | Cons | Risk Level |
|----------|------|------|------------|
| [Strategy 1] | ... | ... | ... |
| [Strategy 2] | ... | ... | ... |

### Historical Context
[Historical analysis would be provided here]

### Educational Notes
[Learning points would be listed here]

{self._get_disclaimer()}

---
*Note: This is a basic template. For detailed market research,
ensure the AI router is configured and available.*
"""
