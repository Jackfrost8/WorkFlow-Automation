from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.database import get_db
from backend.models.user import User, UserRole
from backend.schemas.evc import (
    EVCCancelRequest,
    EVCCompleteRequest,
    EVCRescheduleRequest,
    EVCScheduleRequest,
    EVCVisitResponse,
)
from backend.services.evc_service import (
    cancel_evc_visit,
    complete_evc_visit,
    get_evc_visit_by_id,
    get_evc_visits,
    reschedule_evc_visit,
    schedule_evc_visit,
)

router = APIRouter(prefix="/evc", tags=["Expert Visit Committee (EVC)"])


@router.get(
    "",
    response_model=List[EVCVisitResponse],
    summary="List EVC visits in queue with status and regional filters",
)
def list_evc_queue(
    status: Optional[str] = Query(default=None, description="Status filter or 'DELAYED'"),
    region: Optional[str] = Query(default=None, description="Region filter for Bureau/Admin"),
    visit_mode: Optional[str] = Query(default=None, description="PHYSICAL or VIRTUAL"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[EVCVisitResponse]:
    """Retrieve EVC inspection queue with role-based access filtering."""
    return get_evc_visits(
        db=db,
        user=current_user,
        status_filter=status,
        region=region,
        visit_mode=visit_mode,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{visit_id}",
    response_model=EVCVisitResponse,
    summary="Get EVC visit inspection details",
)
def get_evc_details(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EVCVisitResponse:
    """Retrieve detailed EVC inspection record subject to access boundaries."""
    return get_evc_visit_by_id(db=db, visit_id=visit_id, user=current_user)


@router.post(
    "/{visit_id}/schedule",
    response_model=EVCVisitResponse,
    summary="Schedule an EVC inspection visit",
)
def schedule_visit(
    visit_id: int,
    payload: EVCScheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> EVCVisitResponse:
    """Schedule inspection date, lead, members and visit mode."""
    return schedule_evc_visit(db=db, visit_id=visit_id, user=current_user, payload=payload)


@router.post(
    "/{visit_id}/reschedule",
    response_model=EVCVisitResponse,
    summary="Reschedule an EVC inspection visit",
)
def reschedule_visit(
    visit_id: int,
    payload: EVCRescheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> EVCVisitResponse:
    """Update scheduled date with documented justification."""
    return reschedule_evc_visit(db=db, visit_id=visit_id, user=current_user, payload=payload)


@router.post(
    "/{visit_id}/complete",
    response_model=EVCVisitResponse,
    summary="Record EVC inspection completion and findings",
)
def complete_visit(
    visit_id: int,
    payload: EVCCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> EVCVisitResponse:
    """Complete inspection and record recommendations and deficiencies."""
    return complete_evc_visit(db=db, visit_id=visit_id, user=current_user, payload=payload)


@router.post(
    "/{visit_id}/cancel",
    response_model=EVCVisitResponse,
    summary="Cancel an EVC inspection",
)
def cancel_visit(
    visit_id: int,
    payload: EVCCancelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN])
    ),
) -> EVCVisitResponse:
    """Cancel pending or scheduled EVC visit."""
    return cancel_evc_visit(db=db, visit_id=visit_id, user=current_user, reason=payload.reason)
