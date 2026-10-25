import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class EscalationLevel(str, enum.Enum):
    LEVEL_1_REMINDER = "LEVEL_1_REMINDER"          # Approaching SLA limit
    LEVEL_2_REGIONAL = "LEVEL_2_REGIONAL"          # Lapsed, regional officer escalation
    LEVEL_3_BUREAU = "LEVEL_3_BUREAU"              # Extended overdue, bureau officer escalation
    LEVEL_4_ADMIN = "LEVEL_4_ADMIN"                # Critical unresolved escalation


class Notification(Base, TimestampMixin):
    """In-app alert and notification message."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="notifications")
    application = relationship("Application", back_populates="notifications")


class EscalationRecord(Base, TimestampMixin):
    """Audit-tracked escalation event triggered by deadline lapses."""

    __tablename__ = "escalation_records"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    escalation_level = Column(Enum(EscalationLevel), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    trigger_time = Column(DateTime, nullable=False)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at = Column(DateTime, nullable=True)

    application = relationship("Application", back_populates="escalations")
    stage = relationship("WorkflowStage")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])
