# Phase 16 Implementation Plan — Web Search Tool and External Content Boundary

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `0705a1c04dde03fcdfd16a9de3d4f4d6431a5d30` ("Close Durable Workflow
Lifecycle Foundation"), branch `phase-4-ai-reasoning-and-write-actions`,
working tree clean. `poetry run pytest -q` — **1878 passed, 0 failed**,
re-run fresh for this planning turn. No pre-existing failure exists.

---

## 1. Purpose

Give Jarvis its first real external-network capability: a deterministic,
read-only web-search tool that returns live search results directly to
Nathan. No AI reasoning involvement, no write authority, no autonomous
behavior of any kind.

## 2. Scope

**In scope:** one new tool (`web_search`), a small provider/adapter
boundary between Jarvis and the concrete DuckDuckGo implementation, one
new deterministic command, a stable Jarvis-owned result model, and full
security/observability/rendering treatment consistent with every existing
GREEN tool.

**Explicitly out of scope (repeated here from the authorizing instructions,
verified against no contrary evidence anywhere in the repository):**
autonomous browsing; arbitrary URL fetching; webpage summarization; AI
summarization of search results; AI-authored queries; AI-selected tool
execution; a Research Agent; scheduling/background execution;
notifications; any workflow-resumption change; a plugin architecture;
multi-provider routing; user-configurable result counts; deduplication
logic; a maximum query-length limit (see §9).

## 3. Repository Inspection Performed Before This Plan

Directly inspected this turn, not recalled from memory:

- **Master Specification**: Ch26 (Long-Term Vision & Roadmap) explicitly
  lists "Web search... tools" under its own "Phase 1 — Foundation"
  objective — this repository's Phase 16 fulfills that literal bullet,
  arriving later in this repo's own numbering than the spec's macro-phase
  language, consistent with how every prior phase's numbering has already
  diverged from the spec's own macro-phase count (Phase 5–15 already
  cover far more than the spec's "Phase 1" bullet list literally
  describes). No dedicated "web search" or "external network tool"
  chapter exists; Ch17 (Plugin Architecture), Ch20 (AI Agent System §
  Research Agent), and Ch22 (Computer Control) are the nearest
  spec chapters describing *larger* capabilities this phase deliberately
  does not attempt.
- **README** "Next Phase" section (current, unmodified by this plan):
  states the next numbered direction "has not been chosen and still
  requires its own fresh review" — consistent with treating Phase 16 as
  a fresh, evidence-based decision, not a foregone conclusion.
- **`core/command_router.py`**: `_file_prefix()` (longest-prefix-first,
  sorted by length descending) is a generic, reusable prefix-matching
  helper already used by `_FILE_READ_PREFIXES`, `_MEMORY_SUMMARY_PREFIXES`,
  etc. — directly reusable for the new command, not file-specific despite
  its name. A dead, unused `_SEARCH_KEYWORDS` constant exists at module
  level (line 139) — confirmed by repository-wide grep to have exactly
  one reference (its own declaration); a *different*, actually-used
  `_SEARCH_KEYWORDS` exists in `planner/planner.py` for the unrelated,
  lower-priority keyword-fallback path only reached when `match()`
  returns `None`. Neither is touched by this plan; the new command is
  handled by an explicit, dedicated prefix table exactly like every
  other Phase 6–15 command.
- **`tools/base_tool.py`**: `BaseTool.action_for()` returns a string that
  is independently classified by `SecurityManager.classify_action()` —
  confirmed via `tools/executor.py:116`
  (`self._security.classify_action(tool.action_for(request))`). This
  means a tool's classification can be made **completely independent of
  user-supplied content** by having `action_for()` return a fixed string
  — the design every existing read-only tool with free-text input
  (`MemoryTool`'s search operation, `ApprovalHistoryTool`,
  `WorkflowHistoryTool`) already uses, and the design this plan adopts
  (§7).
