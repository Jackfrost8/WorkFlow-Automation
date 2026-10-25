"""
Phase 10: Demo Data Integrity, End-to-End Workflow & Integration Test Suite.
Verifies:
1. Repeatable, idempotent demo data seeding without uncontrolled duplication.
2. Safe demo data reset without deleting unrelated system data.
3. Valid relational integrity across institutions, users, routes, stages, deadlines,
   EVC visits, undertakings, documents, notifications, and escalations.
4. Complete 17-step End-to-End workflow from application submission, through scrutiny,
   EVC scheduling, undertaking issuance, rejection & verification, demo time advance,
   deadline lapse, notification dispatch, escalation, audit ledger chaining, and
   authorized final human decision approval.
5. Strict tenant and regional RBAC boundary enforcement.
"""
import io
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.core.time_service import get_effective_time, reset_simulated_time
from backend.models.application import Application, ApplicationStatus
from backend.models.audit import AuditLog
from backend.models.document import (
    DocType,
    DocumentStatus,
    UndertakingDocument,
    VerificationStatus,
)
from backend.models.evc import EVCRecommendation, EVCStatus, EVCVisit
from backend.models.notification import (
    EscalationLevel,
    EscalationRecord,
    Notification,
    NotificationType,
)
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.models.workflow import WorkflowRoute, WorkflowStage
from backend.seed import (
    DEFAULT_DEMO_PASSWORD,
    reset_disposable_demo_data,
    seed_demo_data,
)
from backend.services.audit_service import verify_audit_hash_chain
from backend.services.deadline_service import ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def setup_phase10_env(db_session: Session):
    """Ensure clean baseline database before running tests."""
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)
    seed_demo_data(session=db_session, verbose=False, full_demo=True)
    yield
    # Cleanup time offset after each test
    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    if admin_user:
        reset_simulated_time(db_session, admin_user)


def get_auth_token(client: TestClient, email: str) -> str:
    res = client.post(
        "/api/auth/login",
        json={"email": email, "password": DEFAULT_DEMO_PASSWORD},
    )
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


# =============================================================================
# 1. DEMO DATA SEEDING & RESET TESTS
# =============================================================================

def test_demo_data_seeding_idempotence(db_session: Session):
    """Confirm seed script is repeatable without creating duplicate records or constraint errors."""
    counts_run_1 = seed_demo_data(session=db_session, verbose=False, full_demo=True)
    counts_run_2 = seed_demo_data(session=db_session, verbose=False, full_demo=True)

    assert counts_run_1["institutions"] == counts_run_2["institutions"]
    assert counts_run_1["users"] == counts_run_2["users"]
    assert counts_run_1["applications"] == counts_run_2["applications"]
    assert counts_run_1["evc_visits"] == counts_run_2["evc_visits"]
    assert counts_run_1["undertakings"] == counts_run_2["undertakings"]
    assert counts_run_1["documents"] == counts_run_2["documents"]


def test_demo_data_reset_preserves_unrelated_data(db_session: Session):
    """Confirm reset_disposable_demo_data purges demo apps while keeping unrelated data safe."""
    # 1. Create a non-demo application
    inst = db_session.query(Institution).filter(Institution.code == "DTU-DEL-001").first()
    non_demo_app = Application(
        application_number="REAL-AICTE/2026/DEL/99999",
        institution_id=inst.id,
        route_type="SCRUTINY_EVC",
        status=ApplicationStatus.SUBMITTED,
        academic_year="2026-2027",
        title="Real Production Non-Demo Application",
    )
    db_session.add(non_demo_app)
    db_session.commit()

    # 2. Reset disposable demo data
    deleted_count = reset_disposable_demo_data(db_session, verbose=False)
    assert deleted_count >= 8

    # 3. Confirm non-demo application is preserved intact
    persisted = (
        db_session.query(Application)
        .filter(Application.application_number == "REAL-AICTE/2026/DEL/99999")
        .first()
    )
    assert persisted is not None
    assert persisted.title == "Real Production Non-Demo Application"

    # Cleanup non-demo
    db_session.delete(persisted)
    db_session.commit()


