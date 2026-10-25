"""
Centralized demo time simulation service.
Calculates effective business time based on real UTC clock and persistent database offset.
When ENABLE_TIME_SIMULATION is False (e.g. production), always returns real UTC time.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models.setting import SystemSetting
from backend.models.user import User, UserRole
from backend.services.audit_service import log_audit_event

settings = get_settings()

SETTING_KEY_OFFSET_SECONDS = "simulated_time_offset_seconds"


def get_demo_offset_seconds(db: Optional[Session] = None) -> float:
    """Retrieve persistent time offset in seconds from database."""
    if not settings.ENABLE_TIME_SIMULATION:
        return 0.0

    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        record = (
            db.query(SystemSetting)
            .filter(SystemSetting.key == SETTING_KEY_OFFSET_SECONDS)
            .first()
        )
        if not record or not record.value:
            return 0.0
        return float(record.value)
    except Exception:
        return 0.0
    finally:
        if close_session:
            db.close()


def get_effective_time(db: Optional[Session] = None) -> datetime:
    """
    Get current effective business datetime (UTC-aware).
    Calculated as real UTC time + persistent demo offset.
    In real production deployment (ENABLE_TIME_SIMULATION=False), returns real UTC time.
    """
    real_now = datetime.now(timezone.utc)
    offset = get_demo_offset_seconds(db)
    if offset == 0.0:
        return real_now
    return real_now + timedelta(seconds=offset)


def get_simulated_time_status(db: Optional[Session] = None) -> Dict[str, Any]:
    """Retrieve detailed time status: real clock, effective clock, and offset."""
    real_now = datetime.now(timezone.utc)
    offset_sec = get_demo_offset_seconds(db)
    effective_now = real_now + timedelta(seconds=offset_sec)

    return {
        "is_simulation_enabled": settings.ENABLE_TIME_SIMULATION,
        "is_simulated": settings.ENABLE_TIME_SIMULATION and offset_sec > 0,
        "real_time": real_now.isoformat(),
        "simulated_time": effective_now.isoformat(),
        "real_date": real_now.strftime("%Y-%m-%d"),
        "simulated_date": effective_now.strftime("%Y-%m-%d"),
        "offset_seconds": offset_sec,
        "offset_days": round(offset_sec / 86400.0, 4),
    }


def advance_simulated_time(
    db: Session,
    admin_user: User,
    days: float,
    run_check: bool = True,
) -> Dict[str, Any]:
    """
    Advance persistent demo time by a validated number of days.
    Only authorized ADMIN users may invoke.
    Optionally triggers deadline check against the new effective simulated date.
    """
    if not settings.ENABLE_TIME_SIMULATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Time simulation is disabled in this deployment environment.",
        )

    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators are authorized to advance simulated demo time.",
        )

    if days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Advancement days must be strictly positive (greater than 0).",
        )
    if days > 365.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Advancement days cannot exceed 365 days in a single operation.",
        )

    old_offset = get_demo_offset_seconds(db)
    delta_seconds = days * 86400.0
    new_offset = old_offset + delta_seconds

    # Persist in system_settings
    setting_record = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == SETTING_KEY_OFFSET_SECONDS)
        .first()
    )
    if not setting_record:
        setting_record = SystemSetting(
            key=SETTING_KEY_OFFSET_SECONDS,
            value=str(new_offset),
            description="Persistent simulated time offset in seconds",
        )
        db.add(setting_record)
    else:
        setting_record.value = str(new_offset)

    real_now = datetime.now(timezone.utc)
    new_effective_time = real_now + timedelta(seconds=new_offset)

    # Cryptographic Audit Log
    log_audit_event(
        db=db,
        action="TIME_ADVANCED",
        resource_type="SYSTEM",
        resource_id="SIMULATED_TIME",
        user_id=admin_user.id,
        details={
            "days_advanced": days,
            "old_offset_seconds": old_offset,
            "new_offset_seconds": new_offset,
            "effective_simulated_time": new_effective_time.isoformat(),
        },
    )

    db.commit()
    db.refresh(setting_record)

    deadline_results = None
    if run_check:
        from backend.services.deadline_service import check_all_deadlines

        deadline_results = check_all_deadlines(db, reference_time=new_effective_time)

    return {
        "status": "success",
        "message": f"Simulated time advanced by {days} day(s).",
        "real_time": real_now.isoformat(),
        "simulated_time": new_effective_time.isoformat(),
        "new_simulated_date": new_effective_time.strftime("%Y-%m-%d"),
        "offset_seconds": new_offset,
        "offset_days": round(new_offset / 86400.0, 4),
        "days_advanced": days,
        "deadline_evaluation": deadline_results,
    }


def reset_simulated_time(db: Session, admin_user: User) -> Dict[str, Any]:
    """
    Reset simulated time offset to 0.0 (synchronize back with real clock).
    Authorized for ADMIN users only.
    """
    if not settings.ENABLE_TIME_SIMULATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Time simulation is disabled in this deployment environment.",
        )

    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators are authorized to reset simulated demo time.",
        )

    old_offset = get_demo_offset_seconds(db)
    setting_record = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == SETTING_KEY_OFFSET_SECONDS)
        .first()
    )
    if setting_record:
        setting_record.value = "0.0"

    real_now = datetime.now(timezone.utc)

    # Cryptographic Audit Log
    log_audit_event(
        db=db,
        action="TIME_RESET",
        resource_type="SYSTEM",
        resource_id="SIMULATED_TIME",
        user_id=admin_user.id,
        details={
            "old_offset_seconds": old_offset,
            "new_offset_seconds": 0.0,
            "effective_simulated_time": real_now.isoformat(),
        },
    )

    db.commit()

    return {
        "status": "success",
        "message": "Simulated time offset reset to 0. Clock synchronized with real UTC time.",
        "real_time": real_now.isoformat(),
        "simulated_time": real_now.isoformat(),
        "offset_seconds": 0.0,
        "offset_days": 0.0,
    }
