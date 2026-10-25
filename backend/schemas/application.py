from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from backend.models.application import ApplicationStatus
from backend.schemas.institution import InstitutionResponse


class WorkflowStageResponse(BaseModel):
    id: int
    stage_key: str
    name: str
    order_index: int
    sla_days: int
    is_evc_stage: bool
    is_final: bool

    class Config:
        from_attributes = True


class StageHistoryResponse(BaseModel):
    id: int
    application_id: int
    stage_id: Optional[int] = None
    from_stage_id: Optional[int] = None
    to_stage_id: Optional[int] = None
    action: str
    remarks: Optional[str] = None
    actor_user_id: Optional[int] = None
    entered_at: datetime
    exited_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    was_overdue: bool = False

    class Config:
        from_attributes = True


class ApplicationCreate(BaseModel):
    route_type: str = Field(
        ...,
        description="Assigned route: ONLY_SCRUTINY, SCRUTINY_EVC, EVC_SAC, or ONLY_EVC",
    )
    title: str = Field(..., min_length=3, max_length=255, description="Application title / campus expansion")
    description: Optional[str] = Field(default=None, description="Detailed application brief")
    academic_year: str = Field(default="2026-2027", max_length=20)


class CompleteStageRequest(BaseModel):
    remarks: Optional[str] = Field(default=None, description="Stage processing remarks / verification checklist")
    decision: Optional[str] = Field(
        default=None, description="Required for final decision stage: 'APPROVE' or 'REJECT'"
    )
    expected_stage_id: Optional[int] = Field(
        default=None, description="Concurrency check: ensures transition from anticipated stage only"
    )


class ReturnStageRequest(BaseModel):
    reason: str = Field(
        ..., min_length=3, description="Substantive reason for returning application or noting deficiencies"
    )


class ApplicationResponse(BaseModel):
    id: int
    application_number: str
    institution_id: int
    route_id: Optional[int] = None
    route_type: Optional[str] = None
    current_stage_id: Optional[int] = None
    status: ApplicationStatus
    academic_year: str
    title: str
    description: Optional[str] = None
    submission_date: Optional[datetime] = None
    current_stage_deadline: Optional[datetime] = None
    final_decision_date: Optional[datetime] = None
    final_decision_by_user_id: Optional[int] = None
    final_decision_remarks: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    institution: Optional[InstitutionResponse] = None
    current_stage: Optional[WorkflowStageResponse] = None
    stage_history: List[StageHistoryResponse] = []

    class Config:
        from_attributes = True
