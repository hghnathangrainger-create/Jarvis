"""
command_router.py

Command routing for the Jarvis AI Operating System (Phase 7, Batch 1;
explicit file-summary command added in Phase 8, Batch 2).

Responsibilities:
    - Match a user's natural-language request text to the name of a
      registered tool, if a known phrasing applies.
    - Build the input dictionary the matched tool expects from that text.
    - Recognise the explicit file-summary command and extract its path
      (match_file_summary), as a separate, narrow operation from
      match()/build_input() - summarising a file is a multi-step
      AI-reasoning workflow, not a single tool execution.

Does NOT:
    - Classify security tiers (that is the Security Manager's job).
    - Execute anything, or hold a reference to the Tool Executor.
    - Decide what happens when no tool matches; the caller (the Jarvis Core)
      decides what to do with a None result.

This module is a mechanical extraction of logic that used to live directly on
JarvisOrchestrator (_match_tool and _build_tool_input, Phases 1-6). It was
moved here, unchanged in behaviour, so the Core does not become "a collection
of business logic" - the Master Specification's own description of what the
Jarvis Core must never become. Every phrase that routed to a tool before this
move still routes to the same tool with the same input; nothing about how a
request is matched changed as part of the move.
"""

from __future__ import annotations

import re

from tools.registry import ToolRegistry

# Recognised intents map to a built-in tool and the input that tool expects.
# Only safe, read-only tools are wired here in Phase 1.
_ECHO_KEYWORDS: tuple[str, ...] = ("echo", "repeat", "say")
_INFO_KEYWORDS: tuple[str, ...] = ("system info", "version", "about", "who are you")
_MEMORY_KEYWORDS: tuple[str, ...] = ("memory", "memories", "remember", "recall")

#: Leading phrases that indicate a file-listing request. The text after the
#: phrase is treated as the directory path.
_FILE_LIST_PREFIXES: tuple[str, ...] = (
    "list files in",
    "show files in",
    "list files",
    "show files",
    "list directory",
    "list dir",
)

#: Leading phrases that indicate a file-reading request. The text after the
#: phrase is treated as the file path. All of these are read-only; "open" here
#: means "open to read", never to modify.
_FILE_READ_PREFIXES: tuple[str, ...] = (
    "read file",
    "show file",
    "open file",
    "read the file",
    "cat file",
)

#: Practical read-only workflow aliases. Each maps an exact phrase (matched
#: case-insensitively, after stripping surrounding whitespace) to a fixed tool
#: and path, so a beginner can use a friendly command instead of typing a path.
#: Every alias here is read-only: it routes only to file_list or file_read.
_WORKFLOW_ALIASES: dict[str, tuple[str, str]] = {
    "show project files": ("file_list", "."),
    "list project files": ("file_list", "."),
    "show docs": ("file_list", "docs"),
    "list docs": ("file_list", "docs"),
    "read readme": ("file_read", "README.md"),
    "show readme": ("file_read", "README.md"),
    "show phase 3 plan": ("file_read", "docs/phase_3_implementation_plan.md"),
    "read phase 3 plan": ("file_read", "docs/phase_3_implementation_plan.md"),
}

#: Exact, read-only approval-history commands (matched case-insensitively,
#: after stripping surrounding whitespace). Every one of these routes to the
#: read-only ApprovalHistoryTool. All five are GREEN: none of them can
#: approve, decline, or execute anything, because the history store they read
#: from carries no tool_name or tool_input for any past request (Phase 6,
#: Batch 1).
_APPROVAL_HISTORY_EXACT: dict[str, str] = {
    "show approval history": "history",
    "show recent approvals": "recent",
    "show approved actions": "approved",
    "show declined actions": "declined",
}

#: Leading phrases for showing a single approval by id, e.g.
#: "show approval <request_id>". Checked only after the exact phrases above,
#: so "show approval history" is never mistaken for a lookup of an approval
#: literally named "history".
_APPROVAL_DETAIL_PREFIXES: tuple[str, ...] = ("show approval", "view approval")

#: Exact, read-only workflow-history commands (matched case-insensitively,
#: after stripping surrounding whitespace). Every one of these routes to the
#: read-only WorkflowHistoryTool (Durable Workflow Lifecycle Foundation - a
#: prerequisite turn, not a numbered phase). Both are GREEN: neither can
#: start, resume, pause, or execute anything, because the history store they
#: read from carries no tool_input or resolved-step-input for any past
#: workflow. Not to be confused with _WORKFLOW_ALIASES above, which is an
#: unrelated, pre-existing Phase 7 table of friendly file-path aliases.
_WORKFLOW_HISTORY_EXACT: dict[str, str] = {
    "show workflow history": "history",
    "show recent workflows": "recent",
}

#: Leading phrases for showing a single workflow's full history by id, e.g.
#: "show workflow <workflow_id>". Checked only after the exact phrases
#: above, so "show workflow history" is never mistaken for a lookup of a
#: workflow literally named "history".
_WORKFLOW_DETAIL_PREFIXES: tuple[str, ...] = ("show workflow", "view workflow")

#: The one exact, mandatory prefix for Jarvis's first external-network
#: command (Phase 16). Routes to the read-only WebSearchTool. Checked
#: directly against every other exact/prefix table in this module during
#: planning: it shares no keyword with _MEMORY_KEYWORDS
#: ("memory"/"memories"/"remember"/"recall"), _WORKFLOW_ALIASES,
#: _APPROVAL_HISTORY_EXACT/_APPROVAL_DETAIL_PREFIXES, or
#: _WORKFLOW_HISTORY_EXACT/_WORKFLOW_DETAIL_PREFIXES. A single fixed
#: phrasing is used deliberately - no looser synonym set - mirroring
#: Phase 15's own exact-command-grammar discipline.
_WEB_SEARCH_PREFIXES: tuple[str, ...] = ("search the web for",)

#: Leading phrases that indicate a create-file request. The text after the
#: phrase is the path, optionally followed by " with <content>". Creating a
#: file is a WRITE action (YELLOW) and always requires approval.
_FILE_CREATE_PREFIXES: tuple[str, ...] = (
    "create text file",
    "create file",
    "create a file",
    "new file",
    "make file",
)

#: Leading phrases that indicate an append-file request. Appending is a WRITE
#: action (YELLOW) and always requires approval. Two shapes are supported:
#:   "append <content> to file <path>"
#:   "append to file <path> <content>"
_FILE_APPEND_PREFIXES: tuple[str, ...] = (
    "append text file",
    "append to file",
    "append to",
    "append",
)
_SEARCH_KEYWORDS: tuple[str, ...] = ("search", "find", "look up", "lookup")

#: Leading phrases that indicate an explicit file-summary request (Phase 8,
#: Batch 2). The text after the phrase is treated as the file path. This is
#: deliberately a separate, narrow match from the file_read prefixes above:
#: summarising a file is a multi-step AI-reasoning workflow, not a single
#: tool execution, so it is never returned by match()/build_input(), which
#: only ever name a registered tool the orchestrator can execute directly.
_FILE_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise file",
    "summarize file",
)