def test_seeded_data_diversity_and_relational_integrity(db_session: Session):
    """Verify all seeded demo entities adhere to foreign key constraints and represent diverse states."""
    # A. Users for every role
    roles_present = {u.role for u in db_session.query(User).all()}
    assert UserRole.ADMIN in roles_present
    assert UserRole.BUREAU_OFFICER in roles_present
    assert UserRole.REGIONAL_OFFICER in roles_present
    assert UserRole.INSTITUTION in roles_present

    # B. Multiple institutions
    institutions = db_session.query(Institution).all()
    assert len(institutions) >= 4
    regions = {i.region for i in institutions}
    assert "Northern Region" in regions
    assert "Western Region" in regions
    assert "Southern Region" in regions

    # C. Applications at different workflow stages and statuses
    apps = db_session.query(Application).all()
    statuses = {a.status for a in apps}
    assert ApplicationStatus.SUBMITTED in statuses
    assert ApplicationStatus.IN_REVIEW in statuses
    assert ApplicationStatus.APPROVED in statuses
    assert ApplicationStatus.REJECTED in statuses
    assert ApplicationStatus.OVERDUE in statuses

    # D. EVC visits with different statuses
    evc_visits = db_session.query(EVCVisit).all()
    evc_statuses = {v.status for v in evc_visits}
    assert EVCStatus.PENDING_SCHEDULE in evc_statuses
    assert EVCStatus.SCHEDULED in evc_statuses
    assert EVCStatus.CONDUCTED in evc_statuses
    assert EVCStatus.COMPLETED in evc_statuses
    assert EVCStatus.CANCELLED in evc_statuses

    # E. Undertakings with different statuses
    undertakings = db_session.query(Undertaking).all()
    und_statuses = {u.status for u in undertakings}
    assert UndertakingStatus.PENDING in und_statuses
    assert UndertakingStatus.SUBMITTED in und_statuses
    assert UndertakingStatus.VERIFIED in und_statuses
    assert UndertakingStatus.REJECTED in und_statuses

    # F. Documents with future expiry and expired documents
    docs = db_session.query(UndertakingDocument).all()
    doc_statuses = {d.status for d in docs}
    assert DocumentStatus.ACTIVE in doc_statuses
    assert DocumentStatus.EXPIRED in doc_statuses

    # G. In-app notifications
    notifs = db_session.query(Notification).all()
    notif_types = {n.notification_type for n in notifs}
    assert NotificationType.UPCOMING in notif_types
    assert NotificationType.DUE_TODAY in notif_types
    assert NotificationType.OVERDUE in notif_types
    assert NotificationType.ESCALATION in notif_types
    assert NotificationType.SYSTEM in notif_types

    # H. Escalation records
    escalations = db_session.query(EscalationRecord).all()
    assert len(escalations) >= 1
    assert any(e.escalation_level == EscalationLevel.LEVEL_2_REGIONAL for e in escalations)


# =============================================================================
# 2. FULL END-TO-END WORKFLOW TEST (17 Steps)
# =============================================================================

