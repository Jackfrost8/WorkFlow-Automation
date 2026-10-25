from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.background.scheduler import run_deadline_check_manual, start_scheduler
from backend.config import get_settings
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
from backend.services.deadline_service import check_all_deadlines, ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_deadline_test_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_test_application(
    db_session: Session,
    institution_code: str = "DTU-DEL-001",
    deadline_offset_days: float = 2.0,
    ref_time: Optional[datetime] = None,
) -> Application:
    base = ref_time or datetime.now(timezone.utc)
    inst = db_session.query(Institution).filter(Institution.code == institution_code).first()
    deadline = base + timedelta(days=deadline_offset_days)

    app = Application(
        institution_id=inst.id,
        application_type_id=1,
        route_id=1,
        application_number=f"APP-TEST-{int(base.timestamp())}-{inst.id}",
        title=f"Test Application {inst.name}",
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
# 1. UPCOMING REMINDERS & DUE TODAY
# ==============================================================================

def test_upcoming_reminders_and_due_today(db_session: Session):
    """
    Verify reminders generated for items approaching deadline:
    - 2 days remaining (within 3-day reminder threshold) -> UPCOMING
    - 0.5 days remaining (due today) -> DUE_TODAY
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    # 1. App due in 2 days
    app_upcoming = create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=2.0, ref_time=base_time)
    # 2. App due today (in 10 hours)
    app_today = create_test_application(db_session, "COEP-MAH-002", deadline_offset_days=0.4, ref_time=base_time)

    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["reminders_created"] >= 2

    # Check notification records
    notifs = db_session.query(Notification).filter(Notification.application_id.in_([app_upcoming.id, app_today.id])).all()
    assert len(notifs) >= 2

    today_notif = [n for n in notifs if n.application_id == app_today.id and n.notification_type == NotificationType.DUE_TODAY]
    assert len(today_notif) >= 1
    assert "Today" in today_notif[0].title

    upcoming_notif = [n for n in notifs if n.application_id == app_upcoming.id and n.notification_type == NotificationType.UPCOMING]
    assert len(upcoming_notif) >= 1
    assert "Upcoming" in upcoming_notif[0].title


# ==============================================================================
# 2. OVERDUE ITEMS & HUMAN AUTHORITY PRESERVATION
# ==============================================================================

def test_overdue_items_generation(db_session: Session):
    """
    Verify overdue notices generated when due date has passed.
    Crucial: Workflow application status must NOT be auto-transitioned.
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    # Lapsed 1 day ago (below 2-day escalation threshold)
    app_overdue = create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=-1.0, ref_time=base_time)
    initial_status = app_overdue.status

    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["overdue_created"] >= 1

    # In-app notification with OVERDUE type
    overdue_notif = (
        db_session.query(Notification)
        .filter(Notification.application_id == app_overdue.id, Notification.notification_type == NotificationType.OVERDUE)
        .first()
    )
    assert overdue_notif is not None
    assert "OVERDUE" in overdue_notif.title

    # Human authority check: status remains unchanged
    db_session.refresh(app_overdue)
    assert app_overdue.status == initial_status


# ==============================================================================
# 3. SLA ESCALATIONS & AUDIT LOGGING
# ==============================================================================

