# Jarvis — Phase 32 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 32 — Webpage Fetch/Read Safety Foundation (very risky: planning + 3 batches, complete)
**Date:** 2026-07-12

---

## Executive Summary

Phase 32 builds a narrow, deterministic, internal-only safety foundation for fetching and reading a single webpage: URL/target validation (`WebFetchPolicy`), a safe network fetcher (`SafeWebFetcher`), and a deterministic HTML-to-text extractor (`html_text_extractor.py`). It closes a genuine, long-disclosed structural gap — Jarvis's web search has only ever returned titles/snippets, never full page content — without making webpage fetching user-facing in any way. Nothing in the running system calls this foundation yet: no command, no tool, no `SecurityManager` rule, and no AI/workflow/scheduler/dashboard/Inbox integration. It is a safety layer sitting unused, proven correct and adversarially hardened in isolation, ready for a separately-scoped future phase to build one narrow, user-visible capability on top of it.

## Baseline

```
Branch:                    phase-4-ai-reasoning-and-write-actions
Phase 31 final commit:     afa7871
Full suite before Phase 32: 2848 passed, 0 failed
```

## Batch Sequence and Results

| Batch | Delivered | Commit | Full suite after |
|---|---|---|---|
| Planning | `docs/phase_32_implementation_plan.md` — no code | (uncommitted until Batch 1) | 2848 (unchanged) |
| 1 | `web/fetch_policy.py`, `WebFetchPolicy` | `93aa3dc` | 2905 |
| 2 | `web/safe_web_fetcher.py`, `SafeWebFetcher`, httpx promoted to direct dependency | `ef0d826` | 2955 |
| 3 | `web/html_text_extractor.py`, end-to-end pipeline tests, documentation closure | (this report) | 3003 |

## Files Changed (cumulative across all three batches)

