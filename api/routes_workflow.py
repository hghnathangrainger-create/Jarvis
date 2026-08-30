"""
routes_workflow.py

Workflow endpoints for the Jarvis API.

Responsibilities:
    - GET  /api/workflows — list active workflows.
    - GET  /api/workflows/{id} — get workflow status with step details.
    - POST /api/workflows/{id}/approve — approve a pending YELLOW/RED step.
    - POST /api/workflows/{id}/cancel — cancel a running workflow.

Does NOT:
    - Implement workflow execution (delegates to WorkflowEngine/Orchestrator).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user
from api.models import ApprovalRequest, WorkflowStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _get_orchestrator() -> Any:
    """Lazy-import and return the global orchestrator."""
    from api.app import get_orchestrator

    return get_orchestrator()


@router.get("")
async def list_workflows(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List active (paused) workflows."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        return {"workflows": []}

    try:
        approvals = orchestrator.approvals
        pending = approvals.list_pending() if hasattr(approvals, "list_pending") else []
        return {
            "workflows": [
                {
                    "request_id": getattr(r, "request_id", ""),
                    "action": getattr(r, "action", ""),
                    "status": "pending",
                }
                for r in pending
            ],
            "total": len(pending),
        }
    except Exception as exc:
        logger.error("Failed to list workflows: %s", exc)
        return {"workflows": [], "total": 0, "error": str(exc)}


@router.get("/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow(
    workflow_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> WorkflowStatusResponse:
    """Get workflow status with step details."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator not available",
        )

    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        steps=[],
        status="unknown",
        progress_pct=0.0,
    )


@router.post("/{workflow_id}/approve")
async def approve_workflow(
    workflow_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Approve a pending workflow step."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator not available",
        )

    try:
        approvals = orchestrator.approvals
        if hasattr(approvals, "approve"):
            from approval.approval_models import ApprovalDecision

            decision = ApprovalDecision(
                request_id=workflow_id,
                approved=True,
                decided_by="api_user",
            )
            approvals.approve(decision)
            return {"status": "approved", "workflow_id": workflow_id}
        return {"status": "not_found", "workflow_id": workflow_id}
    except Exception as exc:
        logger.error("Failed to approve workflow: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve: {exc}",
        )


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a running workflow."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator not available",
        )

    try:
        approvals = orchestrator.approvals
        if hasattr(approvals, "decline"):
            from approval.approval_models import ApprovalDecision

            decision = ApprovalDecision(
                request_id=workflow_id,
                approved=False,
                decided_by="api_user",
            )
            approvals.decline(decision)
            return {"status": "cancelled", "workflow_id": workflow_id}
        return {"status": "not_found", "workflow_id": workflow_id}
    except Exception as exc:
        logger.error("Failed to cancel workflow: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel: {exc}",
        )
