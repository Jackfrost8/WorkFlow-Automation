import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class DocType(str, enum.Enum):
    LAND_LEASE = "LAND_LEASE"
    FIRE_SAFETY = "FIRE_SAFETY"
    BUILDING_COMPLETION = "BUILDING_COMPLETION"
    AFFIDAVIT_UNDERTAKING = "AFFIDAVIT_UNDERTAKING"
    AICTE_APPROVAL_PREV = "AICTE_APPROVAL_PREV"
    EVC_INSPECTION_REPORT = "EVC_INSPECTION_REPORT"
    UNDERTAKING_EVIDENCE = "UNDERTAKING_EVIDENCE"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class VerificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class UndertakingDocument(Base, TimestampMixin):
    """Institutional undertaking, lease, or compliance document."""

    __tablename__ = "undertaking_documents"

    id = Column(Integer, primary_key=True, index=True)
    institution_id = Column(
        Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    doc_type = Column(Enum(DocType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    stored_file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    file_hash_sha256 = Column(String(64), nullable=False)
    mime_type = Column(String(100), default="application/pdf", nullable=False)

    issue_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True, index=True)
    status = Column(
        Enum(DocumentStatus), default=DocumentStatus.ACTIVE, nullable=False, index=True
    )
    verification_status = Column(
        Enum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False, index=True
    )
    verified_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at = Column(DateTime, nullable=True)
    verification_remarks = Column(Text, nullable=True)
    uploaded_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    institution = relationship("Institution", back_populates="documents")
    application = relationship("Application", back_populates="documents")
    verified_by = relationship("User", foreign_keys=[verified_by_user_id])
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])
