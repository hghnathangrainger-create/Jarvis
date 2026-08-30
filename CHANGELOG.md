# Changelog

All notable changes to the Jarvis AI Operating System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **System Lifecycle management** (`lifecycle/`) — Chapter 29 of the blueprint:
  - LifecycleManager with startup sequencing (10 steps in dependency order)
  - Graceful shutdown with signal handlers (SIGINT, SIGTERM)
  - Crash recovery — detects and resumes interrupted workflows from checkpoints
  - Safe Mode — GREEN-tier-only operation with manual activation via API
  - Subsystem status tracking with per-subsystem state (starting/ready/failed/disabled)
  - Lifecycle event audit trail logged to observability system
  - `--safe-mode` CLI flag for direct Safe Mode startup
  - WebSocket broadcasts for SYSTEM_SHUTDOWN and SAFE_MODE_ACTIVATED events
- **Android Client backend** (`android/`) — server-side support for the Android companion app:
  - Device registration and tracking with FCM token managementn  - Push notification service via Firebase Cloud Messaging (optional, graceful fallback)
  - Remote command queue with 5-minute TTL expiry
  - Command routing: chat → orchestrator, approve/cancel → approval manager, status → system status
  - AndroidManager facade wrapping device store, notifications, and command queue
  - 6 API endpoints: register, unregister, devices, command, poll, ack
  - AndroidTool (GREEN) for CLI: list devices, send notifications, broadcast
  - WebSocket auto-push for approval requests to Android devices via FCM
