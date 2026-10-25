"""
Pydantic schemas package for AICTE Workflow Automation Platform.
"""
from backend.schemas.health import HealthResponse
from backend.schemas.common import MessageResponse, PaginatedResponse
from backend.schemas.institution import (
    InstitutionBase,
    InstitutionCreate,
    InstitutionResponse,
)
from backend.schemas.user import UserBase, UserCreate, UserResponse
from backend.schemas.auth import LoginRequest, TokenResponse, UserUpdate
from backend.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    CompleteStageRequest,
    ReturnStageRequest,
    StageHistoryResponse,
    WorkflowStageResponse,
)
from backend.schemas.evc import (
    EVCCancelRequest,
    EVCCompleteRequest,
    EVCRescheduleRequest,
    EVCScheduleRequest,
    EVCVisitResponse,
)

__all__ = [
    "HealthResponse",
    "MessageResponse",
    "PaginatedResponse",
    "InstitutionBase",
    "InstitutionCreate",
    "InstitutionResponse",
    "UserBase",
    "UserCreate",
    "UserResponse",
    "LoginRequest",
    "TokenResponse",
    "UserUpdate",
    "ApplicationCreate",
    "ApplicationResponse",
    "CompleteStageRequest",
    "ReturnStageRequest",
    "StageHistoryResponse",
    "WorkflowStageResponse",
    "EVCCancelRequest",
    "EVCCompleteRequest",
    "EVCRescheduleRequest",
    "EVCScheduleRequest",
    "EVCVisitResponse",
]