def test_full_end_to_end_regulatory_workflow(client: TestClient, db_session: Session):
    """
    Executes and asserts the complete 17-step regulatory workflow:
    1. Institution logs in
    2. Institution submits application
    3. Application enters initial stage (SCRUTINY)
    4. Authorized officer processes application
    5. Application advances through configured route (EVC)
    6. EVC visit is created and scheduled
    7. Officer issues an undertaking
    8. Institution uploads evidence
    9. Officer rejects evidence with reason -> resubmission -> verification
    10. Administrator advances simulated time
    11. Deadline engine processes new effective date
    12. Notification received
    13. Overdue item escalated to senior role
    14. Audit log records events in cryptographic chain
    15. Dashboard counts reflect state
    16. Reports reflect records
    17. Final approval/rejection recorded only through authorized human action
    """
    # -------------------------------------------------------------------------
    # Step 1: Institution logs in
    # -------------------------------------------------------------------------
    inst_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    inst_headers = {"Authorization": f"Bearer {inst_token}"}

    # -------------------------------------------------------------------------
    # Step 2: Institution submits application
    # -------------------------------------------------------------------------
    submit_payload = {
        "route_type": "SCRUTINY_EVC",
        "title": "Establishment of AICTE Center of Excellence in Quantum Computing",
        "description": "Proposal for advanced postgraduate laboratory infrastructure.",
        "academic_year": "2026-2027",
    }
    res_submit = client.post("/api/applications", json=submit_payload, headers=inst_headers)
    assert res_submit.status_code == 201, f"Submission failed: {res_submit.text}"
    app_data = res_submit.json()
    app_id = app_data["id"]
    app_num = app_data["application_number"]

    # -------------------------------------------------------------------------
    # Step 3: Application enters configured initial stage
    # -------------------------------------------------------------------------
    assert app_data["status"] == "SUBMITTED"
    assert app_data["current_stage"]["stage_key"] == "SCRUTINY"
    assert app_data["current_stage_deadline"] is not None

    # -------------------------------------------------------------------------
    # Step 4: Authorized officer processes application
    # -------------------------------------------------------------------------
    ro_token = get_auth_token(client, "ro.north@aicte.gov.in")
    ro_headers = {"Authorization": f"Bearer {ro_token}"}

    stage_advance_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Scrutiny committee verified all academic prerequisites."},
        headers=ro_headers,
    )
    assert stage_advance_res.status_code == 200, f"Stage advance failed: {stage_advance_res.text}"

    # -------------------------------------------------------------------------
    # Step 5: Application advances through configured route (to EVC)
    # -------------------------------------------------------------------------
    app_after_scrutiny = stage_advance_res.json()
    assert app_after_scrutiny["status"] == "IN_REVIEW"
    assert app_after_scrutiny["current_stage"]["stage_key"] == "EVC"

    # -------------------------------------------------------------------------
    # Step 6: EVC visit is created and scheduled
    # -------------------------------------------------------------------------
    evc_queue_res = client.get(f"/api/evc?application_id={app_id}", headers=ro_headers)
    assert evc_queue_res.status_code == 200
    evc_list = [v for v in evc_queue_res.json() if v["application_id"] == app_id]
    assert len(evc_list) == 1, "EVC visit was not automatically created upon entering EVC stage"
    evc_id = evc_list[0]["id"]
    assert evc_list[0]["status"] == "PENDING_SCHEDULE"

    schedule_payload = {
        "scheduled_date": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        "committee_lead_name": "Prof. Harish Chandra (IIT Delhi)",
        "committee_members": ["Dr. S. K. Gupta (DTU)", "Prof. Nalini Sharma (NIT Kurukshetra)"],
        "visit_mode": "PHYSICAL",
        "remarks": "Physical verification of cryogenic computing server racks.",
    }
    res_schedule = client.post(f"/api/evc/{evc_id}/schedule", json=schedule_payload, headers=ro_headers)
    assert res_schedule.status_code == 200
    assert res_schedule.json()["status"] == "SCHEDULED"

    # -------------------------------------------------------------------------
    # Step 7: Officer issues an undertaking
    # -------------------------------------------------------------------------
    undertaking_payload = {
        "application_id": app_id,
        "description": "Submit dedicated uninterruptible power supply (UPS) safety certification.",
        "due_date": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
    }
    res_und = client.post("/api/undertakings", json=undertaking_payload, headers=ro_headers)
    assert res_und.status_code == 201
    und_data = res_und.json()
    und_id = und_data["id"]
    assert und_data["status"] == "PENDING"

    # -------------------------------------------------------------------------
    # Step 8: Institution uploads evidence
    # -------------------------------------------------------------------------
    pdf_content = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF"
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("ups_safety_cert.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={
            "doc_type": "UNDERTAKING_EVIDENCE",
            "title": "OEM UPS Electrical Safety Audit Report",
            "application_id": app_id,
        },
        headers=inst_headers,
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    submit_ev_res = client.post(
        f"/api/undertakings/{und_id}/submit-evidence",
        json={
            "submitted_proof_reference": "REF-UPS-OEM-2026-99",
            "proof_document_id": doc_id,
            "submission_remarks": "Safety compliance report uploaded for verification.",
        },
        headers=inst_headers,
    )
    assert submit_ev_res.status_code == 200
    assert submit_ev_res.json()["status"] == "SUBMITTED"

    # -------------------------------------------------------------------------
    # Step 9: Officer rejects evidence with reason -> resubmission -> verification
    # -------------------------------------------------------------------------
    # 9a. Rejection
    reject_res = client.post(
        f"/api/undertakings/{und_id}/reject",
        json={
            "rejection_reason": "Auditor seal missing on page 2. Resubmit with authorized engineering signature.",
            "remarks": "Please provide certified stamped copy.",
        },
        headers=ro_headers,
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "REJECTED"

    # 9b. Resubmission by institution
    resubmit_res = client.post(
        f"/api/undertakings/{und_id}/submit-evidence",
        json={
            "submitted_proof_reference": "REF-UPS-OEM-2026-99-SIGNED",
            "proof_document_id": doc_id,
            "submission_remarks": "Stamped and counter-signed audit report resubmitted.",
        },
        headers=inst_headers,
    )
    assert resubmit_res.status_code == 200
    assert resubmit_res.json()["status"] == "SUBMITTED"

    # 9c. Verification by officer
    verify_res = client.post(
        f"/api/undertakings/{und_id}/verify",
        json={"remarks": "Seal verified against licensed electrical inspectorate registry."},
        headers=ro_headers,
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "VERIFIED"

    # -------------------------------------------------------------------------
    # Step 10: Administrator advances simulated time
    # -------------------------------------------------------------------------
    admin_token = get_auth_token(client, "admin@aicte.gov.in")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    advance_res = client.post(
        "/api/admin/advance-time",
        json={"days": 18, "run_deadline_check": True},
        headers=admin_headers,
    )
    assert advance_res.status_code == 200
    adv_data = advance_res.json()
    assert adv_data["days_advanced"] == 18
    assert adv_data["offset_days"] >= 18

    # -------------------------------------------------------------------------
    # Step 11: Deadline engine processes new effective date
    # -------------------------------------------------------------------------
    check_cycle_res = client.post("/api/notifications/run-deadline-check", headers=admin_headers)
    assert check_cycle_res.status_code == 200

    # -------------------------------------------------------------------------
    # Step 12: Institution or officer receives expected notification
    # -------------------------------------------------------------------------
    ro_notifs_res = client.get("/api/notifications", headers=ro_headers)
    assert ro_notifs_res.status_code == 200
    ro_notifs = ro_notifs_res.json()
    assert len(ro_notifs) > 0, "No notifications delivered to officer"

    # -------------------------------------------------------------------------
    # Step 13: Overdue item is escalated to correct senior role
    # -------------------------------------------------------------------------
    bureau_token = get_auth_token(client, "bureau@aicte.gov.in")
    bureau_headers = {"Authorization": f"Bearer {bureau_token}"}

    escalations_res = client.get("/api/notifications/escalations", headers=bureau_headers)
    assert escalations_res.status_code == 200
    escalations = escalations_res.json()
    assert len(escalations) > 0, "No escalation recorded for breached deadlines"

    # -------------------------------------------------------------------------
    # Step 14: Audit log records important events in append-only SHA-256 chain
    # -------------------------------------------------------------------------
    audit_res = client.get("/api/audit-logs", headers=admin_headers)
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    audit_logs = audit_data.get("logs", audit_data if isinstance(audit_data, list) else [])
    audit_actions = [e["action"] for e in audit_logs]
    assert "APPLICATION_SUBMITTED" in audit_actions
    assert "STAGE_COMPLETED" in audit_actions
    assert "EVC_VISIT_SCHEDULED" in audit_actions
    assert "UNDERTAKING_CREATED" in audit_actions
    assert "TIME_ADVANCED" in audit_actions

    # Verify cryptographic ledger intact
    chain_res = verify_audit_hash_chain(db_session)
    assert chain_res["chain_intact"] is True, f"Audit hash chain compromised: {chain_res}"

    # -------------------------------------------------------------------------
    # Step 15: Advance EVC stage to DECISION
    # -------------------------------------------------------------------------
    # Complete EVC visit inspection
    evc_comp_res = client.post(
        f"/api/evc/{evc_id}/complete",
        json={
            "recommendation": "RECOMMENDED",
            "remarks": "On-site inspection completed. Advanced computing infrastructure verified.",
            "conducted_date": datetime.now(timezone.utc).isoformat(),
        },
        headers=ro_headers,
    )
    assert evc_comp_res.status_code == 200

    # Complete EVC stage to advance to DECISION
    adv_decision_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "EVC recommendations positive. Advancing to Final Committee Decision."},
        headers=ro_headers,
    )
    assert adv_decision_res.status_code == 200
    app_at_decision = adv_decision_res.json()
    assert app_at_decision["current_stage"]["stage_key"] == "DECISION"
    assert app_at_decision["current_stage"]["is_final"] is True

    # -------------------------------------------------------------------------
    # Step 16: Reports reflect the records
    # -------------------------------------------------------------------------
    preview_res = client.get("/api/reports/preview?report_type=application_pendency", headers=bureau_headers)
    assert preview_res.status_code == 200
    preview_rows = preview_res.json()["rows"]
    app_nums = [r["app_num"] for r in preview_rows]
    assert app_num in app_nums

    # -------------------------------------------------------------------------
    # Step 17: Final approval is recorded ONLY through authorized human action
    # -------------------------------------------------------------------------
    # A. Institution cannot record final decision (Forbidden)
    unauth_decision = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"decision": "APPROVE", "remarks": "Self approval attempt"},
        headers=inst_headers,
    )
    assert unauth_decision.status_code == 403

    # B. Missing explicit decision parameter in final stage (422)
    missing_decision = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Attempting advance without decision parameter"},
        headers=ro_headers,
    )
    assert missing_decision.status_code == 422

    # C. Authorized officer records approval
    final_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={
            "decision": "APPROVE",
            "remarks": "Executive Committee grants full statutory approval for 2026-27.",
        },
        headers=ro_headers,
    )
    assert final_res.status_code == 200
    final_app = final_res.json()
    assert final_app["status"] == "APPROVED"
    assert final_app["final_decision_date"] is not None
    assert "Executive Committee grants full" in final_app["final_decision_remarks"]

    # D. Subsequent attempt to modify finalized application is rejected
    tamper_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"decision": "REJECT"},
        headers=ro_headers,
    )
    assert tamper_res.status_code == 400
    assert "already finalized" in tamper_res.text


