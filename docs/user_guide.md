# Jarvis Operating Guide

A practical, task-oriented reference for actually running and using Jarvis. Unlike `README.md` (which is a phase-by-phase build log), this document is organized around *what you want to do* right now — kept current as a living document, updated in place whenever a phase changes user-facing behavior, rather than describing one fixed point in the project's history.

Everything described here is verified directly against the current codebase whenever this guide is updated — nothing here is aspirational or planned. If something you observe running Jarvis doesn't match this guide, the codebase is the source of truth; check the highest-numbered `docs/phase_NN_completion_report.md` for the most recently closed phase.

---

## 1. What Jarvis Can Do Right Now

Jarvis is a personal, local, single-user AI assistant with three cooperating processes and a durable SQLite database. Today it can:

- Remember and recall notes (memory), with optional AI-generated summaries of them.
- Read, list, search (by name or content), create, append to, copy, and move/rename files on your machine.
- Search the web (snippets/metadata only) and optionally get an AI summary of the results.
- Run a small number of daily, fixed-time scheduled web-search summaries automatically, saved to a durable Inbox.
- Show you, at CLI startup, a short heads-up if new scheduled results have shown up since you last checked.
- Show you all of the above in a read-only dashboard window.

Every action that changes anything (writing a file, saving/changing a memory, creating a schedule) requires your explicit approval before it happens. Nothing Jarvis does is autonomous or irreversible without you saying yes first.

---

## 2. How the Main Pieces Fit Together

Jarvis is **three independent programs sharing one SQLite database file** — there is no server, no network connection between them, and no shared memory. Each is started separately, and none of them require the others to be running.

| Process | Started with | What it does |
|---|---|---|
| **CLI** | `poetry run python main.py` | The interactive assistant — type requests, approve/decline actions, see responses. Only process that can *write*. |
| **Dashboard** | `poetry run python dashboard.py` | A read-only window showing everything durably stored — memories, approvals, workflows, Inbox, schedules. Cannot run commands or change anything. |
| **Scheduler** | `poetry run python scheduler.py` | A background loop that checks once a minute for due scheduled web searches and runs them, saving results to the Inbox. |

They all point at the same database file (`data/jarvis.db` by default, or whatever `DATABASE_PATH` is set to). You can run any subset of them at once, in any order, in separate terminals. There is no Core service, no HTTP server, and no IPC bridge connecting them — confirmed directly in every one of these files' own composition code.

---

## 3. How to Run the CLI

```powershell
poetry install
poetry run python main.py
```

On startup you'll see `Jarvis Online.`, a short usage reminder, and — if any new scheduled Inbox entries exist since you last checked — a one-line notice (see §8). Type a request at the `you>` prompt. Type `exit`, `quit`, or `bye` to leave (case-insensitive).

**Environment variables** (set in a `.env` file in the project root):

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Always required** to start any of the three processes at all — Jarvis refuses to load configuration without it, even if you never enable AI reasoning. A placeholder value works fine if you don't plan to use AI features. | *(none — required)* |
| `AI_REASONING_ENABLED` | Turns on live Claude calls for summaries. | `false` (fully rule-based, no real API calls) |
| `AI_MODEL` | Which Claude model to use. | `claude-sonnet-4-6` |
| `DATABASE_PATH` | Where the SQLite file lives. | `data/jarvis.db` |
| `APPROVAL_TIMEOUT_SECONDS` | How long a YELLOW approval waits before expiring. | `60` |
| `LOG_LEVEL` | Logging verbosity. | `INFO` |

**Console logging:** since Phase 54, Jarvis also prints one structured log line to the console for every action it takes (alongside your typed input and its printed response) — for example `2026-...+00:00 [tool_executor] tool_call -> success tier=green 0ms | tool=echo success=True`. This is controlled by the `LOG_LEVEL` setting above: the default, `INFO`, shows every action, including successful ones; set it to `WARNING` or higher for a quieter console showing only blocked/failed actions. This is independent of the durable audit log, which always records everything regardless of `LOG_LEVEL`.

With `AI_REASONING_ENABLED` unset or `false`, every summary command (file summary, web-search summary, memory summaries, scheduled summaries) will simply report that AI reasoning is unavailable, without ever calling the Claude API — but `ANTHROPIC_API_KEY` must still be set to *something* for Jarvis to start at all (confirmed directly in `config/settings.py`).

---

## 4. How to Run the Dashboard

```powershell
poetry run python dashboard.py
```

