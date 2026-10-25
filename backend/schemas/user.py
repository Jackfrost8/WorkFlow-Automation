from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from backend.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr = Field(..., description="Unique user email address")
    full_name: str = Field(..., max_length=255, description="Full name of officer or administrator")
    role: UserRole = Field(..., description="Assigned platform role")
    region: Optional[str] = Field(default=None, description="Regional office designation if applicable")
    institution_id: Optional[int] = Field(default=None, description="Institution ID for institutional users")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="Plaintext password for registration")


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
