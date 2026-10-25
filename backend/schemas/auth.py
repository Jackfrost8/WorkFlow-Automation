from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from backend.models.user import UserRole
from backend.schemas.user import UserResponse


class LoginRequest(BaseModel):
    """Payload submitted to authenticate a user."""

    email: EmailStr = Field(..., description="Registered user email address")
    password: str = Field(..., min_length=1, description="Account password")


class TokenResponse(BaseModel):
    """Access token and user profile returned upon successful authentication."""

    access_token: str = Field(..., description="Signed JWT Bearer access token")
    token_type: str = Field(default="bearer", description="Token schema type")
    user: UserResponse = Field(..., description="Authenticated user profile metadata")


class UserUpdate(BaseModel):
    """Fields allowed when updating an existing user."""

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = Field(default=None)
    role: Optional[UserRole] = Field(default=None, description="Only Admin can alter user roles")
    region: Optional[str] = Field(default=None, max_length=100)
    institution_id: Optional[int] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    password: Optional[str] = Field(default=None, min_length=8)
