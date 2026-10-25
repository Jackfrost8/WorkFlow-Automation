import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class UndertakingStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Undertaking(Base, TimestampMixin):
    """
    Statutory Undertaking & Compliance Commitment model.
    Tracks institutional commitments/deficiencies requiring formal evidence.
    Lifecycle: PENDING -> SUBMITTED -> VERIFIED
    If rejected: SUBMITTED -> REJECTED
    Resubmission: REJECTED -> SUBMITTED
    """

    __tablename__ = "undertakings"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    institution_id = Column(
        Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description = Column(Text, nullable=False)
    due_date = Column(DateTime, nullable=False, index=True)
    status = Column(
        Enum(UndertakingStatus), default=UndertakingStatus.PENDING, nullable=False, index=True
    )

    # Submitted evidence reference
    submitted_proof_reference = Column(String(500), nullable=True)
    proof_document_id = Column(
        Integer, ForeignKey("undertaking_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitted_at = Column(DateTime, nullable=True)
    submission_remarks = Column(Text, nullable=True)

    # Officer verification
    verified_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    verified_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    verification_remarks = Column(Text, nullable=True)

    # Relationships
    application = relationship("Application", back_populates="undertakings")
    institution = relationship("Institution")
    proof_document = relationship("UndertakingDocument", foreign_keys=[proof_document_id])
    verified_by = relationship("User", foreign_keys=[verified_by_user_id])