Opens a separate window titled **"Jarvis — Dashboard (read-only)"**. It reads the same database the CLI/scheduler use and refreshes automatically every 5 seconds, plus a manual "Refresh now" button. See §9 for what each tab shows. Closing the dashboard window has no effect on the CLI or scheduler.

---

## 5. How to Run the Scheduler

```powershell
poetry run python scheduler.py
```

Runs forever, checking every 60 seconds whether any enabled schedule is due. **The scheduler must actually be running for scheduled summaries to happen** — creating a schedule via the CLI only stores it; nothing runs it unless `scheduler.py` is running somewhere (this terminal, a background window, whatever you prefer). Stopping it (Ctrl+C) simply pauses checking; no schedule is lost, and it picks up exactly where it left off next time it runs.

Like the CLI (§3), this process also prints one structured log line to the console per action (each poll cycle, each schedule claimed and run), controlled by the same `LOG_LEVEL` setting — the default, `INFO`, shows every check and run; `WARNING` or higher shows only problems.

---

## 6. Command Reference (Grouped by Task)

All commands below are typed at the CLI's `you>` prompt. They are matched case-insensitively.

### Basic / info commands (GREEN — safe, no approval)

| Command | What it does |
|---|---|
| `echo <text>`, `repeat <text>`, `say <text>` | Repeats the text back. |
| `system info`, `version`, `about`, `who are you` | Shows basic Jarvis system information. |
| `show config`, `show settings` | Shows current configuration status (AI model, timeouts, database path, etc.). Never shows the API key's value — only whether it's set. |
| `help`, `list commands`, `show commands` | Lists every currently supported command grammar phrase and a short description (Phase 43). Static, hand-maintained text — never AI-generated. |
| `health check`, `show health`, `system health` | Reports basic system health: settings loaded, database path reachable, tool registry populated, console logging configured, Inbox/Schedule/Quarantine stores reachable, and a Security Manager self-classification check (Phase 57). Read-only; never shows the API key's value; never opens a new database connection, constructs a new store, or creates a file or row. |

### Memory commands

| Command | Does | Tier |
|---|---|---|
| `remember this: <text>` | Saves a memory (general category). | GREEN |
| `remember this as <category>: <text>` | Saves a memory under a specific category. | GREEN |
| `show memories` | Lists recent memories. | GREEN |
| `show memories in <category>` | Lists memories in one category. | GREEN |
| `search memories for <query>` | Searches memory content. | GREEN |
| `search memories in <category> for <query>` | Searches within one category. | GREEN |
| `update memory <id>: <new text>` | Replaces a memory's content. | YELLOW |
| `move memory <id> to <category>` | Re-categorizes a memory. | YELLOW |
| `forget memory <id>` | Deletes one memory. | YELLOW |
| `forget all` / `forget all memories` | Deletes **every** memory. | **RED — always blocked, never runs** |

### File commands

| Command | Does | Tier |
|---|---|---|
| `list files`, `list files in <path>`, `show files in <path>`, `list directory`, `list dir` | Lists a directory. | GREEN |
| `read file <path>`, `show file <path>`, `open file <path>`, `cat file <path>` | Shows a file's contents. | GREEN |
| `search files for <pattern>` / `find files named <pattern>` | Finds files whose **name** contains `<pattern>` (case-insensitive), recursively from the project directory. | GREEN |
| `find files containing <text>` / `search files containing <text>` | Finds files whose **content** contains `<text>` (case-insensitive), recursively from the project directory. Shows a short one-line context snippet per match — never the full file. | GREEN |
| `create file <path> with <content>` | Creates a new file. `with <content>` is optional (creates an empty file). | YELLOW |
| `append <content> to file <path>` or `append to file <path> <content>` | Appends text to an existing file. | YELLOW |
| `copy file <source> to <destination>` | Copies an existing file to a new path. | YELLOW |
| `move file <source> to <destination>` / `rename file <source> to <destination>` | Moves or renames an existing file to a new path. | YELLOW |
| `delete file <path>` | Moves an existing file into a Jarvis-managed quarantine folder — **not a permanent delete**. Records the file's original location for future reference. | YELLOW |
| `list quarantine` / `show quarantine` | Lists what's currently inside the quarantine folder — name, size, modified time, and original path when known. | GREEN |
| `restore file <quarantine-file-or-path>` | Moves a quarantined file back to its recorded original location. Only works for files with known original-path metadata. | YELLOW |
| `summarise file <path>` / `summarize file <path>` | Reads a file and produces an AI summary of it (advisory only; requires `AI_REASONING_ENABLED`). | GREEN (reading), summary is advisory |

