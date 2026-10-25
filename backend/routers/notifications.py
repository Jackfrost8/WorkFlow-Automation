from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.database import get_db
from backend.models.notification import (
    DeadlineRule,
    EscalationRecord,
    Notification,
    TrackableEntityType,
)
from backend.models.user import User, UserRole
from backend.schemas.notification import (
    DeadlineRuleResponse,
    DeadlineRuleUpdateRequest,
    EscalationRecordResponse,
    NotificationMarkReadRequest,
    NotificationResponse,
)
from backend.services.audit_service import log_audit_event
from backend.services.deadline_service import check_all_deadlines, ensure_default_deadline_rules

router = APIRouter(prefix="/notifications", tags=["Notifications & Escalations"])


@router.get(
    "",
    response_model=List[NotificationResponse],
    summary="List current user's in-app notifications",
)
def list_user_notifications(
    is_read: Optional[bool] = Query(default=None, description="Filter by read status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve in-app notifications for the authenticated user.
    Guarantees privacy: No user can view another user's notifications.
    """
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)
    return query.order_by(Notification.id.desc()).all()


@router.get(
    "/unread-count",
    summary="Get count of unread notifications for current user",
)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return count of unread notifications for navbar badges."""
    count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .count()
    )
    return {"unread_count": count}


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark specific notification as read",
)
def mark_notification_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a notification as read. Enforces strict ownership."""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    if notification.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot mark another user's notification as read.",
        )

    notification.is_read = True
    notification.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(notification)
    return notification


@router.post(
    "/mark-all-read",
    summary="Mark all unread notifications as read",
)
def mark_all_as_read(
    payload: Optional[NotificationMarkReadRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all or selected unread notifications for current user as read."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    )
    if payload and payload.notification_ids:
        query = query.filter(Notification.id.in_(payload.notification_ids))

    now_utc = datetime.now(timezone.utc)
    updated_count = query.update(
        {Notification.is_read: True, Notification.read_at: now_utc},
        synchronize_session=False,
    )
    db.commit()
    return {"message": f"Marked {updated_count} notification(s) as read."}


@router.get(
    "/escalations",
    response_model=List[EscalationRecordResponse],
    summary="List SLA escalation records",
)
def list_escalations(
    current_user: User = Depends(
        require_roles(UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN)
    ),
    db: Session = Depends(get_db),
):
    """List SLA escalations for authorized officers and administrators."""
    query = db.query(EscalationRecord)
    if current_user.role == UserRole.REGIONAL_OFFICER:
        query = query.filter(EscalationRecord.recipient_user_id == current_user.id)
    return query.order_by(EscalationRecord.id.desc()).all()


@router.get(
    "/rules",
    response_model=List[DeadlineRuleResponse],
    summary="List configurable deadline and escalation rules",
)
def list_deadline_rules(
    current_user: User = Depends(require_roles(UserRole.BUREAU_OFFICER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """List all configurable deadline rules."""
    ensure_default_deadline_rules(db)
    return db.query(DeadlineRule).order_by(DeadlineRule.id.asc()).all()


@router.patch(
    "/rules/{rule_id}",
    response_model=DeadlineRuleResponse,
    summary="Update deadline rule configuration",
)
def update_deadline_rule(
    rule_id: int,
    payload: DeadlineRuleUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Administrator updates deadline rule thresholds or status."""
    rule = db.query(DeadlineRule).filter(DeadlineRule.id == rule_id).first()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deadline rule not found.",
        )

    changes = {}
    if payload.reminder_threshold_days is not None:
        changes["reminder_threshold_days"] = {
            "old": rule.reminder_threshold_days,
            "new": payload.reminder_threshold_days,
        }
        rule.reminder_threshold_days = payload.reminder_threshold_days
    if payload.escalation_threshold_days is not None:
        changes["escalation_threshold_days"] = {
            "old": rule.escalation_threshold_days,
            "new": payload.escalation_threshold_days,
        }
        rule.escalation_threshold_days = payload.escalation_threshold_days
    if payload.escalation_recipient_role is not None:
        changes["escalation_recipient_role"] = {
            "old": rule.escalation_recipient_role.value if rule.escalation_recipient_role else None,
            "new": payload.escalation_recipient_role.value if payload.escalation_recipient_role else None,
        }
        rule.escalation_recipient_role = payload.escalation_recipient_role
    if payload.is_active is not None:
        changes["is_active"] = {"old": rule.is_active, "new": payload.is_active}
        rule.is_active = payload.is_active
    if payload.description is not None:
        changes["description"] = {"old": rule.description, "new": payload.description}
        rule.description = payload.description

    if changes:
        log_audit_event(
            db=db,
            action="DEADLINE_RULE_UPDATED",
            resource_type="DEADLINE_RULE",
            resource_id=str(rule.id),
            user_id=current_user.id,
            details={"rule_id": rule.id, "entity_type": rule.entity_type.value, "changes": changes},
        )

    db.commit()
    db.refresh(rule)
    return rule


@router.post(
    "/run-deadline-check",
    summary="Trigger deadline evaluation cycle manually",
)
def trigger_deadline_check(
    current_user: User = Depends(require_roles(UserRole.BUREAU_OFFICER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Manually invoke the deadline evaluation cycle."""
    results = check_all_deadlines(db)
    return {
        "status": "success",
        "message": "Deadline and SLA escalation evaluation cycle completed.",
        "results": results,
    }
