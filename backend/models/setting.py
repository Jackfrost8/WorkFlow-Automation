from sqlalchemy import Column, Integer, String, Text
from backend.database import Base
from backend.models.base import TimestampMixin


class SystemSetting(Base, TimestampMixin):
    """Platform system settings (e.g. simulated time offset, SLA defaults)."""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