**File search notes (Phase 24):** always searches from the project directory (there is no "in `<directory>`" clause); results are capped at 50 by default (a message tells you if more may exist); noisy directories are always skipped (`.git`, `__pycache__`, `.pytest_cache`, virtual environments, `node_modules`, build/cache folders); binary and unreadable files are silently skipped rather than causing an error; content search never shows more than a short snippet of the matching line — never a full file's contents. File search cannot move, rename, copy, or delete anything — it is exactly as read-only as `list files`/`read file`.

**File copy notes (Phase 25):** copies exactly one file to one new path — never a directory, never recursive. The source file is never read as text and never modified, moved, renamed, or deleted; it is byte-for-byte unchanged after the copy (verified even for binary files). **The destination must not already exist** — this tool will never overwrite anything, and approving the command does not change that: if the destination exists, the copy is refused regardless of your decision. The destination's parent folder must already exist (this tool does not create folders), matching `create file`'s own behavior exactly.

**File move/rename notes (Phase 26):** `move file` and `rename file` are two names for the exact same command — a destination in the same folder is effectively a rename, a destination in a different folder is a move, and both go through the same tool. Moves/renames exactly one file — never a directory, never recursive. **The destination must not already exist**, and approving the command does not change that — the refusal is absolute, exactly like `copy file`. The destination's parent folder must already exist (this tool does not create folders). Unlike copy, **the original path stops existing** after a successful move — that is the whole point of "move," and it is exactly why this command requires approval before it happens.

**File delete notes (Phase 35; metadata added Phase 37):** `delete file <path>` does not permanently destroy anything — it moves the file into `.jarvis_trash/`, a hidden, Jarvis-managed quarantine folder created automatically the first time it's needed, right in the same location you're running Jarvis from. The file still exists afterward; it's just no longer at its original path. Each quarantined file gets a unique name (so quarantining two different files that happen to share a name never causes one to overwrite the other), and a file already inside `.jarvis_trash/` cannot be "deleted" again. This command only handles single files — directories and symlinks are both rejected with a clear explanation. Since Phase 37, every newly quarantined file also has its original location recorded durably (not just encoded in the quarantine filename), and since Phase 38 that metadata powers a `restore file` command (see below). Treat this as a safer alternative to permanent deletion, **not** as a full trash-management system: there is still no `empty trash` command and no automatic cleanup — once quarantined, a file stays in `.jarvis_trash/` until you restore it or manage it yourself outside of Jarvis (e.g. in your regular file manager).

**Quarantine listing notes (Phase 36; original-path display added Phase 37):** `list quarantine`/`show quarantine` show you what's currently sitting in `.jarvis_trash/` — each file's name, size, when it was quarantined, and, since Phase 37, its original path when that's known. Files quarantined before Phase 37 (or quarantined while metadata recording failed) show `original path: unknown (quarantined before metadata tracking)` instead — an honest fallback, never a guess based on the filename. This is read-only: it never reads a file's actual content, never writes any quarantine metadata itself, never creates the quarantine folder if it doesn't exist yet (it just tells you nothing's been quarantined), and never restores, deletes, or cleans anything up. It exists purely so you can check what's in quarantine without leaving Jarvis or opening a file manager.

**File restore notes (Phase 38):** `restore file <quarantine-file-or-path>` moves one quarantined file back to its recorded original location — you can name it either by the bare filename `list quarantine`/`show quarantine` shows, or by a path, as long as it resolves to a file directly inside `.jarvis_trash/` (anything else, including a path that tries to escape the quarantine folder, is rejected). It only works for files with a known original-path metadata record: a file quarantined before Phase 37's metadata tracking existed — or anything else with no record — shows an honest failure explaining Jarvis cannot restore it automatically, never a guess. It never overwrites: if something already exists at the recorded original path, the restore is refused and the file stays safely in quarantine. It never recreates a missing folder either: if the original parent folder no longer exists, the restore is refused rather than recreating it. It does not restore folders/directories, does not empty the trash, does not permanently delete anything, and does not restore more than one file per request — there is no "restore all." It adds no dashboard, AI, workflow, scheduler, or Inbox integration.

### Web search commands

| Command | Does | Tier |
|---|---|---|
| `search the web for <query>` | Runs a live web search and shows raw results (title/URL/snippet only — never full page content). | GREEN |
| `summarise web search for <query>` / `summarize web search for <query>` | Searches, then asks AI to synthesize a summary of the snippets. On success, also saves a copy to the Inbox (see §8). | GREEN (search), summary is advisory |

### Webpage read command (Phase 33)

| Command | Does | Tier |
|---|---|---|
| `read webpage <url>` | Fetches one webpage through Phase 32's safety foundation and shows its extracted, bounded plain text — no summary, no AI. | YELLOW — requires approval |

