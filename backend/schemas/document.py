from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from backend.models.document import DocType, DocumentStatus, VerificationStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution_id: int
    application_id: Optional[int] = None
    doc_type: DocType
    title: str
    file_name: str
    file_size_bytes: int
    file_hash_sha256: str
    mime_type: str
    issue_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    status: DocumentStatus
    verification_status: VerificationStatus
    verified_by_user_id: Optional[int] = None
    verified_at: Optional[datetime] = None
    verification_remarks: Optional[str] = None
    uploaded_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class DocumentVerifyRequest(BaseModel):
    status: VerificationStatus = Field(
        ..., description="Verification outcome: VERIFIED or REJECTED"
    )
    remarks: Optional[str] = Field(
        default=None, description="Officer verification remarks or deficiency details"
    )


class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    issue_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    status: Optional[DocumentStatus] = None
