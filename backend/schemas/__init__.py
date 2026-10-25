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
from backend.schemas.document import (
    DocumentResponse,
    DocumentVerifyRequest,
    DocumentUpdateRequest,
)
from backend.schemas.undertaking import (
    UndertakingCreateRequest,
    UndertakingSubmitEvidenceRequest,
    UndertakingVerifyRequest,
    UndertakingRejectRequest,
    UndertakingResponse,
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
    "DocumentResponse",
    "DocumentVerifyRequest",
    "DocumentUpdateRequest",
    "UndertakingCreateRequest",
    "UndertakingSubmitEvidenceRequest",
    "UndertakingVerifyRequest",
    "UndertakingRejectRequest",
    "UndertakingResponse",
]