Unlike `search the web for <query>` above, this sends a network request to an arbitrary, Nathan-supplied target rather than one fixed, vetted search provider, so it always requires approval first. On approval, Jarvis validates the URL, fetches the page, extracts its visible text, strips any terminal/ANSI control sequences the page's own text might contain, and displays the result — never rewritten, never summarized, and never saved anywhere. If the URL is unsafe (points at a private/local network address, uses a disallowed scheme, etc.) or the fetch otherwise fails, you still see the approval prompt first (the URL is not pre-validated before asking), and then a clean, honest failure message after approving — nothing crashes and nothing is silently retried. The page's own text is never treated as an instruction: Jarvis does not follow links, act on anything the page says, or read a second page on its own.

### Webpage summary command (Phase 34; explicit Inbox save added Phase 61)

| Command | Does | Tier |
|---|---|---|
| `summarize webpage <url>` / `summarise webpage <url>` | Fetches one webpage (same approval-gated path as `read webpage <url>`) and asks AI to summarize its extracted text. Does **not** save to the Inbox. | YELLOW — requires approval |
| `summarize webpage <url> and save to inbox` / `summarise webpage <url> and save to inbox` | Same as above, and — only once a real summary has actually been produced — also saves it to the Inbox. | YELLOW — requires approval |

Approval happens **before** fetching, exactly like the plain read command — in fact both commands above reuse that exact same approval step, so the AI is never involved until an approved fetch has already succeeded. Only after that does Jarvis wrap the extracted text as untrusted context (explicitly disclosed to the AI as possibly incomplete, outdated, or containing text designed to look like instructions) and ask it for a summary. The summary is shown to you either way; the plain `summarize webpage <url>` command never saves it anywhere — not the Inbox, not a file, not fed into any other command — each request is a completely fresh fetch and summary. The `... and save to inbox` variant additionally stores the exact text you were shown (never the raw webpage content) as a new Inbox entry, but only after a real success: a failed fetch, a failed or unavailable AI summary, a declined or expired approval, or a blocked action all save nothing, exactly like the plain command's own failure handling. Neither command browses multiple pages, follows links, or acts on anything the page's text says, no matter how it's phrased. If approval is declined or times out, or if the fetch or summarization fails for any reason, you get a clear, honest explanation and nothing is fetched, summarized, or saved.

### Memory summary commands (all advisory AI syntheses; require `AI_REASONING_ENABLED`)

| Command | Summarizes |
|---|---|
| `summarise memory <id>` / `summarize memory <id>` | One specific memory. |
| `summarise memories <id1> <id2> ...` / `summarize memories ...` | A specific list of memories by id. |
| `summarise memories about <query>` / `summarize memories about <query>` | Memories matching a search query. |
| `summarise memories in <category>` / `summarize memories in <category>` | Memories in one category. |
| `summarise recent memories` / `summarize recent memories` | The most recent memories. |
| `summarise latest <count> memories` / `summarize latest <count> memories` | A specific number of the most recent memories. |

None of these write anywhere — they only read memory and produce an advisory summary in the response.

### Schedule commands (Phase 21/22)

| Command | Does | Tier |
|---|---|---|
| `schedule web search summary for <query> at <HH:MM>` | Creates a new daily schedule that searches `<query>` and saves an AI summary to the Inbox at `<HH:MM>` (24-hour, host local time) every day. | YELLOW |
| `list schedules` / `show schedules` | Lists every configured schedule, its time, enabled state, and last run. | GREEN |
| `enable schedule <id>` | Re-activates a disabled schedule. | YELLOW |
| `disable schedule <id>` | Deactivates a schedule (the only way to stop one — there is no delete command). | YELLOW |

Creating, enabling, or disabling a schedule requires approval because it commits Jarvis to running something unattended in the future — the same reasoning as any other guarded write.

### Workflow commands (fixed, multi-step sequences)

| Command | Does |
|---|---|
| `remember this and show it back: <text>` | Saves a memory, then immediately shows it back to you (both steps GREEN). |
| `remember this and forget it: <text>` | Saves a memory, then asks approval to immediately delete it again. |
| `create file <path> with <content> and show it` | Creates a file (with approval), then reads it back to you. |
| `update memory <id>: <content> and show it back` | Updates a memory (with approval), then shows the new content. |
| `search files for <pattern> and copy first to <destination>` | Searches by filename; if exactly one file matches, asks approval to copy it. Zero or multiple matches stop honestly instead of guessing. No AI, no file delete — see below. |

