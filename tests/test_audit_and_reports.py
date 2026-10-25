import io
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.core.security import create_access_token
from backend.core.time_service import get_effective_date, get_effective_time, reset_simulated_time
from backend.database import SessionLocal
from backend.main import app
from backend.models.application import Application, ApplicationStatus
from backend.models.audit import AuditLog
from backend.models.document import DocType, UndertakingDocument
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.notification import DeadlineRule, TrackableEntityType
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.services.audit_service import (
    log_audit_event,
    sanitize_audit_details,
    verify_audit_hash_chain,
)
from backend.services.report_service import sanitize_cell_for_csv

client = TestClient(app)
DEMO_PASSWORD = "Demo@AICTE2026!"


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Ensure clean simulated time before and after tests."""
    db = SessionLocal()
    admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if admin_user:
        reset_simulated_time(db, admin_user)
    db.close()
    yield
    db = SessionLocal()
    admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if admin_user:
        reset_simulated_time(db, admin_user)
    db.close()


def get_token(email: str) -> str:
    """Obtain auth token for test user."""
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    db.close()
    if not user:
        raise ValueError(f"User {email} not found in database")
    return create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role.value})


# =====================================================================
# A. AUDIT LOG TESTS
# =====================================================================


def test_audit_log_secrets_redaction():
    """Verify that passwords, tokens, and secrets are strictly redacted in audit logs."""
    db = SessionLocal()
    sensitive_payload = {
        "user_email": "admin@aicte.gov.in",
        "password": "PlaintextPassword123!",
        "hashed_password": "$2b$12$eX4mpleH4sh...",
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "api_key": "secret-key-abcdef",
        "smtp_password": "super-secret-smtp",
        "nested": {
            "token": "nested-bearer-token",
            "safe_field": "public_data",
        },
    }

    sanitized = sanitize_audit_details(sensitive_payload)
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["hashed_password"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["smtp_password"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["safe_field"] == "public_data"
    assert sanitized["user_email"] == "admin@aicte.gov.in"

    # Test database persistence of sanitized event
    log_entry = log_audit_event(
        db=db,
        action="TEST_SENSITIVE_ACTION",
        resource_type="SYSTEM",
        resource_id="0",
        details=sensitive_payload,
    )
    db.commit()

    saved = db.query(AuditLog).filter(AuditLog.id == log_entry.id).first()
    details = json.loads(saved.details_json)
    assert details["password"] == "[REDACTED]"
    assert "PlaintextPassword123!" not in saved.details_json
    db.close()


def test_audit_events_login_success_and_failure():
    """Verify that login events (success and failure) create immutable audit logs."""
    # 1. Failed Login with invalid password
    res_fail = client.post(
        "/api/auth/login",
        json={"email": "admin@aicte.gov.in", "password": "WrongPassword999!"},
    )
    assert res_fail.status_code == 401

    db = SessionLocal()
    fail_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOGIN_FAILED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert fail_log is not None
    fail_details = json.loads(fail_log.details_json)
    assert fail_details["email"] == "admin@aicte.gov.in"
    assert "password" not in fail_details
    assert "WrongPassword999!" not in fail_log.details_json

    # 2. Successful Login
    res_succ = client.post(
        "/api/auth/login",
        json={"email": "admin@aicte.gov.in", "password": DEMO_PASSWORD},
    )
    assert res_succ.status_code == 200

    succ_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOGIN_SUCCESS")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert succ_log is not None
    succ_details = json.loads(succ_log.details_json)
    assert succ_details["email"] == "admin@aicte.gov.in"
    assert succ_details["role"] == "ADMIN"
    db.close()


def test_unauthorized_audit_log_access():
    """Verify that INSTITUTION and REGIONAL_OFFICER cannot query centralized audit logs."""
    dtu_token = get_token("inst.dtu@aicte.gov.in")
    ro_token = get_token("ro.north@aicte.gov.in")
    bureau_token = get_token("bureau@aicte.gov.in")
    admin_token = get_token("admin@aicte.gov.in")

    # Institution role -> 403 Forbidden
    res_inst = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_inst.status_code == 403

    # Regional officer role -> 403 Forbidden
    res_ro = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_ro.status_code == 403

    # Bureau officer role -> 200 OK
    res_bureau = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {bureau_token}"})
    assert res_bureau.status_code == 200
    assert "logs" in res_bureau.json()

    # Admin role -> 200 OK
    res_admin = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert "logs" in res_admin.json()


def test_audit_log_immutability_rejects_modification_and_deletion():
    """Verify that PUT, PATCH, and DELETE operations are explicitly rejected (append-only)."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Attempt PUT on audit log
    res_put = client.put("/api/audit-logs/1", headers=headers, json={"action": "MUTATED"})
    assert res_put.status_code == 405
    assert "append-only" in res_put.json()["detail"].lower()

    # Attempt PATCH on audit log
    res_patch = client.patch("/api/audit-logs/1", headers=headers, json={"action": "MUTATED"})
    assert res_patch.status_code == 405
    assert "append-only" in res_patch.json()["detail"].lower()

    # Attempt DELETE on single audit log
    res_del = client.delete("/api/audit-logs/1", headers=headers)
    assert res_del.status_code == 405
    assert "append-only" in res_del.json()["detail"].lower()

    # Attempt bulk DELETE on audit logs
    res_bulk_del = client.delete("/api/audit-logs", headers=headers)
    assert res_bulk_del.status_code == 405
    assert "append-only" in res_bulk_del.json()["detail"].lower()


