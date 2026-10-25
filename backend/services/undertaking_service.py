from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.document import UndertakingDocument
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.services.audit_service import log_audit_event


def check_undertaking_access(user: User, undertaking: Undertaking, db: Session) -> None:
    """Verify access permission for viewing or acting on an undertaking."""
    if user.role in (UserRole.ADMIN, UserRole.BUREAU_OFFICER):
        return

    if user.role == UserRole.INSTITUTION:
        if user.institution_id != undertaking.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You can only access undertakings for your own institution.",
            )
        return

    if user.role == UserRole.REGIONAL_OFFICER:
        institution = (
            db.query(Institution).filter(Institution.id == undertaking.institution_id).first()
        )
        if not institution or institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Regional Officer cannot access undertakings outside {user.region}.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Unauthorized access to undertaking.",
    )


def create_undertaking(
    db: Session,
    user: User,
    application_id: int,
    description: str,
    due_date: datetime,
) -> Undertaking:
    """
    Create a new statutory undertaking requirement for an application.
    Authorized roles: REGIONAL_OFFICER (in-region), BUREAU_OFFICER, ADMIN.
    """
    if user.role not in (UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only authorized AICTE officers can issue undertaking requirements.",
        )

    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referenced application not found.",
        )

    if user.role == UserRole.REGIONAL_OFFICER:
        if not app.institution or app.institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot issue undertaking for application outside your region ({user.region}).",
            )

    undertaking = Undertaking(
        application_id=app.id,
        institution_id=app.institution_id,
        description=description.strip(),
        due_date=due_date,
        status=UndertakingStatus.PENDING,
    )
    db.add(undertaking)
    db.flush()

    # Chained Audit Log
    log_audit_event(
        db=db,
        action="UNDERTAKING_CREATED",
        resource_type="UNDERTAKING",
        resource_id=str(undertaking.id),
        user_id=user.id,
        details={
            "application_id": app.id,
            "institution_id": app.institution_id,
            "description": description.strip(),
            "due_date": due_date.isoformat(),
            "status": UndertakingStatus.PENDING.value,
        },
    )

    db.commit()
    db.refresh(undertaking)
    return undertaking


def list_undertakings(
    db: Session,
    user: User,
    application_id: Optional[int] = None,
    status_filter: Optional[UndertakingStatus] = None,
) -> List[Undertaking]:
    """Retrieve filtered undertakings respecting role and regional boundaries."""
    query = db.query(Undertaking).join(Application, Undertaking.application_id == Application.id)

    if user.role == UserRole.INSTITUTION:
        query = query.filter(Undertaking.institution_id == user.institution_id)
    elif user.role == UserRole.REGIONAL_OFFICER:
        query = query.join(Institution, Undertaking.institution_id == Institution.id).filter(
            Institution.region == user.region
        )

    if application_id is not None:
        query = query.filter(Undertaking.application_id == application_id)
    if status_filter is not None:
        query = query.filter(Undertaking.status == status_filter)

    return query.order_by(Undertaking.due_date.asc(), Undertaking.id.asc()).all()


def get_undertaking(db: Session, user: User, undertaking_id: int) -> Undertaking:
    """Retrieve single undertaking with RBAC verification."""
    undertaking = db.query(Undertaking).filter(Undertaking.id == undertaking_id).first()
    if not undertaking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Undertaking not found.",
        )
    check_undertaking_access(user, undertaking, db)
    return undertaking


def submit_evidence(
    db: Session,
    user: User,
    undertaking_id: int,
    proof_reference: str,
    proof_document_id: Optional[int] = None,
    remarks: Optional[str] = None,
) -> Undertaking:
    """
    Submit compliance evidence for a pending or previously rejected undertaking.
    Lifecycle transition: PENDING -> SUBMITTED, or REJECTED -> SUBMITTED (resubmission).
    Authorized roles: INSTITUTION (owner) or ADMIN.
    """
    undertaking = db.query(Undertaking).filter(Undertaking.id == undertaking_id).first()
    if not undertaking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Undertaking not found.",
        )

    if user.role == UserRole.INSTITUTION:
        if user.institution_id != undertaking.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You can only submit evidence for your own institution's undertakings.",
            )
    elif user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the responsible institution can submit undertaking evidence.",
        )

    # Validate lifecycle transition
    if undertaking.status == UndertakingStatus.SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evidence has already been submitted and is currently awaiting officer verification.",
        )
    if undertaking.status == UndertakingStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Undertaking has already been verified and marked compliant.",
        )
    if undertaking.status not in (UndertakingStatus.PENDING, UndertakingStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot submit evidence from status '{undertaking.status.value}'.",
        )

    # Validate proof document if provided
    if proof_document_id:
        doc = (
            db.query(UndertakingDocument)
            .filter(
                UndertakingDocument.id == proof_document_id,
                UndertakingDocument.institution_id == undertaking.institution_id,
            )
            .first()
        )
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified proof document not found or does not belong to your institution.",
            )
        if doc.application_id is not None and doc.application_id != undertaking.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified proof document is linked to a different application.",
            )

    now_utc = datetime.now(timezone.utc)
    prev_status = undertaking.status.value

    undertaking.status = UndertakingStatus.SUBMITTED
    undertaking.submitted_proof_reference = proof_reference.strip()
    undertaking.proof_document_id = proof_document_id
    undertaking.submission_remarks = remarks.strip() if remarks else None
    undertaking.submitted_at = now_utc
    # Resubmission resets previous rejection reason
    undertaking.rejection_reason = None

    log_audit_event(
        db=db,
        action="UNDERTAKING_EVIDENCE_SUBMITTED",
        resource_type="UNDERTAKING",
        resource_id=str(undertaking.id),
        user_id=user.id,
        details={
            "previous_status": prev_status,
            "status": UndertakingStatus.SUBMITTED.value,
            "proof_reference": proof_reference.strip(),
            "proof_document_id": proof_document_id,
            "is_resubmission": prev_status == UndertakingStatus.REJECTED.value,
        },
    )

    db.commit()
    db.refresh(undertaking)
    return undertaking