All five workflows above are fixed, deterministic sequences of existing tools — Jarvis does not currently run an AI-reasoning step as part of a workflow, and this is intentional, not a missing feature (see §9 and §11).

### Approval/workflow history commands (all GREEN, read-only)

| Command | Does |
|---|---|
| `show approval history` | Lists past approval requests and their decisions. |
| `show recent approvals` | The last 10, any status. |
| `show approved actions` / `show declined actions` | Filtered by outcome. |
| `show approval <request_id>` / `view approval <request_id>` | One specific approval by its id. |
| `show workflow history` | Lists past workflow runs and their lifecycle. |
| `show recent workflows` | The most recently active workflows. |
| `show workflow <workflow_id>` / `view workflow <workflow_id>` | One specific workflow's full transition history. |

These show durable **history** only — not a live list of things currently awaiting your decision (see §10).

---

## 7. Inbox, Scheduled Summaries, and Startup Notices

**The Inbox** is a durable, append-only record of AI-generated summaries that would otherwise vanish once your terminal scrollback is gone. Three things write to it:

1. **Interactive web search**: `summarise web search for <query>` — after a real, successful summary is produced, it's saved automatically alongside showing it to you.
2. **Scheduled**: a due schedule (see §6/§8) that runs successfully.
3. **Explicit webpage summary** (Phase 61): `summarize webpage <url> and save to inbox` / `summarise webpage <url> and save to inbox` — only when you use this exact opt-in variant, and only after a real, successful summary is produced; the plain `summarize webpage <url>` command (no trailing phrase) never saves anything.

All three are visible in the dashboard's Inbox tab, distinguished internally by `source_type` (`web_search_summary`, `scheduled_web_search_summary`, or `webpage_summary`). The two web-search-based producers are based on search-result **snippets and metadata only** — Jarvis does not read full webpages for those. The webpage-summary producer is different: it stores the AI's summary of a real, fetched webpage's extracted text — but still only the summary text you were already shown, never the raw webpage content itself. A saved entry, from any producer, is a stored **display string**: it is never re-executed, never trusted as an instruction, and never fed back into any AI request. Adversarial-looking text inside a query, URL, or summary (fake commands, URLs, anything) is always just displayed as plain text.

**Scheduled summaries specifically:**
- Schedules fire once per day at a fixed `HH:MM` in your machine's local time — no cron syntax, no recurrence options.
- `scheduler.py` must actually be running for anything to happen (§5).
- If the scheduler wasn't running exactly at the scheduled time, it catches up later the same day the next time it checks — but it never backfills more than once per day, no matter how many days were missed.
- A failed search, an unavailable/failed AI response, or a failed save creates **no** fake Inbox entry — only a genuine success is ever stored.
- Once a schedule is "claimed" for the day (whether it then succeeds or fails), it will not be retried again until the next calendar day.

**Startup notices** (Phase 22): when you start the CLI, if new `scheduled_web_search_summary` Inbox entries exist since you last checked, you'll see one line like:

```
Jarvis notice: 3 scheduled inbox entries were added since your last check. Latest: 2026-07-11 08:00. Open the dashboard Inbox to review them.
```

