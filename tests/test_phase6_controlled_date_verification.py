import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.background.scheduler import get_scheduler_instance, shutdown_scheduler, start_scheduler
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
def setup_review_environment(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_app(
    db_session: Session,
    inst_code: str,
    deadline_offset_days: float,
    ref_time: datetime,
) -> Application:
    inst = db_session.query(Institution).filter(Institution.code == inst_code).first()
    app = Application(
        institution_id=inst.id,
        application_type_id=1,
        route_id=1,
        application_number=f"APP-CTRL-{int(ref_time.timestamp())}-{inst.id}-{int(deadline_offset_days*10)}",
        title=f"Controlled Date Test App ({inst.code})",
        academic_year="2026-2027",
        current_stage_id=1,
        status=ApplicationStatus.IN_REVIEW,
        current_stage_deadline=ref_time + timedelta(days=deadline_offset_days),
    )
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    return app


# ==============================================================================
# 1 & 2. PREMATURE REMINDERS PREVENTED & IN-WINDOW REMINDERS GENERATED
# ==============================================================================

def test_premature_reminders_prevented_and_in_window_generated(db_session: Session):
    """
    Controlled date test:
    - Base time = 2026-10-25 10:00:00 UTC.
    - Rule reminder threshold = 3.0 days.
    - App A due in +5.0 days (outside window): MUST NOT receive reminder.
    - App B due in +2.0 days (inside window): MUST receive UPCOMING reminder.
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

    # App A outside window
    app_outside = create_app(db_session, "DTU-DEL-001", deadline_offset_days=5.0, ref_time=ref_time)
    # App B inside window
    app_inside = create_app(db_session, "COEP-MAH-002", deadline_offset_days=2.0, ref_time=ref_time)

    summary = check_all_deadlines(db_session, reference_time=ref_time)

    # 1. Verify App A has ZERO notifications in database
    notifs_outside = (
        db_session.query(Notification)
        .filter(Notification.application_id == app_outside.id)
        .all()
    )
    assert len(notifs_outside) == 0, f"Expected 0 premature notifications, found: {len(notifs_outside)}"

    # 2. Verify App B has UPCOMING notification in database
    notifs_inside = (
        db_session.query(Notification)
        .filter(Notification.application_id == app_inside.id)
        .all()
    )
    assert len(notifs_inside) >= 1
    assert any(n.notification_type == NotificationType.UPCOMING for n in notifs_inside)
    assert any("Upcoming Deadline" in n.title for n in notifs_inside)


# ==============================================================================
# 3. DUE-TODAY BEHAVIOR
# ==============================================================================

def test_due_today_behavior(db_session: Session):
    """
    Controlled date test:
    - Item due in 0.4 days (~9.6 hours) from reference time.
    - Must be classified as NotificationType.DUE_TODAY with title 'Action Required Today'.
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    app_today = create_app(db_session, "DTU-DEL-001", deadline_offset_days=0.4, ref_time=ref_time)

    check_all_deadlines(db_session, reference_time=ref_time)

    notifs = (
        db_session.query(Notification)
        .filter(Notification.application_id == app_today.id)
        .all()
    )
    assert len(notifs) >= 1
    due_today_notifs = [n for n in notifs if n.notification_type == NotificationType.DUE_TODAY]
    assert len(due_today_notifs) >= 1
    assert "Action Required Today" in due_today_notifs[0].title


# ==============================================================================
# 4. OVERDUE ITEMS IDENTIFICATION & HUMAN AUTHORITY
# ==============================================================================

def test_overdue_identification_without_workflow_mutation(db_session: Session):
    """
    Controlled date test:
    - Item lapsed by 1.2 days (overdue, but below 2.0-day escalation threshold).
    - Notification type must be OVERDUE.
    - Application status must remain unchanged (human authority preserved).
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    app_overdue = create_app(db_session, "DTU-DEL-001", deadline_offset_days=-1.2, ref_time=ref_time)

    initial_status = app_overdue.status
    check_all_deadlines(db_session, reference_time=ref_time)

    # In-app notification generated
    overdue_notif = (
        db_session.query(Notification)
        .filter(Notification.application_id == app_overdue.id, Notification.notification_type == NotificationType.OVERDUE)
        .first()
    )
    assert overdue_notif is not None
    assert "OVERDUE (1.2d)" in overdue_notif.title

    # Escalation record must NOT exist yet (1.2d < 2.0d threshold)
    esc = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app_overdue.id).first()
    assert esc is None

    # Application status strictly preserved
    db_session.refresh(app_overdue)
    assert app_overdue.status == initial_status


# ==============================================================================
# 5 & 6. ESCALATION THRESHOLDS & CONFIGURED RECIPIENTS
# ==============================================================================

def test_escalation_threshold_and_recipient_scoping(db_session: Session):
    """
    Controlled date test:
    - Item lapsed by 1.9 days (< 2.0 threshold) -> NO escalation.
    - Item lapsed by 2.1 days (>= 2.0 threshold) -> Escalates to configured recipient.
    - Reconfigure rule to UserRole.ADMIN -> Escalates to Admin.
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Borderline item: lapsed by 1.9 days -> Should NOT escalate
    app_borderline = create_app(db_session, "DTU-DEL-001", deadline_offset_days=-1.9, ref_time=ref_time)
    check_all_deadlines(db_session, reference_time=ref_time)

    esc_borderline = (
        db_session.query(EscalationRecord)
        .filter(EscalationRecord.application_id == app_borderline.id)
        .first()
    )
    assert esc_borderline is None

    # 2. Exceeded item: lapsed by 2.5 days -> Must escalate to configured Bureau Officer
    app_exceeded = create_app(db_session, "COEP-MAH-002", deadline_offset_days=-2.5, ref_time=ref_time)
    check_all_deadlines(db_session, reference_time=ref_time)

    esc_exceeded = (
        db_session.query(EscalationRecord)
        .filter(EscalationRecord.application_id == app_exceeded.id)
        .first()
    )
    assert esc_exceeded is not None
    bureau_user = db_session.query(User).filter(User.role == UserRole.BUREAU_OFFICER).first()
    assert esc_exceeded.recipient_user_id == bureau_user.id

    # 3. Reconfigure rule: change escalation recipient to ADMIN
    rule = db_session.query(DeadlineRule).filter(DeadlineRule.entity_type == TrackableEntityType.APPLICATION_STAGE).first()
    rule.escalation_recipient_role = UserRole.ADMIN
    db_session.commit()

    app_admin_target = create_app(db_session, "DTU-DEL-001", deadline_offset_days=-3.0, ref_time=ref_time)
    check_all_deadlines(db_session, reference_time=ref_time)

    esc_admin = (
        db_session.query(EscalationRecord)
        .filter(EscalationRecord.application_id == app_admin_target.id)
        .first()
    )
    assert esc_admin is not None
    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    assert esc_admin.recipient_user_id == admin_user.id


# ==============================================================================
# 7. REPEATED CHECKS DO NOT GENERATE DUPLICATES
# ==============================================================================

def test_repeated_checks_idempotency_audit(db_session: Session):
    """
    Verify that executing deadline checks multiple times across the day
    does NOT duplicate notifications or escalations for the same entity and cycle.
    """
    ref_time_1 = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    create_app(db_session, "DTU-DEL-001", deadline_offset_days=1.5, ref_time=ref_time_1)
    create_app(db_session, "COEP-MAH-002", deadline_offset_days=-3.0, ref_time=ref_time_1)

    # Initial Run
    check_all_deadlines(db_session, reference_time=ref_time_1)
    n_count_1 = db_session.query(Notification).count()
    e_count_1 = db_session.query(EscalationRecord).count()
    a_count_1 = db_session.query(AuditLog).filter(AuditLog.action == "SLA_ESCALATION").count()

    # Second Run (same reference time)
    check_all_deadlines(db_session, reference_time=ref_time_1)
    assert db_session.query(Notification).count() == n_count_1
    assert db_session.query(EscalationRecord).count() == e_count_1
    assert db_session.query(AuditLog).filter(AuditLog.action == "SLA_ESCALATION").count() == a_count_1

    # Third Run (2 hours later on same calendar day)
    ref_time_2 = ref_time_1 + timedelta(hours=2)
    check_all_deadlines(db_session, reference_time=ref_time_2)
    assert db_session.query(Notification).count() == n_count_1
    assert db_session.query(EscalationRecord).count() == e_count_1


# ==============================================================================
# 8. DISABLED RULES RESPECTED
# ==============================================================================

def test_disabled_rules_respected_in_database(db_session: Session):
    """Verify that disabled rules produce 0 notifications and 0 escalations."""
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    app = create_app(db_session, "DTU-DEL-001", deadline_offset_days=-5.0, ref_time=ref_time)

    rule = db_session.query(DeadlineRule).filter(DeadlineRule.entity_type == TrackableEntityType.APPLICATION_STAGE).first()
    rule.is_active = False
    db_session.commit()

    summary = check_all_deadlines(db_session, reference_time=ref_time)
    app_notifs = db_session.query(Notification).filter(Notification.application_id == app.id).all()
    app_escs = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app.id).all()

    assert len(app_notifs) == 0
    assert len(app_escs) == 0


