from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from backend.models.undertaking import UndertakingStatus


class UndertakingCreateRequest(BaseModel):
    application_id: int = Field(..., description="ID of application requiring undertaking")
    description: str = Field(
        ..., min_length=3, description="Specific statutory undertaking or deficiency commitment description"
    )
    due_date: datetime = Field(..., description="Target completion deadline for submission of proof")


class UndertakingSubmitEvidenceRequest(BaseModel):
    submitted_proof_reference: str = Field(
        ..., min_length=2, description="Evidence reference number, file description, or tracking token"
    )
    proof_document_id: Optional[int] = Field(
        default=None, description="Optional ID of associated uploaded compliance document"
    )
    submission_remarks: Optional[str] = Field(
        default=None, description="Explanatory notes by institution regarding submitted compliance proof"
    )


class UndertakingVerifyRequest(BaseModel):
    remarks: Optional[str] = Field(
        default=None, description="Officer verification remarks confirming compliance"
    )


class UndertakingRejectRequest(BaseModel):
    rejection_reason: str = Field(
        ..., min_length=3, description="Mandatory substantive reason for rejecting submitted evidence"
    )
    remarks: Optional[str] = Field(
        default=None, description="Additional corrective instructions for the institution"
    )


class UndertakingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    institution_id: int
    description: str
    due_date: datetime
    status: UndertakingStatus
    submitted_proof_reference: Optional[str] = None
    proof_document_id: Optional[int] = None
    submitted_at: Optional[datetime] = None
    submission_remarks: Optional[str] = None
    verified_by_user_id: Optional[int] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    verification_remarks: Optional[str] = None
    created_at: datetime
    updated_at: datetime