This notice shows **only a count and a timestamp** — never the search query, the AI summary text, or any URL. It only counts scheduled entries, never ones you triggered interactively yourself (you're already looking at the screen for those). The very first time this check ever runs, it stays silent and just starts tracking from that point forward, so upgrading never dumps a big historical backlog on you. This is **not** a desktop, phone, or email notification — it only appears in the CLI's own startup text, once, each time you launch it.

---

## 8. Dashboard Guide

Seven tabs, all read-only:

| Tab | Shows |
|---|---|
| **Overview** | A "Jarvis Online" home screen (Phase 62) with four honestly-isolated panels: **System Status** (AI reasoning/model, voice/voice-input configuration, log level, database path, approval timeout, and whether the API key is configured — never its value); **Store Reachability** (a plain reachable/not-reachable check for each durable store this dashboard depends on); **Summary Counts** (the original real-data counts: total memories, recent approval decisions, recently active workflows, total Inbox entries, scheduled Inbox entries); and **Recent Activity** (a merged, real-timestamp, newest-first list across memories, approvals, workflows, inbox, and quarantine — deterministic text only, never AI-generated). Any panel that can't be read shows its own honest error, without affecting the others. |
| **Memories** | Recent memories (filterable by category), full content on selecting a row. |
| **Approval History** | Past approval requests and decisions — durable history, not a live "awaiting your decision" list. |
| **Workflow History** | Recently active workflows and their full recorded transition history on selection — durable history, not resumable state. |
| **Inbox** | Saved summaries (interactive web search, scheduled, and explicit webpage-summary saves), newest first, full text on selection. |
| **Schedules** | Every configured schedule: id, name, query, time, enabled state, last run, created date. |
| **Quarantine** | Recorded quarantined files: name, original path (when known), quarantine path, quarantined-at time, and session id. Durable metadata only — read-only, and a row does not guarantee the file is still physically in `.jarvis_trash/` (it may have already been restored). |

The dashboard **cannot**: run any command, approve or decline anything, create/edit/enable/disable a schedule, delete or change a memory, restore or delete a quarantined file, empty the trash, clean up old quarantined files, or write anything to the database at all — all restore/delete actions remain CLI-only, and both still require YELLOW approval there. It refreshes on a timer (every 5 seconds) plus a manual "Refresh now" button — this is polling, not live/real-time updating, and the title bar itself says "(read-only)".

---

## 9. Safety Model: GREEN / YELLOW / RED

Every action Jarvis can take is classified into exactly one of three tiers before it ever runs, by the Security Manager alone:

- **GREEN** — safe, read-only, or low-risk. Runs immediately, no confirmation needed (e.g. reading a file, listing memories, searching the web).
- **YELLOW** — changes something. Jarvis pauses and asks you to approve or decline before anything happens (e.g. creating a file, updating a memory, creating a schedule). If you don't answer within the approval timeout (default 60 seconds), it expires automatically and nothing runs.
- **RED** — considered too dangerous to ever run, regardless of approval (e.g. `forget all memories`, anything matching "format drive", "wipe drive", "rm -rf", "drop database"). These are always blocked; there is no way to approve past a RED classification.

Anything that doesn't match a known safe pattern defaults to **YELLOW**, never GREEN — Jarvis is conservative by default.

**Pending approvals and paused workflows can survive a restart (Phase 27).** If Jarvis is closed or crashes while a YELLOW action is awaiting your decision, or while a multi-step workflow is paused waiting for one, that state is durably saved and re-checked the next time Jarvis starts. Day-to-day this is invisible — you won't see or need to do anything differently. What changes is only what happens if a restart lands exactly mid-approval: previously that pending state vanished silently with no record; now it is either safely restored (still requiring your explicit approval before anything runs — reload never auto-approves or auto-executes) or, if it can no longer be safely resumed (its tool no longer exists, its action's risk level has changed, the saved data is corrupt, or too much time has passed), it is honestly closed out and recorded in the same approval/workflow history you can already review — never silently dropped, and never run without your say-so.

**Workflows never run an AI-reasoning step, and this is intentional (Phase 30).** The approval prompt you see before a YELLOW step runs shows the action, the reason, and the risk tier — but not the full content a step would write. That's safe today because every workflow only ever writes text you typed yourself, or a plain file path/id carried over from the previous step's result — never text generated on the fly. If an AI summary's own generated text were ever wired directly into a following file-write step, you could end up approving "create this file" without seeing what was actually about to be written into it. So Jarvis doesn't do that: AI summaries stay advisory, shown to you as a response, and saving one to a file is a manual step you do yourself (e.g. copy the text Jarvis showed you into a `create file <path> with <content>` command) — not something a workflow automates.

**Other important safety facts, all true today:**
- AI-generated suggestions are always advisory — they're shown to you as information, never automatically acted on.
- Stored text (memories, Inbox entries, file content) is never treated as an instruction Jarvis follows — it's always just data.
- A scheduled query is never treated as if you typed it live — it's kept in a separate, clearly-marked "untrusted context" section internally, specifically so stored text can never masquerade as a live command.
- Untrusted content from outside Jarvis (web search results, file contents) is always scanned before being shown to the AI, but is never blocked or rewritten — you always see it as-is.

---

## 10. Common Workflows / Example Sessions

**Save a note and see it right away:**
```
you> remember this and show it back: buy milk on Friday
```

**Ask what Jarvis knows:**
```
you> show memories
you> search memories for milk
```

**Find a file without knowing its exact path:**
```
you> search files for readme
jarvis> [OK] File search (name) for 'readme' in .:
          README.md
          docs/user_guide.md

you> find files containing scheduled_web_search_summary
jarvis> [OK] File search (content) for 'scheduled_web_search_summary' in .:
          storage/models.py: source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
          ...
```
No approval needed — file search is read-only, exactly like `list files`/`read file`.

