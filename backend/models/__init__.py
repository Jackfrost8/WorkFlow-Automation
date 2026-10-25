"""
SQLAlchemy models package for AICTE Workflow Automation Platform.
All models are imported here to register with Base.metadata.
"""
from backend.models.base import TimestampMixin
from backend.models.user import User, UserRole, Institution
from backend.models.workflow import (
    ApplicationType,
    WorkflowRoute,
    WorkflowStage,
    StageTransition,
)
from backend.models.application import (
    Application,
    ApplicationStatus,
    ApplicationStageHistory,
)
from backend.models.evc import EVCVisit, EVCStatus, EVCRecommendation
from backend.models.document import (
    UndertakingDocument,
    DocType,
    DocumentStatus,
    VerificationStatus,
)
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.notification import (
    Notification,
    NotificationType,
    EscalationRecord,
    EscalationLevel,
    TrackableEntityType,
    DeadlineRule,
)
from backend.models.audit import AuditLog
from backend.models.setting import SystemSetting

__all__ = [
    "TimestampMixin",
    "User",
    "UserRole",
    "Institution",
    "ApplicationType",
    "WorkflowRoute",
    "WorkflowStage",
    "StageTransition",
    "Application",
    "ApplicationStatus",
    "ApplicationStageHistory",
    "EVCVisit",
    "EVCStatus",
    "EVCRecommendation",
    "UndertakingDocument",
    "DocType",
    "DocumentStatus",
    "VerificationStatus",
    "Undertaking",
    "UndertakingStatus",
    "Notification",
    "NotificationType",
    "TrackableEntityType",
    "DeadlineRule",
    "EscalationRecord",
    "EscalationLevel",
    "AuditLog",
    "SystemSetting",
]
