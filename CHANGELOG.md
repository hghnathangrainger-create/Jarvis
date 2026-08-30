# Changelog

All notable changes to the Jarvis AI Operating System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
