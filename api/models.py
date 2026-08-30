"""
models.py

Pydantic request/response models for the Jarvis API.

Responsibilities:
    - Define typed request bodies and response shapes for every endpoint.
    - Provide validation via Pydantic's built-in constraint checking.

Does NOT:
    - Implement business logic (routes delegate to existing managers).
    - Access the database or filesystem directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    message: str = Field(..., min_length=1, description="The user message")
    mode: str = Field(default="text", description="Chat mode (text, voice)")


class ChatResponse(BaseModel):
    """Response body for POST /api/chat."""

    response: str = Field(..., description="Jarvis response text")
    trace_id: str = Field(default="", description="Observability trace id")
    provider: str = Field(default="", description="AI provider used")
    tokens_used: int = Field(default=0, description="Total tokens consumed")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Request body for POST /api/auth/login."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Response body for POST /api/auth/login."""

    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Approval / Workflow
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    """Request body for approving/declining a pending action."""

    request_id: str
    action: str
    details: str = ""
    tier: str = "yellow"


class WorkflowStatusResponse(BaseModel):
    """Response body for GET /api/workflows/{id}."""

    workflow_id: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "unknown"
    progress_pct: float = 0.0


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryCreateRequest(BaseModel):
    """Request body for POST /api/memory."""

    content: str = Field(..., min_length=1)
    category: str = Field(default="general")
    source: str = Field(default="api")


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    """Request body for POST /api/goals."""

    title: str = Field(..., min_length=1)
    description: str = ""
    priority: str = "medium"


class ProjectCreateRequest(BaseModel):
    """Request body for POST /api/projects."""

    name: str = Field(..., min_length=1)
    description: str = ""
    status: str = "planning"


# ---------------------------------------------------------------------------
# Standard error
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response returned by all endpoints on failure."""

    detail: str
    code: str = "error"
