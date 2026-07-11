# Jarvis Operating Guide

A practical, task-oriented reference for actually running and using Jarvis. Unlike `README.md` (which is a phase-by-phase build log), this document is organized around *what you want to do* right now, as of Phase 22.

Everything described here was verified directly against the current codebase while writing this guide — nothing here is aspirational or planned.

---

## 1. What Jarvis Can Do Right Now

Jarvis is a personal, local, single-user AI assistant with three cooperating processes and a durable SQLite database. Today it can:

- Remember and recall notes (memory), with optional AI-generated summaries of them.
- Read, list, search (by name or content), create, and append to files on your machine.
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

---

## 6. Command Reference (Grouped by Task)

All commands below are typed at the CLI's `you>` prompt. They are matched case-insensitively.

### Basic / info commands (GREEN — safe, no approval)

| Command | What it does |
|---|---|
| `echo <text>`, `repeat <text>`, `say <text>` | Repeats the text back. |
| `system info`, `version`, `about`, `who are you` | Shows basic Jarvis system information. |

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
| `summarise file <path>` / `summarize file <path>` | Reads a file and produces an AI summary of it (advisory only; requires `AI_REASONING_ENABLED`). | GREEN (reading), summary is advisory |

**File search notes (Phase 24):** always searches from the project directory (there is no "in `<directory>`" clause); results are capped at 50 by default (a message tells you if more may exist); noisy directories are always skipped (`.git`, `__pycache__`, `.pytest_cache`, virtual environments, `node_modules`, build/cache folders); binary and unreadable files are silently skipped rather than causing an error; content search never shows more than a short snippet of the matching line — never a full file's contents. File search cannot move, rename, copy, or delete anything — it is exactly as read-only as `list files`/`read file`.

### Web search commands

| Command | Does | Tier |
|---|---|---|
| `search the web for <query>` | Runs a live web search and shows raw results (title/URL/snippet only — never full page content). | GREEN |
| `summarise web search for <query>` / `summarize web search for <query>` | Searches, then asks AI to synthesize a summary of the snippets. On success, also saves a copy to the Inbox (see §8). | GREEN (search), summary is advisory |

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

**The Inbox** is a durable, append-only record of AI-generated web-search summaries that would otherwise vanish once your terminal scrollback is gone. Two things write to it:

1. **Interactive**: `summarise web search for <query>` — after a real, successful summary is produced, it's saved automatically alongside showing it to you.
2. **Scheduled**: a due schedule (see §6/§8) that runs successfully.

Both kinds are visible in the dashboard's Inbox tab, distinguished internally by `source_type` (`web_search_summary` vs `scheduled_web_search_summary`). Every stored summary is based on search-result **snippets and metadata only** — Jarvis does not read full webpages. A saved entry is a stored **display string**: it is never re-executed, never trusted as an instruction, and never fed back into any AI request. Adversarial-looking text inside a query or summary (fake commands, URLs, anything) is always just displayed as plain text.

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

Six tabs, all read-only:

| Tab | Shows |
|---|---|
| **Overview** | Total memories, recent approval decisions, recently active workflows, total Inbox entries, and a real count + latest timestamp of scheduled Inbox entries specifically. |
| **Memories** | Recent memories (filterable by category), full content on selecting a row. |
| **Approval History** | Past approval requests and decisions — durable history, not a live "awaiting your decision" list. |
| **Workflow History** | Recently active workflows and their full recorded transition history on selection — durable history, not resumable state. |
| **Inbox** | Saved summaries (interactive and scheduled), newest first, full text on selection. |
| **Schedules** | Every configured schedule: id, name, query, time, enabled state, last run, created date. |

The dashboard **cannot**: run any command, approve or decline anything, create/edit/enable/disable a schedule, delete or change a memory, or write anything to the database at all. It refreshes on a timer (every 5 seconds) plus a manual "Refresh now" button — this is polling, not live/real-time updating, and the title bar itself says "(read-only)".

---

## 9. Safety Model: GREEN / YELLOW / RED

Every action Jarvis can take is classified into exactly one of three tiers before it ever runs, by the Security Manager alone:

- **GREEN** — safe, read-only, or low-risk. Runs immediately, no confirmation needed (e.g. reading a file, listing memories, searching the web).
- **YELLOW** — changes something. Jarvis pauses and asks you to approve or decline before anything happens (e.g. creating a file, updating a memory, creating a schedule). If you don't answer within the approval timeout (default 60 seconds), it expires automatically and nothing runs.
- **RED** — considered too dangerous to ever run, regardless of approval (e.g. `forget all memories`, anything matching "format drive", "wipe drive", "rm -rf", "drop database"). These are always blocked; there is no way to approve past a RED classification.

Anything that doesn't match a known safe pattern defaults to **YELLOW**, never GREEN — Jarvis is conservative by default.

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
- No full webpage fetching or reading — web search (interactive and scheduled) uses snippets/metadata only.
- No Research Agent or autonomous multi-step research.
- No voice interface, no phone app, no remote client of any kind.
- No Core service, HTTP server, or IPC bridge — the three processes only ever share the SQLite file.
- No dashboard command box or any dashboard write action whatsoever.
- No arbitrary command scheduling — the scheduler runs exactly one hard-coded action type (search + AI summary + save).
- No workflow-triggering, YELLOW, or RED scheduled actions — only the one GREEN scheduled action exists; scheduling itself (create/enable/disable) is YELLOW, but what runs is always GREEN.
- No goals/projects/tasks system.
- No durable, restart-surviving pending approvals or paused workflows — both currently live only in memory while the CLI process is running; if the CLI is closed with something pending, that pending state is gone (though its history, if any was recorded, remains durable and viewable).

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

---

## 13. Future Capabilities Not Yet Implemented

These are real candidates that have been evaluated in past architectural reviews but are **not yet built**, listed here only so expectations stay honest:

- Desktop notification for scheduled Inbox activity (deferred pending real evidence the CLI/dashboard notice isn't enough).
- Webpage fetch/read safety foundation, and eventual webpage summarization / Research Agent work built on it.
- A Core service allowing an interactive dashboard, voice, or phone client.
- Durable (restart-surviving) pending approvals and paused workflows.
- Goals/projects/tasks tracking.
- Additional scheduled action types beyond web-search summaries.
- More Inbox producers beyond web-search summaries.

None of these should be assumed available — always check this guide or the codebase directly rather than assuming a feature exists.