- **Web Dashboard** (`dashboard/`) — real-time system frontend:
  - Single-page app with 8 sections: Today, Tasks, Memory, Knowledge, Audit, Providers, Goals, Settings
  - Dark terminal-themed CSS (background #0a0a0f, accent #00d4aa)
  - Hash-based client-side router (#today, #memory, #goals, etc.)
  - WebSocket real-time updates with auto-reconnect
  - JWT authentication with login page
  - Auto-refresh every 30 seconds as fallback
  - Collapsible sidebar navigation
  - No build tools — pure vanilla JS, no npm/Node.js
- **FastAPI HTTP/WebSocket API server** (`api/` module) for Dashboard and Android Client:
  - JWT authentication with 24-hour token expiry (`api/auth.py`, `api/routes_auth.py`)
  - Chat endpoint — POST `/api/chat` routes messages through the orchestrator
  - Memory endpoints — list, search, create, delete with category filtering
  - Workflow endpoints — list active workflows, approve/cancel pending steps
  - Goal/Project endpoints — CRUD for goals with progress and projects with tasks
  - Plugin endpoints — list, enable, disable installed plugins
  - System endpoints — health check (no auth), AI provider status, observability metrics
  - WebSocket hub (`api/websocket.py`) — real-time event broadcasting with 50-event catch-up buffer
  - CORS middleware, request logging middleware, global exception handler
- **Computer Control module** (`computer_control/`) — full desktop automation:
  - Input automation via pyautogui — click, type, hotkey, scroll, drag, move
  - Window management via pygetwindow/psutil — launch, close, list, switch, resize, move, minimize, maximize
  - Command execution — shell, PowerShell, Python scripts with timeouts and audit logging
  - Screen analysis — screenshots (mss), OCR text extraction (pytesseract), UI element detection, AI vision analysis
  - Security tier enforcement: GREEN (screen), YELLOW (input/window), RED (commands)
  - 4 tool wrappers: InputTool, WindowTool, CommandTool, ScreenTool
- **Plugin architecture** (`plugins/`):
  - Plugin loader with manifest validation and entry point import (`plugins/loader.py`)
  - Plugin sandbox with permission enforcement (`plugins/sandbox.py`)
  - Plugin registry with enable/disable state (`plugins/registry.py`)
  - PluginManagerTool (YELLOW) for listing, enabling, disabling plugins via CLI
- **Voice pipeline** (`voice/`):
  - VoicePipeline with wake word detection, STT, orchestrator integration, and TTS (`voice/pipeline.py`)
  - WhisperSpeechToText provider wrapping faster-whisper (`voice/whisper_stt.py`)
  - Pyttsx3TextToSpeech provider wrapping pyttsx3 (`voice/pyttsx3_tts.py`)
  - WakeWordDetector with configurable sensitivity (`voice/wake_word.py`)
  - VoiceControlTool for managing voice pipeline from CLI
  - `--voice` CLI flag for continuous voice interaction mode
- **Goal & Milestone tracking** (`goals/`):
  - GoalManager with CRUD, milestones, tasks, and progress reports
  - GoalCreateTool, GoalProgressTool, TaskCompleteTool
- **Project management** (`projects/`):
  - ProjectManager with projects, tasks, notes, and status tracking
  - ProjectCreateTool, ProjectStatusTool
- **Knowledge Library** (`knowledge/`):
  - KnowledgeManager with keyword search and ChromaDB semantic search
  - KnowledgeSearchTool (GREEN), KnowledgeAddTool (YELLOW)
- **Observability enhancements**:
  - Structured EventLogger with append-only audit log
  - Tracer for request-level span tracking
  - MetricsCollector for per-provider and per-tool statistics
  - ObservabilityTool exposing metrics, traces, and provider stats via CLI
- Console logging configured from LOG_LEVEL (Phase 54)

### Changed

- `config/settings.py` — added api_host, api_port, api_username, api_password, cors_origins
- `main.py` — added `--server` flag for API server mode, `--voice` flag for voice mode, `--safe-mode` flag, signal handlers for graceful shutdown, all subsystem wiring
- `api/routes_system.py` — lifecycle-aware status endpoint, safe-mode/resume endpoints
- `api/websocket.py` — added broadcast_system_event() for lifecycle events, Android push integration
- `tools/builtin/__init__.py` — exported all new tools (WindowTool, InputTool, CommandTool, ScreenTool, GoalCreateTool, GoalProgressTool, TaskCompleteTool, ProjectCreateTool, ProjectStatusTool, KnowledgeAddTool, KnowledgeSearchTool, ObservabilityTool, PluginManagerTool, VoiceControlTool)
- `pyproject.toml` — added fastapi, uvicorn, python-jose, passlib, websockets, Pillow, mss, pytesseract, pyautogui, pygetwindow, psutil, pyttsx3, sounddevice, numpy

### Tests

- 38 lifecycle tests covering startup sequence, shutdown, crash recovery, safe mode, signal handlers, and API endpoints
- 48 Android tests covering models, device store, notifications, command queue, manager integration, and API endpoints
- 15 dashboard tests covering routes, static files, and API coexistence
- 36 API tests covering login flow, auth enforcement, chat, memory CRUD, workflows, goals, plugins, CORS, WebSocket, and error handling
- Computer control tests covering models, InputAutomator, WindowManager, CommandExecutor, ScreenAnalyzer, and all 4 tool wrappers
- Plugin tests covering loader, sandbox, registry, and PluginManagerTool
- Project management tests covering ProjectManager and tool wrappers
- Voice pipeline tests covering pipeline lifecycle, wake word, STT/TTS providers

## [0.2.0] - 2026-08-30

### Added

- **Multi-provider AI router** with automatic failover across Claude, OpenAI, and Gemini (`ai/router.py`)
- **OpenAI provider** (`ai/providers/openai_provider.py`) implementing AIProvider ABC with the `openai` Python SDK
- **Gemini provider** (`ai/providers/gemini_provider.py`) implementing AIProvider ABC with the `google-genai` Python SDK
- Model string parser supporting `"provider:model"` format (e.g. `"openai:gpt-4o"`, `"gemini:gemini-2.8-flash"`) and `"auto"` routing
- Provider fallback on retryable errors (connection, timeout, API) through the ordered providers tuple
- **ChromaDB vector memory** (`memory/vector_store.py`) with semantic search, metadata filtering, and optional persistent storage
- `semantic_search(query, top_k)` method on `MemoryManager` for embedding-free vector similarity search
- **N-step DAG workflow engine** (`workflow/dag_engine.py`) supporting:
  - Arbitrary number of steps with dependency resolution via topological sort
  - Parallel execution of independent steps via `concurrent.futures.ThreadPoolExecutor`
  - Step-level `on_failure` policies: `abort`, `skip`, or `retry` with configurable `max_retries`
  - Rollback/compensation — automatic reverse-order execution of compensate actions on failure
  - Checkpoint persistence to SQLite after each step (`workflow/checkpoint_store.py`) for crash recovery and resume
  - YELLOW approval gates extending to N-step workflows
  - `get_status(workflow_id, plan)` method returning per-step completion status
- **DAG models** (`workflow/dag_models.py`) — `DAGStepStatus`, `DAGWorkflowStatus`, `DAGStepResult`, `DAGWorkflowResult`, `DAGWorkflowStatusInfo`
- **Checkpoint store** (`workflow/checkpoint_store.py`) — SQLite-backed persistence for workflow step progress
- `WorkflowCheckpointEntry` ORM model in `storage/models.py`
- DAG fields on `PlanStep`: `step_id`, `depends_on`, `on_failure`, `max_retries`, `compensate`, `compensate_input`

### Changed

- `config/settings.py` — added `openai_api_key` (from `OPENAI_API_KEY` env var) and `google_api_key` (from `GOOGLE_API_KEY` env var)
- `ai/router.py` — `AIRouter` now accepts `providers: tuple[AIProvider, ...]` with backward-compatible `provider=` keyword
- `main.py` — wires ClaudeProvider, OpenAIProvider, and GeminiProvider as a providers tuple to AIRouter
- `memory/memory_manager.py` — integrated ChromaDB vector store alongside SQLite; `save()` indexes to both, `forget()` deletes from both
- `planner/plan_models.py` — extended `PlanStep` with DAG fields (`step_id`, `depends_on`, `on_failure`, `max_retries`, `compensate`, `compensate_input`)
- `tools/builtin/config_tool.py` — displays Google API key status alongside existing API keys
- `pyproject.toml` — added `openai`, `google-genai`, and `chromadb` dependencies

### Dependencies

- `openai (>=1.0.0,<2.0.0)` — OpenAI Python SDK
- `google-genai (>=1.0.0,<2.0.0)` — Google Generative AI SDK (replaces deprecated `google-generativeai`)
- `chromadb (>=0.5.0,<1.0.0)` — ChromaDB vector database

### Tests

- 5555 passing, 0 failures, 3 skipped
- 28 new DAG workflow engine tests covering: topological sort, sequential/parallel execution, failure handling, rollback/compensation, checkpoints, YELLOW gates, `on_failure` policies, and backward compatibility
- 15 new memory tests covering: ChromaDB vector store operations, semantic search relevance, metadata filtering, graceful degradation
- Existing tests updated for new `PlanStep` fields and config tool API key display

## [0.1.0] - 2026-07-25

### Added

- Phase 99–101: Compound workflow lifecycle, Verified Action Context, Actionable Required-Argument foundation
- AI reasoning engine with structured prompt building
- Workflow engine with 2-step sequential execution
- Voice I/O (TTS/STT), web fetching, and tool execution framework
- Episodic memory with SQLite storage
- Observability and safety systems
