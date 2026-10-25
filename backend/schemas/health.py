from datetime import datetime
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema returned by the application health check endpoint."""

    status: str = Field(default="healthy", description="Application health status")
    app_name: str = Field(description="Name of the application")
    app_env: str = Field(description="Deployment environment")
    database_connected: bool = Field(description="Database connectivity status")
    timestamp: datetime = Field(description="Current server timestamp")
    time_simulation_enabled: bool = Field(description="Whether simulated time is enabled")
    version: str = Field(default="1.0.0", description="API version")