def test_escalation_thresholds_and_audit_event(db_session: Session):
    """
    Verify that when overdue days exceed escalation threshold:
    - Senior officer is notified.
    - EscalationRecord is persisted.
    - Cryptographic SHA-256 audit entry is logged.
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    # Lapsed 4 days ago (exceeds 2-day threshold)
    app_escalated = create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=-4.0, ref_time=base_time)

    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["escalations_created"] >= 1

    # Verify EscalationRecord
    esc_record = (
        db_session.query(EscalationRecord)
        .filter(EscalationRecord.application_id == app_escalated.id)
        .first()
    )
    assert esc_record is not None
    assert esc_record.escalation_level == EscalationLevel.LEVEL_2_REGIONAL
    assert esc_record.recipient_user_id is not None
    assert "exceeded 2-day threshold" in esc_record.reason

    # Verify AuditLog
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "SLA_ESCALATION", AuditLog.resource_id == str(app_escalated.id))
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.curr_hash is not None
    assert audit_entry.prev_hash is not None


# ==============================================================================
# 4. REPEATED SCHEDULER EXECUTION & DUPLICATE PREVENTION
# ==============================================================================

def test_repeated_scheduler_execution_and_duplicate_prevention(db_session: Session):
    """
    Verify engine idempotency: executing the deadline check repeatedly
    does NOT duplicate notifications or escalation records.
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    # Create 1 upcoming, 1 overdue, and 1 escalated item
    create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=1.5, ref_time=base_time)
    create_test_application(db_session, "COEP-MAH-002", deadline_offset_days=-4.0, ref_time=base_time)

    # Run 1: Should create alerts
    run1 = check_all_deadlines(db_session, reference_time=base_time)
    notif_count_1 = db_session.query(Notification).count()
    esc_count_1 = db_session.query(EscalationRecord).count()
    assert notif_count_1 > 0
    assert esc_count_1 > 0

    # Run 2: Immediately afterwards with identical reference time -> 0 duplicates
    run2 = check_all_deadlines(db_session, reference_time=base_time)
    assert run2["reminders_created"] == 0
    assert run2["overdue_created"] == 0
    assert run2["escalations_created"] == 0

    notif_count_2 = db_session.query(Notification).count()
    esc_count_2 = db_session.query(EscalationRecord).count()
    assert notif_count_2 == notif_count_1
    assert esc_count_2 == esc_count_1

    # Run 3: Repeat again
    run3 = check_all_deadlines(db_session, reference_time=base_time)
    assert run3["reminders_created"] == 0
    assert run3["escalations_created"] == 0


# ==============================================================================
# 5. DISABLED RULES & CONFIGURATION
# ==============================================================================

def test_disabled_rules_are_skipped(db_session: Session):
    """Verify that deactivating a rule causes that entity type to be ignored."""
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=-5.0, ref_time=base_time)

    # Disable APPLICATION_STAGE rule
    rule = db_session.query(DeadlineRule).filter(DeadlineRule.entity_type == TrackableEntityType.APPLICATION_STAGE).first()
    rule.is_active = False
    db_session.commit()

    summary = check_all_deadlines(db_session, reference_time=base_time)
    # No notifications or escalations created for application stage
    notifs = db_session.query(Notification).filter(Notification.entity_type == "APPLICATION_STAGE").all()
    assert len(notifs) == 0


# ==============================================================================
# 6. MISSING RECIPIENTS FALLBACK BEHAVIOR
# ==============================================================================