**Create a file (requires your approval):**
```
you> create file notes.txt with Meeting is at 3pm
jarvis> [NEEDS APPROVAL] ...
=================================================
  APPROVAL REQUIRED - Jarvis needs your decision
=================================================
  Action:     create text file
  Reason:     Action did not match any known rule. Treated as sensitive and routed for confirmation as a precaution.
  Risk tier:  YELLOW (sensitive - needs your approval)
Approve this action? [y]es / [n]o: y
jarvis> [APPROVED] You approved 'create text file'.
jarvis> [OK] ...
```

**Back up a file before editing it (requires your approval):**
```
you> copy file notes.txt to notes.txt.bak
jarvis> [NEEDS APPROVAL] ...
=================================================
  APPROVAL REQUIRED - Jarvis needs your decision
=================================================
  Action:     copy file
  Reason:     Copying a file creates new state and should be confirmed.
  Risk tier:  YELLOW (sensitive - needs your approval)
Approve this action? [y]es / [n]o: y
jarvis> [APPROVED] You approved 'copy file'.
jarvis> [OK] Copied 'notes.txt' to 'notes.txt.bak' (27 bytes).
```
If `notes.txt.bak` already existed, the copy is refused — even after approval — and nothing is overwritten.

**Rename a file, or move it to a different folder (requires your approval):**
```
you> rename file draft.txt to final.txt
jarvis> [NEEDS APPROVAL] ...
=================================================
  APPROVAL REQUIRED - Jarvis needs your decision
=================================================
  Action:     move file
  Reason:     Moving a file changes its location and should be confirmed.
  Risk tier:  YELLOW (sensitive - needs your approval)
Approve this action? [y]es / [n]o: y
jarvis> [APPROVED] You approved 'move file'.
jarvis> [OK] Moved 'draft.txt' to 'final.txt'.
```
`move file` and `rename file` are the same command — `draft.txt` no longer exists afterward; only `final.txt` does. If `final.txt` already existed, the move is refused — even after approval — and `draft.txt` is left exactly where it was.

**Find a file and copy it, in one command (requires your approval):**
```
you> search files for budget.xlsx and copy first to backup/budget.xlsx
jarvis> [NEEDS APPROVAL] ...
=================================================
  APPROVAL REQUIRED - Jarvis needs your decision
=================================================
  Action:     copy file
  Reason:     Copying a file creates new state and should be confirmed.
  Risk tier:  YELLOW (sensitive - needs your approval)
Approve this action? [y]es / [n]o: y
jarvis> [APPROVED] You approved 'copy file'.
jarvis> [OK] Copied '...\budget.xlsx' to 'backup/budget.xlsx' (...bytes).
```
This only proceeds if the search finds **exactly one** matching file. If it finds none, or more than one, Jarvis stops honestly and shows you what it found instead of guessing — narrow your pattern and try again. No AI is involved in choosing the file, and this workflow never deletes anything.

