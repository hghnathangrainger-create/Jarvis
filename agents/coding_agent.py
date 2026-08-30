"""
coding_agent.py

Coding Agent for the Jarvis AI Operating System.

Responsibilities:
    - Take a coding prompt and generate code via AI.
    - Run basic validation (syntax check via ast.parse for Python).
    - Return code with explanation.

Safety:
    - GREEN-only tool access by default.
    - All code execution is sandboxed — never runs untrusted code automatically.
    - Cannot spawn other agents.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentConfig, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a coding assistant. Your job is to:
1. Understand the coding request.
2. Write clean, well-documented code.
3. Include error handling where appropriate.
4. Provide clear explanations of the code.

Always follow best practices. Use type hints where applicable.
Format code blocks with proper syntax highlighting markers."""


class CodingAgent(BaseAgent):
    """Agent specialising in code generation and validation.

    Takes a coding prompt, generates code via AI, runs basic validation,
    and returns code with explanation. All code execution is sandboxed.

    Attributes:
        _ai_router: The AI router for generating responses.
    """

    def __init__(
        self,
        ai_router: Any = None,
        config: AgentConfig | None = None,
    ) -> None:
        """Initialise the coding agent.

        Args:
            ai_router: The AI router for generating responses.
            config: Optional custom configuration.
        """
        if config is None:
            config = AgentConfig(
                agent_type=AgentType.CODING,
                max_execution_time=300,
                allowed_tools=["GREEN"],
                description="Code generation and validation agent",
                system_prompt=_SYSTEM_PROMPT,
            )
        super().__init__(config)
        self._ai_router = ai_router

    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute a coding task.

        Args:
            task: The coding task.

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

                # Validate any Python code blocks
                validation = self._validate_code(result)
                if validation:
                    result += f"\n\n### Validation Notes\n{validation}"

                return result, tokens_used

            except Exception as exc:
                logger.error("AI router failed for coding task: %s", exc)

        # Fallback: basic coding template
        result = self._generate_basic_code(prompt)
        return result, tokens_used

    def _validate_code(self, text: str) -> str:
        """Validate Python code blocks in the generated text.

        Extracts Python code blocks and checks syntax via ast.parse.

        Args:
            text: The generated text containing code blocks.

        Returns:
            Validation notes, or empty string if all valid.
        """
        notes = []
        in_code_block = False
        code_lines = []
        block_lang = ""

        for line in text.split("\n"):
            if line.strip().startswith("```"):
                if in_code_block:
                    # End of code block — validate
                    if block_lang.lower() in ("python", "py", ""):
                        code = "\n".join(code_lines)
                        if code.strip():
                            try:
                                ast.parse(code)
                            except SyntaxError as exc:
                                notes.append(
                                    f"⚠️ Python syntax error in code block: {exc}"
                                )
                    in_code_block = False
                    code_lines = []
                    block_lang = ""
                else:
                    # Start of code block
                    in_code_block = True
                    block_lang = line.strip().lstrip("`").strip()
            elif in_code_block:
                code_lines.append(line)

        if notes:
            return "\n".join(notes)
        return ""

    def _generate_basic_code(self, prompt: str) -> str:
        """Generate a basic code template without AI.

        Args:
            prompt: The coding request.

        Returns:
            A code template.
        """
        return f"""## Code: {prompt}

```python
# Generated code would appear here
# based on the coding request: {prompt}
pass
```

### Explanation
[Code explanation would be provided here]

---
*Note: This is a basic template. For actual code generation,
ensure the AI router is configured and available.*
"""
