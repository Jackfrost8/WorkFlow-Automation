import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class EVCStatus(str, enum.Enum):
    PENDING_SCHEDULE = "PENDING_SCHEDULE"
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    CANCELLED = "CANCELLED"


class EVCRecommendation(str, enum.Enum):
    PENDING = "PENDING"
    RECOMMENDED = "RECOMMENDED"
    DEFICIENCIES_NOTED = "DEFICIENCIES_NOTED"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class EVCVisit(Base, TimestampMixin):
    """Expert Visit Committee (EVC) physical/virtual inspection record."""

    __tablename__ = "evc_visits"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_date = Column(DateTime, nullable=True)
    conducted_date = Column(DateTime, nullable=True)
    status = Column(Enum(EVCStatus), default=EVCStatus.PENDING_SCHEDULE, nullable=False, index=True)

    committee_lead_name = Column(String(255), nullable=True)
    committee_members_json = Column(Text, nullable=True)  # JSON-encoded array of member names/affiliations
    visit_mode = Column(String(50), default="PHYSICAL", nullable=False)  # PHYSICAL or VIRTUAL

    report_file_path = Column(String(500), nullable=True)
    report_file_hash = Column(String(64), nullable=True)
    report_uploaded_at = Column(DateTime, nullable=True)

    recommendation = Column(
        Enum(EVCRecommendation), default=EVCRecommendation.PENDING, nullable=False
    )
    deficiencies = Column(Text, nullable=True)
    remarks = Column(Text, nullable=True)

    application = relationship("Application", back_populates="evc_visits")