**Get an AI-summarized web search, saved to the Inbox automatically:**
```
you> summarise web search for latest AI news
```
(Requires `AI_REASONING_ENABLED=true` and a valid `ANTHROPIC_API_KEY` — otherwise you'll get an honest "AI reasoning unavailable" response, no crash.)

**Set up a daily scheduled summary:**
```
you> schedule web search summary for jarvis ai news at 08:00
jarvis> [NEEDS APPROVAL] ...
Approve this action? [y]es / [n]o: y
jarvis> [APPROVED] You approved 'schedule web search'.
jarvis> [OK] Created schedule 1: 'jarvis ai news' at 08:00 daily.
```
Then, in a separate terminal, leave `scheduler.py` running. Check `list schedules` any time to see its status, or open the dashboard's Schedules/Inbox tabs.

---

## 11. What Jarvis Cannot Do Yet

Confirmed absent from the current codebase — not deferred silently, each explicitly a future decision:

- No desktop, phone, or email/push notifications of any kind — the only "notice" mechanism is the CLI startup line (§7) and the dashboard's real Overview line.
- No autonomous webpage browsing, no multi-page crawling, and no scheduled webpage monitoring. `read webpage <url>` (Phase 33, §6) and `summarize webpage <url>`/`summarise webpage <url>` (Phase 34, §6) each fetch exactly one page per request, never follow links, and never act on anything the page's text says. Neither of these two commands saves what it fetched or summarized anywhere — the explicit `... and save to inbox` variant (Phase 61, §6) is a separate, opt-in command, never automatic. Scheduled web search (§7) still uses snippets/metadata only, unrelated to any of these commands.
- No Research Agent or autonomous multi-step research.
- No voice interface, no phone app, no remote client of any kind.
- No Core service, HTTP server, or IPC bridge — the three processes only ever share the SQLite file.
- No dashboard command box or any dashboard write action whatsoever.
- No arbitrary command scheduling — the scheduler runs exactly one hard-coded action type (search + AI summary + save).
- No workflow-triggering, YELLOW, or RED scheduled actions — only the one GREEN scheduled action exists; scheduling itself (create/enable/disable) is YELLOW, but what runs is always GREEN.
- No goals/projects/tasks system.
- No *permanent* file delete — `delete file <path>` (Phase 35, §6) only quarantines a file into `.jarvis_trash/`; `list quarantine`/`show quarantine` (Phase 36, §6) let you see what's in there, including original path when known (Phase 37, §6); `restore file <path>` (Phase 38, §6) can move a file back, but only when its original-path metadata is known; there is still no empty-trash command and no automatic cleanup/retention policy.
- No AI-reasoning step inside a workflow, and no automatic "save this AI summary to a file/Inbox" action — both are a deliberate safety boundary (§9), not an oversight, and would need their own separate, reviewed design before being built.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Required environment variable 'ANTHROPIC_API_KEY' is not set` | Every process (CLI/dashboard/scheduler) needs this variable set to *something* in `.env`, even if you don't plan to use AI reasoning at all — a placeholder value is fine as long as `AI_REASONING_ENABLED` stays `false`. |
| A summary command says AI reasoning is unavailable | `AI_REASONING_ENABLED` is unset/false, or the API key/credits aren't valid. Everything else in Jarvis still works. |
| A scheduled summary never shows up | Is `scheduler.py` actually running? Check `list schedules` for `enabled`/`last_run_at`. A schedule only runs while the scheduler process is active. |
| The dashboard shows stale data | It refreshes every 5 seconds automatically, or click "Refresh now". |
| An approval seems to have "timed out" | YELLOW approvals expire after `APPROVAL_TIMEOUT_SECONDS` (default 60s) if you don't answer — nothing runs; just retry the command. |
| A command isn't recognized | Check §6 for the exact required phrasing — Jarvis matches fixed, deterministic grammar, not free-form natural language. |
| Not sure what Jarvis is currently configured with | Run `show config` (or `show settings`) — it reports the AI model, whether AI reasoning is enabled, the approval timeout, log level, database path, and debug mode, plus whether the API key is set. It never shows the key's actual value. |

---

## 13. Future Capabilities Not Yet Implemented

These are real candidates that have been evaluated in past architectural reviews but are **not yet built**, listed here only so expectations stay honest:

- Desktop notification for scheduled Inbox activity (deferred pending real evidence the CLI/dashboard notice isn't enough).
- The webpage fetch/read safety foundation (Phase 32), the plain read command (Phase 33, §6), AI webpage summarization (Phase 34, §6), and an explicit, opt-in `... and save to inbox` variant of that summarization command (Phase 61, §6) are all complete. Not yet built, each a distinct, separately-reviewed future decision: scheduled webpage summaries (blocked on the scheduler's current single-hardcoded-action-type design, which has no `type`/`kind` column to extend without a schema change); *automatic* Inbox saving for the plain webpage-summary command (a deliberate non-goal — Phase 61 chose an explicit opt-in command instead, precisely so that approving a fetch is never read as automatic consent to a durable write); and any Research Agent or autonomous multi-step browsing behavior. Further command refinements (e.g. additional grammar) remain possible but are not planned unless Nathan specifically requests them.
- A Core service allowing an interactive dashboard, voice, or phone client. (Phase 41 added an internal, disabled-by-default fake/mock voice foundation — see `docs/phase_41_completion_report.md` — but this is not the same thing: no real audio, microphone, or user-reachable voice command exists today, and no Core service was added.)
- Goals/projects/tasks tracking.
- Additional scheduled action types beyond web-search summaries.
- More Inbox producers beyond web-search summaries and the explicit webpage-summary save command (Phase 61, §6).
- A file delete tool exists (Phase 35, §6) as a quarantine-only move into `.jarvis_trash/`, you can list what's in quarantine including original path when known (Phase 36/37, §6), a `restore file <path>` command (Phase 38, §6) can move a file with known metadata back to its original location, and the dashboard's Quarantine tab (Phase 39, §8) shows recorded quarantine metadata read-only. Not yet built, each a distinct future decision: an `empty trash` command, an automatic cleanup/retention policy, and a bulk/"restore all" command.
- More workflow templates beyond the current five — paused, not closed: the next one should come from a specific need, not just because the machinery exists.
- Automated "save AI summary to file/Inbox" behavior — paused pending a separate design review of how to let you review the exact content before it's written (see §9).

None of these should be assumed available — always check this guide or the codebase directly rather than assuming a feature exists.