def test_missing_regional_officer_falls_back_to_admin(db_session: Session):
    """
    Verify that if an item belongs to an unassigned region, recipient resolution
    falls back cleanly to Bureau Officer / Admin without crashing.
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    # Create institution in an unrepresented region
    exotic_inst = Institution(
        name="North East Frontier Institute",
        code="NEFI-001",
        region="North-Eastern Frontier Region",  # No RO exists for this region in seed!
        contact_email="nefi@aicte.gov.in",
    )
    db_session.add(exotic_inst)
    db_session.commit()

    app = create_test_application(db_session, "NEFI-001", deadline_offset_days=-5.0, ref_time=base_time)

    # Should execute cleanly without unhandled exception
    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["escalations_created"] >= 1

    esc = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app.id).first()
    assert esc is not None
    # Recipient resolved to fallback senior officer
    assert esc.recipient_user_id is not None


# ==============================================================================
# 7. NOTIFICATION PRIVACY ISOLATION & API ENDPOINTS
# ==============================================================================

def test_notification_privacy_isolation(client: TestClient, db_session: Session):
    """Verify that users can only see and mark their own notifications."""
    dtu_user = db_session.query(User).filter(User.email == "inst.dtu@aicte.gov.in").first()
    coep_user = db_session.query(User).filter(User.email == "inst.coep@aicte.gov.in").first()

    # Create 1 notification for DTU and 1 for COEP
    n_dtu = Notification(user_id=dtu_user.id, title="DTU Confidential", message="Private", notification_type=NotificationType.UPCOMING)
    n_coep = Notification(user_id=coep_user.id, title="COEP Confidential", message="Private", notification_type=NotificationType.UPCOMING)
    db_session.add_all([n_dtu, n_coep])
    db_session.commit()

    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")

    # 1. DTU list only contains DTU notification
    res_dtu = client.get("/api/notifications", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_dtu.status_code == 200
    ids = [n["id"] for n in res_dtu.json()]
    assert n_dtu.id in ids
    assert n_coep.id not in ids

    # 2. COEP attempts to mark DTU's notification as read -> 403 Forbidden
    hack_res = client.post(
        f"/api/notifications/{n_dtu.id}/read",
        headers={"Authorization": f"Bearer {coep_token}"},
    )
    assert hack_res.status_code == 403

    # 3. DTU marks their own notification as read -> 200 OK
    read_res = client.post(
        f"/api/notifications/{n_dtu.id}/read",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert read_res.status_code == 200
    assert read_res.json()["is_read"] is True


# ==============================================================================
# 8. EMAIL DELIVERY FAILURE RESILIENCE
# ==============================================================================

def test_email_delivery_failure_resilience(db_session: Session, monkeypatch):
    """
    Verify that when SMTP delivery fails:
    - Attempt is recorded.
    - Delivery failure does NOT crash or abort the transaction.
    - In-app notification is still successfully persisted.
    """
    from backend.services import email_service
    # Enable SMTP but with an unreachable port
    monkeypatch.setattr(email_service.settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(email_service.settings, "SMTP_PORT", 65530)  # closed port

    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    app = create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=1.0, ref_time=base_time)

    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["emails_attempted"] > 0
    assert summary["emails_sent"] == 0  # Delivery failed as expected
    assert summary["reminders_created"] > 0  # In-app notification still created!

    # Verify notification exists in DB despite email failure
    notif = db_session.query(Notification).filter(Notification.application_id == app.id).first()
    assert notif is not None


# ==============================================================================
# 9. SCHEDULER SINGLETON SAFETY
# ==============================================================================

def test_scheduler_singleton_startup():
    """Verify that starting the scheduler multiple times is idempotent."""
    res1 = start_scheduler()
    res2 = start_scheduler()
    # Second invocation should detect existing instance and return False
    assert res2 is False


# ==============================================================================
# 10. MULTI-ENTITY TRACKING (EVC, UNDERTAKING, DOCUMENT EXPIRY)
# ==============================================================================

def test_all_four_entity_types_tracked(db_session: Session):
    """
    Verify that EVC visits, undertakings, and documents with deadlines
    are all tracked by the common deadline engine interface.
    """
    base_time = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    app = create_test_application(db_session, "DTU-DEL-001", deadline_offset_days=10.0, ref_time=base_time)

    # 1. EVC Visit due in 2 days (within 3-day threshold)
    evc = EVCVisit(
        application_id=app.id,
        due_date=base_time + timedelta(days=2.0),
        status=EVCStatus.PENDING_SCHEDULE,
    )
    # 2. Undertaking due in 4 days (within 5-day threshold)
    undertaking = Undertaking(
        application_id=app.id,
        institution_id=app.institution_id,
        description="Build ramps",
        due_date=base_time + timedelta(days=4.0),
        status=UndertakingStatus.PENDING,
    )
    # 3. Document expiring in 15 days (within 30-day threshold)
    doc = UndertakingDocument(
        institution_id=app.institution_id,
        doc_type=DocType.FIRE_SAFETY,
        title="Expiring Fire NOC",
        file_name="fire.pdf",
        stored_file_path="fire.pdf",
        file_size_bytes=100,
        file_hash_sha256="abc",
        expiry_date=base_time + timedelta(days=15.0),
        status=DocumentStatus.ACTIVE,
    )
    db_session.add_all([evc, undertaking, doc])
    db_session.commit()

    summary = check_all_deadlines(db_session, reference_time=base_time)
    assert summary["reminders_created"] >= 3

    # Check that notifications exist for EVC, UNDERTAKING, and DOCUMENT_EXPIRY
    notifs = db_session.query(Notification).all()
    entity_types = {n.entity_type for n in notifs}
    assert "EVC_VISIT" in entity_types
    assert "UNDERTAKING" in entity_types
    assert "DOCUMENT_EXPIRY" in entity_types
