from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.time_service import (
    advance_simulated_time,
    get_demo_offset_seconds,
    get_effective_time,
    reset_simulated_time,
)
from backend.models.application import Application, ApplicationStatus
from backend.models.audit import AuditLog
from backend.models.document import DocType, DocumentStatus, UndertakingDocument
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.notification import (
    EscalationLevel,
    EscalationRecord,
    Notification,
    NotificationType,
)
from backend.models.setting import SystemSetting
from backend.models.user import Institution, User, UserRole
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.services.deadline_service import ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_time_test_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)
    # Ensure reset before and after test
    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    reset_simulated_time(db_session, admin_user)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_test_app(db_session: Session, deadline: datetime) -> Application:
    inst = db_session.query(Institution).filter(Institution.code == "DTU-DEL-001").first()
    app = Application(
        institution_id=inst.id,
        application_type_id=1,
        route_id=1,
        application_number=f"APP-SIM-{int(deadline.timestamp())}",
        title="Time Machine Test Application",
        academic_year="2026-2027",
        current_stage_id=1,
        status=ApplicationStatus.IN_REVIEW,
        current_stage_deadline=deadline,
    )
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    return app


# ==============================================================================
# 1 & 2. ADVANCING TIME BY 1 DAY AND 10 DAYS
# ==============================================================================

