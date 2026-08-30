"""
routes_memory.py

Memory endpoints for the Jarvis API.

Responsibilities:
    - GET  /api/memory — list memories with optional category/limit/offset.
    - GET  /api/memory/search — search memories by keyword.
    - POST /api/memory — add a new memory (YELLOW tier, needs auth).
    - DELETE /api/memory/{id} — delete a memory (RED tier, needs auth).

Does NOT:
    - Implement memory storage (delegates to MemoryManager).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import get_current_user
from api.models import ErrorResponse, MemoryCreateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _get_memory_manager() -> Any:
    """Lazy-import and return the global MemoryManager."""
    from api.app import get_memory_manager

    return get_memory_manager()


@router.get("")
async def list_memories(
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
    memory_manager: Any = Depends(_get_memory_manager),
) -> dict[str, Any]:
    """List memories with optional category filter and pagination."""
    if memory_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not available",
        )

    try:
        if category:
            records = memory_manager.list_by_category(category, limit=limit + offset)
        else:
            records = memory_manager.list_recent(limit=limit + offset)

        # Apply offset manually since MemoryManager doesn't support it natively.
        sliced = records[offset : offset + limit]
        return {
            "memories": [
                {
                    "id": r.id,
                    "content": r.content,
                    "category": r.category,
                    "source": r.source,
                    "created_at": r.created_at.isoformat(),
                }
                for r in sliced
            ],
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.error("Failed to list memories: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list memories: {exc}",
        )


@router.get("/search")
async def search_memories(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
    memory_manager: Any = Depends(_get_memory_manager),
) -> dict[str, Any]:
    """Search memories by keyword (case-insensitive substring match)."""
    if memory_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not available",
        )

    try:
        records = memory_manager.search(q, limit=limit)
        return {
            "memories": [
                {
                    "id": r.id,
                    "content": r.content,
                    "category": r.category,
                    "source": r.source,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ],
            "query": q,
            "total": len(records),
        }
    except Exception as exc:
        logger.error("Failed to search memories: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search memories: {exc}",
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: MemoryCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
    memory_manager: Any = Depends(_get_memory_manager),
) -> dict[str, Any]:
    """Add a new memory. This is a YELLOW-tier operation."""
    if memory_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not available",
        )

    try:
        record = memory_manager.save(
            request.content,
            source=request.source,
            category=request.category,
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Memory content was empty or marked 'do not remember'",
            )
        return {
            "id": record.id,
            "content": record.content,
            "category": record.category,
            "source": record.source,
            "created_at": record.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create memory: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create memory: {exc}",
        )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: int,
    user: dict[str, Any] = Depends(get_current_user),
    memory_manager: Any = Depends(_get_memory_manager),
) -> None:
    """Delete a memory by ID. This is a RED-tier operation."""
    if memory_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not available",
        )

    try:
        deleted = memory_manager.forget(memory_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Memory {memory_id} not found",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete memory: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory: {exc}",
        )