def test_audit_hash_chain_integrity_verification():
    """Verify cryptographic SHA-256 hash chaining from genesis to latest record."""
    admin_token = get_token("admin@aicte.gov.in")
    res = client.get("/api/audit-logs/verify-chain", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["chain_intact"] is True
    assert data["total_records"] > 0
    assert data["broken_at_id"] is None


def test_user_and_rule_change_audit_events():
    """Verify that admin user creation, role changes, and rule updates create audit logs."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create a test officer user
    unique_email = f"audit.officer.{datetime.now().timestamp()}@aicte.gov.in"
    res_create = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": unique_email,
            "password": DEMO_PASSWORD,
            "full_name": "Audit Scrutiny Officer",
            "role": "REGIONAL_OFFICER",
            "region": "North",
        },
    )
    assert res_create.status_code == 201
    new_user_id = res_create.json()["id"]

    db = SessionLocal()
    user_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_CREATED", AuditLog.resource_id == str(new_user_id))
        .first()
    )
    assert user_log is not None
    assert unique_email in user_log.details_json

    # 2. Update user role
    res_update = client.patch(
        f"/api/v1/users/{new_user_id}",
        headers=headers,
        json={"role": "BUREAU_OFFICER"},
    )
    assert res_update.status_code == 200

    role_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_ROLE_CHANGED", AuditLog.resource_id == str(new_user_id))
        .first()
    )
    assert role_log is not None
    assert "BUREAU_OFFICER" in role_log.details_json

    # 3. Update Deadline Rule
    rule = db.query(DeadlineRule).first()
    assert rule is not None
    res_rule = client.patch(
        f"/api/notifications/rules/{rule.id}",
        headers=headers,
        json={"reminder_threshold_days": 6},
    )
    assert res_rule.status_code == 200

    rule_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DEADLINE_RULE_UPDATED", AuditLog.resource_id == str(rule.id))
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert rule_log is not None
    assert "reminder_threshold_days" in rule_log.details_json
    db.close()


# =====================================================================
# B. REPORTING & EXPORT TESTS
# =====================================================================


def test_report_types_metadata_endpoint():
    """Verify report types catalog endpoint."""
    token = get_token("bureau@aicte.gov.in")
    res = client.get("/api/reports/types", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    keys = [t["key"] for t in data["supported_types"]]
    assert "application_pendency" in keys
    assert "overdue_cases" in keys
    assert "document_validity" in keys
    assert "evc_status" in keys


def test_csv_formula_injection_prevention():
    """Verify formula characters (=, +, -, @, \\t, \\r) are sanitized to prevent spreadsheet execution."""
    assert sanitize_cell_for_csv("=SUM(A1:B10)") == "'=SUM(A1:B10)"
    assert sanitize_cell_for_csv("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_cell_for_csv("-12345") == "'-12345"
    assert sanitize_cell_for_csv("@ALERT(1)") == "'@ALERT(1)"
    assert sanitize_cell_for_csv("\tTabSeparated") == "'\tTabSeparated"
    assert sanitize_cell_for_csv("Normal University Title") == "Normal University Title"


def test_application_pendency_csv_and_pdf_export():
    """Test application pendency export in both CSV and PDF formats."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. CSV Export
    res_csv = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv",
        headers=headers,
    )
    assert res_csv.status_code == 200
    assert res_csv.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in res_csv.headers["content-disposition"]
    csv_text = res_csv.text
    assert "App Number" in csv_text
    assert "Institution" in csv_text
    assert "Proposal Title" in csv_text

    # Parse with Pandas to verify RFC 4180 CSV compliance
    df = pd.read_csv(io.StringIO(csv_text))
    assert "App Number" in df.columns
    assert "Status" in df.columns

    # 2. PDF Export
    res_pdf = client.get(
        "/api/reports/export?report_type=application_pendency&format=pdf",
        headers=headers,
    )
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF-")
    assert len(res_pdf.content) > 1000


