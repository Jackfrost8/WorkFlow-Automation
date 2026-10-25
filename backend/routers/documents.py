from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.database import get_db
from backend.models.document import DocType, DocumentStatus, UndertakingDocument, VerificationStatus
from backend.models.user import Institution, User, UserRole
from backend.schemas.document import DocumentResponse, DocumentUpdateRequest, DocumentVerifyRequest
from backend.services.document_service import (
    check_document_access,
    get_document_file_path,
    save_uploaded_file,
    update_document_metadata,
    verify_document,
)

router = APIRouter(prefix="/documents", tags=["Document Management & Compliance"])


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload statutory compliance or lease document",
)
async def upload_document(
    file: UploadFile = File(..., description="Document file (.pdf, .png, .jpg, .jpeg)"),
    doc_type: DocType = Form(..., description="Classification of document"),
    title: str = Form(..., min_length=2, max_length=255, description="Document title"),
    application_id: Optional[int] = Form(default=None, description="Associated application ID"),
    institution_id: Optional[int] = Form(default=None, description="Institution ID (for officer uploads)"),
    issue_date: Optional[datetime] = Form(default=None, description="Document issuance date"),
    expiry_date: Optional[datetime] = Form(default=None, description="Document expiration date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Secure document upload endpoint.
    Validates file extension, magic header signature, and configurable size limits.
    Files are stored outside static directories using random server-generated filenames.
    """
    return await save_uploaded_file(
        db=db,
        user=current_user,
        file=file,
        doc_type=doc_type,
        title=title,
        institution_id=institution_id,
        application_id=application_id,
        issue_date=issue_date,
        expiry_date=expiry_date,
    )


@router.get(
    "",
    response_model=List[DocumentResponse],
    summary="List accessible compliance and lease documents",
)
def list_documents(
    institution_id: Optional[int] = Query(default=None),
    application_id: Optional[int] = Query(default=None),
    doc_type: Optional[DocType] = Query(default=None),
    doc_status: Optional[DocumentStatus] = Query(default=None, alias="status"),
    verification_status: Optional[VerificationStatus] = Query(default=None),
    expiring_within_days: Optional[int] = Query(
        default=None, ge=1, le=365, description="Filter documents expiring within N days"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List documents with role and region-based access control."""
    query = db.query(UndertakingDocument)

    # RBAC Filtering
    if current_user.role == UserRole.INSTITUTION:
        query = query.filter(UndertakingDocument.institution_id == current_user.institution_id)
    elif current_user.role == UserRole.REGIONAL_OFFICER:
        query = query.join(Institution, UndertakingDocument.institution_id == Institution.id).filter(
            Institution.region == current_user.region
        )

    # Optional Filters
    if institution_id is not None:
        if current_user.role == UserRole.INSTITUTION and institution_id != current_user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot query documents of other institutions.",
            )
        query = query.filter(UndertakingDocument.institution_id == institution_id)

    if application_id is not None:
        query = query.filter(UndertakingDocument.application_id == application_id)
    if doc_type is not None:
        query = query.filter(UndertakingDocument.doc_type == doc_type)
    if doc_status is not None:
        query = query.filter(UndertakingDocument.status == doc_status)
    if verification_status is not None:
        query = query.filter(UndertakingDocument.verification_status == verification_status)

    if expiring_within_days is not None:
        now_utc = datetime.now(timezone.utc)
        horizon = now_utc + timedelta(days=expiring_within_days)
        query = query.filter(
            UndertakingDocument.expiry_date.isnot(None),
            UndertakingDocument.expiry_date >= now_utc,
            UndertakingDocument.expiry_date <= horizon,
        )

    return query.order_by(UndertakingDocument.id.desc()).all()


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve document metadata with RBAC verification."""
    doc = db.query(UndertakingDocument).filter(UndertakingDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    check_document_access(current_user, doc, db)
    return doc


@router.get(
    "/{document_id}/download",
    summary="Securely download document file",
)
def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream document file to authorized clients.
    Guarantees isolation: Institutions can only download their own documents;
    Regional officers can only download documents for institutions within their region.
    """
    doc = db.query(UndertakingDocument).filter(UndertakingDocument.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    check_document_access(current_user, doc, db)

    file_path = get_document_file_path(doc)
    return FileResponse(
        path=file_path,
        filename=doc.file_name,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.file_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{document_id}/verify",
    response_model=DocumentResponse,
    summary="Officer verification of compliance document",
)
def verify_document_endpoint(
    document_id: int,
    payload: DocumentVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Officer marks compliance document as VERIFIED or REJECTED."""
    return verify_document(
        db=db,
        user=current_user,
        doc_id=document_id,
        verif_status=payload.status,
        remarks=payload.remarks,
    )


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Update document metadata",
)
def update_document(
    document_id: int,
    payload: DocumentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update metadata, validity dates, or status."""
    return update_document_metadata(
        db=db,
        user=current_user,
        doc_id=document_id,
        title=payload.title,
        issue_date=payload.issue_date,
        expiry_date=payload.expiry_date,
        status_override=payload.status,
    )
