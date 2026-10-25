from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class InstitutionBase(BaseModel):
    name: str = Field(..., max_length=255, description="Full registered name of the institution")
    code: str = Field(..., max_length=50, description="Unique AICTE Institution Code")
    region: str = Field(..., max_length=100, description="AICTE Regional Office jurisdiction")
    address: Optional[str] = Field(default=None, description="Physical address of the campus")
    contact_email: EmailStr = Field(..., description="Official contact email")
    contact_phone: Optional[str] = Field(default=None, description="Contact phone number")
    establishment_year: Optional[int] = Field(default=None, ge=1800, le=2100)


class InstitutionCreate(InstitutionBase):
    pass


class InstitutionResponse(InstitutionBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
