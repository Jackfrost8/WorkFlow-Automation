import enum
from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    INSTITUTION = "INSTITUTION"
    REGIONAL_OFFICER = "REGIONAL_OFFICER"
    BUREAU_OFFICER = "BUREAU_OFFICER"
    ADMIN = "ADMIN"


class Institution(Base, TimestampMixin):
    """Institutional entity registered on AICTE platform."""

    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    region = Column(String(100), nullable=False, index=True)
    address = Column(Text, nullable=True)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(50), nullable=True)
    establishment_year = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    users = relationship("User", back_populates="institution")
    applications = relationship("Application", back_populates="institution")
    documents = relationship("UndertakingDocument", back_populates="institution")


class User(Base, TimestampMixin):
    """Authenticated user with role-based permissions."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, index=True)
    region = Column(String(100), nullable=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    institution = relationship("Institution", back_populates="users")
    audit_logs = relationship("AuditLog", back_populates="actor")
    notifications = relationship("Notification", back_populates="user")