#: Leading phrases that indicate an explicit AI web-search-summary request
#: (Phase 18, Batch 2). The text after the phrase is the raw, unparsed
#: search query. Deliberately a separate, narrow match from
#: match()/build_input() and from _WEB_SEARCH_PREFIXES (the raw,
#: non-AI "search the web for <query>" command, Phase 16): summarising web
#: search results is a multi-step AI-reasoning workflow (search, then
#: reason about the results), not a single tool execution, so it is never
#: returned by match()/build_input(). Checked directly against every
#: existing exact/prefix table in this module: "summarise web search for"
#: shares no leading word with "search the web for" (different first
#: word: "summarise"/"summarize" vs "search") or with any
#: "summarise memor(y/ies)..." family prefix (different second word: "web"
#: vs "memory"/"memories") - confirmed by direct comparison, not assumed.
_WEB_SEARCH_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise web search for",
    "summarize web search for",
)

#: Leading phrases that indicate an explicit memory-summary request (Phase 9,
#: Batch 2). The text after the phrase is treated as the raw, unparsed
#: trailing id text. Deliberately a separate, narrow match from
#: match()/build_input(), mirroring _FILE_SUMMARY_PREFIXES: summarising a
#: memory is a multi-step AI-reasoning workflow, not a single tool
#: execution, so it is never returned by match()/build_input(), which only
#: ever name a registered tool the orchestrator can execute directly.
_MEMORY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise memory",
    "summarize memory",
)

#: Leading phrases that indicate an explicit query-based memory-summary
#: request (Phase 11, Batch 2). The text after the phrase is treated as the
#: raw, unparsed trailing query text. This prefix is a strict
#: superset-string of _MEMORY_SET_SUMMARY_PREFIXES below ("summarise
#: memories about" starts with "summarise memories"), so the caller
#: (JarvisOrchestrator.handle_request) MUST check match_memory_query_summary
#: before match_memory_set_summary, or a query-based request would be
#: incorrectly swallowed by the plural explicit-id matcher and rejected as
#: an invalid id list (docs/phase_11_implementation_plan.md, Section
#: 3.1/3.2.1 - a concrete collision verified, not hypothetical). This
#: prefix does not collide with _MEMORY_SUMMARY_PREFIXES (singular) in
#: either direction: "summarise memory" and "summarise memories" diverge at
#: the word's 6th character ('y' vs 'i').
_MEMORY_QUERY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise memories about",
    "summarize memories about",
)

#: Leading phrases that indicate an explicit category-based memory-summary
#: request (Phase 12, Batch 2). The text after the phrase is treated as the
#: raw, unparsed trailing category text. This prefix is a strict
#: superset-string of _MEMORY_SET_SUMMARY_PREFIXES below ("summarise
#: memories in" starts with "summarise memories"), so the caller
#: (JarvisOrchestrator.handle_request) MUST check
#: match_memory_category_summary before match_memory_set_summary, or a
#: category-based request would be incorrectly swallowed by the plural
#: explicit-id matcher and rejected as an invalid id list
#: (docs/phase_12_implementation_plan.md, Section 3.1/3.2 - the same
#: collision class Phase 11 already discovered and fixed for its own
#: "about" grammar). This prefix does not collide with
#: _MEMORY_QUERY_SUMMARY_PREFIXES (Phase 11) in either direction:
#: "summarise memories in" and "summarise memories about" diverge at their
#: second word ("in" vs "about"), so check order between these two new
#: matchers does not affect correctness.
_MEMORY_CATEGORY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise memories in",
    "summarize memories in",
)

#: Leading phrases that indicate an explicit multi-memory-summary request
#: (Phase 10, Batch 2). The text after the phrase is treated as the raw,
#: unparsed trailing id-list text. Deliberately a separate, narrow match from
#: _MEMORY_SUMMARY_PREFIXES: "memory" and "memories" diverge at their 5th
#: character, so the two can never collide as prefixes of one another in
#: either direction - verified directly, not merely assumed - so checking
#: order between the singular and plural matchers does not matter. This
#: prefix DOES collide with _MEMORY_QUERY_SUMMARY_PREFIXES and
#: _MEMORY_CATEGORY_SUMMARY_PREFIXES above (it is a strict prefix of both)
#: - see the ordering requirement documented there.
_MEMORY_SET_SUMMARY_PREFIXES: tuple[str, ...] = (
    "summarise memories",
    "summarize memories",
)

#: The exact, complete leading phrase for the Phase 15 all-GREEN workflow
#: command "remember this and show it back: <text>" (Retrieval Workflow
#: Maintenance's sibling capability turn - Phase 15, Batch 3). Includes the
#: mandatory trailing colon: the colon is part of the required grammar, not
#: a separator checked separately, so "remember this and show it back"
#: (no colon), "remember and show it back: ..." (missing "this"), "remember
#: this then show it back: ..." (wrong connector), and "remember this and
#: show: ..." (missing "it back") all correctly fail to match at all -
#: falling through to whatever the existing, unrelated generic "remember
#: this" handling in _build_memory_input already does with them, never
#: silently becoming this workflow. This prefix is checked in
#: JarvisOrchestrator.handle_request() before the fallback to
#: _handle_request_core()/match() - the same dispatch position every
#: Phase 8-14 special-case matcher already occupies - because
#: "remember this and show it back: ..." would otherwise be captured by
#: match()'s own generic memory-keyword routing and misinterpreted as a
#: plain "remember this: ..." save (docs/phase_15_implementation_plan.md,
#: Batch 3 investigation).
_REMEMBER_AND_SHOW_BACK_WORKFLOW_PREFIX = "remember this and show it back:"

#: The exact, complete leading phrase for the Phase 15 GREEN-then-YELLOW
#: workflow command "remember this and forget it: <text>". Same exact-
#: grammar and dispatch-ordering rationale as
#: _REMEMBER_AND_SHOW_BACK_WORKFLOW_PREFIX above: the trailing colon is
#: mandatory, and this must be checked before the fallback to
#: _handle_request_core()/match() for the same reason.
_REMEMBER_AND_FORGET_WORKFLOW_PREFIX = "remember this and forget it:"

#: The exact, fixed trailing suffix for the Phase 17 "create file <path>
#: with <content> and show it" workflow command. Unlike the two Phase 15
#: workflow prefixes above (matched at the START of the text, before any
#: free text begins, which makes them unambiguous by construction), this
#: workflow's trigger phrase is a SUFFIX that comes AFTER Nathan's own
#: free-form path/content text - a materially more fragile grammar shape.
#: match_create_and_read_workflow() below checks this suffix via a real
#: str.endswith() comparison against the fully stripped text (never a
#: substring search), so an occurrence of these words in the MIDDLE of
#: content never triggers anything. Disclosed, accepted limitation
#: (docs/phase_17_implementation_plan.md, Section 5): if Nathan's own
#: intended file content itself legitimately ends with the exact literal
#: words "and show it", the workflow trigger is indistinguishable from
#: that content and will always fire, stripping those trailing words from
#: what is actually written. This is not fixed in Phase 17 - no quoting/
#: escaping convention exists in this codebase, and inventing one (or
#: guessing intent, or asking AI to disambiguate) was explicitly out of
#: scope.
_CREATE_AND_READ_WORKFLOW_SUFFIX = " and show it"

