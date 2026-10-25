from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class AdvanceTimeRequest(BaseModel):
    days: float = Field(
        ...,
        gt=0,
        le=365,
        description="Number of days to advance simulated business time (1 to 365 days)",
    )
    run_deadline_check: bool = Field(
        default=True,
        description="Whether to immediately run the deadline evaluation cycle against the new effective date",
    )


class SimulatedTimeStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_simulation_enabled: bool
    real_time: str
    simulated_time: str
    offset_seconds: float
    offset_days: float
    real_date: Optional[str] = None
    simulated_date: Optional[str] = None
    is_simulated: Optional[bool] = None


class AdvanceTimeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    message: str
    real_time: str
    simulated_time: str
    new_simulated_date: Optional[str] = None
    offset_seconds: float
    offset_days: float
    days_advanced: float
    deadline_evaluation: Optional[Dict[str, Any]] = None
