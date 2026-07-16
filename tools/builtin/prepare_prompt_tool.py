"""
prepare_prompt_tool.py

A safe, read-only tool that assembles a well-structured, Claude-ready
prompt for the user to copy and paste into an actual Claude
conversation themselves (Phase 86, Batch 2 - "Claude Prompt Studio").

PreparePromptTool is a GREEN tool: it only calls ai/prompt_studio.py's
deterministic, AI-free assembly function and returns the resulting
text locally. It never calls the Claude API, any other AI provider,
AIRouter, AIReasoningEngine, or PromptBuilder, and never sends the
generated prompt anywhere - the text is printed to the CLI only, for
the user's own manual copy/paste use.

Supported input (via input_data):
    mode: one of ai.prompt_studio.known_modes() (required) - e.g.
        "implementation", "review", "brainstorm", "critique", "compare".
    goal: the user's free-text goal (required, non-empty) - embedded
        verbatim in the generated prompt, never interpreted or parsed
        as an instruction to Jarvis itself.

Safety note:
    This tool never edits, patches, stages, commits, or applies any
    change to this or any other repository, never accesses git or a
    subprocess to determine the current branch/commit/phase, and never
    fabricates that state - every generated prompt includes an
    explicit "fill in yourself" placeholder for it instead.
"""

from __future__ import annotations

from ai.prompt_studio import PromptContext, build_prompt, known_modes
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin.jarvis_brain_tool import JarvisBrainStatusTool


class PreparePromptTool(BaseTool):
    """Assembles a Claude-ready prompt for manual copy/paste use.

    Read-only and safe; never calls any AI provider and never sends
    the generated prompt anywhere - it is returned as local text only.
    """

    def __init__(self, brain_status_tool: JarvisBrainStatusTool) -> None:
        """Initialise the tool with the already-built JarvisBrainStatusTool.

        Reusing the whole tool (rather than its individual Settings/
        store/manager dependencies directly) means this tool's own
        "Jarvis Context" section always reflects exactly the same real
        data "jarvis brain status" itself reports, via
        JarvisBrainStatusTool.get_context() - a structured method call,
        never a text-scrape of that tool's own formatted output.

        Args:
            brain_status_tool: The application's already-constructed
                JarvisBrainStatusTool (Phase 86, Batch 1). Only
                get_context() is ever called.
        """
        self._brain_status_tool = brain_status_tool

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "prepare_prompt".
        """
        return "prepare_prompt"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Assembles a Claude-ready prompt (implementation/review/"
            "brainstorm/critique/compare) for you to copy and paste "
            "manually. Read-only and safe; never calls any AI provider."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Always the same fixed phrase, regardless of which mode or goal
        text was used, so classification never varies with user input.
        Deliberately phrased with the existing, unchanged "show"
        keyword so the Security Manager's own established generic GREEN
        rule already covers it - no new Security Manager rule is
        required for this tool.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show prepared prompt", classified GREEN.
        """
        return "show prepared prompt"

    def run(self, request: ToolRequest) -> ToolResult:
        """Assemble and return a Claude-ready prompt as local text.

        Args:
            request: The request. Recognised input keys:
                mode: one of ai.prompt_studio.known_modes() (required).
                goal: the user's free-text goal (required, non-empty).

        Returns:
            A successful ToolResult containing the assembled prompt
            text, or a failed result if mode is missing/unrecognised or
            goal is missing/empty. Never calls any AI provider and
            never sends the generated text anywhere.
        """
        raw_mode = request.input_data.get("mode")
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            return self.fail(
                "Missing required input: 'mode' (one of: "
                f"{', '.join(known_modes())})."
            )
        mode = raw_mode.strip().casefold()
        if mode not in known_modes():
            return self.fail(
                f"Unknown mode '{raw_mode}'. Use one of: "
                f"{', '.join(known_modes())}."
            )

        raw_goal = request.input_data.get("goal")
        if not isinstance(raw_goal, str) or not raw_goal.strip():
            return self.fail(
                "Missing required input: 'goal' (non-empty free text "
                "describing what you want a Claude prompt for)."
            )
        goal = raw_goal.strip()

        context: PromptContext = self._brain_status_tool.get_context()
        prompt = build_prompt(mode=mode, goal=goal, context=context)

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=prompt,
            metadata={
                "operation": "prepare_prompt",
                "mode": mode,
            },
        )
