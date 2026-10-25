from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationStageHistory, ApplicationStatus
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.user import Institution, User, UserRole
from backend.models.workflow import WorkflowRoute, WorkflowStage
from backend.services.audit_service import log_audit_event
from backend.core.time_service import get_effective_time
from backend.workflow.config import ensure_default_workflow_routes


def generate_application_number(db: Session, institution: Institution) -> str:
    """Generate a readable, unique AICTE application identifier."""
    year = datetime.now(timezone.utc).year
    count = db.query(Application).count() + 1
    region_code = "".join(filter(str.isalnum, institution.region)).upper()[:5] or "DEL"
    return f"AICTE/{year}/{region_code}/{count:05d}"


def submit_application(
    db: Session,
    institution_id: int,
    user_id: int,
    route_type: str,
    title: str,
    description: Optional[str] = None,
    academic_year: str = "2026-2027",
) -> Application:
    """
    Submit a new institutional application, assign initial stage, calculate SLA deadline,
    and initialize stage history within an atomic database transaction.
    """
    ensure_default_workflow_routes(db)

    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution ID {institution_id} not found",
        )

    route = db.query(WorkflowRoute).filter(WorkflowRoute.code == route_type).first()
    if not route or not route.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow route '{route_type}' is invalid or inactive",
        )

    first_stage = (
        db.query(WorkflowStage)
        .filter(WorkflowStage.route_id == route.id, WorkflowStage.order_index == 1)
        .first()
    )
    if not first_stage:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route '{route_type}' has no initial stage configured",
        )

    now = get_effective_time(db)
    stage_deadline = now + timedelta(days=first_stage.sla_days)
    app_number = generate_application_number(db, institution)

    application = Application(
        application_number=app_number,
        institution_id=institution.id,
        route_id=route.id,
        route_type=route.code,
        current_stage_id=first_stage.id,
        status=ApplicationStatus.SUBMITTED,
        academic_year=academic_year,
        title=title.strip(),
        description=description.strip() if description else None,
        submission_date=now,
        current_stage_deadline=stage_deadline,
    )
    db.add(application)
    db.flush()

    # Create initial stage history entry
    initial_history = ApplicationStageHistory(
        application_id=application.id,
        stage_id=first_stage.id,
        from_stage_id=None,
        to_stage_id=first_stage.id,
        action="SUBMIT",
        remarks="Application submitted by institution",
        actor_user_id=user_id,
        entered_at=now,
        deadline_at=stage_deadline,
        was_overdue=False,
    )
    db.add(initial_history)

    # Automatic EVC visit creation if the first stage is EVC
    if first_stage.is_evc_stage:
        evc_visit = EVCVisit(
            application_id=application.id,
            due_date=stage_deadline,
            status=EVCStatus.PENDING_SCHEDULE,
            visit_mode="PHYSICAL",
        )
        db.add(evc_visit)

    # Audit integration
    log_audit_event(
        db=db,
        action="APPLICATION_SUBMITTED",
        resource_type="APPLICATION",
        resource_id=str(application.id),
        user_id=user_id,
        details={
            "application_number": app_number,
            "route_type": route_type,
            "initial_stage": first_stage.stage_key,
            "institution": institution.name,
        },
    )

    db.commit()
    db.refresh(application)
    return application


