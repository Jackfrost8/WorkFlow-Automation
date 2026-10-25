from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.database import get_db
from backend.models.application import Application, ApplicationStatus
from backend.models.user import Institution, User, UserRole
from backend.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    CompleteStageRequest,
    ReturnStageRequest,
)
from backend.services.workflow_engine import complete_stage, return_application, submit_application

router = APIRouter(prefix="/applications", tags=["Applications & Workflow Engine"])


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new institutional approval application",
)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationResponse:
    """
    Submit application and initialize workflow route.
    Restricted to INSTITUTION accounts (or ADMIN).
    """
    if current_user.role not in [UserRole.INSTITUTION, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only registered institutions or administrators can submit applications",
        )

    if current_user.role == UserRole.INSTITUTION:
        if not current_user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User account is not linked to an active institution record",
            )
        institution_id = current_user.institution_id
    else:
        # Admin submitting: take first institution or create test
        first_inst = db.query(Institution).first()
        if not first_inst:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No institutions exist to associate with this application",
            )
        institution_id = first_inst.id

    app = submit_application(
        db=db,
        institution_id=institution_id,
        user_id=current_user.id,
        route_type=payload.route_type,
        title=payload.title,
        description=payload.description,
        academic_year=payload.academic_year,
    )
    return ApplicationResponse.model_validate(app)


@router.get(
    "",
    response_model=List[ApplicationResponse],
    summary="List applications with role-based scoping",
)
def list_applications(
    status_filter: Optional[ApplicationStatus] = Query(default=None, alias="status"),
    route_type: Optional[str] = Query(default=None),
    region: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[ApplicationResponse]:
    """
    Retrieve applications based on authenticated user's role:
    - INSTITUTION: Own applications only.
    - REGIONAL_OFFICER: Applications within assigned region.
    - BUREAU_OFFICER & ADMIN: Cross-region access.
    """
    query = db.query(Application).join(Institution, Application.institution_id == Institution.id)

    # 1. Role-based scoping
    if current_user.role == UserRole.INSTITUTION:
        query = query.filter(Application.institution_id == current_user.institution_id)
    elif current_user.role == UserRole.REGIONAL_OFFICER:
        if current_user.region:
            query = query.filter(Institution.region == current_user.region)
    # Bureau Officer & Admin can see all, with optional region filtering
    if region and current_user.role in [UserRole.BUREAU_OFFICER, UserRole.ADMIN]:
        query = query.filter(Institution.region == region)

    # 2. General filters
    if status_filter:
        query = query.filter(Application.status == status_filter)
    if route_type:
        query = query.filter(Application.route_type == route_type)

    applications = query.order_by(Application.created_at.desc()).offset(skip).limit(limit).all()
    return [ApplicationResponse.model_validate(a) for a in applications]


@router.get(
    "/{application_id}",
    response_model=ApplicationResponse,
    summary="Get application details, stages, and history",
)
def get_application_by_id(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationResponse:
    """Retrieve full application details subject to ownership and regional rules."""
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application ID {application_id} not found",
        )

    # Ownership check for institutions
    if current_user.role == UserRole.INSTITUTION:
        if app.institution_id != current_user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: you do not have permission to view this application",
            )

    # Regional check for regional officers
    if current_user.role == UserRole.REGIONAL_OFFICER:
        if app.institution.region != current_user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Application belongs to {app.institution.region}, not {current_user.region}",
            )

    return ApplicationResponse.model_validate(app)


@router.post(
    "/{application_id}/complete-stage",
    response_model=ApplicationResponse,
    summary="Complete current stage and advance application, or approve/reject at decision stage",
)
def complete_application_stage(
    application_id: int,
    payload: CompleteStageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> ApplicationResponse:
    """Advance stage or finalize approval/rejection decision (Officers and Admin only)."""
    app = complete_stage(
        db=db,
        application_id=application_id,
        user=current_user,
        remarks=payload.remarks,
        decision=payload.decision,
        expected_stage_id=payload.expected_stage_id,
    )
    return ApplicationResponse.model_validate(app)


@router.post(
    "/{application_id}/return",
    response_model=ApplicationResponse,
    summary="Return application with deficiencies/remarks",
)
def return_application_stage(
    application_id: int,
    payload: ReturnStageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> ApplicationResponse:
    """Return an application to previous stage or applicant for remediation (Officers and Admin only)."""
    app = return_application(
        db=db,
        application_id=application_id,
        user=current_user,
        reason=payload.reason,
    )
    return ApplicationResponse.model_validate(app)