def test_overdue_cases_report_and_time_awareness():
    """Verify overdue cases report accurately reflects demo time advancement."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Advance time by +14 days to cause statutory deadlines to lapse
    client.post("/api/admin/advance-time", headers=headers, json={"days": 14})

    # Export Overdue cases CSV
    res = client.get(
        "/api/reports/export?report_type=overdue_cases&format=csv",
        headers=headers,
    )
    assert res.status_code == 200
    df = pd.read_csv(io.StringIO(res.text))
    assert "Entity Type" in df.columns
    assert "Days Overdue" in df.columns
    assert "Due Date" in df.columns
    assert len(df) > 0  # Advancing time should have produced overdue items!


def test_document_validity_and_evc_status_exports():
    """Test document validity and EVC status exports."""
    bureau_token = get_token("bureau@aicte.gov.in")
    headers = {"Authorization": f"Bearer {bureau_token}"}

    # Document validity PDF
    res_doc = client.get(
        "/api/reports/export?report_type=document_validity&format=pdf",
        headers=headers,
    )
    assert res_doc.status_code == 200
    assert res_doc.content.startswith(b"%PDF-")

    # EVC status CSV
    res_evc = client.get(
        "/api/reports/export?report_type=evc_status&format=csv",
        headers=headers,
    )
    assert res_evc.status_code == 200
    df = pd.read_csv(io.StringIO(res_evc.text))
    assert "Visit ID" in df.columns
    assert "Visit Status" in df.columns


def test_institution_reporting_data_isolation():
    """Verify that an institution user only receives reports containing their own records."""
    dtu_token = get_token("inst.dtu@aicte.gov.in")
    coep_token = get_token("inst.coep@aicte.gov.in")

    # DTU exports application pendency
    res_dtu = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_dtu.status_code == 200
    df_dtu = pd.read_csv(io.StringIO(res_dtu.text))

    # All institutions in DTU's report must strictly be DTU
    if len(df_dtu) > 0:
        for inst_name in df_dtu["Institution"]:
            assert "Delhi" in inst_name or "DTU" in inst_name
            assert "COEP" not in inst_name

    # COEP exports application pendency
    res_coep = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv",
        headers={"Authorization": f"Bearer {coep_token}"},
    )
    assert res_coep.status_code == 200
    df_coep = pd.read_csv(io.StringIO(res_coep.text))

    # All institutions in COEP's report must strictly be COEP
    if len(df_coep) > 0:
        for inst_name in df_coep["Institution"]:
            assert "COEP" in inst_name or "Pune" in inst_name
            assert "Delhi" not in inst_name


def test_regional_officer_boundary_enforcement_in_reports():
    """Verify that Regional Officers are restricted to their region and cannot request other regions."""
    ro_north_token = get_token("ro.north@aicte.gov.in")
    ro_west_token = get_token("ro.west@aicte.gov.in")

    # RO North requests North -> 200 OK
    res_north = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&region=North",
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_north.status_code == 200
    df_north = pd.read_csv(io.StringIO(res_north.text))
    if len(df_north) > 0:
        for reg in df_north["Region"]:
            assert "NORTH" in reg.upper()

    # RO North attempts to request West -> 403 Forbidden
    res_forbidden = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&region=West",
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_forbidden.status_code == 403
    assert "assigned region" in res_forbidden.json()["detail"].lower()


def test_empty_reports_handling():
    """Verify that querying dates with no records gracefully handles empty CSV and PDF output."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Query far-future date range where 0 records exist
    future_start = "2099-01-01"
    future_end = "2099-12-31"

    # 1. Empty CSV
    res_csv = client.get(
        f"/api/reports/export?report_type=application_pendency&format=csv&start_date={future_start}&end_date={future_end}",
        headers=headers,
    )
    assert res_csv.status_code == 200
    df = pd.read_csv(io.StringIO(res_csv.text))
    assert len(df) == 0
    assert "App Number" in df.columns

    # 2. Empty PDF
    res_pdf = client.get(
        f"/api/reports/export?report_type=application_pendency&format=pdf&start_date={future_start}&end_date={future_end}",
        headers=headers,
    )
    assert res_pdf.status_code == 200
    assert res_pdf.content.startswith(b"%PDF-")


def test_invalid_filter_validation():
    """Verify input validation for unsupported report types, formats, and malformed dates."""
    admin_token = get_token("admin@aicte.gov.in")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Unsupported report type
    res_type = client.get(
        "/api/reports/export?report_type=invalid_type&format=csv",
        headers=headers,
    )
    assert res_type.status_code == 400
    assert "Unsupported report type" in res_type.json()["detail"]

    # Unsupported format
    res_fmt = client.get(
        "/api/reports/export?report_type=application_pendency&format=docx",
        headers=headers,
    )
    assert res_fmt.status_code == 400
    assert "Unsupported format" in res_fmt.json()["detail"]

    # Malformed date
    res_date = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&start_date=not-a-date",
        headers=headers,
    )
    assert res_date.status_code == 400
    assert "Invalid start_date format" in res_date.json()["detail"]

    # start_date > end_date
    res_order = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&start_date=2026-12-01&end_date=2026-01-01",
        headers=headers,
    )
    assert res_order.status_code == 400
    assert "start_date cannot be later than end_date" in res_order.json()["detail"]


def test_report_preview_endpoint():
    """Verify JSON preview endpoint for frontend UI tables."""
    officer_token = get_token("ro.north@aicte.gov.in")
    res = client.get(
        "/api/reports/preview?report_type=application_pendency&limit=5",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["report_type"] == "application_pendency"
    assert "columns" in data
    assert "rows" in data
    assert isinstance(data["rows"], list)
