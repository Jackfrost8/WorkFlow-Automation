import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class ApplicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    OVERDUE = "OVERDUE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Application(Base, TimestampMixin):
    """Institutional approval application entity."""

    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    application_number = Column(String(100), unique=True, nullable=False, index=True)
    institution_id = Column(
        Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_type_id = Column(
        Integer, ForeignKey("application_types.id", ondelete="RESTRICT"), nullable=False
    )
    current_stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.DRAFT, nullable=False, index=True)

    academic_year = Column(String(20), nullable=False, default="2026-2027")
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    submission_date = Column(DateTime, nullable=True)
    current_stage_deadline = Column(DateTime, nullable=True)
    final_decision_date = Column(DateTime, nullable=True)
    final_decision_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    final_decision_remarks = Column(Text, nullable=True)

    institution = relationship("Institution", back_populates="applications")
    application_type = relationship("ApplicationType", back_populates="applications")
    current_stage = relationship("WorkflowStage")
    final_decision_by = relationship("User", foreign_keys=[final_decision_by_user_id])
    stage_history = relationship(
        "ApplicationStageHistory", back_populates="application", cascade="all, delete-orphan"
    )
    evc_visits = relationship(
        "EVCVisit", back_populates="application", cascade="all, delete-orphan"
    )
    documents = relationship(
        "UndertakingDocument", back_populates="application", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "Notification", back_populates="application", cascade="all, delete-orphan"
    )
    escalations = relationship(
        "EscalationRecord", back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationStageHistory(Base, TimestampMixin):
    """Immutable log of application movements through workflow stages."""

    __tablename__ = "application_stage_history"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    to_stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    action = Column(String(100), nullable=False)  # e.g., SUBMIT, FORWARD, RETURN, APPROVE, REJECT
    remarks = Column(Text, nullable=True)
    actor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at = Column(DateTime, nullable=False)
    exited_at = Column(DateTime, nullable=True)
    deadline_at = Column(DateTime, nullable=True)
    was_overdue = Column(Boolean, default=False, nullable=False)

    application = relationship("Application", back_populates="stage_history")
    from_stage = relationship("WorkflowStage", foreign_keys=[from_stage_id])
    to_stage = relationship("WorkflowStage", foreign_keys=[to_stage_id])
    actor = relationship("User", foreign_keys=[actor_user_id])