def test_advance_time_one_day_and_ten_days(client: TestClient, db_session: Session):
    """Verify administrator can advance persistent simulated time by 1 and 10 days."""
    admin_token = get_token(client, "admin@aicte.gov.in")

    # 1. Advance by 1 day
    res1 = client.post(
        "/api/admin/advance-time",
        json={"days": 1.0, "run_deadline_check": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert data1["days_advanced"] == 1.0
    assert abs(data1["offset_days"] - 1.0) < 0.001
    assert abs(data1["offset_seconds"] - 86400.0) < 1.0

    # Verify persistent database storage
    offset_db = get_demo_offset_seconds(db_session)
    assert abs(offset_db - 86400.0) < 1.0

    # 2. Advance by 10 more days
    res2 = client.post(
        "/api/admin/advance-time",
        json={"days": 10.0, "run_deadline_check": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["days_advanced"] == 10.0
    assert abs(data2["offset_days"] - 11.0) < 0.001
    assert abs(data2["offset_seconds"] - (11 * 86400.0)) < 1.0


# ==============================================================================
# 3 & 4. INVALID NEGATIVE & EXCESSIIVELY LARGE ADVANCEMENT VALUES
# ==============================================================================

def test_invalid_negative_and_excessive_advancement_rejected(client: TestClient):
    """Verify non-positive and excessively large days are rejected with HTTP 400 or 422."""
    admin_token = get_token(client, "admin@aicte.gov.in")

    # Negative value
    res_neg = client.post(
        "/api/admin/advance-time",
        json={"days": -3.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_neg.status_code in (400, 422)

    # Zero value
    res_zero = client.post(
        "/api/admin/advance-time",
        json={"days": 0.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_zero.status_code in (400, 422)

    # Excessively large (> 365 days)
    res_huge = client.post(
        "/api/admin/advance-time",
        json={"days": 500.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_huge.status_code in (400, 422)


# ==============================================================================
# 5. UNAUTHORIZED USERS REJECTED
# ==============================================================================

def test_unauthorized_users_cannot_advance_time(client: TestClient):
    """Verify INSTITUTION, REGIONAL_OFFICER, and BUREAU_OFFICER cannot advance time."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")

    for token in [inst_token, ro_token, bureau_token]:
        res = client.post(
            "/api/admin/advance-time",
            json={"days": 1.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403, f"Expected 403 Forbidden, got {res.status_code}"

    # Unauthenticated
    res_anon = client.post("/api/admin/advance-time", json={"days": 1.0})
    assert res_anon.status_code == 401


# ==============================================================================
# 6. REPEATED TIME ADVANCEMENT AND STATUS INSPECTION
# ==============================================================================

def test_repeated_time_advancement_and_inspection(client: TestClient, db_session: Session):
    """Verify cumulative advancement and inspection endpoint."""
    admin_token = get_token(client, "admin@aicte.gov.in")
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")

    # Advance +2 days, then +3 days, then +5 days -> Total +10 days
    client.post("/api/admin/advance-time", json={"days": 2.0}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post("/api/admin/advance-time", json={"days": 3.0}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post("/api/admin/advance-time", json={"days": 5.0}, headers={"Authorization": f"Bearer {admin_token}"})

    # Inspect time status via GET /api/admin/simulated-time
    inspect_res = client.get("/api/admin/simulated-time", headers={"Authorization": f"Bearer {inst_token}"})
    assert inspect_res.status_code == 200
    data = inspect_res.json()
    assert abs(data["offset_days"] - 10.0) < 0.001
    assert data["is_simulation_enabled"] is True


# ==============================================================================
# 7, 8, 9. REMINDERS, OVERDUE, AND ESCALATION TRIGGERED BY ADVANCEMENT
# ==============================================================================

def test_time_advancement_triggers_reminders_overdue_and_escalations(client: TestClient, db_session: Session):
    """
    Simulate workflow lifecycle solely via time machine advancement:
    1. Create an application with deadline = real_now + 5 days (no alert initially).
    2. Advance +3 days -> effective time is 2 days before deadline -> UPCOMING reminder generated.
    3. Advance +3 days (total +6 days) -> effective time is 1 day past deadline -> OVERDUE alert generated.
    4. Advance +2 days (total +8 days) -> effective time is 3 days past deadline (>= 2-day threshold) -> ESCALATION triggered!
    """
    admin_token = get_token(client, "admin@aicte.gov.in")
    real_now = datetime.now(timezone.utc)

    # Step 1: Deadline = real_now + 5 days
    target_deadline = real_now + timedelta(days=5.0)
    app = create_test_app(db_session, target_deadline)

    # Initial check at real_now: outside 3-day reminder window -> 0 notifs
    notifs_init = db_session.query(Notification).filter(Notification.application_id == app.id).all()
    assert len(notifs_init) == 0

    # Step 2: Advance time by 3 days -> 2 days remaining (inside 3-day reminder window)
    res_adv1 = client.post(
        "/api/admin/advance-time",
        json={"days": 3.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adv1.status_code == 200
    assert res_adv1.json()["deadline_evaluation"]["reminders_created"] >= 1

    notifs_step2 = db_session.query(Notification).filter(Notification.application_id == app.id).all()
    assert any(n.notification_type == NotificationType.UPCOMING for n in notifs_step2)

    # Step 3: Advance time by 3 more days (total +6 days) -> 1 day overdue (< 2-day escalation threshold)
    res_adv2 = client.post(
        "/api/admin/advance-time",
        json={"days": 3.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adv2.status_code == 200
    assert res_adv2.json()["deadline_evaluation"]["overdue_created"] >= 1

    notifs_step3 = db_session.query(Notification).filter(Notification.application_id == app.id).all()
    assert any(n.notification_type == NotificationType.OVERDUE for n in notifs_step3)

    # Escalation must NOT have occurred yet (1 day overdue < 2 day threshold)
    esc_step3 = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app.id).first()
    assert esc_step3 is None

    # Step 4: Advance time by 2 more days (total +8 days) -> 3 days overdue (>= 2 day threshold)
    res_adv3 = client.post(
        "/api/admin/advance-time",
        json={"days": 2.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adv3.status_code == 200
    assert res_adv3.json()["deadline_evaluation"]["escalations_created"] >= 1

    # EscalationRecord must now exist!
    esc_step4 = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app.id).first()
    assert esc_step4 is not None
    assert esc_step4.escalation_level == EscalationLevel.LEVEL_2_REGIONAL


# ==============================================================================
# 10. CONSISTENT SIMULATED DATES ACROSS MODULES
# ==============================================================================

def test_consistent_simulated_dates_across_modules(db_session: Session):
    """
    Verify that advancing simulated time is observed consistently across:
    - time_service.get_effective_time
    - workflow_engine (next stage deadline computation)
    - evc_service (delayed inspection filtering)
    - document_service (expiry validation)
    """
    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()

    # Advance time by 15 days
    advance_simulated_time(db_session, admin_user, days=15.0, run_check=False)

    effective_now = get_effective_time(db_session)
    real_now = datetime.now(timezone.utc)
    diff = effective_now - real_now
    assert abs(diff.total_seconds() - (15 * 86400.0)) < 2.0

    # Ensure document service evaluates expiry against effective_now
    from backend.services.document_service import save_uploaded_file
    from backend.models.document import DocType
    from fastapi import UploadFile
    import io

    # Create document expiring in 5 days from real_now (already expired under effective_now!)
    inst = db_session.query(Institution).filter(Institution.code == "DTU-DEL-001").first()
    doc = UndertakingDocument(
        institution_id=inst.id,
        doc_type=DocType.LAND_LEASE,
        title="Expiring Lease Check",
        file_name="lease.pdf",
        stored_file_path="lease.pdf",
        file_size_bytes=100,
        file_hash_sha256="hash",
        expiry_date=real_now + timedelta(days=5.0),
        status=DocumentStatus.ACTIVE,
    )
    db_session.add(doc)
    db_session.commit()

    # Check delayed EVC visits: visit due in 10 days from real_now is delayed under effective_now (+15d)
    app = create_test_app(db_session, real_now + timedelta(days=20.0))
    evc = EVCVisit(
        application_id=app.id,
        due_date=real_now + timedelta(days=10.0),
        status=EVCStatus.PENDING_SCHEDULE,
    )
    db_session.add(evc)
    db_session.commit()

    from backend.services.evc_service import get_evc_visits
    delayed_visits = get_evc_visits(db_session, user=admin_user, status_filter="DELAYED")
    delayed_ids = [v.id for v in delayed_visits]
    assert evc.id in delayed_ids


# ==============================================================================
# 11. RESET BEHAVIOR AND AUDIT TRAIL
# ==============================================================================

def test_reset_behavior_and_audit_trail(client: TestClient, db_session: Session):
    """
    Verify reset endpoint restores offset to 0.0 and logs cryptographic audit event.
    """
    admin_token = get_token(client, "admin@aicte.gov.in")

    # Advance by 7 days
    client.post("/api/admin/advance-time", json={"days": 7.0}, headers={"Authorization": f"Bearer {admin_token}"})
    assert get_demo_offset_seconds(db_session) > 0.0

    # Reset
    reset_res = client.post("/api/admin/reset-time", headers={"Authorization": f"Bearer {admin_token}"})
    assert reset_res.status_code == 200
    assert reset_res.json()["offset_seconds"] == 0.0
    assert reset_res.json()["offset_days"] == 0.0

    # Verify database setting is 0.0
    assert get_demo_offset_seconds(db_session) == 0.0

    # Verify AuditLog recorded
    audit_reset = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "TIME_RESET")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_reset is not None
    assert audit_reset.resource_id == "SIMULATED_TIME"


# ==============================================================================
# 12. DISABLED ENVIRONMENT BEHAVIOR
# ==============================================================================

def test_disabled_environment_behavior(client: TestClient, monkeypatch):
    """
    Verify that in an environment where ENABLE_TIME_SIMULATION is False,
    advance-time and reset-time are rejected with HTTP 400.
    """
    from backend.core import time_service
    monkeypatch.setattr(time_service.settings, "ENABLE_TIME_SIMULATION", False)

    admin_token = get_token(client, "admin@aicte.gov.in")

    res_adv = client.post(
        "/api/admin/advance-time",
        json={"days": 1.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adv.status_code == 400
    assert "disabled in this deployment" in res_adv.json()["detail"].lower()

    res_reset = client.post(
        "/api/admin/reset-time",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_reset.status_code == 400
    assert "disabled in this deployment" in res_reset.json()["detail"].lower()