#: The exact, fixed trailing suffix for the Phase 17 "update memory <id>:
#: <content> and show it back" workflow command. Same suffix-shape
#: rationale and same disclosed, accepted ambiguity as
#: _CREATE_AND_READ_WORKFLOW_SUFFIX above, for replacement memory content
#: that itself legitimately ends with the exact literal words "and show
#: it back".
_UPDATE_AND_SHOW_WORKFLOW_SUFFIX = " and show it back"

#: The exact, complete recent-memory-summary commands (Phase 13, Batch 2).
#: Unlike every other summary-family command, this one carries no trailing
#: free-text argument at all - there is no query, category, or id list to
#: extract - so it is matched as a complete phrase, never as a prefix.
#: Because the qualifier ("recent") sits between "summarise"/"summarize" and
#: "memories" rather than after "memories" (contrast
#: _MEMORY_QUERY_SUMMARY_PREFIXES's "about" and
#: _MEMORY_CATEGORY_SUMMARY_PREFIXES's "in", both of which follow
#: "memories"), neither phrase here is a superset-string of
#: _MEMORY_SET_SUMMARY_PREFIXES ("summarise memories") in either direction,
#: and neither is a superset-string of _MEMORY_SUMMARY_PREFIXES ("summarise
#: memory") either - confirmed by direct string comparison, not merely
#: assumed (docs/phase_13_implementation_plan.md, Section 4.1). This means,
#: unlike Phase 11/12, dispatch-order placement relative to the other four
#: summary-family matchers does not affect correctness.
_MEMORY_RECENT_SUMMARY_EXACT: tuple[str, ...] = (
    "summarise recent memories",
    "summarize recent memories",
)

#: The compiled, case-insensitive grammar for a count-based recent-memory-
#: summary command (Phase 14, Batch 2): "summarise latest <count> memories"
#: / "summarize latest <count> memories". Unlike every other summary-family
#: matcher, which recognises a fixed prefix and treats everything after it
#: as unconstrained trailing text, this is the first grammar in the
#: repository requiring a fixed prefix AND a fixed, mandatory suffix
#: ("memories" at the very end) - natural English count phrasing places
#: the number before the noun, not at the end of the string, so a simple
#: prefix-only extraction cannot express it (docs/phase_14_implementation_
#: plan.md, Section 4.3). `fullmatch` requires the literal "memories" to be
#: the final token, so any extra trailing text ("... memories about
#: security", "... memories in project") fails the match entirely rather
#: than being silently ignored; the required "latest" keyword and the
#: required "memories" suffix mean this can never collide with
#: _MEMORY_SET_SUMMARY_PREFIXES ("summarise memories"),
#: _MEMORY_SUMMARY_PREFIXES ("summarise memory"), or
#: _MEMORY_RECENT_SUMMARY_EXACT ("summarise recent memories" - no "latest"
#: token) in either direction - confirmed by direct trace, not merely
#: assumed (Phase 14 plan, Section 4.2/4.3). The captured group is the raw,
#: unvalidated count text - this matcher recognises grammatical shape
#: only; numeric validity is
#: ai.memory_selection.select_recent_memory_ids_by_count()'s own concern
#: (Phase 14 plan, Section 5.1).
#:
#: Batch 2 refinement over the plan's own illustrative `(.+)` capture
#: group: `(\S+)` is used instead, requiring the captured segment to be a
#: single, internally-whitespace-free token. This was found necessary
#: while writing this batch's own non-match tests: a greedy `(.+)` would
#: also match "summarise latest 5 stored memories", silently absorbing the
#: extra qualifier word "stored" into the captured "count" text ("5
#: stored") - a command the plan explicitly lists as a required
#: non-match, not a match-with-invalid-content. `(\S+)` closes this gap -
#: it cannot span the space between "5" and "stored", so that command now
#: correctly fails to match at all - while preserving every other intended
#: behaviour: a single malformed word ("five") still matches and is
#: correctly deferred to select_recent_memory_ids_by_count() for
#: rejection, and arbitrary internal whitespace around the digits (e.g.
#: "latest  5  memories") is still tolerated by the surrounding `\s+`
#: separators, now without even needing a downstream `.strip()` - `\S+`
#: never captures leading/trailing whitespace to begin with. No Batch 1
#: code is affected by this refinement.
_MEMORY_RECENT_COUNT_SUMMARY_PATTERN = re.compile(
    r"(?:summarise|summarize)\s+latest\s+(\S+)\s+memories", re.IGNORECASE
)


