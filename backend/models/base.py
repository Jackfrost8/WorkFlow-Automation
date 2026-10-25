from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from backend.database import Base


class TimestampMixin:
    """Reusable mixin providing created_at and updated_at UTC timestamps."""

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
