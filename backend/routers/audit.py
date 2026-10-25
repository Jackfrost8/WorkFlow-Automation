import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.database import get_db
from backend.models.audit import AuditLog
from backend.models.user import User, UserRole
from backend.services.audit_service import query_audit_logs, verify_audit_hash_chain

router = APIRouter(prefix="/audit-logs", tags=["Audit Log & Governance"])


@router.get(
    "",
    summary="Query centralized append-only audit trail",
    status_code=status.HTTP_200_OK,
)
def list_audit_logs(
    action: Optional[str] = Query(default=None, description="Filter by event action name"),
    resource_type: Optional[str] = Query(default=None, description="Filter by entity resource type"),
    resource_id: Optional[str] = Query(default=None, description="Filter by resource ID"),
    user_id: Optional[int] = Query(default=None, description="Filter by actor user ID"),
    start_date: Optional[str] = Query(default=None, description="Filter from date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="Filter to date (YYYY-MM-DD)"),
    search: Optional[str] = Query(default=None, description="Search query across action, entity, details"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.BUREAU_OFFICER])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    List audit records with cryptographic hash chain details.
    Restricted to Admin and Bureau Officer roles. Non-authorized roles are rejected with 403 Forbidden.
    """
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid start_date format. Expected YYYY-MM-DD.",
            )
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid end_date format. Expected YYYY-MM-DD.",
            )

    logs, total_count = query_audit_logs(
        db=db,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        start_date=start_dt,
        end_date=end_dt,
        search=search,
        skip=skip,
        limit=limit,
    )

    formatted = []
    for log in logs:
        details_obj = {}
        if log.details_json:
            try:
                details_obj = json.loads(log.details_json)
            except Exception:
                details_obj = {"raw": log.details_json}

        formatted.append(
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "user_id": log.user_id,
                "actor_email": log.actor.email if log.actor else None,
                "actor_name": log.actor.full_name if log.actor else None,
                "actor_role": log.actor.role.value if log.actor else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "ip_address": log.ip_address,
                "details": details_obj,
                "prev_hash": log.prev_hash,
                "curr_hash": log.curr_hash,
            }
        )

    return {
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "logs": formatted,
    }


@router.get(
    "/verify-chain",
    summary="Verify cryptographic SHA-256 hash chaining integrity",
    status_code=status.HTTP_200_OK,
)
def verify_chain(
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.BUREAU_OFFICER])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Validate that no audit records have been tampered with or removed.
    Computes and cross-checks every link in the cryptographic SHA-256 chain from genesis.
    """
    verification = verify_audit_hash_chain(db)
    return verification


@router.get(
    "/{log_id}",
    summary="Get single audit entry by ID",
    status_code=status.HTTP_200_OK,
)
def get_audit_log(
    log_id: int,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.BUREAU_OFFICER])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve single audit log entry by ID."""
    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log #{log_id} not found",
        )

    details_obj = {}
    if log.details_json:
        try:
            details_obj = json.loads(log.details_json)
        except Exception:
            details_obj = {"raw": log.details_json}

    return {
        "id": log.id,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        "user_id": log.user_id,
        "actor_email": log.actor.email if log.actor else None,
        "actor_name": log.actor.full_name if log.actor else None,
        "actor_role": log.actor.role.value if log.actor else None,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "ip_address": log.ip_address,
        "details": details_obj,
        "prev_hash": log.prev_hash,
        "curr_hash": log.curr_hash,
    }


# =====================================================================
# IMMUTABILITY & APPEND-ONLY ENFORCEMENT ENDPOINTS
# =====================================================================


@router.put(
    "/{log_id}",
    summary="Reject update operations on audit log (Immutable)",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
)
def reject_audit_update(log_id: int):
    """Explicitly prohibit update operations on audit records."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit records are immutable and append-only. Modification and deletion are strictly prohibited.",
    )


@router.patch(
    "/{log_id}",
    summary="Reject partial update operations on audit log (Immutable)",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
)
def reject_audit_patch(log_id: int):
    """Explicitly prohibit patch operations on audit records."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit records are immutable and append-only. Modification and deletion are strictly prohibited.",
    )


@router.delete(
    "/{log_id}",
    summary="Reject deletion operations on audit log (Immutable)",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
)
def reject_audit_delete(log_id: int):
    """Explicitly prohibit delete operations on audit records."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit records are immutable and append-only. Modification and deletion are strictly prohibited.",
    )


@router.delete(
    "",
    summary="Reject bulk deletion operations on audit log (Immutable)",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
)
def reject_audit_bulk_delete():
    """Explicitly prohibit bulk deletion of audit records."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit records are immutable and append-only. Modification and deletion are strictly prohibited.",
    )