def complete_stage(
    db: Session,
    application_id: int,
    user: User,
    remarks: Optional[str] = None,
    decision: Optional[str] = None,
    expected_stage_id: Optional[int] = None,
) -> Application:
    """
    Advance an application from its current stage to the next valid stage,
    or record final approval/rejection decision.
    """
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application ID {application_id} not found",
        )

    # Concurrency / repeated request check
    if expected_stage_id and application.current_stage_id != expected_stage_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application stage has already transitioned or changed",
        )

    # Terminal state check
    if application.status in [ApplicationStatus.APPROVED, ApplicationStatus.REJECTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application is already finalized with status: {application.status.value}",
        )

    # Regional officer boundary enforcement
    if user.role == UserRole.REGIONAL_OFFICER:
        if application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {application.institution.region}, not {user.region}",
            )

    curr_stage = application.current_stage
    if not curr_stage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application has no active stage assigned",
        )

    # Role authorization check for stage
    allowed_roles = [r.strip() for r in curr_stage.authorized_roles.split(",")]
    if user.role.value not in allowed_roles and user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' is not authorized to process stage '{curr_stage.name}'",
        )

    now = get_effective_time(db)

    # Find the current active stage history entry
    active_history = (
        db.query(ApplicationStageHistory)
        .filter(
            ApplicationStageHistory.application_id == application.id,
            ApplicationStageHistory.exited_at.is_(None),
        )
        .order_by(ApplicationStageHistory.id.desc())
        .first()
    )

    # CASE A: Final Decision Stage
    if curr_stage.is_final:
        if not decision or decision.upper() not in ["APPROVE", "REJECT"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Final decision requires an explicit decision parameter: 'APPROVE' or 'REJECT'",
            )

        decision_upper = decision.upper()
        application.status = (
            ApplicationStatus.APPROVED if decision_upper == "APPROVE" else ApplicationStatus.REJECTED
        )
        application.final_decision_date = now
        application.final_decision_by_user_id = user.id
        application.final_decision_remarks = remarks.strip() if remarks else None

        if active_history:
            active_history.exited_at = now
            active_history.action = decision_upper
            active_history.remarks = remarks
            active_history.actor_user_id = user.id

        log_audit_event(
            db=db,
            action="FINAL_DECISION_RECORDED",
            resource_type="APPLICATION",
            resource_id=str(application.id),
            user_id=user.id,
            details={
                "decision": decision_upper,
                "stage": curr_stage.stage_key,
                "remarks": remarks,
            },
        )

        db.commit()
        db.refresh(application)
        return application

    # CASE B: Intermediate Stage Transition
    next_stage = (
        db.query(WorkflowStage)
        .filter(
            WorkflowStage.route_id == application.route_id,
            WorkflowStage.order_index == curr_stage.order_index + 1,
        )
        .first()
    )
    if not next_stage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No subsequent stage defined after '{curr_stage.name}' in route",
        )

    # Close active history entry
    if active_history:
        active_history.exited_at = now
        active_history.action = "STAGE_COMPLETED"
        active_history.remarks = remarks
        active_history.actor_user_id = user.id

    # Advance stage
    next_deadline = now + timedelta(days=next_stage.sla_days)
    application.current_stage_id = next_stage.id
    application.status = ApplicationStatus.IN_REVIEW
    application.current_stage_deadline = next_deadline

    # Create next history entry
    new_history = ApplicationStageHistory(
        application_id=application.id,
        stage_id=next_stage.id,
        from_stage_id=curr_stage.id,
        to_stage_id=next_stage.id,
        action="STAGE_ENTERED",
        remarks=f"Advanced from {curr_stage.name}",
        actor_user_id=user.id,
        entered_at=now,
        deadline_at=next_deadline,
        was_overdue=False,
    )
    db.add(new_history)

    # Automatic EVC record creation upon entering EVC
    if next_stage.is_evc_stage:
        existing_evc = db.query(EVCVisit).filter(EVCVisit.application_id == application.id).first()
        if not existing_evc:
            db.add(
                EVCVisit(
                    application_id=application.id,
                    due_date=next_deadline,
                    status=EVCStatus.PENDING_SCHEDULE,
                    visit_mode="PHYSICAL",
                )
            )

    log_audit_event(
        db=db,
        action="STAGE_COMPLETED",
        resource_type="APPLICATION",
        resource_id=str(application.id),
        user_id=user.id,
        details={
            "completed_stage": curr_stage.stage_key,
            "next_stage": next_stage.stage_key,
            "remarks": remarks,
        },
    )

    db.commit()
    db.refresh(application)
    return application


def return_application(
    db: Session,
    application_id: int,
    user: User,
    reason: str,
) -> Application:
    """
    Return an application with a mandatory reason.
    - If at first stage, sets status to ACTION_REQUIRED for applicant remediation.
    - If at subsequent stage, moves back to preceding stage with ACTION_REQUIRED status.
    """
    if not reason or len(reason.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A substantive return reason (minimum 3 characters) is required",
        )

    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application ID {application_id} not found",
        )

    if application.status in [ApplicationStatus.APPROVED, ApplicationStatus.REJECTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot return an already finalized application ({application.status.value})",
        )

    # Regional officer boundary enforcement
    if user.role == UserRole.REGIONAL_OFFICER:
        if application.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {application.institution.region}, not {user.region}",
            )

    curr_stage = application.current_stage
    now = get_effective_time(db)

    # Close active history entry
    active_history = (
        db.query(ApplicationStageHistory)
        .filter(
            ApplicationStageHistory.application_id == application.id,
            ApplicationStageHistory.exited_at.is_(None),
        )
        .order_by(ApplicationStageHistory.id.desc())
        .first()
    )
    if active_history:
        active_history.exited_at = now
        active_history.action = "RETURN"
        active_history.remarks = reason.strip()
        active_history.actor_user_id = user.id

    if curr_stage.order_index > 1:
        # Move back to previous stage
        prev_stage = (
            db.query(WorkflowStage)
            .filter(
                WorkflowStage.route_id == application.route_id,
                WorkflowStage.order_index == curr_stage.order_index - 1,
            )
            .first()
        )
        target_stage = prev_stage or curr_stage
    else:
        target_stage = curr_stage

    application.current_stage_id = target_stage.id
    application.status = ApplicationStatus.ACTION_REQUIRED
    application.current_stage_deadline = now + timedelta(days=target_stage.sla_days)

    return_history = ApplicationStageHistory(
        application_id=application.id,
        stage_id=target_stage.id,
        from_stage_id=curr_stage.id,
        to_stage_id=target_stage.id,
        action="RETURNED_TO_STAGE" if curr_stage.order_index > 1 else "RETURNED_TO_APPLICANT",
        remarks=reason.strip(),
        actor_user_id=user.id,
        entered_at=now,
        deadline_at=application.current_stage_deadline,
        was_overdue=False,
    )
    db.add(return_history)

    log_audit_event(
        db=db,
        action="APPLICATION_RETURNED",
        resource_type="APPLICATION",
        resource_id=str(application.id),
        user_id=user.id,
        details={
            "from_stage": curr_stage.stage_key,
            "to_stage": target_stage.stage_key,
            "reason": reason.strip(),
        },
    )

    db.commit()
    db.refresh(application)
    return application
