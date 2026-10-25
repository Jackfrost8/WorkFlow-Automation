from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampMixin


class ApplicationType(Base, TimestampMixin):
    """Category of AICTE application (e.g., New Technical Campus, EoA, New Program)."""

    __tablename__ = "application_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    routes = relationship("WorkflowRoute", back_populates="application_type")
    applications = relationship("Application", back_populates="application_type")


class WorkflowRoute(Base, TimestampMixin):
    """Configurable workflow route linked to an application type."""

    __tablename__ = "workflow_routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    application_type_id = Column(
        Integer, ForeignKey("application_types.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    application_type = relationship("ApplicationType", back_populates="routes")
    stages = relationship("WorkflowStage", back_populates="route", order_by="WorkflowStage.order_index")
    transitions = relationship("StageTransition", back_populates="route")


class WorkflowStage(Base, TimestampMixin):
    """A distinct approval stage in a workflow route."""

    __tablename__ = "workflow_stages"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(
        Integer, ForeignKey("workflow_routes.id", ondelete="CASCADE"), nullable=False
    )
    stage_key = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    order_index = Column(Integer, nullable=False, default=1)
    sla_days = Column(Integer, nullable=False, default=7)
    # Comma-separated roles allowed to process this stage (e.g. "REGIONAL_OFFICER,BUREAU_OFFICER")
    authorized_roles = Column(String(255), nullable=False, default="REGIONAL_OFFICER")
    is_evc_stage = Column(Boolean, default=False, nullable=False)
    is_final = Column(Boolean, default=False, nullable=False)

    route = relationship("WorkflowRoute", back_populates="stages")


class StageTransition(Base, TimestampMixin):
    """Permitted transition between two workflow stages."""

    __tablename__ = "stage_transitions"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(
        Integer, ForeignKey("workflow_routes.id", ondelete="CASCADE"), nullable=False
    )
    from_stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="CASCADE"), nullable=False
    )
    to_stage_id = Column(
        Integer, ForeignKey("workflow_stages.id", ondelete="CASCADE"), nullable=False
    )
    action_name = Column(String(100), nullable=False)  # e.g. "FORWARD", "RETURN", "APPROVE", "REJECT"
    requires_remarks = Column(Boolean, default=False, nullable=False)

    route = relationship("WorkflowRoute", back_populates="transitions")
    from_stage = relationship("WorkflowStage", foreign_keys=[from_stage_id])
    to_stage = relationship("WorkflowStage", foreign_keys=[to_stage_id])