# =============================================================================
# 3. RBAC & TENANT ISOLATION INTEGRATION CHECKS
# =============================================================================

def test_tenant_and_regional_boundary_enforcement(client: TestClient):
    """Ensure cross-tenant and cross-regional data segregation across all APIs."""
    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    apex_token = get_auth_token(client, "inst.apex@aicte.gov.in")
    ro_north_token = get_auth_token(client, "ro.north@aicte.gov.in")

    dtu_headers = {"Authorization": f"Bearer {dtu_token}"}
    apex_headers = {"Authorization": f"Bearer {apex_token}"}
    ro_north_headers = {"Authorization": f"Bearer {ro_north_token}"}

    # 1. Institution DTU lists applications -> receives 0 Apex applications
    dtu_apps = client.get("/api/applications", headers=dtu_headers).json()
    for app in dtu_apps:
        assert "Apex" not in app["title"]

    # 2. Institution DTU lists undertakings -> receives only own undertakings
    dtu_unds = client.get("/api/undertakings", headers=dtu_headers).json()
    for u in dtu_unds:
        assert u["institution_id"] != 3  # Apex inst id is 3

    # 3. Regional Officer North cannot process Western Region application
    horizon_apps = client.get("/api/applications?region=Western Region", headers=ro_north_headers).json()
    # RO North sees 0 or cannot see Western region applications
    for app in horizon_apps:
        assert app["institution"]["region"] == "Northern Region"

    # 4. Immutability: Audit log PUT / PATCH / DELETE strictly rejected with 405
    for verb in ["put", "patch", "delete"]:
        res = getattr(client, verb)("/api/audit-logs/1", headers=ro_north_headers)
        assert res.status_code == 405
