import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin
from backend.models.user import UserRole


class EscalationLevel(str, enum.Enum):
    LEVEL_1_REMINDER = "LEVEL_1_REMINDER"          # Approaching SLA limit
    LEVEL_2_REGIONAL = "LEVEL_2_REGIONAL"          # Lapsed, regional officer escalation
    LEVEL_3_BUREAU = "LEVEL_3_BUREAU"              # Extended overdue, bureau officer escalation
    LEVEL_4_ADMIN = "LEVEL_4_ADMIN"                # Critical unresolved escalation


class NotificationType(str, enum.Enum):
    UPCOMING = "UPCOMING"
    DUE_TODAY = "DUE_TODAY"
    OVERDUE = "OVERDUE"
    ESCALATION = "ESCALATION"
    SYSTEM = "SYSTEM"


class TrackableEntityType(str, enum.Enum):
    APPLICATION_STAGE = "APPLICATION_STAGE"
    EVC_VISIT = "EVC_VISIT"
    UNDERTAKING = "UNDERTAKING"
    DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY"


class DeadlineRule(Base, TimestampMixin):
    """Configurable deadline, reminder, and escalation rules stored in the database."""

    __tablename__ = "deadline_rules"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(Enum(TrackableEntityType), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    reminder_threshold_days = Column(Integer, default=3, nullable=False)
    escalation_threshold_days = Column(Integer, default=2, nullable=False)
    escalation_recipient_role = Column(Enum(UserRole), default=UserRole.REGIONAL_OFFICER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(Text, nullable=True)


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
    notification_type = Column(
        Enum(NotificationType), default=NotificationType.SYSTEM, nullable=False, index=True
    )
    entity_type = Column(String(50), nullable=True, index=True)
    entity_id = Column(Integer, nullable=True, index=True)
    event_key = Column(String(255), nullable=True, index=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="notifications")
    application = relationship("Application", back_populates="notifications")


class EscalationRecord(Base, TimestampMixin):
    """Audit-tracked escalation event triggered by deadline lapses."""

    __tablename__ = "escalation_records"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    entity_type = Column(String(50), default="APPLICATION", nullable=False, index=True)
    entity_id = Column(Integer, nullable=True, index=True)
    event_key = Column(String(255), nullable=True, index=True)
    escalation_level = Column(Enum(EscalationLevel), nullable=False, index=True)
    recipient_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    recipient = relationship("User", foreign_keys=[recipient_user_id])
