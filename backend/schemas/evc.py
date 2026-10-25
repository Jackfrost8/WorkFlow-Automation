import json
from datetime import datetime, timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator
from backend.models.evc import EVCRecommendation, EVCStatus


class EVCScheduleRequest(BaseModel):
    scheduled_date: datetime = Field(..., description="Date and time of the proposed EVC inspection")
    committee_lead_name: str = Field(..., min_length=2, max_length=255, description="Name of visiting committee head")
    committee_members: Optional[List[str]] = Field(default=None, description="Names and affiliations of committee members")
    visit_mode: str = Field(default="PHYSICAL", description="PHYSICAL or VIRTUAL")
    remarks: Optional[str] = Field(default=None, description="Scheduling notes or requirements")


class EVCRescheduleRequest(BaseModel):
    new_scheduled_date: datetime = Field(..., description="Revised date and time for inspection")
    reason: str = Field(..., min_length=3, description="Substantive reason for rescheduling inspection")
    remarks: Optional[str] = Field(default=None)


class EVCCompleteRequest(BaseModel):
    recommendation: EVCRecommendation = Field(
        ..., description="Committee finding: RECOMMENDED, DEFICIENCIES_NOTED, or NOT_RECOMMENDED"
    )
    deficiencies: Optional[str] = Field(default=None, description="Documented deficiencies or non-compliances")
    remarks: Optional[str] = Field(default=None, description="Inspection summary comments")
    conducted_date: Optional[datetime] = Field(default=None, description="Date visit was executed")
    report_file_path: Optional[str] = Field(default=None)


class EVCCancelRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Justification for cancelling inspection")


class EVCVisitResponse(BaseModel):
    id: int
    application_id: int
    scheduled_date: Optional[datetime] = None
    conducted_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    status: EVCStatus
    rescheduled_count: int = 0
    committee_lead_name: Optional[str] = None
    committee_members: List[str] = []
    visit_mode: str = "PHYSICAL"
    recommendation: EVCRecommendation
    deficiencies: Optional[str] = None
    remarks: Optional[str] = None
    officer_remarks: Optional[str] = None
    is_delayed: bool = False

    application_number: Optional[str] = None
    institution_name: Optional[str] = None
    region: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_visit(cls, visit: Any) -> "EVCVisitResponse":
        """Custom transformer parsing JSON members and computing delay status."""
        members: List[str] = []
        if visit.committee_members_json:
            try:
                members = json.loads(visit.committee_members_json)
            except Exception:
                members = []

        now = datetime.now(timezone.utc)
        # Check delay: pending or scheduled and past due date
        is_delayed = False
        if visit.due_date and visit.status in [EVCStatus.PENDING_SCHEDULE, EVCStatus.SCHEDULED]:
            # Convert to aware if naive for comparison
            due = visit.due_date if visit.due_date.tzinfo else visit.due_date.replace(tzinfo=timezone.utc)
            if due < now:
                is_delayed = True

        app_num = visit.application.application_number if visit.application else None
        inst_name = visit.application.institution.name if visit.application and visit.application.institution else None
        reg = visit.application.institution.region if visit.application and visit.application.institution else None

        return cls(
            id=visit.id,
            application_id=visit.application_id,
            scheduled_date=visit.scheduled_date,
            conducted_date=visit.conducted_date,
            due_date=visit.due_date,
            status=visit.status,
            rescheduled_count=visit.rescheduled_count,
            committee_lead_name=visit.committee_lead_name,
            committee_members=members,
            visit_mode=visit.visit_mode,
            recommendation=visit.recommendation,
            deficiencies=visit.deficiencies,
            remarks=visit.remarks,
            officer_remarks=visit.officer_remarks,
            is_delayed=is_delayed,
            application_number=app_num,
            institution_name=inst_name,
            region=reg,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
        )
