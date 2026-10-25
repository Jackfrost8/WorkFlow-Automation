from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.core.time_service import (
    advance_simulated_time,
    get_simulated_time_status,
    reset_simulated_time,
)
from backend.database import get_db
from backend.models.audit import AuditLog
from backend.models.user import User, UserRole
from backend.schemas.admin_time import (
    AdvanceTimeRequest,
    AdvanceTimeResponse,
    SimulatedTimeStatusResponse,
)

router = APIRouter(prefix="/admin", tags=["Administrator Demo Time Simulation"])


@router.get(
    "/simulated-time",
    response_model=SimulatedTimeStatusResponse,
    summary="Inspect current simulated business date and persistent offset",
)
@router.get(
    "/time",
    response_model=SimulatedTimeStatusResponse,
    include_in_schema=False,
)
def inspect_simulated_time(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Inspect real clock, simulated effective business clock, and active offset.
    Accessible to all authenticated users for synchronized dashboard time display.
    """
    return get_simulated_time_status(db)


@router.post(
    "/advance-time",
    response_model=AdvanceTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Advance simulated business time by a validated number of days",
)
def advance_time_endpoint(
    payload: AdvanceTimeRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Advance application-level persistent demo time offset.
    Only authorized Administrators can advance time.
    Automatically executes the deadline evaluation engine against the new effective date.
    """
    return advance_simulated_time(
        db=db,
        admin_user=current_user,
        days=payload.days,
        run_check=payload.run_deadline_check,
    )


@router.post(
    "/reset-time",
    status_code=status.HTTP_200_OK,
    summary="Reset simulated time offset to zero (re-sync with real UTC time)",
)
def reset_time_endpoint(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Reset simulated time offset to zero, re-synchronizing with the real system clock.
    Only authorized Administrators can reset time.
    """
    return reset_simulated_time(
        db=db,
        admin_user=current_user,
    )


@router.get(
    "/audit-logs",
    summary="List immutable, cryptographically chained audit events",
)
def list_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    action: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.BUREAU_OFFICER)),
    db: Session = Depends(get_db),
):
    """Query append-only cryptographic audit logs with actor and hash verification."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)

    logs = query.order_by(AuditLog.id.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "user_id": log.user_id,
            "actor_email": log.actor.email if log.actor else None,
            "actor_name": log.actor.full_name if log.actor else None,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "ip_address": log.ip_address,
            "details": log.details_json,
            "prev_hash": log.prev_hash,
            "curr_hash": log.curr_hash,
        }
        for log in logs
    ]


@router.get(
    "/workflows",
    summary="List configurable workflow routes, stages, and SLAs",
)
def list_workflow_routes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve all workflow routes and stage SLAs."""
    from backend.models.workflow import WorkflowRoute
    from backend.workflow.config import ensure_default_workflow_routes

    ensure_default_workflow_routes(db)
    routes = db.query(WorkflowRoute).filter(WorkflowRoute.is_active == True).all()
    result = []
    for r in routes:
        stages_data = [
            {
                "id": s.id,
                "stage_key": s.stage_key,
                "name": s.name,
                "order_index": s.order_index,
                "sla_days": s.sla_days,
                "authorized_roles": s.authorized_roles,
                "is_evc_stage": s.is_evc_stage,
                "is_final": s.is_final,
            }
            for s in r.stages
        ]
        result.append({
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "stages": stages_data,
        })
    return result