- `web/__init__.py` (new) — package docstring.
- `web/fetch_policy.py` (new, Batch 1; extended Batch 2) — `WebFetchPolicy`, `ValidatedTarget`, `RejectedTarget`, `FetchRejectionReason`, `RedirectPolicy`, `TimeoutPolicy`, `SizeLimitPolicy`, and the public `blocked_ip_reason()`/`parse_ip_literal()` helpers (renamed from module-private in Batch 2 so `SafeWebFetcher` could reuse the exact same IP-blocking predicate for DNS-resolved addresses).
- `web/safe_web_fetcher.py` (new, Batch 2) — `SafeWebFetcher`, `FetchedPage`, `WebFetchSuccess`, `WebFetchFailure`, `WebFetchFailureReason`.
- `web/html_text_extractor.py` (new, Batch 3) — `extract_text_from_page()`, `extract_text_from_fetched_page()`, `extract_html_text()`, `extract_plain_text()`, `ExtractedText`, `TextExtractionSuccess`, `TextExtractionFailure`, `TextExtractionFailureReason`.
- `pyproject.toml` / `poetry.lock` (Batch 2) — `httpx` promoted from a transitive to an explicit direct dependency; confirmed to add zero new packages (`poetry lock` changed only the lock file's content-hash).
- `tests/unit/test_web_fetch_policy.py` (57 tests, Batch 1).
- `tests/unit/test_safe_web_fetcher.py` (50 tests, Batch 2).
- `tests/unit/test_html_text_extractor.py` (new, 30 tests, Batch 3).
- `tests/integration/test_phase32_pipeline_end_to_end.py` (new, 18 tests, Batch 3).
- `docs/phase_32_implementation_plan.md` (planning), `docs/phase_32_completion_report.md` (this report).
- `README.md` — new `web/` directory-tree entry and `## Phase 32` section.
- `docs/user_guide.md` — §11 ("What Jarvis Cannot Do Yet") and §13 ("Future Capabilities Not Yet Implemented") updated to honestly reflect that the safety foundation now exists internally while remaining entirely non-user-facing.

## Batch 1 Recap — `WebFetchPolicy`

Pure, deterministic, zero-I/O URL validation. Allow-lists `http`/`https` only; rejects malformed URLs, missing scheme/hostname, embedded credentials, localhost names, and IP literals in private/loopback/link-local/multicast/reserved/metadata ranges (IPv4 and IPv6) via the standard library's own `ipaddress` predicates, never hand-rolled CIDR math. Declares (but does not enforce) `RedirectPolicy`/`TimeoutPolicy`/`SizeLimitPolicy` value objects for the batches that follow. Full detail in `docs/phase_32_implementation_plan.md` and the Batch 1 commit (`93aa3dc`).

## Batch 2 Recap — `SafeWebFetcher`

The one module permitted to import `httpx`. Re-validates every target with `WebFetchPolicy` before any network access, resolves the hostname, validates every resolved IP address with the same blocking predicate Batch 1 already proved correct for literals (failing closed if *any* resolved address is unsafe, not just the first), then **pins** the actual TCP/TLS connection to the validated IP while preserving the original hostname for the `Host` header and TLS SNI (via httpx/httpcore's `sni_hostname` extension) — closing the DNS-rebinding race rather than merely documenting it as a residual risk. GET-only; automatic redirect-following disabled in favour of manual, re-validated, capped hops; streaming size-limit enforcement; content-type allow-list checked before any body byte is read; every failure mode (policy rejection, DNS failure, blocked resolved IP, timeout, connection error, oversized response, wrong/missing content-type, too many redirects, rejected redirect target, HTTP error status, and a last-resort `UNEXPECTED_ERROR` safety net) returned as data, never a raised exception. Full detail in the Batch 2 commit (`ef0d826`).

## Batch 3 — Text Extraction, Pipeline Verification, and Closure

### Text extraction behavior

`web/html_text_extractor.py` provides:
- `extract_html_text(html_source: str) -> ExtractedText` — parses via the standard library's `html.parser.HTMLParser` only (no new dependency, no rendering, no JavaScript execution, no subresource fetching). Content of `<script>`, `<style>`, `<noscript>`, and `<template>` is discarded entirely, via a single shared skip-depth counter that can only ever widen (never prematurely narrow) the skipped region — so an unclosed skip-tag in malformed HTML fails safe by excluding *more* text, never by leaking script/style content. HTML comments are ignored; entities are decoded via `HTMLParser`'s own `convert_charrefs=True`. Whitespace is collapsed to single spaces, with one deliberate exception discovered during testing: a fixed set of block-level tags (`p`, `div`, `li`, headings, etc.) insert a single word-boundary space at their start/end, so two adjacent block elements with no whitespace between them in the source (e.g. `<p>Hello</p><p>World</p>`, common in minified HTML) do not collapse into one glued word.
- `extract_plain_text(text_source: str) -> ExtractedText` — `text/plain` content is passed through with only line-ending normalisation and outer trimming; its whitespace is *not* collapsed, since for plain text, whitespace is part of the content itself, not markup noise. This is the "clearly tested decision" between the two content categories.
- `extract_text_from_page(content_type, body, *, charset=None) -> TextExtractionResult` — dispatches on content-type, decodes bytes using the declared charset with a UTF-8/`errors="replace"` fallback (mirroring `FileReadTool`'s own convention), and returns `TextExtractionSuccess`/`TextExtractionFailure` (`UNSUPPORTED_CONTENT_TYPE`, `INVALID_INPUT`) — never raises.
- `extract_text_from_fetched_page(page: FetchedPage) -> TextExtractionResult` — convenience wrapper accepting a `SafeWebFetcher`-produced page directly.
- Output is hard-capped at 200,000 characters, with `ExtractedText.truncated` honestly reporting whether the cap was hit — never a silent partial fill.

A real correctness bug was found and fixed during this batch: the first implementation collapsed all whitespace with no boundary awareness, so `<p>Hello</p><p>World</p>` (no whitespace between the tags in the source) extracted as `"HelloWorld"` — a genuinely wrong result, not merely a test-authoring assumption. Fixed by adding a small, fixed set of block-boundary tags that insert a single space at their start/end before the final whitespace-collapse pass.

### End-to-end safety verification

`tests/integration/test_phase32_pipeline_end_to_end.py` chains `WebFetchPolicy` → `SafeWebFetcher` → `html_text_extractor` exactly as a future integration would, entirely within the test module (no new production "pipeline" function was added — chaining is the caller's responsibility, matching the "smallest foundation" scope). Covers: valid HTML/plain-text pages fetched and extracted; disallowed content-type and oversized responses failing before extraction is ever reached; an unsafe original URL never triggering a fetch; an unsafe redirect target never reaching extraction; a redirect chain within the hop limit succeeding end-to-end; a redirect chain over the limit failing safely; network and DNS errors failing safely; and malformed HTML from a genuinely successful fetch still producing a safe `TextExtractionSuccess`. Structural tests additionally prove, by direct AST/source inspection, that none of the three `web/` modules import `ai`, `workflow`, `scheduler`, `dashboard`/`ui`, `tools`, `core`, `security`, `approval`, or `storage`, and that no file outside `web/` (across `tools/`, `core/`, `ai/`, `workflow/`, `ui/`, `approval/`, `storage/`, and `main.py`) imports `web/` back — confirming the foundation remains completely one-directional and unwired.

### Documentation/closure updates

- `README.md`: added a `web/` line to the repository directory tree, and a new `## Phase 32 — Webpage Fetch/Read Safety Foundation (complete)` section summarising all three batches and their explicit non-goals.
- `docs/user_guide.md` §11 ("What Jarvis Cannot Do Yet"): the existing "no full webpage fetching" bullet updated to disclose that an internal, unintegrated safety foundation now exists, while remaining honest that nothing user-facing has changed.
- `docs/user_guide.md` §13 ("Future Capabilities Not Yet Implemented"): the existing forward-looking bullet updated from "not yet built" to "the foundation itself is complete; everything built on top of it remains a distinct future decision" — naming a user-facing command, AI summarization, a Research Agent, and routing through `AIContextBlock.from_untrusted()`/`PromptBuilder`'s injection scan as the specific, separately-reviewable next steps.
- No other documentation was touched; the Master Specification was not updated (no repository evidence required it).

## Tests Added (Batch 3)

- `tests/unit/test_html_text_extractor.py` — 30 tests: `text/plain` pass-through (including line-ending normalisation), simple and XHTML extraction, malformed/severely broken markup never raising, the unclosed-`<script>`-swallows-the-rest behaviour, script/style/noscript/template removal, nested-skip-tag handling, comment ignoring, named/numeric entity decoding, whitespace collapsing, the output character cap (with and without truncation), empty/whitespace-only content, non-bytes/non-string invalid input, unsupported content-type rejection, charset fallback and honouring, the `FetchedPage` convenience wrapper, and two structural proofs (no forbidden imports, no `open()` call).
- `tests/integration/test_phase32_pipeline_end_to_end.py` — 18 tests, detailed above.

## Final Verification

```
Focused (all four Phase 32 test files together): 155 passed
poetry run pytest -q:                            3003 passed, 0 failed (run twice, stable; +48 since Batch 2's 2955)
poetry run ruff check web tests/unit/test_web_fetch_policy.py
    tests/unit/test_safe_web_fetcher.py tests/unit/test_html_text_extractor.py
    tests/integration/test_phase32_pipeline_end_to_end.py:   All checks passed!
Full-repo ruff:                                  689 pre-existing errors, confirmed byte-for-byte
    unchanged from the prior commit via `git stash` comparison - nothing new introduced;
    no ruff-cleanup work performed, per explicit instruction.
git diff --check:                                clean
```

## Non-Goals Confirmed (all three batches, restated exhaustively)

No CLI command; no registered `ToolRegistry` entry; no `CommandRouter` grammar; no `SecurityManager` rule (nothing is classified, since nothing is callable); no AI integration of any kind — no `AIContextBlock` is constructed anywhere in `web/`, and no fetched or extracted content has been shown to an AI; no webpage summarization; no Research Agent or autonomous browsing; no workflow, scheduler, dashboard, or Inbox integration; no automated save-to-file; no Core service; no file delete; no voice, phone, goals, projects, or tasks. Confirmed by direct, repeated structural (AST-based) test across all three modules and, separately, by scanning every other production directory (`tools/`, `core/`, `ai/`, `workflow/`, `ui/`, `approval/`, `storage/`, and `main.py`) to confirm none of them import `web/` back.

## Remaining Limitations / Disclosed, Not Fixed

- **DNS-rebinding defence is per-call, not global.** `SafeWebFetcher` resolves, validates, and pins the connection target fresh on every `fetch()` call (and on every redirect hop within that call) — this closes the resolve-then-connect race *within* a single fetch, but says nothing about OS-level DNS caching or connection reuse *across* separate `SafeWebFetcher` calls. This is the correct granularity for a "fetch this one URL" service and was a deliberate, disclosed design boundary from Batch 2, not an oversight.
- **The single-total-timeout is an approximation.** `SafeWebFetcher` applies `policy.timeout_policy.total_seconds` uniformly to httpx's connect/read/write/pool phases (each phase gets that budget independently), rather than enforcing one true wall-clock cap across the whole request. A stricter combined deadline would need an additional watchdog mechanism; this was judged unnecessary complexity for a foundation nothing calls yet, and is easy to add later if a real need appears.
- **Text extraction discards layout structure entirely.** By design, `html_text_extractor.py` is a text extractor, not a layout-preserving renderer — no paragraph/heading/list structure survives extraction beyond the single word-boundary space at block-tag edges. This is namely a stated non-goal, not a gap.
- **Future work, not yet built, each a distinct decision:** a user-facing command/tool to trigger a fetch; `ai/webpage_ingestion.py` (would mirror `ai/web_search_ingestion.py` exactly — one fetch, wrap extracted text in `AIContextBlock.from_untrusted(text, source=f"webpage:{url!r}")`, rely on `PromptBuilder`'s already-existing automatic injection scan, no new scanning code needed); any webpage summarization or Research Agent behavior; any scheduled/dashboard/workflow integration.

---

## Status Statement

**Phase 32 complete for its defined scope: a proven, adversarially-tested, internal-only webpage fetch/read safety foundation — URL validation, safe network fetching with genuine connect-time DNS-rebinding protection, and deterministic text extraction — sitting unused behind no command, no tool, and no AI/workflow/scheduler/dashboard integration of any kind.** Delivered across a planning pass and three batches exactly as classified ("very risky: planning + 3 batches"), with one real bug found and fixed in each of Batches 2 and 3 before closure, and zero scope creep beyond the explicitly approved boundaries at every step.