# ==============================================================================
# 9. MISSING RECIPIENTS HANDLED SAFELY
# ==============================================================================

def test_missing_recipients_safe_resolution(db_session: Session):
    """
    Verify that an institution in an unmapped region without a regional officer
    safely defaults to Bureau Officer or Admin without unhandled exceptions.
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    ghost_inst = Institution(
        name="Ghost Campus Overseas",
        code="GHOST-999",
        region="Unassigned Antarctica",
        contact_email="ghost@aicte.gov.in",
    )
    db_session.add(ghost_inst)
    db_session.commit()

    app = create_app(db_session, "GHOST-999", deadline_offset_days=-4.0, ref_time=ref_time)

    # Must complete cleanly
    summary = check_all_deadlines(db_session, reference_time=ref_time)
    assert summary["escalations_created"] >= 1

    esc = db_session.query(EscalationRecord).filter(EscalationRecord.application_id == app.id).first()
    assert esc is not None
    assert esc.recipient_user_id is not None  # Successfully resolved to Bureau or Admin fallback


# ==============================================================================
# 10. NOTIFICATION ACCESS PROPERLY RESTRICTED VIA API
# ==============================================================================

def test_in_app_notification_api_access_restriction(client: TestClient, db_session: Session):
    """
    API security test:
    1. Institution cannot view other institution's notifications.
    2. Institution cannot mark other user's notification as read.
    3. Institution cannot access escalation records (/api/notifications/escalations -> 403).
    4. Only Bureau Officer and Admin can access and update deadline rules.
    """
    dtu_user = db_session.query(User).filter(User.email == "inst.dtu@aicte.gov.in").first()
    coep_user = db_session.query(User).filter(User.email == "inst.coep@aicte.gov.in").first()

    notif_dtu = Notification(user_id=dtu_user.id, title="DTU Private Notice", message="Secret", notification_type=NotificationType.UPCOMING)
    notif_coep = Notification(user_id=coep_user.id, title="COEP Private Notice", message="Secret", notification_type=NotificationType.UPCOMING)
    db_session.add_all([notif_dtu, notif_coep])
    db_session.commit()

    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")
    admin_token = get_token(client, "admin@aicte.gov.in")

    # 1. Privacy filter on list
    res_dtu = client.get("/api/notifications", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_dtu.status_code == 200
    ids = [n["id"] for n in res_dtu.json()]
    assert notif_dtu.id in ids
    assert notif_coep.id not in ids

    # 2. Cross-user read attempt -> 403 Forbidden
    res_hack = client.post(f"/api/notifications/{notif_dtu.id}/read", headers={"Authorization": f"Bearer {coep_token}"})
    assert res_hack.status_code == 403

    # 3. Escalations list forbidden for institutions -> 403 Forbidden
    res_esc_inst = client.get("/api/notifications/escalations", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_esc_inst.status_code == 403

    # 4. Escalations list allowed for officers -> 200 OK
    res_esc_ro = client.get("/api/notifications/escalations", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_esc_ro.status_code == 200

    # 5. Rules update forbidden for institutions and ROs -> 403 Forbidden
    res_rule_ro = client.patch("/api/notifications/rules/1", json={"reminder_threshold_days": 5}, headers={"Authorization": f"Bearer {ro_token}"})
    assert res_rule_ro.status_code == 403

    # 6. Rules update permitted for Admin -> 200 OK
    res_rule_admin = client.patch("/api/notifications/rules/1", json={"reminder_threshold_days": 5}, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_rule_admin.status_code == 200
    assert res_rule_admin.json()["reminder_threshold_days"] == 5


# ==============================================================================
# 11. EMAIL FAILURES DO NOT PREVENT IN-APP NOTIFICATIONS
# ==============================================================================

def test_email_failure_does_not_abort_in_app_notification(db_session: Session, monkeypatch):
    """
    Verify that an SMTP socket timeout or connection refused exception
    does NOT crash the engine or abort in-app notification creation.
    """
    from backend.services import email_service
    monkeypatch.setattr(email_service.settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "invalid-smtp-host.invalid")
    monkeypatch.setattr(email_service.settings, "SMTP_PORT", 25)

    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    app = create_app(db_session, "DTU-DEL-001", deadline_offset_days=1.0, ref_time=ref_time)

    summary = check_all_deadlines(db_session, reference_time=ref_time)
    assert summary["emails_attempted"] > 0
    assert summary["emails_sent"] == 0
    assert summary["reminders_created"] > 0

    # Notification safely exists in database
    notif = db_session.query(Notification).filter(Notification.application_id == app.id).first()
    assert notif is not None


# ==============================================================================
# 12. AUDIT EVENTS ARE RECORDED CORRECTLY
# ==============================================================================

def test_escalation_audit_event_integrity(db_session: Session):
    """
    Verify that every escalation event produces a valid SHA-256 chained audit record
    with proper action, details JSON, and non-empty hash.
    """
    ref_time = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    app = create_app(db_session, "COEP-MAH-002", deadline_offset_days=-4.0, ref_time=ref_time)

    check_all_deadlines(db_session, reference_time=ref_time)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "SLA_ESCALATION", AuditLog.resource_id == str(app.id))
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.resource_type == "APPLICATION_STAGE"
    assert audit_entry.curr_hash is not None
    assert len(audit_entry.curr_hash) == 64  # SHA-256 hex string

    # Verify JSON details contain threshold and recipient details
    details = json.loads(audit_entry.details_json)
    assert "lapsed_days" in details
    assert "threshold_days" in details
    assert "recipient_role" in details


# ==============================================================================
# 13. SCHEDULER INITIALIZATION DOES NOT CREATE DUPLICATE JOBS
# ==============================================================================

def test_scheduler_initialization_no_duplicate_jobs():
    """
    Verify that repeated start_scheduler() invocations do NOT create duplicate jobs
    in the APScheduler background job store.
    """
    shutdown_scheduler()
    res1 = start_scheduler()
    assert res1 is True

    # Attempt second start in same process
    res2 = start_scheduler()
    assert res2 is False

    # Check job registry
    sched = get_scheduler_instance()
    assert sched is not None
    jobs = sched.get_jobs()
    matching_jobs = [j for j in jobs if j.id == "aicte_deadline_engine_job"]
    assert len(matching_jobs) == 1, f"Expected exactly 1 scheduled job, found: {len(matching_jobs)}"
    shutdown_scheduler()