- **`security/security_manager.py`**: full `_RULES` tuple inspected.
  Confirmed no existing RED/YELLOW keyword (`"download"`, `"execute"`,
  `"delete"`, `"remove"`, etc.) is a substring of the fixed action string
  this plan proposes (`"search the web"` — see §7). Confirmed the
  existing generic `"search"` → GREEN rule already exists and would also
  match, but the plan does not rely on it, to keep the new tool's
  classification independent and explicit rather than incidental.
- **`ai/providers/base.py` / `ai/providers/claude.py`**: the existing
  precedent for an abstract-provider-plus-one-concrete-adapter boundary
  (`AIProvider(ABC)` + `ClaudeProvider(AIProvider)`), injected into
  `AIRouter` by `main.py`. This plan's provider boundary (§5) is
  structurally modeled on this precedent, deliberately **not** placed
  under `ai/` (this is not an AI provider, and placing it there would
  misleadingly imply AI/trust involvement it does not have), and
  deliberately **not** built as a subpackage anticipating multiple
  interchangeable providers — `ai/providers/` anticipates real
  multi-provider routing (Ch24 AI Provider Independence); this plan's own
  explicit instruction is to avoid that shape here.
- **`ai/file_ingestion.py` / `ai/context_models.py`**: the exact,
  established untrusted-external-content pattern
  (`AIContextBlock.untrusted(...)`, `ContentTrust.UNTRUSTED`) that any
  *future* AI-facing extension of this tool would be required to reuse —
  confirmed to exist and to be reusable without modification; **not
  invoked anywhere in Phase 16's own scope**, since Phase 16 has no
  AI-facing path at all.
- **`tools/executor.py`**: `_emit_audit_event()` (Phase 15 Batch 4A's
  corrective closure) already wraps every tool's audit emission,
  regardless of which tool, in the narrow `try/except Exception: pass`
  isolation pattern. **Finding: no new observability-isolation code is
  needed for this tool** — `ToolExecutor`'s existing, already-fixed
  isolation covers `WebSearchTool` for free, exactly as it already covers
  every other tool.
- **`ui/cli.py`**: confirmed by prior, direct reading (Phase 15 Batch 4
  and this foundation turn) that `format_response()` only ever prints
  `JarvisResponse`/`ToolResult` text — there is no code path anywhere
  that re-parses a `ToolResult.output` string as a new command, plan, or
  instruction.
- **Test conventions**: `unittest.mock`/`monkeypatch` are already used
  across the suite (e.g. `tests/unit/test_main_ai_wiring.py`) to avoid
  live external calls — the same "every test uses a fake provider"
  discipline already established for `ClaudeProvider` is directly
  reusable for `DuckDuckGoSearchProvider`: **no test in this phase should
  ever make a real network call.**

## 4. Dependency and API Inspection (installed environment, this turn)

Directly verified, not assumed:

- Installed package: `duckduckgo-search` **8.1.1** (confirmed via
  `poetry show` and `pip show`).
- Import surface: `from duckduckgo_search import DDGS`.
- **`DDGS.__init__(self, headers=None, proxy=None, proxies=None,
  timeout: int | None = 10, verify: bool = True)`** — timeout is directly
  and explicitly controllable via the constructor; default 10 seconds.
- **`DDGS.text(keywords: str, region=None, safesearch="moderate",
  timelimit=None, backend="auto", max_results: int | None = None) ->
  list[dict[str, str]]`** — synchronous, blocking. Confirmed via
  `inspect.signature` and the method's own docstring, not memory.
- **Result dict shape, confirmed directly from the installed package's
  own source** (`duckduckgo_search/duckduckgo_search.py`): every result
  dict has exactly three keys, `"title"`, `"href"`, `"body"` — all
  passed through the library's own `_normalize`/`_normalize_url` helpers
  before being returned.
- **Exceptions** (`duckduckgo_search.exceptions`): `DuckDuckGoSearchException`
  (base), `RatelimitException`, `TimeoutException`, and
  `ConversationLimitException` (unrelated to text search).
