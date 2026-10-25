from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class MessageResponse(BaseModel):
    """Generic status/message response schema."""

    message: str = Field(..., description="Descriptive status message")
    success: bool = Field(default=True, description="Whether the operation succeeded")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination wrapper schema."""

    items: List[T] = Field(..., description="List of items for current page")
    total: int = Field(..., description="Total count across all pages")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=20, description="Items per page")