class CommandRouter:
    """Matches request text to a registered tool and builds its input.

    The router is stateless aside from its ToolRegistry collaborator; a
    single instance can be shared across the application. It never classifies
    risk and never executes anything - it only decides which tool, if any, a
    piece of request text refers to, and what input that tool needs.

    Attributes:
        _registry: Used to check which tools are actually registered, so a
            match is never returned for a tool that is not available.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        """Initialise the router with the tool registry to check against.

        Args:
            registry: The ToolRegistry used to verify a matched tool is
                actually registered before it is returned as a match.
        """
        self._registry = registry

    def match(self, text: str) -> str | None:
        """Map a request to a known safe tool name, if one applies.

        Only tools that are actually registered are returned, so the
        orchestrator never routes to a tool that is not available.

        Args:
            text: The stripped request text.

        Returns:
            The name of a registered tool to handle the request, or None.
        """
        lowered = text.casefold()

        # Practical workflow aliases are checked first: an exact friendly phrase
        # maps to a fixed read-only tool. Only route if that tool is registered.
        alias = _WORKFLOW_ALIASES.get(lowered.strip())
        if alias is not None and self._registry.has_tool(alias[0]):
            return alias[0]

        # Approval history commands are read-only and GREEN. The four fixed
        # views are matched as exact phrases first; only if the text is not
        # one of those does "show approval <id>" / "view approval <id>" get
        # treated as a lookup of a single entry. None of these commands can
        # approve, decline, or execute anything (Phase 6, Batch 1).
        if lowered.strip() in _APPROVAL_HISTORY_EXACT and self._registry.has_tool(
            "approval_history"
        ):
            return "approval_history"

        if any(
            lowered.startswith(prefix) for prefix in _APPROVAL_DETAIL_PREFIXES
        ) and self._registry.has_tool("approval_history"):
            return "approval_history"

        # Workflow history commands are read-only and GREEN, mirroring the
        # approval-history block immediately above (Durable Workflow
        # Lifecycle Foundation - a prerequisite turn, not a numbered phase).
        # None of these commands can start, resume, pause, or execute a
        # workflow.
        if lowered.strip() in _WORKFLOW_HISTORY_EXACT and self._registry.has_tool(
            "workflow_history"
        ):
            return "workflow_history"

        if any(
            lowered.startswith(prefix) for prefix in _WORKFLOW_DETAIL_PREFIXES
        ) and self._registry.has_tool("workflow_history"):
            return "workflow_history"

        # Web search (Phase 16): Jarvis's first external-network command.
        # Read-only and GREEN - see WebSearchTool.action_for()'s own fixed,
        # query-independent action string for why query content can never
        # influence classification.
        if self._file_prefix(lowered, _WEB_SEARCH_PREFIXES) is not None and (
            self._registry.has_tool("web_search")
        ):
            return "web_search"

        # File commands are checked next because their phrasing is specific.
        # Only route to a file tool if it is actually registered.
        if self._file_prefix(lowered, _FILE_LIST_PREFIXES) is not None and (
            self._registry.has_tool("file_list")
        ):
            return "file_list"

        if self._file_prefix(lowered, _FILE_READ_PREFIXES) is not None and (
            self._registry.has_tool("file_read")
        ):
            return "file_read"

        # Write commands (create, append) are YELLOW and require approval. They
        # are matched here but the safety gate is enforced by the Tool Executor,
        # exactly as for any other YELLOW action.
        if self._file_prefix(lowered, _FILE_CREATE_PREFIXES) is not None and (
            self._registry.has_tool("file_create")
        ):
            return "file_create"

        if self._file_prefix(lowered, _FILE_APPEND_PREFIXES) is not None and (
            self._registry.has_tool("file_append")
        ):
            return "file_append"

        # Bulk forget is dangerous (RED). Route it to the forget tool so its
        # action string ("forget all memories") is classified RED by the
        # Security Manager and blocked by the Tool Executor - never to the
        # read-only memory tool, which would misclassify it as a safe list.
        if lowered.startswith("forget all") and self._registry.has_tool(
            "memory_forget"
        ):
            return "memory_forget"

        # Memory change commands (update, move, forget) are YELLOW and must be
        # matched before the generic read-only memory tool. The safety gate is
        # still enforced by the Tool Executor; this only selects the tool.
        if lowered.startswith("forget memory") and self._registry.has_tool(
            "memory_forget"
        ):
            return "memory_forget"

        if (
            lowered.startswith("update memory") or lowered.startswith("move memory")
        ) and self._registry.has_tool("memory_update"):
            return "memory_update"

        if self._contains(lowered, _MEMORY_KEYWORDS) and self._registry.has_tool(
            "memory"
        ):
            return "memory"

        if self._contains(lowered, _INFO_KEYWORDS) and self._registry.has_tool("info"):
            return "info"

        if self._contains(lowered, _ECHO_KEYWORDS) and self._registry.has_tool("echo"):
            return "echo"

        return None

    def match_file_summary(self, text: str) -> str | None:
        """Match an explicit file-summary request and extract its path.

        Recognises "summarise file <path>" and "summarize file <path>"
        (Phase 8, Batch 2). This is a distinct, narrow operation from
        match()/build_input(): it never names a registered tool for the
        orchestrator to execute directly, because summarising a file is a
        multi-step AI-reasoning workflow (read the file, then reason about
        its contents), not a single tool execution. Only recognised when
        file_read is registered, since that is the tool this workflow reads
        through.

        Args:
            text: The stripped request text.

        Returns:
            The extracted path if the text matches a file-summary command -
            possibly an empty string, if the phrase was used with no path -
            or None if the text does not match this command at all.
        """
        if not self._registry.has_tool("file_read"):
            return None

        lowered = text.casefold()
        if self._file_prefix(lowered, _FILE_SUMMARY_PREFIXES) is None:
            return None

        return self._extract_path(text, _FILE_SUMMARY_PREFIXES)

    def match_web_search_summary(self, text: str) -> str | None:
        """Match an explicit AI web-search-summary request and extract its query.

        Recognises "summarise web search for <query>" and "summarize web
        search for <query>" (Phase 18, Batch 2). This is a distinct,
        narrow operation from match()/build_input(): it never names a
        registered tool for the orchestrator to execute directly, because
        summarising web search results is a multi-step AI-reasoning
        workflow (search, then reason about the results), not a single
        tool execution.

        Unlike match_file_summary, this method does not gate on any tool
        being registered: this command never goes through ToolExecutor
        or WebSearchTool at all (it calls WebSearchProvider.search()
        directly, mirroring match_memory_summary's own precedent for
        MemoryManager), so there is no registry check that would
        honestly reflect whether the workflow can actually run. Whether
        the required web_search_provider collaborator is available is
        the orchestrator's own responsibility to check.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing query text if the text matches
            this command - possibly empty, if the phrase was used with
            no query - or None if the text does not match this command's
            grammar at all.
        """
        lowered = text.casefold()
        prefix = self._file_prefix(lowered, _WEB_SEARCH_SUMMARY_PREFIXES)
        if prefix is None:
            return None

        return text[len(prefix) :].strip()

    def match_memory_summary(self, text: str) -> str | None:
        """Match an explicit memory-summary request and extract its raw id text.

        Recognises "summarise memory <id>" and "summarize memory <id>"
        (Phase 9, Batch 2). This is a distinct, narrow operation from
        match()/build_input(), mirroring match_file_summary(): it never names
        a registered tool for the orchestrator to execute directly, because
        summarising a memory is a multi-step AI-reasoning workflow (retrieve
        the memory, then reason about its contents), not a single tool
        execution.

        Only the raw trailing text is extracted here - unlike
        _extract_memory_id/_extract_trailing_id (used by the existing
        "forget memory <id>"/"show memory <id>" commands, which parse
        straight to an int for a ToolExecutor-routed tool's input), the id
        here is deliberately left as unparsed text. This command never goes
        through ToolExecutor or MemoryTool, so validating and parsing it into
        an int is the orchestrator's responsibility, not this router's
        (Phase 9 plan, Section 18, Batch 2).

        Unlike match_file_summary, this method does not gate on any tool
        being registered: memory summarisation never goes through a
        registered tool at all, so there is no registry check that would
        honestly reflect whether the workflow can actually run. Whether the
        required memory_manager collaborator is available is the
        orchestrator's own responsibility to check.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing text if the text matches a
            memory-summary command - possibly empty, or non-numeric, if the
            phrase was used with no id or a malformed one - or None if the
            text does not match this command at all.
        """
        lowered = text.casefold()
        prefix = self._file_prefix(lowered, _MEMORY_SUMMARY_PREFIXES)
        if prefix is None:
            return None

        return text[len(prefix) :].strip()

    def match_memory_query_summary(self, text: str) -> str | None:
        """Match an explicit query-based memory-summary request and extract
        its raw query text.

        Recognises "summarise memories about <query>" and "summarize
        memories about <query>" (Phase 11, Batch 2) - the query-based
        sibling of match_memory_summary()/match_memory_set_summary(). Only
        the raw trailing text is extracted here, exactly as those methods
        already do: query parsing, empty/whitespace-query rejection, and
        deterministic search selection are the orchestrator's
        responsibility (docs/phase_11_implementation_plan.md, Section
        3/6), not this router's. This method never interprets the query
        semantically, never escapes or normalises it, and never performs
        natural-language routing of any kind - the only input it
        recognises is the literal, required "about" grammar plus whatever
        text follows it.

        The caller MUST check this method before match_memory_set_summary():
        "summarise memories about" is a strict superset-string of
        "summarise memories", so checking the plural explicit-id matcher
        first would incorrectly swallow a query-based request
        (docs/phase_11_implementation_plan.md, Section 3.1/3.2.1). This
        method does not collide with match_memory_summary() (singular) in
        either direction: "summarise memory" and "summarise memories"
        diverge at the word's 6th character ('y' vs 'i'), confirmed
        non-colliding, so its position relative to that check does not
        affect correctness.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing query text if the text matches a
            query-based memory-summary command - possibly empty, if the
            phrase was used with no query text at all - or None if the
            text does not match this command at all.
        """
        lowered = text.casefold()
        prefix = self._file_prefix(lowered, _MEMORY_QUERY_SUMMARY_PREFIXES)
        if prefix is None:
            return None

        return text[len(prefix) :].strip()

    def match_memory_category_summary(self, text: str) -> str | None:
        """Match an explicit category-based memory-summary request and
        extract its raw category text.

        Recognises "summarise memories in <category>" and "summarize
        memories in <category>" (Phase 12, Batch 2) - the category-based
        sibling of match_memory_query_summary()/match_memory_set_summary().
        Only the raw trailing text is extracted here, exactly as those
        methods already do: category validation, canonicalisation, and
        deterministic category lookup are the orchestrator/selector's
        responsibility (docs/phase_12_implementation_plan.md, Section
        4/5), not this router's. This method never interprets the category
        semantically, never normalises or validates it, and never performs
        natural-language routing of any kind - the only input it
        recognises is the literal, required "in" grammar plus whatever
        text follows it.

        The caller MUST check this method before match_memory_set_summary():
        "summarise memories in" is a strict superset-string of "summarise
        memories", so checking the plural explicit-id matcher first would
        incorrectly swallow a category-based request
        (docs/phase_12_implementation_plan.md, Section 3.1/3.2). This
        method does not collide with match_memory_summary() (singular) or
        match_memory_query_summary() (Phase 11) in either direction:
        "summarise memory" diverges at the word's 6th character ('y' vs
        'i'), and "summarise memories about" diverges at the second word
        ("about" vs "in") - so its position relative to either of those
        checks does not affect correctness.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing category text if the text matches a
            category-based memory-summary command - possibly empty, if
            the phrase was used with no category text at all - or None if
            the text does not match this command at all.
        """
        lowered = text.casefold()
        prefix = self._file_prefix(lowered, _MEMORY_CATEGORY_SUMMARY_PREFIXES)
        if prefix is None:
            return None

        return text[len(prefix) :].strip()

    def match_memory_recent_summary(self, text: str) -> bool:
        """Match the exact, complete recent-memory-summary command.

        Recognises only the exact phrases "summarise recent memories" and
        "summarize recent memories" (Phase 13, Batch 2), matched
        case-insensitively after stripping surrounding whitespace - never
        as a prefix. Unlike match_memory_summary/match_memory_query_summary/
        match_memory_category_summary/match_memory_set_summary, this
        command carries no trailing free-text argument at all: there is no
        query, category, or id list to extract, so there is nothing for
        this method to return except whether the exact command was used.
        Any extra trailing text - "summarise recent memories about
        security", "summarise recent memories in project", "summarise
        recent memories 5", "summarise very recent memories" - names a
        different, unrecognised command; it is never silently accepted as
        this one with the extra tokens ignored
        (docs/phase_13_implementation_plan.md, Section 4.2).

        This method does not collide with match_memory_summary (singular),
        match_memory_query_summary, match_memory_category_summary, or
        match_memory_set_summary in either direction (Section 4.1) - its
        position relative to those checks in the caller's dispatch order
        does not affect correctness, unlike the query/category matchers'
        genuine ordering requirement relative to the plural matcher.

        Args:
            text: The stripped request text.

        Returns:
            True if text is exactly one of the two recognised phrases
            (case-insensitively, ignoring only surrounding whitespace),
            False otherwise - including when extra trailing text is
            present.
        """
        return text.strip().casefold() in _MEMORY_RECENT_SUMMARY_EXACT

    def match_memory_recent_count_summary(self, text: str) -> str | None:
        """Match a count-based recent-memory-summary request and extract
        its raw count text.

        Recognises "summarise latest <count> memories" and "summarize
        latest <count> memories" (Phase 14, Batch 2) - the user-count-
        bounded sibling of match_memory_recent_summary(). Unlike that
        method (an exact match with no trailing content at all), this
        grammar has real content to extract, so - like
        match_memory_query_summary()/match_memory_category_summary()/
        match_memory_set_summary() - it returns the raw captured text, or
        None if the text does not have this exact shape.

        This is the first summary-family grammar requiring both a fixed
        prefix ("summarise latest"/"summarize latest") and a fixed,
        mandatory suffix ("memories") with required content between them -
        every other matcher only ever recognises a prefix and treats
        everything after it as trailing text. `fullmatch` against the
        compiled pattern means any extra trailing content after the final
        "memories" ("... memories about security", "... memories in
        project") fails the match entirely - it is never silently accepted
        with the extra tokens ignored; a missing count ("summarise latest
        memories") also fails to match, since the captured group requires
        at least one non-whitespace character strictly between "latest "
        and " memories"; and an extra qualifier word between the count and
        "memories" ("summarise latest 5 stored memories") also fails to
        match, since the captured group cannot span the whitespace
        separating two words (docs/phase_14_implementation_plan.md,
        Section 4.3).

        This method performs no validation of the captured text beyond
        recognising the grammatical shape: it does not check whether the
        captured text is numeric, in range, or otherwise well-formed - a
        grammatically complete but semantically invalid count (for example
        "summarise latest five memories" or "summarise latest 55
        memories") still matches and returns its raw text unchanged.
        Numeric/range validation is
        ai.memory_selection.select_recent_memory_ids_by_count()'s own
        responsibility (Phase 14 plan, Section 5.1), mirroring exactly how
        match_memory_category_summary() defers category validity to
        select_memory_ids_by_category().

        This method does not collide with match_memory_summary (singular),
        match_memory_query_summary, match_memory_category_summary,
        match_memory_recent_summary, or match_memory_set_summary in either
        direction (Phase 14 plan, Section 4.2/4.3) - its position relative
        to those checks in the caller's dispatch order does not affect
        correctness.

        Args:
            text: The stripped request text.

        Returns:
            The raw, unvalidated captured count text (a single,
            internally-whitespace-free token) if text matches this exact
            grammar - possibly non-numeric or out of range, if the phrase
            was used with a malformed count - or None if the text does not
            match this grammar at all.
        """
        match = _MEMORY_RECENT_COUNT_SUMMARY_PATTERN.fullmatch(text)
        if match is None:
            return None

        return match.group(1)

    def match_memory_set_summary(self, text: str) -> str | None:
        """Match an explicit multi-memory-summary request and extract its
        raw id-list text.

        Recognises "summarise memories <ids>" and "summarize memories <ids>"
        (Phase 10, Batch 2) - the plural sibling of match_memory_summary().
        Only the raw trailing text is extracted here, exactly as
        match_memory_summary() already does for a single id: parsing
        individual tokens, stable deduplication, and cardinality validation
        are the orchestrator's responsibility
        (docs/phase_10_implementation_plan.md, Section 10.1/17), not this
        router's. This method requires only an explicit id list; it never
        performs natural-language search, recency-based selection,
        category-based selection, or any form of automatic or AI-driven
        memory selection - the only input it ever recognises is the literal
        digits the user typed.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing text if the text matches a
            multi-memory-summary command - possibly empty or malformed, if
            the phrase was used with no ids or an invalid list - or None if
            the text does not match this command at all.
        """
        lowered = text.casefold()
        prefix = self._file_prefix(lowered, _MEMORY_SET_SUMMARY_PREFIXES)
        if prefix is None:
            return None

        return text[len(prefix) :].strip()

    def match_remember_and_show_back_workflow(self, text: str) -> str | None:
        """Match the exact "remember this and show it back: <text>" command.

        Recognises only this exact, complete leading phrase (Phase 15,
        Batch 3), including its mandatory trailing colon, matched
        case-insensitively. Like match_memory_summary and its siblings,
        this never names a registered tool for the orchestrator to execute
        directly - a workflow command is a multi-step execution handled by
        its own dedicated Orchestrator handler, not a single tool_name
        dispatched through match()/build_input(). Only the raw trailing
        text is extracted; whether it is empty or whitespace-only after
        stripping is the orchestrator's responsibility to reject honestly,
        exactly as the Phase 11 query matcher defers empty-query rejection
        to its own handler.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing text if the text starts with the
            exact required phrase (case-insensitively) - possibly empty or
            whitespace-only - or None if the text does not match this
            command's grammar at all.
        """
        lowered = text.casefold()
        if not lowered.startswith(_REMEMBER_AND_SHOW_BACK_WORKFLOW_PREFIX):
            return None

        return text[len(_REMEMBER_AND_SHOW_BACK_WORKFLOW_PREFIX) :].strip()

    def match_remember_and_forget_workflow(self, text: str) -> str | None:
        """Match the exact "remember this and forget it: <text>" command.

        Recognises only this exact, complete leading phrase (Phase 15,
        Batch 3), including its mandatory trailing colon, matched
        case-insensitively. Mirrors
        match_remember_and_show_back_workflow exactly, for the
        GREEN-then-YELLOW sibling workflow.

        Args:
            text: The stripped request text.

        Returns:
            The extracted raw trailing text if the text starts with the
            exact required phrase (case-insensitively) - possibly empty or
            whitespace-only - or None if the text does not match this
            command's grammar at all.
        """
        lowered = text.casefold()
        if not lowered.startswith(_REMEMBER_AND_FORGET_WORKFLOW_PREFIX):
            return None

        return text[len(_REMEMBER_AND_FORGET_WORKFLOW_PREFIX) :].strip()

    def match_create_and_read_workflow(self, text: str) -> tuple[str, str] | None:
        """Match the exact "create file <path> with <content> and show it"
        command (Phase 17, Batch 2).

        Requires BOTH an existing create-file prefix (_FILE_CREATE_PREFIXES)
        AND the exact, fixed trailing suffix " and show it" (matched via
        str.endswith on the fully stripped text, never a substring search,
        so an occurrence of those words in the middle of content never
        triggers anything). Returns None - a clean non-match, falling
        through to the ordinary, completely unmodified generic
        match()/build_input() -> file_create path - whenever either
        condition is absent, so the standalone "create file <path> with
        <content>" command (with no trailing suffix) is entirely
        unaffected by this method's existence.

        Once both conditions hold, the suffix is removed by length (not
        by re-searching) and the remaining text is handed directly to the
        existing, unmodified _extract_create_input() classmethod - no new
        path/content-splitting logic exists here.

        Disclosed, accepted limitation (docs/phase_17_implementation_plan.md,
        Section 5): content that itself legitimately ends with the exact
        literal words "and show it" cannot be distinguished from the
        workflow trigger and will always be treated as this workflow,
        with those trailing words stripped from what is actually written.

        Args:
            text: The stripped request text.

        Returns:
            A (path, content) tuple - each possibly empty, exactly as
            _extract_create_input() already tolerates for the standalone
            command - or None if the text does not match this workflow's
            grammar at all.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        if self._file_prefix(lowered, _FILE_CREATE_PREFIXES) is None:
            return None
        if not lowered.endswith(_CREATE_AND_READ_WORKFLOW_SUFFIX):
            return None

        without_suffix = stripped[: len(stripped) - len(_CREATE_AND_READ_WORKFLOW_SUFFIX)]
        return self._extract_create_input(without_suffix)

    def match_update_and_show_workflow(
        self, text: str
    ) -> tuple[int | None, str] | None:
        """Match the exact "update memory <id>: <content> and show it back"
        command (Phase 17, Batch 2).

        Requires BOTH the exact leading phrase "update memory" AND the
        exact, fixed trailing suffix " and show it back" (matched via
        str.endswith on the fully stripped text, never a substring
        search). Returns None - a clean non-match, falling through to the
        ordinary, completely unmodified _build_memory_update_input() path
        - whenever either condition is absent, so the standalone "update
        memory <id>: <content>" command (with no trailing suffix), and
        its sibling "move memory <id> to <category>" command (which never
        starts with "update memory" at all), are both entirely unaffected
        by this method's existence.

        Once both conditions hold, the suffix is removed by length, and
        the same id-extraction and first-colon-split logic
        _build_memory_update_input()'s own "update" branch already uses is
        applied directly - no new parsing logic exists here.

        Disclosed, accepted limitation (docs/phase_17_implementation_plan.md,
        Section 5): replacement content that itself legitimately ends
        with the exact literal words "and show it back" cannot be
        distinguished from the workflow trigger and will always be
        treated as this workflow, with those trailing words stripped from
        what is actually stored.

        Args:
            text: The stripped request text.

        Returns:
            A (memory_id, content) tuple - memory_id is None when it
            cannot be parsed as an integer, exactly as
            _extract_memory_id() already tolerates for the standalone
            command; content may be empty - or None if the text does not
            match this workflow's grammar at all.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        if not lowered.startswith("update memory"):
            return None
        if not lowered.endswith(_UPDATE_AND_SHOW_WORKFLOW_SUFFIX):
            return None

        without_suffix = stripped[: len(stripped) - len(_UPDATE_AND_SHOW_WORKFLOW_SUFFIX)]
        memory_id = self._extract_memory_id(without_suffix, "update memory")
        content = ""
        if ":" in without_suffix:
            content = without_suffix.split(":", 1)[1].strip()
        return memory_id, content

    def build_input(self, tool_name: str, text: str) -> dict[str, object]:
        """Build the input dictionary for the matched tool.

        Args:
            tool_name: The name of the tool that will run.
            text: The stripped request text.

        Returns:
            The input dictionary the tool expects.
        """
        if tool_name == "memory":
            return self._build_memory_input(text)

        if tool_name == "memory_update":
            return self._build_memory_update_input(text)

        if tool_name == "approval_history":
            return self._build_approval_history_input(text)

        if tool_name == "workflow_history":
            return self._build_workflow_history_input(text)

        if tool_name == "web_search":
            return self._build_web_search_input(text)

        if tool_name == "memory_forget":
            if text.strip().casefold().startswith("forget all"):
                # Bulk forget: no id. The tool's action classifies RED and the
                # executor blocks it; nothing is ever forgotten in bulk.
                return {"all": True}
            return {"memory_id": self._extract_memory_id(text, "forget memory")}

        if tool_name == "echo":
            return {"text": text}

        if tool_name == "file_list":
            alias = _WORKFLOW_ALIASES.get(text.casefold().strip())
            if alias is not None:
                return {"path": alias[1]}
            path = self._extract_path(text, _FILE_LIST_PREFIXES)
            # Default to the current directory when no path is given.
            return {"path": path or "."}

        if tool_name == "file_read":
            alias = _WORKFLOW_ALIASES.get(text.casefold().strip())
            if alias is not None:
                return {"path": alias[1]}
            path = self._extract_path(text, _FILE_READ_PREFIXES)
            return {"path": path}

        if tool_name == "file_create":
            path, content = self._extract_create_input(text)
            return {"path": path, "content": content}

        if tool_name == "file_append":
            path, content = self._extract_append_input(text)
            return {"path": path, "content": content}

        # info takes no input
        return {}

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        """Report whether any keyword appears in the text.

        Args:
            text: The already-lowercased text to search.
            keywords: The keywords to look for.

        Returns:
            True if any keyword is present, False otherwise.
        """
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _file_prefix(lowered: str, prefixes: tuple[str, ...]) -> str | None:
        """Return the first file-command prefix the text starts with.

        Prefixes are checked longest-first so that a more specific phrase (for
        example "list files in") is preferred over a shorter one ("list files").

        Args:
            lowered: The already-lowercased request text.
            prefixes: The candidate prefixes to check.

        Returns:
            The matching prefix, or None if the text starts with none of them.
        """
        for prefix in sorted(prefixes, key=len, reverse=True):
            if lowered.startswith(prefix):
                return prefix
        return None

    @classmethod
    def _extract_path(cls, text: str, prefixes: tuple[str, ...]) -> str:
        """Extract the path portion of a file command.

        The matching prefix is removed from the start of the request, and the
        remainder is treated as the path. A leading filler word ("the") and
        surrounding quotes or whitespace are stripped.

        Args:
            text: The original (unlowered) request text.
            prefixes: The prefixes for this file command.

        Returns:
            The extracted path, or an empty string if none was given.
        """
        prefix = cls._file_prefix(text.casefold(), prefixes)
        if prefix is None:
            return ""

        remainder = text[len(prefix) :].strip()
        # Drop a leading filler word such as "the" ("read the file the notes").
        if remainder.casefold().startswith("the "):
            remainder = remainder[4:].strip()
        # Strip surrounding quotes if the user quoted the path.
        return remainder.strip("'\"").strip()

    @classmethod
    def _extract_create_input(cls, text: str) -> tuple[str, str]:
        """Extract (path, content) from a create-file command.

        The recognised shape is: "<create-prefix> <path> with <content>". The
        "with <content>" part is optional; when absent, the content is empty and
        an empty file is created.

        Args:
            text: The original request text.

        Returns:
            A tuple of (path, content). Either may be empty, in which case the
            tool itself reports the problem (empty path is rejected).
        """
        remainder = cls._strip_write_prefix(text, _FILE_CREATE_PREFIXES)
        path_part, content = cls._split_on_keyword(remainder, " with ")
        return cls._clean_path(path_part), content

    @classmethod
    def _extract_append_input(cls, text: str) -> tuple[str, str]:
        """Extract (path, content) from an append-file command.

        Two shapes are recognised:
            "append <content> to file <path>"
            "append to file <path> <content>"
        The first shape is preferred: if the phrase contains " to file " or
        " to ", the text before it is the content and the text after it is the
        path.

        Args:
            text: The original request text.

        Returns:
            A tuple of (path, content). Either may be empty, in which case the
            tool itself reports the problem.
        """
        remainder = cls._strip_write_prefix(text, _FILE_APPEND_PREFIXES)

        for separator in (" to file ", " to "):
            if separator in remainder.casefold():
                idx = remainder.casefold().index(separator)
                content = remainder[:idx].strip()
                path_part = remainder[idx + len(separator) :].strip()
                return cls._clean_path(path_part), cls._clean_content(content)

        # No separator: treat the whole remainder as the path, no content. The
        # append tool will then reject the empty content, which is correct.
        return cls._clean_path(remainder), ""

    @classmethod
    def _strip_write_prefix(cls, text: str, prefixes: tuple[str, ...]) -> str:
        """Remove the matching write-command prefix from the text.

        Args:
            text: The original request text.
            prefixes: The write-command prefixes to check.

        Returns:
            The text after the prefix, stripped, or the original text if no
            prefix matched.
        """
        prefix = cls._file_prefix(text.casefold(), prefixes)
        if prefix is None:
            return text.strip()
        return text[len(prefix) :].strip()

    @staticmethod
    def _split_on_keyword(text: str, keyword: str) -> tuple[str, str]:
        """Split text once on a keyword, case-insensitively.

        Args:
            text: The text to split.
            keyword: The separator to split on (for example, " with ").

        Returns:
            A tuple of (before, after). If the keyword is absent, after is
            empty and before is the whole text.
        """
        lowered = text.casefold()
        if keyword in lowered:
            idx = lowered.index(keyword)
            return text[:idx].strip(), text[idx + len(keyword) :].strip()
        return text.strip(), ""

    @staticmethod
    def _clean_path(path_part: str) -> str:
        """Clean an extracted path fragment.

        Args:
            path_part: The raw path fragment.

        Returns:
            The path with a leading "the ", surrounding quotes, and whitespace
            removed.
        """
        cleaned = path_part.strip()
        if cleaned.casefold().startswith("the "):
            cleaned = cleaned[4:].strip()
        return cleaned.strip("'\"").strip()

    @staticmethod
    def _clean_content(content: str) -> str:
        """Clean an extracted content fragment.

        Args:
            content: The raw content fragment.

        Returns:
            The content with surrounding quotes and whitespace removed.
        """
        return content.strip().strip("'\"")

    @classmethod
    def _build_memory_input(cls, text: str) -> dict[str, object]:
        """Parse a memory command into a memory-tool input dictionary.

        Six command shapes are recognised (case-insensitively):
            remember this: <text>                     -> save (general)
            remember this as <category>: <text>       -> save (<category>)
            show memories                             -> list
            show memories in <category>               -> list (<category>)
            search memories for <query>               -> search
            search memories in <category> for <query> -> search (<category>)

        Anything unrecognised falls back to a plain list, so the command is
        always safe and read-only by default.

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the memory tool.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        # --- Show one by id: "show memory <id>" ---
        if lowered.startswith("show memory") or lowered.startswith("view memory"):
            memory_id = cls._extract_trailing_id(stripped)
            if memory_id is not None:
                return {"operation": "get", "memory_id": memory_id}
            # "show memories" (no id) falls through to the list handling below.

        # --- Save: "remember this[ as <category>]: <content>" ---
        if lowered.startswith("remember this"):
            after = stripped[len("remember this"):]
            category: str | None = None
            # Optional "as <category>" before the colon.
            if after.casefold().lstrip().startswith("as "):
                as_part = after.lstrip()[3:]
                if ":" in as_part:
                    cat_text, content = as_part.split(":", 1)
                    category = cat_text.strip()
                    return {
                        "operation": "save",
                        "content": content.strip(),
                        "category": category,
                    }
            # Plain "remember this: <content>".
            if ":" in after:
                _, content = after.split(":", 1)
                return {"operation": "save", "content": content.strip()}
            # "remember this <content>" with no colon: treat the rest as content.
            return {"operation": "save", "content": after.strip()}

        # --- Search: "search memories [in <category>] for <query>" ---
        if "search" in lowered and (
            "memor" in lowered
        ):
            category = cls._extract_between(lowered, stripped, " in ", " for ")
            query = cls._extract_after(stripped, " for ")
            result: dict[str, object] = {"operation": "search"}
            if query:
                result["query"] = query
            if category:
                result["category"] = category
            return result

        # --- List: "show memories [in <category>]" ---
        if ("show" in lowered or "list" in lowered) and "memor" in lowered:
            category = cls._extract_after(stripped, " in ")
            result = {"operation": "list"}
            if category:
                result["category"] = category
            return result

        # Fallback: safe read-only list.
        return {"operation": "list"}

    @staticmethod
    def _extract_after(text: str, marker: str) -> str:
        """Return the text after a marker phrase, cleaned. Empty if absent.

        Args:
            text: The original text.
            marker: The marker phrase to search for (case-insensitive).

        Returns:
            The trimmed, unquoted text after the marker, or "" if not present.
        """
        lowered = text.casefold()
        idx = lowered.find(marker)
        if idx == -1:
            return ""
        return text[idx + len(marker):].strip().strip("'\"")

    @staticmethod
    def _extract_between(text: str, lowered: str, start: str, end: str) -> str:
        """Return the text between two markers, cleaned. Empty if absent.

        Args:
            text: The original text.
            lowered: The lower-cased original text (for index finding).
            start: The starting marker phrase.
            end: The ending marker phrase.

        Returns:
            The trimmed text between the markers, or "" if the pair is absent.
        """
        start_idx = lowered.find(start)
        if start_idx == -1:
            return ""
        after_start = start_idx + len(start)
        end_idx = lowered.find(end, after_start)
        if end_idx == -1:
            return ""
        return text[after_start:end_idx].strip().strip("'\"")

    @classmethod
    def _build_memory_update_input(cls, text: str) -> dict[str, object]:
        """Parse an update or move command into memory_update tool input.

        Recognised shapes:
            update memory <id>: <new text>   -> operation "update"
            move memory <id> to <category>   -> operation "move"

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the memory_update tool. Missing pieces are
            left absent so the tool reports the problem clearly.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        if lowered.startswith("move memory"):
            memory_id = cls._extract_memory_id(stripped, "move memory")
            category = cls._extract_after(stripped, " to ")
            result: dict[str, object] = {"operation": "move"}
            if memory_id is not None:
                result["memory_id"] = memory_id
            if category:
                result["category"] = category
            return result

        # Default: update content. "update memory <id>: <new text>"
        memory_id = cls._extract_memory_id(stripped, "update memory")
        content = ""
        if ":" in stripped:
            content = stripped.split(":", 1)[1].strip()
        result = {"operation": "update"}
        if memory_id is not None:
            result["memory_id"] = memory_id
        if content:
            result["content"] = content
        return result

    @classmethod
    def _build_approval_history_input(cls, text: str) -> dict[str, object]:
        """Parse an approval-history command into a tool input dictionary.

        Five command shapes are recognised (case-insensitively):
            show approval history   -> history (most recent, any status)
            show recent approvals   -> recent (last 10, any status)
            show approved actions   -> approved
            show declined actions   -> declined
            show approval <id>      -> get (a single entry by request_id)
            view approval <id>      -> get (a single entry by request_id)

        The <id> for "get" is an approval request_id (a UUID string, not a
        numeric memory id), so it is taken as the raw trailing text rather
        than parsed as an integer.

        Anything unrecognised falls back to "history", so the command is
        always read-only by default.

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the approval_history tool.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        operation = _APPROVAL_HISTORY_EXACT.get(lowered)
        if operation is not None:
            return {"operation": operation}

        for prefix in _APPROVAL_DETAIL_PREFIXES:
            if lowered.startswith(prefix):
                request_id = stripped[len(prefix):].strip().strip(":").strip()
                if request_id:
                    return {"operation": "get", "request_id": request_id}

        return {"operation": "history"}

    @classmethod
    def _build_workflow_history_input(cls, text: str) -> dict[str, object]:
        """Parse a workflow-history command into a tool input dictionary.

        Four command shapes are recognised (case-insensitively):
            show workflow history   -> history (most recent, all workflows)
            show recent workflows   -> recent (last 10 transitions)
            show workflow <id>      -> get (one workflow's full history)
            view workflow <id>      -> get (one workflow's full history)

        The <id> for "get" is a workflow_id (a UUID string), so it is taken
        as the raw trailing text rather than parsed as an integer.

        Anything unrecognised falls back to "history", so the command is
        always read-only by default.

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the workflow_history tool.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        operation = _WORKFLOW_HISTORY_EXACT.get(lowered)
        if operation is not None:
            return {"operation": operation}

        for prefix in _WORKFLOW_DETAIL_PREFIXES:
            if lowered.startswith(prefix):
                workflow_id = stripped[len(prefix):].strip().strip(":").strip()
                if workflow_id:
                    return {"operation": "get", "workflow_id": workflow_id}

        return {"operation": "history"}

    @classmethod
    def _build_web_search_input(cls, text: str) -> dict[str, object]:
        """Parse a web-search command into a tool input dictionary.

        One shape is recognised (case-insensitively):
            search the web for <query>

        The <query> is the raw trailing text, surrounding quotes and
        whitespace stripped. No further parsing, filtering, or rewriting
        is applied - WebSearchTool itself is responsible for rejecting an
        empty query.

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the web_search tool.
        """
        stripped = text.strip()
        prefix = cls._file_prefix(stripped.casefold(), _WEB_SEARCH_PREFIXES)
        if prefix is None:
            return {"query": ""}

        query = stripped[len(prefix):].strip().strip("'\"").strip()
        return {"query": query}

    @staticmethod
    def _extract_memory_id(text: str, prefix: str) -> int | None:
        """Extract the first integer id following a command prefix.

        Args:
            text: The original request text.
            prefix: The command prefix (e.g. "forget memory") to strip first.

        Returns:
            The id as an int, or None if none was found.
        """
        lowered = text.casefold()
        idx = lowered.find(prefix.casefold())
        remainder = text[idx + len(prefix):] if idx != -1 else text
        for token in remainder.replace(":", " ").split():
            if token.isdigit():
                return int(token)
        return None

    @staticmethod
    def _extract_trailing_id(text: str) -> int | None:
        """Extract a numeric id from a 'show memory <id>' style command.

        Args:
            text: The original request text.

        Returns:
            The id as an int, or None if no numeric token is present.
        """
        for token in text.replace(":", " ").split():
            if token.isdigit():
                return int(token)
        return None
