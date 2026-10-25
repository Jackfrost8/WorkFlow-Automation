from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.core.time_service import (
    advance_simulated_time,
    get_simulated_time_status,
    reset_simulated_time,
)
from backend.database import get_db
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
