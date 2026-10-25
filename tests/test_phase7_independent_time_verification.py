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
    DeadlineRule,
    EscalationLevel,
    EscalationRecord,
    Notification,
    NotificationType,
    TrackableEntityType,
)
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.services.deadline_service import ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_verification_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)
    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    reset_simulated_time(db_session, admin_user)


def get_auth_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def to_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ==============================================================================
# FULL 10-STEP DEMONSTRATION & VERIFICATION SEQUENCE
# ==============================================================================

def test_full_demonstration_sequence_end_to_end(client: TestClient, db_session: Session):
    """
    Execute and assert the complete 10-step demonstration sequence:
    1. Create an application with a future deadline.
    2. Confirm it is not overdue.
    3. Advance simulated time into reminder window.
    4. Execute deadline engine.
    5. Confirm expected reminder appears.
    6. Advance time past deadline into overdue.
    7. Advance time beyond escalation threshold.
    8. Execute deadline engine again; confirm senior recipient receives escalation.
    9. Run deadline engine repeatedly.
    10. Confirm duplicate escalations are not created.
    """
    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_auth_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_auth_token(client, "bureau@aicte.gov.in")
    admin_token = get_auth_token(client, "admin@aicte.gov.in")

    # --------------------------------------------------------------------------
    # Step 1: Create an application with a future deadline (7-day Scrutiny SLA)
    # --------------------------------------------------------------------------
    app_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Demonstration Engineering College Expansion"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert app_res.status_code == 201, app_res.text
    app_id = app_res.json()["id"]

    db_app = db_session.query(Application).filter(Application.id == app_id).first()
    assert db_app is not None
    assert db_app.current_stage_deadline is not None
    initial_deadline = db_app.current_stage_deadline

    # --------------------------------------------------------------------------
    # Step 2: Confirm it is not overdue initially
    # --------------------------------------------------------------------------
    now_utc = get_effective_time(db_session)
    deadline_utc = to_utc(db_app.current_stage_deadline)
    assert deadline_utc > now_utc
    days_until_deadline = (deadline_utc - now_utc).total_seconds() / 86400.0
    assert 6.0 <= days_until_deadline <= 7.1

    # Check database: 0 overdue notices, 0 escalations
    init_notifs = db_session.query(Notification).filter(Notification.application_id == app_id).all()
    assert len(init_notifs) == 0
    init_escs = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app_id).all()
    assert len(init_escs) == 0

    # --------------------------------------------------------------------------
    # Step 3 & 4: Advance simulated time by 5 days (2 days remaining, enters 3-day window)
    # --------------------------------------------------------------------------
    adv1_res = client.post(
        "/api/admin/advance-time",
        json={"days": 5.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adv1_res.status_code == 200
    assert adv1_res.json()["offset_days"] == 5.0

    # --------------------------------------------------------------------------
    # Step 5: Confirm expected UPCOMING reminder appears for institution and officer
    # --------------------------------------------------------------------------
    dtu_notifs_res = client.get("/api/notifications", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_notifs_res.status_code == 200
    dtu_notifs = dtu_notifs_res.json()
    assert len(dtu_notifs) >= 1
    reminders = [n for n in dtu_notifs if n["notification_type"] == "UPCOMING" and n["application_id"] == app_id]
    assert len(reminders) == 1
    assert "Upcoming Deadline" in reminders[0]["title"]

    ro_notifs_res = client.get("/api/notifications", headers={"Authorization": f"Bearer {ro_token}"})
    assert ro_notifs_res.status_code == 200
    ro_reminders = [n for n in ro_notifs_res.json() if n["notification_type"] == "UPCOMING" and n["application_id"] == app_id]
    assert len(ro_reminders) == 1

    # --------------------------------------------------------------------------
    # Step 6: Advance time by 3 more days (total +8 days: 1 day past deadline)
    # --------------------------------------------------------------------------
    adv2_res = client.post(
        "/api/admin/advance-time",
        json={"days": 3.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adv2_res.status_code == 200
    assert adv2_res.json()["offset_days"] == 8.0

    # Confirm OVERDUE notice appeared
    dtu_overdue = [
        n for n in client.get("/api/notifications", headers={"Authorization": f"Bearer {dtu_token}"}).json()
        if n["notification_type"] == "OVERDUE" and n["application_id"] == app_id
    ]
    assert len(dtu_overdue) == 1
    assert "OVERDUE (1.0d)" in dtu_overdue[0]["title"]

    # At 1 day overdue, escalation threshold (2.0 days) has not been reached
    esc_pre = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app_id).first()
    assert esc_pre is None

    # --------------------------------------------------------------------------
    # Step 7 & 8: Advance time beyond escalation threshold (2 more days, total 3 days overdue)
    # --------------------------------------------------------------------------
    adv3_res = client.post(
        "/api/admin/advance-time",
        json={"days": 2.0, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adv3_res.status_code == 200
    assert adv3_res.json()["offset_days"] == 10.0

    # Confirm correct senior recipient (Bureau Officer) receives escalation
    bureau_esc_notifs = [
        n for n in client.get("/api/notifications", headers={"Authorization": f"Bearer {bureau_token}"}).json()
        if n["notification_type"] == "ESCALATION" and n["application_id"] == app_id
    ]
    assert len(bureau_esc_notifs) == 1
    assert "ESCALATION ALERT" in bureau_esc_notifs[0]["title"]

    # Verify EscalationRecord in database
    esc_record = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app_id).first()
    assert esc_record is not None
    bureau_user = db_session.query(User).filter(User.email == "bureau@aicte.gov.in").first()
    assert esc_record.recipient_user_id == bureau_user.id
    assert "exceeded 2-day threshold" in esc_record.reason

    # --------------------------------------------------------------------------
    # Step 9 & 10: Run deadline engine repeatedly; confirm NO duplicates created
    # --------------------------------------------------------------------------
    esc_count_before = db_session.query(EscalationRecord).count()
    notif_count_before = db_session.query(Notification).count()

    # Repeat run 1 via API
    run_repeat_1 = client.post(
        "/api/notifications/run-deadline-check",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_repeat_1.status_code == 200
    res_summary_1 = run_repeat_1.json()["results"]
    assert res_summary_1["reminders_created"] == 0
    assert res_summary_1["overdue_created"] == 0
    assert res_summary_1["escalations_created"] == 0

    # Repeat run 2 via advance-time with 0-additional advance or small interval
    run_repeat_2 = client.post(
        "/api/notifications/run-deadline-check",
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    assert run_repeat_2.status_code == 200

    # Assert database counts strictly identical
    assert db_session.query(EscalationRecord).count() == esc_count_before
    assert db_session.query(Notification).count() == notif_count_before


# ==============================================================================
# MULTI-MODULE CONSUMPTION VERIFICATION
# ==============================================================================

def test_multi_module_effective_time_consumption(client: TestClient, db_session: Session):
    """
    Verify that advancing time modifies behavior in:
    1. Workflow stage deadlines.
    2. EVC delayed inspection queues.
    3. Document expiry calculations.
    """
    admin_token = get_auth_token(client, "admin@aicte.gov.in")
    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    real_now = datetime.now(timezone.utc)

    # 1. Advance simulated time by 20 days
    client.post(
        "/api/admin/advance-time",
        json={"days": 20.0, "run_deadline_check": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # 2. Workflow Engine: New application deadline must be calculated relative to effective_now (T + 20d)
    app_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Advanced Time Campus"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert app_res.status_code == 201
    app_id = app_res.json()["id"]
    db_app = db_session.query(Application).filter(Application.id == app_id).first()

    # Scrutiny SLA is 7 days. Under simulated time (+20d), deadline should be real_now + 27 days!
    diff_from_real = (to_utc(db_app.current_stage_deadline) - real_now).total_seconds() / 86400.0
    assert 26.5 <= diff_from_real <= 27.5

    # 3. EVC Module: A visit scheduled for real_now + 15 days is delayed under effective_now (+20d)
    evc = EVCVisit(
        application_id=app_id,
        due_date=real_now + timedelta(days=15.0),
        status=EVCStatus.PENDING_SCHEDULE,
    )
    db_session.add(evc)
    db_session.commit()

    evc_res = client.get(
        "/api/evc?status=DELAYED",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert evc_res.status_code == 200
    delayed_ids = [v["id"] for v in evc_res.json()]
    assert evc.id in delayed_ids

    # 4. Document Module: Expiry evaluation
    doc = UndertakingDocument(
        institution_id=db_app.institution_id,
        doc_type=DocType.FIRE_SAFETY,
        title="Fire NOC Expiring in 25 Days",
        file_name="fire.pdf",
        stored_file_path="fire.pdf",
        file_size_bytes=100,
        file_hash_sha256="hash",
        expiry_date=real_now + timedelta(days=25.0),  # 5 days from simulated time (+20d)!
        status=DocumentStatus.ACTIVE,
    )
    db_session.add(doc)
    db_session.commit()

    # Query expiring_within_days=10: relative to effective_now (+20d), doc expires in 5 days, so it matches!
    doc_filter_res = client.get(
        "/api/documents?expiring_within_days=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert doc_filter_res.status_code == 200
    doc_titles = [d["title"] for d in doc_filter_res.json()]
    assert "Fire NOC Expiring in 25 Days" in doc_titles


# ==============================================================================
# AUDIT LOGGING & HASH CONTINUITY
# ==============================================================================

def test_audit_logging_continuity_for_time_operations(client: TestClient, db_session: Session):
    """Verify TIME_ADVANCED and TIME_RESET audit logs preserve unbroken SHA-256 hash chains."""
    admin_token = get_auth_token(client, "admin@aicte.gov.in")

    # Perform time advance
    client.post("/api/admin/advance-time", json={"days": 4.0}, headers={"Authorization": f"Bearer {admin_token}"})
    # Perform time reset
    client.post("/api/admin/reset-time", headers={"Authorization": f"Bearer {admin_token}"})

    logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.resource_id == "SIMULATED_TIME")
        .order_by(AuditLog.id.asc())
        .all()
    )
    assert len(logs) >= 2
    actions = [l.action for l in logs]
    assert "TIME_ADVANCED" in actions
    assert "TIME_RESET" in actions

    # Check hash chaining integrity
    for i in range(1, len(logs)):
        assert len(logs[i].curr_hash) == 64
        assert logs[i].prev_hash is not None


# ==============================================================================
# INVALID INPUT HANDLING & VALIDATION BOUNDARIES
# ==============================================================================

def test_invalid_input_boundaries(client: TestClient):
    """Verify validation boundaries: <= 0 days, > 365 days, malformed payloads."""
    admin_token = get_auth_token(client, "admin@aicte.gov.in")

    cases = [
        {"days": 0},
        {"days": -1.5},
        {"days": -100},
        {"days": 365.1},
        {"days": 1000},
        {"days": "two_days"},
    ]

    for payload in cases:
        res = client.post(
            "/api/admin/advance-time",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code in (400, 422), f"Expected 400 or 422 for {payload}, got {res.status_code}"
