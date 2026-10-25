import json
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.evc import EVCRecommendation, EVCStatus, EVCVisit
from backend.models.user import Institution, User, UserRole
from backend.schemas.evc import (
    EVCCompleteRequest,
    EVCRescheduleRequest,
    EVCScheduleRequest,
    EVCVisitResponse,
)
from backend.services.audit_service import log_audit_event


def get_evc_visits(
    db: Session,
    user: User,
    status_filter: Optional[str] = None,
    region: Optional[str] = None,
    visit_mode: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[EVCVisitResponse]:
    """Retrieve EVC visits scoped by role and jurisdictional boundaries."""
    query = (
        db.query(EVCVisit)
        .join(Application, EVCVisit.application_id == Application.id)
        .join(Institution, Application.institution_id == Institution.id)
    )

    # 1. Role-based scoping
    if user.role == UserRole.INSTITUTION:
        query = query.filter(Application.institution_id == user.institution_id)
    elif user.role == UserRole.REGIONAL_OFFICER:
        if user.region:
            query = query.filter(Institution.region == user.region)

    # Cross-region filtering for Bureau / Admin
    if region and user.role in [UserRole.BUREAU_OFFICER, UserRole.ADMIN]:
        query = query.filter(Institution.region == region)

    if visit_mode:
        query = query.filter(EVCVisit.visit_mode == visit_mode)

    # 2. Status filtering (supporting 'DELAYED' pseudo-status)
    now = datetime.now(timezone.utc)
    if status_filter:
        if status_filter.upper() == "DELAYED":
            query = query.filter(
                EVCVisit.status.in_([EVCStatus.PENDING_SCHEDULE, EVCStatus.SCHEDULED]),
                EVCVisit.due_date.isnot(None),
                EVCVisit.due_date < now,
            )
        else:
            query = query.filter(EVCVisit.status == status_filter)

    visits = query.order_by(EVCVisit.created_at.desc()).offset(skip).limit(limit).all()
    return [EVCVisitResponse.from_orm_visit(v) for v in visits]


def get_evc_visit_by_id(
    db: Session,
    visit_id: int,
    user: User,
) -> EVCVisitResponse:
    """Retrieve details for a specific EVC visit record with authorization checks."""
    visit = db.query(EVCVisit).filter(EVCVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EVC Visit ID {visit_id} not found",
        )

    # Access control
    if user.role == UserRole.INSTITUTION:
        if visit.application.institution_id != user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: you do not own the application for this inspection",
            )
    elif user.role == UserRole.REGIONAL_OFFICER:
        if visit.application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Visit belongs to {visit.application.institution.region}, not {user.region}",
            )

    return EVCVisitResponse.from_orm_visit(visit)


def schedule_evc_visit(
    db: Session,
    visit_id: int,
    user: User,
    payload: EVCScheduleRequest,
) -> EVCVisitResponse:
    """
    Schedule an EVC inspection visit.
    Restricted to authorized officers within their regional jurisdiction.
    """
    visit = db.query(EVCVisit).filter(EVCVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EVC Visit ID {visit_id} not found",
        )

    # Role & Regional check
    if user.role == UserRole.INSTITUTION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institutions are not permitted to schedule EVC inspections",
        )
    if user.role == UserRole.REGIONAL_OFFICER:
        if visit.application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {visit.application.institution.region}",
            )

    # Status check
    if visit.status in [EVCStatus.COMPLETED, EVCStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot schedule inspection for visit with status '{visit.status.value}'",
        )

    visit.scheduled_date = payload.scheduled_date
    visit.committee_lead_name = payload.committee_lead_name.strip()
    visit.committee_members_json = json.dumps(payload.committee_members or [])
    visit.visit_mode = payload.visit_mode
    visit.officer_remarks = payload.remarks
    visit.status = EVCStatus.SCHEDULED

    log_audit_event(
        db=db,
        action="EVC_VISIT_SCHEDULED",
        resource_type="EVC_VISIT",
        resource_id=str(visit.id),
        user_id=user.id,
        details={
            "application_id": visit.application_id,
            "scheduled_date": payload.scheduled_date.isoformat(),
            "committee_lead": payload.committee_lead_name,
            "visit_mode": payload.visit_mode,
        },
    )

    db.commit()
    db.refresh(visit)
    return EVCVisitResponse.from_orm_visit(visit)