def verify_evidence(
    db: Session,
    user: User,
    undertaking_id: int,
    remarks: Optional[str] = None,
) -> Undertaking:
    """
    Officer verifies submitted evidence and marks undertaking compliant.
    Lifecycle transition: SUBMITTED -> VERIFIED.
    Authorized roles: REGIONAL_OFFICER (in-region), BUREAU_OFFICER, ADMIN.
    """
    if user.role not in (UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only authorized AICTE officers can verify undertaking evidence.",
        )

    undertaking = db.query(Undertaking).filter(Undertaking.id == undertaking_id).first()
    if not undertaking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Undertaking not found.",
        )

    if user.role == UserRole.REGIONAL_OFFICER:
        institution = (
            db.query(Institution).filter(Institution.id == undertaking.institution_id).first()
        )
        if not institution or institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot verify undertakings outside your region ({user.region}).",
            )

    if undertaking.status != UndertakingStatus.SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot verify undertaking with status '{undertaking.status.value}'. Must be 'SUBMITTED'.",
        )

    now_utc = datetime.now(timezone.utc)
    undertaking.status = UndertakingStatus.VERIFIED
    undertaking.verified_by_user_id = user.id
    undertaking.verified_at = now_utc
    undertaking.verification_remarks = remarks.strip() if remarks else None
    undertaking.rejection_reason = None

    log_audit_event(
        db=db,
        action="UNDERTAKING_VERIFIED",
        resource_type="UNDERTAKING",
        resource_id=str(undertaking.id),
        user_id=user.id,
        details={
            "status": UndertakingStatus.VERIFIED.value,
            "remarks": remarks,
        },
    )

    db.commit()
    db.refresh(undertaking)
    return undertaking


def reject_evidence(
    db: Session,
    user: User,
    undertaking_id: int,
    rejection_reason: str,
    remarks: Optional[str] = None,
) -> Undertaking:
    """
    Officer rejects submitted evidence with mandatory reason. Returns undertaking to institution for resubmission.
    Lifecycle transition: SUBMITTED -> REJECTED.
    Authorized roles: REGIONAL_OFFICER (in-region), BUREAU_OFFICER, ADMIN.
    """
    if user.role not in (UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only authorized AICTE officers can reject undertaking evidence.",
        )

    if not rejection_reason or len(rejection_reason.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A substantive rejection reason (at least 3 characters) is required.",
        )

    undertaking = db.query(Undertaking).filter(Undertaking.id == undertaking_id).first()
    if not undertaking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Undertaking not found.",
        )

    if user.role == UserRole.REGIONAL_OFFICER:
        institution = (
            db.query(Institution).filter(Institution.id == undertaking.institution_id).first()
        )
        if not institution or institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot reject undertakings outside your region ({user.region}).",
            )

    if undertaking.status != UndertakingStatus.SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject undertaking with status '{undertaking.status.value}'. Must be 'SUBMITTED'.",
        )

    now_utc = datetime.now(timezone.utc)
    undertaking.status = UndertakingStatus.REJECTED
    undertaking.verified_by_user_id = user.id
    undertaking.verified_at = now_utc
    undertaking.rejection_reason = rejection_reason.strip()
    undertaking.verification_remarks = remarks.strip() if remarks else None

    log_audit_event(
        db=db,
        action="UNDERTAKING_REJECTED",
        resource_type="UNDERTAKING",
        resource_id=str(undertaking.id),
        user_id=user.id,
        details={
            "status": UndertakingStatus.REJECTED.value,
            "rejection_reason": rejection_reason.strip(),
            "remarks": remarks,
        },
    )

    db.commit()
    db.refresh(undertaking)
    return undertaking
