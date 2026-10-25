from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base


class AuditLog(Base):
    """
    Append-only, cryptographically hash-chained audit log entity.
    Maintains immutable trail of workflow transitions, file updates, and officer actions.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    resource_id = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    details_json = Column(Text, nullable=True)

    prev_hash = Column(String(64), nullable=False, default="GENESIS")
    curr_hash = Column(String(64), nullable=False, index=True)

    actor = relationship("User", back_populates="audit_logs")