def reschedule_evc_visit(
    db: Session,
    visit_id: int,
    user: User,
    payload: EVCRescheduleRequest,
) -> EVCVisitResponse:
    """Reschedule an existing EVC visit with documented justification."""
    visit = db.query(EVCVisit).filter(EVCVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EVC Visit ID {visit_id} not found",
        )

    if user.role == UserRole.INSTITUTION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institutions are not permitted to reschedule EVC inspections",
        )
    if user.role == UserRole.REGIONAL_OFFICER:
        if visit.application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {visit.application.institution.region}",
            )

    if visit.status in [EVCStatus.COMPLETED, EVCStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reschedule visit in terminal status '{visit.status.value}'",
        )

    old_date = visit.scheduled_date.isoformat() if visit.scheduled_date else "Unscheduled"
    visit.scheduled_date = payload.new_scheduled_date
    visit.rescheduled_count += 1
    visit.officer_remarks = f"Rescheduled: {payload.reason.strip()}. {payload.remarks or ''}".strip()
    visit.status = EVCStatus.SCHEDULED

    log_audit_event(
        db=db,
        action="EVC_VISIT_RESCHEDULED",
        resource_type="EVC_VISIT",
        resource_id=str(visit.id),
        user_id=user.id,
        details={
            "application_id": visit.application_id,
            "previous_date": old_date,
            "new_date": payload.new_scheduled_date.isoformat(),
            "reason": payload.reason.strip(),
            "rescheduled_count": visit.rescheduled_count,
        },
    )

    db.commit()
    db.refresh(visit)
    return EVCVisitResponse.from_orm_visit(visit)


def complete_evc_visit(
    db: Session,
    visit_id: int,
    user: User,
    payload: EVCCompleteRequest,
) -> EVCVisitResponse:
    """Record completion of EVC inspection along with findings and recommendations."""
    visit = db.query(EVCVisit).filter(EVCVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EVC Visit ID {visit_id} not found",
        )

    if user.role == UserRole.INSTITUTION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institutions cannot record completion of inspections",
        )
    if user.role == UserRole.REGIONAL_OFFICER:
        if visit.application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {visit.application.institution.region}",
            )

    if visit.status in [EVCStatus.COMPLETED, EVCStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Visit is already in status '{visit.status.value}'",
        )

    now = datetime.now(timezone.utc)
    visit.conducted_date = payload.conducted_date or now
    visit.recommendation = payload.recommendation
    visit.deficiencies = payload.deficiencies.strip() if payload.deficiencies else None
    visit.remarks = payload.remarks.strip() if payload.remarks else None
    visit.report_file_path = payload.report_file_path
    visit.status = EVCStatus.COMPLETED

    log_audit_event(
        db=db,
        action="EVC_VISIT_COMPLETED",
        resource_type="EVC_VISIT",
        resource_id=str(visit.id),
        user_id=user.id,
        details={
            "application_id": visit.application_id,
            "recommendation": payload.recommendation.value,
            "conducted_date": visit.conducted_date.isoformat(),
            "has_deficiencies": bool(payload.deficiencies),
        },
    )

    db.commit()
    db.refresh(visit)
    return EVCVisitResponse.from_orm_visit(visit)


def cancel_evc_visit(
    db: Session,
    visit_id: int,
    user: User,
    reason: str,
) -> EVCVisitResponse:
    """Cancel a scheduled or pending EVC visit."""
    visit = db.query(EVCVisit).filter(EVCVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EVC Visit ID {visit_id} not found",
        )

    if user.role == UserRole.INSTITUTION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Institutions cannot cancel EVC visits",
        )
    if user.role == UserRole.REGIONAL_OFFICER:
        if visit.application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {visit.application.institution.region}",
            )

    if visit.status == EVCStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel an already completed EVC visit",
        )

    visit.status = EVCStatus.CANCELLED
    visit.remarks = f"Cancelled: {reason.strip()}"

    log_audit_event(
        db=db,
        action="EVC_VISIT_CANCELLED",
        resource_type="EVC_VISIT",
        resource_id=str(visit.id),
        user_id=user.id,
        details={
            "application_id": visit.application_id,
            "reason": reason.strip(),
        },
    )

    db.commit()
    db.refresh(visit)
    return EVCVisitResponse.from_orm_visit(visit)