- **Compatibility finding (significant, disclosed): the installed
  package emits a `RuntimeWarning` on every call** — reproduced directly
  this turn:
  `"This package (duckduckgo_search) has been renamed to ddgs! Use pip
  install ddgs instead."` The `ddgs` package is **not** installed in this
  environment (confirmed: `import ddgs` fails). **This plan does not
  upgrade or switch to `ddgs` in Phase 16** — that would be an
  undisclosed scope change to a dependency the user did not authorize
  touching. It is recorded here as disclosed, carried-forward debt (§13,
  §17) and as the single strongest piece of evidence justifying the
  provider-boundary decision in §5: a thin adapter is what allows a
  future migration to `ddgs` (or any other provider) without touching
  `WebSearchTool`, `CommandRouter`, or `ToolExecutor` at all.
- **Live-call attempt this turn**: a real call to `DDGS(timeout=5).text(...)`
  was attempted directly in this environment; it returned `[]` (an empty
  list, no exception) rather than populated results — most likely because
  this sandboxed environment has no outbound network access. This means
  end-to-end *live* network-failure behavior could not be directly
  observed here; the exception types and timeout mechanism used in this
  plan are taken from the installed package's own documented signature
  and docstring, which is direct evidence, even though a live failure
  path could not be exercised in this environment.

## 5. Provider Boundary Decision

**Smallest appropriate boundary, modeled on `ai/providers/` but
deliberately not copying its subpackage shape** (§3): two new, flat
modules directly under `tools/` (not `tools/builtin/`, since a provider
is not a `BaseTool`; not `ai/`, since this is not an AI provider):

- **`tools/web_search_provider.py`** — `SearchResult` (frozen dataclass:
  `title: str`, `url: str`, `snippet: str` — see §6), `WebSearchProvider`
  (`ABC`, one abstract method: `search(query: str, *, max_results: int)
  -> list[SearchResult]`), and `WebSearchProviderError` (one exception
  type, raised for any provider-level failure — network, timeout, rate
  limit, or unexpected error — so `WebSearchTool` only ever needs to
  catch one exception type, never a provider-specific one).
- **`tools/duckduckgo_search_provider.py`** — `DuckDuckGoSearchProvider(WebSearchProvider)`,
  wrapping `DDGS(timeout=...).text(...)`, translating the raw
  `list[dict[str, str]]` into `list[SearchResult]`, and translating every
  `duckduckgo_search.exceptions.*` exception (plus any other unexpected
  exception) into `WebSearchProviderError`.

`WebSearchTool` (§ Batch 2) depends **only** on the `WebSearchProvider`
abstraction, injected via its constructor — structurally identical to how
`MemoryTool` depends only on `MemoryManager` and `AIRouter` depends only
on `AIProvider`. This is explicitly **not** a plugin system: there is no
registry, no manifest, no dynamic provider selection, and no
configuration-driven provider switching. Exactly one concrete provider is
constructed, once, in `main.py`.

## 6. Search Result Model

```python
@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
```

Mapped directly from the verified DuckDuckGo dict shape (§4):
`"title"` → `title`, `"href"` → `url`, `"body"` → `snippet`. No raw
provider dict or object ever crosses the `WebSearchProvider` boundary —
`DuckDuckGoSearchProvider.search()` is the only place a raw dict is ever
touched. This is the minimum field set that is both (a) genuinely
returned by the provider and (b) sufficient to render a useful,
non-misleading result to Nathan (§11) — no additional speculative fields
(e.g. a full-page-content field) are added, since the provider does not
supply one.

## 7. Command Grammar and Security Classification

