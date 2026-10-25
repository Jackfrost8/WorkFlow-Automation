from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.models.notification import EscalationLevel, NotificationType, TrackableEntityType
from backend.models.user import UserRole


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    application_id: Optional[int] = None
    title: str
    message: str
    notification_type: NotificationType
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationMarkReadRequest(BaseModel):
    notification_ids: Optional[List[int]] = Field(
        default=None, description="Optional list of notification IDs. If omitted, marks all unread as read."
    )


class DeadlineRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: TrackableEntityType
    name: str
    reminder_threshold_days: int
    escalation_threshold_days: int
    escalation_recipient_role: UserRole
    is_active: bool
    description: Optional[str] = None


class DeadlineRuleUpdateRequest(BaseModel):
    reminder_threshold_days: Optional[int] = Field(default=None, ge=1, le=90)
    escalation_threshold_days: Optional[int] = Field(default=None, ge=1, le=90)
    escalation_recipient_role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class EscalationRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: Optional[int] = None
    entity_type: str
    entity_id: Optional[int] = None
    escalation_level: EscalationLevel
    recipient_user_id: Optional[int] = None
    reason: str
    trigger_time: datetime
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None
    created_at: datetime
