from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend.config import get_settings, Settings
from backend.database import get_db, check_db_connection
from backend.schemas.health import HealthResponse

router = APIRouter(prefix="", tags=["Health & Diagnostics"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Health & Readiness Check",
    description="Returns service availability, environment information, and database connection status.",
)
def get_health(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> HealthResponse:
    db_ok = check_db_connection()
    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        database_connected=db_ok,
        timestamp=datetime.now(timezone.utc),
        time_simulation_enabled=settings.ENABLE_TIME_SIMULATION,
        version="1.0.0",
    )