**Command:** `search the web for <query>` — one exact, mandatory prefix,
matched case-insensitively via the existing `_file_prefix()` helper
(trivially "longest-prefix-first" with a single candidate). Mirrors the
project's established preference for one exact, unambiguous phrasing per
capability (e.g. Phase 15's two workflow commands) over multiple loose
synonyms.

**Collision check performed directly against the current `_RULES`,
`_MEMORY_KEYWORDS`, `_WORKFLOW_ALIASES`, `_APPROVAL_HISTORY_EXACT`, and
`_WORKFLOW_HISTORY_EXACT` tables**: no overlap in either direction. The
phrase contains neither `"memory"`/`"memories"`/`"remember"`/`"recall"`
nor any existing exact/prefix phrase from any other command table.

**Security classification**: `WebSearchTool.action_for()` returns a
**fixed, query-independent string**, `"search the web"`, regardless of
the user's actual query content. This is a deliberate security decision,
not an oversight: it guarantees a user's (or, hypothetically, a future
AI's, though none exists in this phase) search query text can **never**
influence this tool's own security tier, no matter what words it
contains — mirroring exactly how `MemoryTool`'s search operations and
`ApprovalHistoryTool`/`WorkflowHistoryTool`'s operations already classify
via a fixed action string, never the raw request text. Confirmed against
the full `_RULES` table (§3): `"search the web"` matches only the
existing generic `"search"` → GREEN rule (and would still resolve GREEN
even without it, since no RED/YELLOW keyword is a substring).

**Why GREEN/read-only is appropriate** (see also §12): the action is
fixed and content-independent; the tool creates, modifies, deletes,
installs, approves, and executes nothing; its only effect is a network
read and a formatted text return. This is the identical safety shape
`FileReadTool` already has for local file reads.

## 8. Input Boundaries — Explicit Decisions

Every externally reachable boundary decided explicitly, per the
authorizing instructions (no boundary left implicit):

- **Empty/whitespace-only query**: the router still matches on the fixed
  prefix (mirroring `_extract_path`'s existing behavior of returning `""`
  and letting the tool itself reject it); `WebSearchTool.run()` rejects
  it with `fail("A web search requires a non-empty query.")` before any
  provider call is made.
- **Whitespace normalization**: the query is `.strip()`ped only; no
  internal whitespace collapsing, matching how no other tool in this
  repository rewrites user-supplied text beyond stripping.
- **Maximum query length**: **explicitly decided not to enforce one**.
  No evidence (from the installed package, its docs, or this
  repository's own conventions) justifies a specific number; an
  unusually long query is treated exactly like any other query that
  happens to return zero results or a provider error — no special case.
  This is a stated decision, not an omission.
- **Result limit**: fixed at a small constant, `_DEFAULT_MAX_RESULTS = 5`,
  passed directly as `DDGS.text(..., max_results=5)`. Not
  user-configurable in Phase 16 (explicit non-goal — keeps the grammar
  and scope minimal, mirrors `ApprovalHistoryTool`/`WorkflowHistoryTool`'s
  own fixed, non-configurable limits).
- **Malformed individual result**: if a returned dict is missing an
  expected key, that single result is skipped; the remaining valid
  results are still returned — mirroring the established Phase 10–14
  precedent that one bad record never discards the rest.
- **Duplicate results**: **explicitly not deduplicated** in Phase 16 —
  the provider's own result ordering and content are passed through
  as-is; deduplication logic is unjustified complexity without evidence
  of it being a real, observed problem.
- **Provider/network failure, rate limit, timeout**: every
  `duckduckgo_search.exceptions.*` type, plus any other unexpected
  exception raised inside `DuckDuckGoSearchProvider.search()`, is caught
  at the provider boundary and re-raised as one `WebSearchProviderError`;
  `WebSearchTool.run()` catches exactly that one type and returns
  `fail(...)` with an honest, non-technical message — never an uncaught
  exception, never a partial crash of the CLI.
- **Timeout value**: fixed and explicit — `DDGS(timeout=10)`, the
  library's own documented default, made explicit in code rather than
  left implicit. The synchronous CLI blocks for up to this long; this is
  disclosed as a known, accepted limitation (§13), consistent with every
  other Jarvis action already being synchronous and blocking.
- **Zero results**: **not a failure** —
  `ok("No web results were found for '<query>'.")`, mirroring the
  established honest "no records found" precedent from the memory
  retrieval family (Phase 9–14), never a `fail()`.

## 9. Observability Isolation

**Finding: no new isolation code is required.** `ToolExecutor._emit_audit_event()`
(Phase 15 Batch 4A) already wraps every tool's audit emission in the
established narrow `try/except Exception: pass` pattern, regardless of
which tool ran. `WebSearchTool` emits no audit events of its own — it
only returns a `ToolResult`, exactly like every other built-in tool. This
means a failing audit logger already cannot turn a successful web search
into a failed authoritative result, for free, with zero new code.

## 10. Result Rendering

`WebSearchTool.run()` formats output as a numbered list, each entry
showing title, URL, and snippet, clearly separated from any Jarvis-authored
text — mirroring `ApprovalHistoryTool`/`WorkflowHistoryTool`'s existing
"labelled field" rendering convention rather than blending external text
into narrative prose. The rendering must never claim Jarvis has "read"
or "visited" a page — only that a search was performed and these
title/URL/snippet results were returned. A fixed, one-line disclaimer
noting these are search-result snippets, not full page contents, is
included in the tool's own description (surfaced wherever tool
descriptions are shown) and in the output header, so the distinction is
visible to Nathan at the point of use, not only in documentation.

## 11. Security Review

- **Prompt injection content inside titles/snippets**: not applicable in
  this phase's own scope — there is no AI-facing path at all, so
  `PromptBuilder.scan_for_injection()` is never invoked on this content.
  The risk model differs fundamentally from an AI-facing path: the
  content is displayed to Nathan, a human, who is not susceptible to
  prompt injection in the way an LLM context window is.
- **Malicious URLs**: displayed as inert text only. `WebSearchTool` never
  fetches, follows, opens, or renders a URL as a clickable/executable
  link — it only prints the string returned by the provider. Nathan would
  have to manually copy and open a URL in his own browser; nothing in
  this phase automates that step.
- **Result text containing command-like instructions** (e.g. a snippet
  reading "delete file X"): inert. Confirmed structurally (§3): no code
  path anywhere in `ui/cli.py` or `core/orchestrator.py` re-parses a
  `ToolResult.output` string as a new command, plan, or instruction.
  `SecurityManager.classify_action()` is called exactly once, before the
  search runs, against the fixed action string — never again, and never
  against result content.
- **Search-result poisoning** (a malicious page ranking highly and
  embedding fake instructions): mitigated by the same reasoning — Jarvis's
  own execution authority is never delegated to, or derived from, result
  content. A poisoned result can mislead a human reader exactly as it
  could in any web browser; it cannot cause Jarvis to take any action, by
  construction.
- **External content trust classification**: even though this phase has
  no AI-facing path, every search result is treated, by architecture and
  by documentation, as untrusted external content — the same
  classification Phase 7/8 already established for file and memory
  content presented to AI. This is a forward-compatible naming/documentation
  discipline, not a functional requirement in Phase 16 (there is nothing
  to "untrust" yet, since nothing is trusted by default here).
- **Why GREEN/read-only classification is appropriate**: see §7 — fixed,
  content-independent action string; zero state mutation; zero execution
  authority granted to result content.
- **Why direct display does not grant execution authority**: `ToolResult.output`
  is terminal — it is displayed and nothing else, confirmed structurally,
  not merely assumed.
- **What boundary would be required before search results may reach AI
  reasoning**: exactly the boundary Phase 8 already built and this phase
  does not need — each result (or the combined result set) would need to
  be wrapped as one or more `AIContextBlock.untrusted(...)` instances and
  pass through `PromptBuilder.scan_for_injection()` before ever reaching
  an `AIReasoningRequest`, with its own dedicated review of that specific
  data flow at that time. **Not built in Phase 16.**

## 12. Dependency and Failure Review

- **Network unavailable**: caught as a provider-level exception (or, per
  this environment's own observed behavior — an empty list with no
  exception, §4), both handled: an exception becomes a `fail()`; an empty
  list becomes the honest "no results found" `ok()` message (§8) — Jarvis
  cannot always distinguish "no results" from "no network" given the
  library's own documented behavior, and this plan does not invent a way
  to do so without evidence.
- **Provider/package exception**: every `duckduckgo_search.exceptions.*`
  type plus any unexpected exception → `WebSearchProviderError` → `fail()`.
- **Timeout**: `TimeoutException` is one of the caught exception types;
  the fixed 10-second constructor timeout bounds the blocking call.
- **Malformed individual result / partial result sets**: handled per §8
  — skip the bad entry, keep the good ones.
- **Provider API drift**: the disclosed `duckduckgo_search` → `ddgs`
  rename (§4) is the concrete instance of this risk; the provider
  boundary (§5) is what would let a future migration happen without
  touching `WebSearchTool` or anything above it. Not fixed in Phase 16 —
  disclosed as carried-forward debt (§17).
- **Synchronous CLI blocking**: accepted and disclosed, consistent with
  every existing Jarvis action; no async, no cancellation, no background
  execution (explicitly out of scope per the authorizing instructions).

## 13. Batch Plan

### Batch 1 — Search Provider Boundary

- **Purpose**: establish the stable Jarvis-owned result model and
  provider abstraction, plus the concrete DuckDuckGo adapter, entirely
  independent of the tool/command layer.
- **Production files**: `tools/web_search_provider.py` (new),
  `tools/duckduckgo_search_provider.py` (new).
- **Test files**: `tests/unit/test_web_search_provider.py` (new — the
  ABC's contract and `SearchResult`'s shape),
  `tests/unit/test_duckduckgo_search_provider.py` (new — using a fake,
  injected `DDGS`-shaped stub; **no real network call in any test**,
  covering: successful mapping of the three verified dict keys,
  malformed-result skipping, each exception type's translation to
  `WebSearchProviderError`, and the fixed timeout being passed through).
- **Invariants protected**: no raw provider dict crosses the boundary;
  every provider exception becomes exactly one Jarvis-owned exception
  type.
- **Non-goals**: no tool, no command routing, no `main.py` wiring yet.
- **Verification commands**: `poetry run pytest tests/unit/test_web_search_provider.py tests/unit/test_duckduckgo_search_provider.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, e.g. "Add web search provider boundary and DuckDuckGo adapter (Phase 16 Batch 1)".

### Batch 2 — Read-Only Tool, Command Routing, Composition Wiring

- **Purpose**: make the capability reachable end-to-end through the
  ordinary, unmodified command/execution path.
- **Production files**: `tools/builtin/web_search_tool.py` (new),
  `tools/builtin/__init__.py` (export), `core/command_router.py`
  (`_WEB_SEARCH_PREFIXES`, `match()`/`build_input()` wiring), `main.py`
  (construct `DuckDuckGoSearchProvider()` once, register
  `WebSearchTool(provider)`).
- **Test files**: `tests/unit/test_web_search_tool.py` (new — action
  string fixed regardless of query content, empty-query rejection,
  zero-results honest message, malformed-result skipping surfaced through
  the tool, using a fake `WebSearchProvider`), `tests/unit/test_command_router.py`
  (extended — exact-prefix match, no collision with existing tables,
  query extraction), `tests/unit/test_main_ai_wiring.py`-style smoke
  check or a new small wiring test confirming `main.py` constructs
  exactly one provider instance.
- **Invariants protected**: `SecurityManager.classify_action()` remains
  the sole authority (no bypass); the fixed action string is unaffected
  by query content (a dedicated test asserts this with several
  adversarial query strings containing RED/YELLOW keywords, e.g. a query
  literally containing the word "delete" or "execute").
- **Non-goals**: no AI-facing path, no result-count configuration, no
  second command phrasing.
- **Verification commands**: `poetry run pytest tests/unit/test_web_search_tool.py tests/unit/test_command_router.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, e.g. "Add WebSearchTool and wire deterministic web-search command (Phase 16 Batch 2)".

### Batch 3 — End-to-End Verification, Adversarial Security Tests, Documentation, Closure

- **Purpose**: prove the full real stack (real `SecurityManager`, real
  `ToolExecutor`, real `CommandRouter`, a fake injected search provider —
  never a real network call) end to end; adversarially test the security
  properties claimed in §11; document and close.
- **Production files**: none expected (documentation only); any
  narrowly-justified correction found during this batch's own review
  will be disclosed here, not silently applied.
- **Test files**: `tests/integration/test_web_search_end_to_end.py` (new
  — real CLI session via `ui.cli.JarvisCLI`, real orchestrator wiring,
  fake provider; proves: the command is classified GREEN and runs
  without approval; a query containing RED/YELLOW-style keywords does
  not elevate the tier; a snippet containing command-like text is
  displayed verbatim and triggers no action; a provider exception
  produces a clean `fail()` message, never a crash; zero results produce
  the honest empty message).
- **Documentation**: `README.md` (new Phase 16 section, following the
  established per-phase style), `docs/phase_16_implementation_plan.md`
  (this document — tracked at this point, per the established
  Phase 15/foundation-turn convention of staying untracked through
  planning and being added to git only at closure), `docs/phase_16_completion_report.md`
  (new, at closure).
- **Invariants protected**: full-stack proof that no result content can
  ever become execution authority (§11), and that the fixed
  classification holds under real `SecurityManager.classify_action()`,
  not just a unit-level assumption.
- **Non-goals**: no scope beyond verification, adversarial testing, and
  documentation.
- **Verification commands**: `poetry run pytest tests/integration/test_web_search_end_to_end.py -v`, then full `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one commit for the closure documentation and any
  narrowly-justified correction, following the same staging discipline
  used at every prior phase's closure (only the files this batch actually
  touches).

## 14. Plan-vs-Master-Spec Reconciliation

| Item | Classification | Reasoning |
|---|---|---|
| A web-search tool exists at all | **A — direct match** | Fulfills Ch26's explicit "Web search... tools" Phase-1 bullet, arriving at this repo's own Phase 16 — a timing divergence already established by every prior phase, not a new one. |
| Provider/adapter boundary (ABC + one concrete adapter) | **B — narrow, repository-grounded refinement** | Not spec-mandated; modeled directly on the already-existing `AIProvider`/`ClaudeProvider` precedent, deliberately scaled down (no subpackage, no multi-provider registry) per explicit instruction. |
| Fixed, query-independent action string for classification | **B — narrow refinement** | Not spec-mandated; mirrors the existing `MemoryTool`/`ApprovalHistoryTool`/`WorkflowHistoryTool` precedent for keeping user content out of the classification decision. |
| Plugin/manifest architecture (Ch17) | **Deliberately deferred, not attempted** | Explicitly out of scope per instruction; no partial realization exists — no manifest, no permission declaration, no sandboxing. |
| Research Agent (Ch20) | **Deliberately deferred, not attempted** | No autonomous behavior, no agent lifecycle, no multi-step research workflow. |
| AI-facing summarization / ingestion (Ch8-style pattern) | **Deliberately deferred, not attempted, but boundary pre-identified** | The exact reusable mechanism (`AIContextBlock.untrusted`) is named in §11 for a *future* phase; nothing is built now. |

**No unresolved D (undisclosed deviation) or E (scope creep) exists in
this plan.**

## 15. Adversarial Planning Review

- **Are we accidentally building a browser instead of search?** No — no
  URL fetching, no HTML rendering, no page-content retrieval of any kind;
  only the provider's own title/url/snippet metadata is ever touched.
- **Are raw web results leaking into an AI trusted-context path?** No —
  zero AI-facing code path exists anywhere in this plan; the only
  consumer of `SearchResult` is `WebSearchTool`, whose only output is
  `ToolResult.output`, displayed by the CLI.
- **Is the concrete provider coupled too deeply into Jarvis?** No —
  `WebSearchTool` depends only on the `WebSearchProvider` abstraction;
  `DuckDuckGoSearchProvider` is constructed exactly once, in `main.py`,
  and nothing above the provider boundary references
  `duckduckgo_search`-specific types.
- **Are we classifying a network tool GREEN too casually?** No — the
  classification is fixed, content-independent, mutation-free, and
  confirmed directly against every existing `_RULES` entry (§3, §7); the
  same reasoning already applied to `FileReadTool`.
- **Can malicious result text cause any action?** No — confirmed
  structurally, not assumed: no code path re-parses `ToolResult.output`
  as a command anywhere in this repository.
- **Are we claiming more information than the provider actually
  returned?** No — the result model (§6) and rendering rule (§10) are
  both scoped to exactly the three fields the provider returns; the
  output explicitly avoids implying a page was read.
- **Are timeout/reliability semantics honest for a synchronous CLI?**
  Yes — a fixed, explicit timeout is disclosed, blocking behavior is
  disclosed, and no false reliability guarantee (retries, async,
  cancellation) is claimed.
- **Are we building unnecessary plugin/provider-routing infrastructure?**
  No — exactly one ABC, one concrete adapter, no registry, no dynamic
  selection, no configuration-driven switching.
- **Does the phase remain genuinely useful without AI summarization?**
  Yes — Nathan receives real, live, current information Jarvis has never
  been able to provide under any prior phase; this is standalone value,
  not merely a stepping stone to a future AI-facing feature.

## 16. Final Recommended Architecture

`WebSearchTool(BaseTool)` (GREEN) → depends on `WebSearchProvider` (ABC)
→ implemented by `DuckDuckGoSearchProvider`, wrapping the installed
`duckduckgo_search==8.1.1` package's `DDGS.text()`. Routed via one new
`CommandRouter` exact-prefix entry into the ordinary, unmodified
`ToolExecutor.execute()` path. No new observability code needed
(`ToolExecutor`'s existing isolation already covers it). No AI-facing
path exists anywhere in this architecture.

## 17. Final Command Grammar

`search the web for <query>` — one exact, mandatory prefix, matched
case-insensitively, extracted via the existing `_file_prefix()` helper.

## 18. Final Search-Result Model

`SearchResult(title: str, url: str, snippet: str)` — a frozen,
Jarvis-owned dataclass; never a raw provider dict.

## 19. Final Provider-Boundary Decision

Two new flat modules under `tools/` (`tools/web_search_provider.py`,
`tools/duckduckgo_search_provider.py`) — one ABC, one concrete adapter,
no subpackage, no registry, no multi-provider routing.

## 20. Final Security Classification Rationale

Fixed, query-independent action string (`"search the web"`); zero state
mutation; zero execution-authority path from result content back into
the system; classification happens exactly once, before the search runs,
never against result content.

## 21. Final Batch Sequence

Batch 1 (provider boundary) → Batch 2 (tool, routing, wiring) → Batch 3
(end-to-end verification, adversarial security tests, documentation,
closure) — as detailed in §13.

## 22. Explicit Phase 16 Non-Goals

Repeated here for closure-time reference: autonomous browsing; arbitrary
URL fetching; webpage summarization; AI summarization of search results;
AI-authored queries; AI-selected tool execution; a Research Agent;
scheduling/background execution; notifications; workflow-resumption
changes; a plugin architecture; multi-provider routing;
user-configurable result counts; deduplication logic; a maximum
query-length limit; migrating off the deprecated `duckduckgo_search`
package to `ddgs`.

## 23. Likely Phase 17 Follow-On Boundary

Two independent, legitimate directions, neither authorized by this plan:
(a) AI-facing summarization of search results, reusing Phase 8's
untrusted-content-ingestion pattern exactly (§11's named boundary); or
(b) continuing the durable-workflow-lifecycle branch (resumable
checkpoints) evaluated in the prior architectural review. Which of these
(or another candidate) becomes Phase 17 remains an open,
separately-scoped decision, consistent with this repository's established
practice of not pre-announcing the next phase during the current one's
own planning.
