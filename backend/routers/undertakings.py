from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.database import get_db
from backend.models.undertaking import UndertakingStatus
from backend.models.user import User
from backend.schemas.undertaking import (
    UndertakingCreateRequest,
    UndertakingRejectRequest,
    UndertakingResponse,
    UndertakingSubmitEvidenceRequest,
    UndertakingVerifyRequest,
)
from backend.services.undertaking_service import (
    create_undertaking,
    get_undertaking,
    list_undertakings,
    reject_evidence,
    submit_evidence,
    verify_evidence,
)

router = APIRouter(prefix="/undertakings", tags=["Statutory Undertakings & Compliance"])


@router.post(
    "",
    response_model=UndertakingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue an undertaking requirement for an application",
)
def create_undertaking_endpoint(
    payload: UndertakingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Issue a formal statutory undertaking requirement.
    Only authorized officers (REGIONAL_OFFICER for regional application, BUREAU_OFFICER, ADMIN) may create.
    """
    return create_undertaking(
        db=db,
        user=current_user,
        application_id=payload.application_id,
        description=payload.description,
        due_date=payload.due_date,
    )


@router.get(
    "",
    response_model=List[UndertakingResponse],
    summary="List accessible statutory undertakings",
)
def list_undertakings_endpoint(
    application_id: Optional[int] = Query(default=None),
    status_filter: Optional[UndertakingStatus] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve undertakings list with RBAC filters.
    Institutions can view only their own undertakings.
    Regional officers can view undertakings for applications in their region.
    """
    return list_undertakings(
        db=db,
        user=current_user,
        application_id=application_id,
        status_filter=status_filter,
    )


@router.get(
    "/{undertaking_id}",
    response_model=UndertakingResponse,
    summary="Get single undertaking details",
)
def get_undertaking_endpoint(
    undertaking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full undertaking details with RBAC checks."""
    return get_undertaking(
        db=db,
        user=current_user,
        undertaking_id=undertaking_id,
    )


@router.post(
    "/{undertaking_id}/submit-evidence",
    response_model=UndertakingResponse,
    summary="Submit compliance evidence for an undertaking",
)
def submit_evidence_endpoint(
    undertaking_id: int,
    payload: UndertakingSubmitEvidenceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Institution submits evidence/proof reference for a pending or previously rejected undertaking.
    Transitions: PENDING -> SUBMITTED or REJECTED -> SUBMITTED (resubmission).
    """
    return submit_evidence(
        db=db,
        user=current_user,
        undertaking_id=undertaking_id,
        proof_reference=payload.submitted_proof_reference,
        proof_document_id=payload.proof_document_id,
        remarks=payload.submission_remarks,
    )


@router.post(
    "/{undertaking_id}/verify",
    response_model=UndertakingResponse,
    summary="Verify compliance evidence",
)
def verify_evidence_endpoint(
    undertaking_id: int,
    payload: Optional[UndertakingVerifyRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Officer marks submitted undertaking evidence as verified.
    Transition: SUBMITTED -> VERIFIED.
    """
    remarks = payload.remarks if payload else None
    return verify_evidence(
        db=db,
        user=current_user,
        undertaking_id=undertaking_id,
        remarks=remarks,
    )


@router.post(
    "/{undertaking_id}/reject",
    response_model=UndertakingResponse,
    summary="Reject submitted compliance evidence",
)
def reject_evidence_endpoint(
    undertaking_id: int,
    payload: UndertakingRejectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Officer rejects submitted evidence with a substantive reason.
    Returns undertaking to the institution for resubmission.
    Transition: SUBMITTED -> REJECTED.
    """
    return reject_evidence(
        db=db,
        user=current_user,
        undertaking_id=undertaking_id,
        rejection_reason=payload.rejection_reason,
        remarks=payload.remarks,
    )
