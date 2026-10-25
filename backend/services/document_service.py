import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.document import DocType, DocumentStatus, UndertakingDocument, VerificationStatus
from backend.models.user import Institution, User, UserRole
from backend.services.audit_service import log_audit_event

settings = get_settings()

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAGIC_SIGNATURES = {
    ".pdf": b"%PDF-",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}
MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def sanitize_filename(filename: str) -> str:
    """Sanitize client-supplied filename to prevent injection and directory traversal."""
    if not filename:
        return "document"
    # Take basename only
    base = Path(filename).name
    # Strip any directory separators or control chars
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    return sanitized if sanitized else "document"


def validate_file_content(content: bytes, extension: str, max_size: int) -> None:
    """Validate file content size and signature magic bytes."""
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(content) > max_size:
        raise HTTPException(
            status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
            detail=f"File size exceeds maximum permitted limit of {max_size} bytes.",
        )

    expected_magic = MAGIC_SIGNATURES.get(extension)
    if expected_magic and not content.startswith(expected_magic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File content does not match declared file extension '{extension}'.",
        )


def check_document_access(user: User, doc: UndertakingDocument, db: Session) -> None:
    """Verify role-based and regional access permissions to a document."""
    if user.role in (UserRole.ADMIN, UserRole.BUREAU_OFFICER):
        return

    if user.role == UserRole.INSTITUTION:
        if user.institution_id != doc.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You can only access documents belonging to your institution.",
            )
        return

    if user.role == UserRole.REGIONAL_OFFICER:
        institution = db.query(Institution).filter(Institution.id == doc.institution_id).first()
        if not institution or institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Regional Officer cannot access documents outside {user.region}.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Unauthorized document access.",
    )


async def save_uploaded_file(
    db: Session,
    user: User,
    file: UploadFile,
    doc_type: DocType,
    title: str,
    institution_id: Optional[int] = None,
    application_id: Optional[int] = None,
    issue_date: Optional[datetime] = None,
    expiry_date: Optional[datetime] = None,
) -> UndertakingDocument:
    """Securely validate, hash, persist to disk, and record uploaded document in database."""
    # Resolve target institution
    if user.role == UserRole.INSTITUTION:
        target_institution_id = user.institution_id
        if not target_institution_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not associated with an institution.",
            )
    else:
        if not institution_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="institution_id is required when uploading as an officer.",
            )
        target_institution_id = institution_id

    # Verify institution existence & regional boundary
    institution = db.query(Institution).filter(Institution.id == target_institution_id).first()
    if not institution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target institution not found.",
        )
    if user.role == UserRole.REGIONAL_OFFICER and institution.region != user.region:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot upload document for an institution outside your region ({user.region}).",
        )

    # Validate dates
    if issue_date and expiry_date:
        if expiry_date <= issue_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expiry date must be strictly later than issue date.",
            )

    # Determine document status based on expiry
    doc_status = DocumentStatus.ACTIVE
    if expiry_date:
        now_utc = datetime.now(timezone.utc)
        exp_utc = (
            expiry_date if expiry_date.tzinfo is not None else expiry_date.replace(tzinfo=timezone.utc)
        )
        if exp_utc < now_utc:
            doc_status = DocumentStatus.EXPIRED

    # Validate file extension
    raw_filename = file.filename or "upload"
    ext = Path(raw_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension '{ext}' is not permitted. Permitted types: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    # Read content
    content = await file.read()
    validate_file_content(content, ext, settings.MAX_UPLOAD_SIZE_BYTES)

    # Compute SHA-256 hash
    file_hash = hashlib.sha256(content).hexdigest()

    # Generate server-side random filename to eliminate path traversal risk
    server_filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_path = (upload_dir / server_filename).resolve()
    if not dest_path.is_relative_to(upload_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid server destination path.",
        )

    # Write file to disk
    dest_path.write_bytes(content)

    # Sanitize client filename
    safe_original_name = sanitize_filename(raw_filename)
    mime_type = file.content_type or MIME_MAP.get(ext, "application/octet-stream")

    # Create document record
    doc = UndertakingDocument(
        institution_id=target_institution_id,
        application_id=application_id,
        doc_type=doc_type,
        title=title.strip(),
        file_name=safe_original_name,
        stored_file_path=server_filename,
        file_size_bytes=len(content),
        file_hash_sha256=file_hash,
        mime_type=mime_type,
        issue_date=issue_date,
        expiry_date=expiry_date,
        status=doc_status,
        verification_status=VerificationStatus.PENDING,
        uploaded_by_user_id=user.id,
    )
    db.add(doc)
    db.flush()

    # Cryptographic Audit Log
    log_audit_event(
        db=db,
        action="DOCUMENT_UPLOAD",
        resource_type="DOCUMENT",
        resource_id=str(doc.id),
        user_id=user.id,
        details={
            "institution_id": target_institution_id,
            "application_id": application_id,
            "doc_type": doc_type.value,
            "title": title,
            "file_name": safe_original_name,
            "file_size_bytes": len(content),
            "file_hash_sha256": file_hash,
            "status": doc_status.value,
            "expiry_date": expiry_date.isoformat() if expiry_date else None,
        },
    )

    db.commit()
    db.refresh(doc)
    return doc


def get_document_file_path(doc: UndertakingDocument) -> Path:
    """Resolve and verify server filesystem path for a document."""
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    target_path = (upload_dir / doc.stored_file_path).resolve()

    if not target_path.is_relative_to(upload_dir) or not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Underlying document file not found on storage.",
        )
    return target_path


