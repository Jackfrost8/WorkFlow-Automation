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
]
