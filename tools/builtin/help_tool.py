"""
help_tool.py

A safe tool that lists Jarvis's currently supported commands (Phase 43;
updated Phase 84 to surface the optional grammar clauses Phases 81-83
shipped: schedule naming, file-read character limits, and result-count
limits for file/memory list and search).

HelpTool is a GREEN tool: it returns a static, hand-maintained list of
command grammar phrases and one-line descriptions. It changes nothing,
touches no external resource, and is never AI-generated - the exact
same static-content pattern InfoTool already established.

This is deliberately not a generic, introspectable command registry:
CommandRouter has no machine-readable grammar table to read from (its
matching logic is a sequence of hand-written keyword/prefix checks), so
building one now would be a much larger refactor than this phase's
narrow discoverability goal calls for. Instead, this list is maintained
by hand, alongside docs/user_guide.md's own "Command Reference" table
(Section 6) - the same kind of manual-accuracy discipline this project
already relies on for README.md/docs/user_guide.md themselves.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: One line per command family, grouped to match docs/user_guide.md's own
#: "Command Reference" section (Section 6) ordering exactly, so both stay
#: easy to keep in sync by hand. Every phrase listed here is a real,
#: currently-matched CommandRouter grammar - nothing here is invented or
#: aspirational. "(approval required)" marks a YELLOW action; unmarked
#: lines are GREEN; "forget all"/"forget all memories" is the one
#: RED, always-blocked action.
_HELP_LINES: tuple[str, ...] = (
    "Available Jarvis commands:",
    "",
    "Basic:",
    "  echo <text> / repeat <text> / say <text> - repeats the text back",
    "  system info / version / about / who are you - shows basic system information",
    "  show config / show settings - shows current configuration status",
    "  help / list commands / show commands - shows this list",
    "  health check / show health / system health - reports basic system health "
    "(settings, database, tool registry, logging, Inbox/Schedule/Quarantine stores, "
    "Security Manager self-check)",
    "",
    "Memory:",
    "  remember this: <text> / remember this as <category>: <text> - saves a memory",
    "  show memories / show memories in <category> - lists memories (up to 10 by default)",
    "  show memory categories / list memory categories - shows a real count of memories "
    "in each known category, including honest zeros",
    "  search memories for <query> / search memories in <category> for <query> - searches "
    "memory (up to 10 results by default)",
    "  ... limit <N> - add to any memory list/search command above to show up to <N> "
    "results instead of the default (up to 50)",
    "  update memory <id>: <new text> - replaces a memory's content (approval required)",
    "  move memory <id> to <category> - re-categorizes a memory (approval required)",
    "  forget memory <id> - deletes one memory (approval required)",
    "  forget all / forget all memories - deletes every memory (blocked outright, never runs)",
    "  summarise memory <id> / summarise memories <id1> <id2> ... / summarise memories about "
    "<query> / summarise memories in <category> / summarise recent memories / summarise "
    "latest <count> memories - AI summary of memories (advisory; requires AI_REASONING_ENABLED)",
    "",
    "Files:",
    "  list files / list files in <path> / show files in <path> / list directory / list dir "
    "- lists a directory (up to 50 entries by default; add limit <N> for up to 500)",
    "  read file <path> / show file <path> / open file <path> / cat file <path> - shows a "
    "file's contents (up to 4000 characters by default)",
    "  read file <path> up to <N> chars / ... up to <N> characters - same as above, but "
    "reads up to <N> characters instead (up to 100,000)",
    "  search files for <pattern> / find files named <pattern> - finds files by name (up "
    "to 50 results by default; add limit <N> for up to 500)",
    "  find files containing <text> / search files containing <text> - finds files by "
    "content (up to 50 results by default; add limit <N> for up to 500)",
    "  create file <path> with <content> - creates a new file (approval required)",
    "  append <content> to file <path> - appends to an existing file (approval required)",
    "  copy file <source> to <destination> - copies a file (approval required)",
    "  move file <source> to <destination> / rename file <source> to <destination> - moves "
    "or renames a file (approval required)",
    "  delete file <path> - quarantines a file, never permanent (approval required)",
    "  list quarantine / show quarantine - lists quarantined files",
    "  restore file <quarantine-file-or-path> - restores a quarantined file (approval required)",
    "  summarise file <path> / summarize file <path> - AI summary of a file (advisory; "
    "requires AI_REASONING_ENABLED)",
    "",
    "Web:",
    "  search the web for <query> - runs a live web search",
    "  summarise web search for <query> / summarize web search for <query> - searches and AI-"
    "summarizes results, saves a copy to the Inbox",
    "  read webpage <url> - fetches and shows a webpage's text (approval required)",
    "  summarize webpage <url> / summarise webpage <url> - fetches and AI-summarizes a "
    "webpage (approval required); does not save to the Inbox",
    "  summarize webpage <url> and save to inbox / summarise webpage <url> and save to "
    "inbox - same as above, and also saves the summary to the Inbox on success "
    "(approval required)",
    "",
    "Schedules:",
    "  schedule web search summary for <query> at <HH:MM> - creates a daily schedule "
    "(approval required)",
    "  ... as <name> - add to the command above to give the schedule a name",
    "  list schedules / show schedules - lists configured schedules",
    "  enable schedule <id> - re-activates a schedule (approval required)",
    "  disable schedule <id> - deactivates a schedule (approval required)",
    "",
    "Workflows (fixed, multi-step sequences):",
    "  remember this and show it back: <text> - saves a memory, then shows it back",
    "  remember this and forget it: <text> - saves a memory, then asks approval to delete it",
    "  create file <path> with <content> and show it - creates a file (approval required), "
    "then reads it back",
    "  update memory <id>: <content> and show it back - updates a memory (approval "
    "required), then shows the new content",
    "  search files for <pattern> and copy first to <destination> - searches by filename, "
    "then asks approval to copy the single match",
    "",
    "History:",
    "  show approval history / show recent approvals / show approved actions / show "
    "declined actions / show approval <id> / view approval <id> - approval history",
    "  show workflow history / show recent workflows / show workflow <id> / view workflow "
    "<id> - workflow history",
)


class HelpTool(BaseTool):
    """Lists Jarvis's currently supported commands.

    Read-only and safe; the output is a fixed, hand-maintained constant,
    never generated by AI and never derived from CommandRouter at
    runtime.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "help".
        """
        return "help"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Lists Jarvis's currently supported commands. Safe and read-only."

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Always the same fixed phrase, regardless of which grammar alias
        ("help", "list commands", or "show commands") was used, so
        classification never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show available commands", classified GREEN.
        """
        return "show available commands"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the static list of currently supported commands.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult containing the command list.
        """
        return self.ok("\n".join(_HELP_LINES))