def verify_document(
    db: Session,
    user: User,
    doc_id: int,
    verif_status: VerificationStatus,
    remarks: Optional[str] = None,
) -> UndertakingDocument:
    """Perform officer verification on a document."""
    if user.role not in (UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only authorized officers can verify documents.",
        )

    doc = db.query(UndertakingDocument).filter(UndertakingDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if user.role == UserRole.REGIONAL_OFFICER:
        institution = db.query(Institution).filter(Institution.id == doc.institution_id).first()
        if not institution or institution.region != user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot verify documents outside your region ({user.region}).",
            )

    now_utc = datetime.now(timezone.utc)
    doc.verification_status = verif_status
    doc.verified_by_user_id = user.id
    doc.verified_at = now_utc
    doc.verification_remarks = remarks.strip() if remarks else None

    action = "DOCUMENT_VERIFIED" if verif_status == VerificationStatus.VERIFIED else "DOCUMENT_REJECTED"
    log_audit_event(
        db=db,
        action=action,
        resource_type="DOCUMENT",
        resource_id=str(doc.id),
        user_id=user.id,
        details={
            "verification_status": verif_status.value,
            "remarks": remarks,
        },
    )

    db.commit()
    db.refresh(doc)
    return doc


def update_document_metadata(
    db: Session,
    user: User,
    doc_id: int,
    title: Optional[str] = None,
    issue_date: Optional[datetime] = None,
    expiry_date: Optional[datetime] = None,
    status_override: Optional[DocumentStatus] = None,
) -> UndertakingDocument:
    """Update document metadata with date and status recalculation."""
    doc = db.query(UndertakingDocument).filter(UndertakingDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    check_document_access(user, doc, db)

    # Role restriction: only officers or admin can update metadata after upload
    if user.role == UserRole.INSTITUTION and doc.verification_status == VerificationStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify metadata of an already verified document.",
        )

    new_issue = issue_date if issue_date is not None else doc.issue_date
    new_expiry = expiry_date if expiry_date is not None else doc.expiry_date

    if new_issue and new_expiry:
        if new_expiry <= new_issue:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expiry date must be strictly later than issue date.",
            )

    changes = {}
    if title is not None and title.strip() != doc.title:
        changes["title"] = {"old": doc.title, "new": title.strip()}
        doc.title = title.strip()

    if issue_date is not None:
        changes["issue_date"] = {"old": doc.issue_date, "new": issue_date}
        doc.issue_date = issue_date

    if expiry_date is not None:
        changes["expiry_date"] = {"old": doc.expiry_date, "new": expiry_date}
        doc.expiry_date = expiry_date
        now_utc = datetime.now(timezone.utc)
        exp_utc = (
            expiry_date if expiry_date.tzinfo is not None else expiry_date.replace(tzinfo=timezone.utc)
        )
        doc.status = DocumentStatus.EXPIRED if exp_utc < now_utc else DocumentStatus.ACTIVE

    if status_override is not None:
        changes["status"] = {"old": doc.status.value, "new": status_override.value}
        doc.status = status_override

    if changes:
        log_audit_event(
            db=db,
            action="DOCUMENT_METADATA_UPDATED",
            resource_type="DOCUMENT",
            resource_id=str(doc.id),
            user_id=user.id,
            details={"changes": changes},
        )
        db.commit()
        db.refresh(doc)

    return doc
