"""
routes_goals.py

Goal and project endpoints for the Jarvis API.

Responsibilities:
    - GET  /api/goals — list goals with progress.
    - POST /api/goals — create a goal.
    - GET  /api/projects — list projects.
    - GET  /api/projects/{id} — project status with tasks.

Does NOT:
    - Implement goal/project logic (delegates to GoalManager/ProjectManager).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user
from api.models import GoalCreateRequest, ProjectCreateRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["goals"])


def _get_goal_manager() -> Any:
    """Lazy-import and return the global GoalManager."""
    from api.app import get_goal_manager

    return get_goal_manager()


def _get_project_manager() -> Any:
    """Lazy-import and return the global ProjectManager."""
    from api.app import get_project_manager

    return get_project_manager()


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


@router.get("/api/goals")
async def list_goals(
    user: dict[str, Any] = Depends(get_current_user),
    goal_manager: Any = Depends(_get_goal_manager),
) -> dict[str, Any]:
    """List all active goals with progress."""
    if goal_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Goal system not available",
        )

    try:
        goals = goal_manager.list_active_goals()
        result = []
        for g in goals:
            progress = {}
            if g.id is not None:
                try:
                    progress = goal_manager._store.get_progress(g.id)
                except Exception:
                    progress = {}
            result.append(
                {
                    "id": g.id,
                    "title": g.title,
                    "description": g.description,
                    "status": g.status,
                    "priority": g.priority,
                    "progress": progress,
                }
            )
        return {"goals": result, "total": len(result)}
    except Exception as exc:
        logger.error("Failed to list goals: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list goals: {exc}",
        )


@router.post("/api/goals", status_code=status.HTTP_201_CREATED)
async def create_goal(
    request: GoalCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
    goal_manager: Any = Depends(_get_goal_manager),
) -> dict[str, Any]:
    """Create a new goal."""
    if goal_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Goal system not available",
        )

    try:
        goal = goal_manager.create_goal(
            title=request.title,
            description=request.description,
            priority=request.priority,
        )
        return {
            "id": goal.id,
            "title": goal.title,
            "description": goal.description,
            "status": goal.status,
            "priority": goal.priority,
        }
    except Exception as exc:
        logger.error("Failed to create goal: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create goal: {exc}",
        )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/api/projects")
async def list_projects(
    user: dict[str, Any] = Depends(get_current_user),
    project_manager: Any = Depends(_get_project_manager),
) -> dict[str, Any]:
    """List all projects."""
    if project_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project system not available",
        )

    try:
        projects = project_manager.list_projects()
        return {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "status": p.status,
                    "goal_id": p.goal_id,
                }
                for p in projects
            ],
            "total": len(projects),
        }
    except Exception as exc:
        logger.error("Failed to list projects: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list projects: {exc}",
        )


@router.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    user: dict[str, Any] = Depends(get_current_user),
    project_manager: Any = Depends(_get_project_manager),
) -> dict[str, Any]:
    """Get project status with tasks."""
    if project_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project system not available",
        )

    try:
        project = project_manager.get_project(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )

        tasks = []
        if project.id is not None:
            try:
                tasks = project_manager.list_tasks(project.id)
            except Exception:
                tasks = []

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "goal_id": project.goal_id,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "assigned_to": t.assigned_to,
                }
                for t in tasks
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get project: {exc}",
        )


@router.post("/api/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
    project_manager: Any = Depends(_get_project_manager),
) -> dict[str, Any]:
    """Create a new project."""
    if project_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project system not available",
        )

    try:
        project = project_manager.create_project(
            name=request.name,
            description=request.description,
            status=request.status,
        )
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
        }
    except Exception as exc:
        logger.error("Failed to create project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create project: {exc}",
        )
