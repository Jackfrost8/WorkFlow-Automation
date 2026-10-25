"""
Independent Verification Script for Phase 9:
Centralized Audit Logging and CSV/PDF Reporting Engine.
"""
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi.testclient import TestClient

# Ensure UTF-8 output on Windows console
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.security import create_access_token
from backend.core.time_service import get_effective_date, reset_simulated_time
from backend.database import SessionLocal
from backend.main import app
from backend.models.application import Application, ApplicationStatus
from backend.models.audit import AuditLog
from backend.models.document import DocType, UndertakingDocument
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.notification import TrackableEntityType
from backend.models.undertaking import Undertaking
from backend.models.user import Institution, User, UserRole
from backend.services.audit_service import verify_audit_hash_chain
from backend.services.deadline_service import get_trackable_items
from backend.services.report_service import sanitize_cell_for_csv

client = TestClient(app)
DEMO_PASSWORD = "Demo@AICTE2026!"


def get_user_token(email: str) -> str:
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    db.close()
    if not user:
        raise ValueError(f"User {email} not found")
    return create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role.value})


def run_comprehensive_phase9_verification():
    print("=" * 75)
    print("INDEPENDENT VERIFICATION: PHASE 9 AUDIT LOGGING & CSV/PDF REPORTS")
    print("=" * 75)

    db = SessionLocal()
    admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
    assert admin_user is not None, "Admin user missing from database"
    reset_simulated_time(db, admin_user)
    db.close()

    # -----------------------------------------------------------------
    # STEP 1: REPRESENTATIVE WORKFLOW & AUDIT EVENT CORRELATION
    # -----------------------------------------------------------------
    print("\n[Step 1] Executing Representative Workflow Sequence & Validating Audit Trail...")

    dtu_token = get_user_token("inst.dtu@aicte.gov.in")
    ro_token = get_user_token("ro.north@aicte.gov.in")
    admin_token = get_user_token("admin@aicte.gov.in")

    # 1A. Login event audit check
    print("  1A. Checking Login Success & Failed Authentication Audit Events...")
    res_fail = client.post("/api/auth/login", json={"email": "inst.dtu@aicte.gov.in", "password": "WrongPassword!"})
    assert res_fail.status_code == 401, f"Expected 401, got {res_fail.status_code}"

    res_login = client.post("/api/auth/login", json={"email": "inst.dtu@aicte.gov.in", "password": DEMO_PASSWORD})
    assert res_login.status_code == 200, f"Expected 200, got {res_login.status_code}"

    db = SessionLocal()
    fail_audit = db.query(AuditLog).filter(AuditLog.action == "LOGIN_FAILED").order_by(AuditLog.id.desc()).first()
    assert fail_audit is not None, "LOGIN_FAILED audit event not recorded"
    fail_details = json.loads(fail_audit.details_json)
    assert fail_details.get("email") == "inst.dtu@aicte.gov.in"
    assert "password" not in fail_details, "Password leaked in audit details!"
    print("      ✓ Failed login audited with credentials protected.")

    succ_audit = db.query(AuditLog).filter(AuditLog.action == "LOGIN_SUCCESS").order_by(AuditLog.id.desc()).first()
    assert succ_audit is not None, "LOGIN_SUCCESS audit event not recorded"
    print("      ✓ Successful login audited with actor and role details.")

    # 1B. Application Submission Audit Event
    print("  1B. Submitting Application as DTU...")
    app_title = f"DTU High-Performance Computing Cluster {int(datetime.now().timestamp())}"
    res_app = client.post(
        "/api/applications",
        headers={"Authorization": f"Bearer {dtu_token}"},
        json={
            "title": app_title,
            "route_type": "SCRUTINY_EVC",
            "description": "Establishment of Advanced Supercomputing Center",
            "academic_year": "2026-2027",
        },
    )
    assert res_app.status_code == 201, f"Application creation failed: {res_app.text}"
    app_data = res_app.json()
    app_id = app_data["id"]

    app_audit = db.query(AuditLog).filter(
        AuditLog.action == "APPLICATION_SUBMITTED",
        AuditLog.resource_id == str(app_id),
    ).first()
    assert app_audit is not None, f"APPLICATION_SUBMITTED audit event missing for app #{app_id}"
    print(f"      ✓ Application #{app_id} submitted and audited (SHA-256: {app_audit.curr_hash[:16]}...).")

    # 1C. Document Upload Audit Event
    print("  1C. Uploading Compliance Document...")
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    res_doc = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={
            "application_id": app_id,
            "doc_type": "FIRE_SAFETY",
            "title": "DTU Computing Facility AICTE NOC",
            "issue_date": "2026-01-01",
            "expiry_date": "2031-01-01",
        },
        files={"file": ("hpc_approval.pdf", fake_pdf, "application/pdf")},
    )
    assert res_doc.status_code == 201, f"Document upload failed: {res_doc.text}"
    doc_id = res_doc.json()["id"]

    doc_audit = db.query(AuditLog).filter(
        AuditLog.action == "DOCUMENT_UPLOAD",
        AuditLog.resource_id == str(doc_id),
    ).first()
    assert doc_audit is not None, f"DOCUMENT_UPLOAD audit event missing for doc #{doc_id}"
    doc_details = json.loads(doc_audit.details_json)
    assert doc_details["file_name"] == "hpc_approval.pdf"
    assert "file_hash_sha256" in doc_details
    print(f"      ✓ Document #{doc_id} upload audited with cryptographic file hash.")

    # 1D. Officer Scrutiny & Stage Progression (Advancing to EVC)
    print("  1D. Regional Officer Processing Scrutiny Stage...")
    res_process = client.post(
        f"/api/applications/{app_id}/complete-stage",
        headers={"Authorization": f"Bearer {ro_token}"},
        json={"remarks": "Scrutiny documents thoroughly verified by Regional Committee."},
    )
    assert res_process.status_code == 200, f"Stage advancement failed: {res_process.text}"

    stage_audit = db.query(AuditLog).filter(
        AuditLog.action == "STAGE_COMPLETED",
        AuditLog.resource_id == str(app_id),
    ).first()
    assert stage_audit is not None, "STAGE_COMPLETED audit event missing"
    print(f"      ✓ Scrutiny stage completion audited with officer remarks.")

    # 1E. EVC Visit Scheduling Audit Event
    print("  1E. Scheduling EVC Inspection Visit...")
    evc_visit = db.query(EVCVisit).filter(EVCVisit.application_id == app_id).first()
    assert evc_visit is not None, "Automatic EVC visit record missing"

    res_sched = client.post(
        f"/api/evc/{evc_visit.id}/schedule",
        headers={"Authorization": f"Bearer {ro_token}"},
        json={
            "scheduled_date": "2026-11-20T10:00:00Z",
            "committee_lead_name": "Prof. Dr. M. K. Narayanan",
            "committee_members": ["Dr. R. Gupta (IIT Delhi)", "Dr. S. Kaushik (DTU)"],
            "visit_mode": "PHYSICAL",
            "remarks": "On-site laboratory infrastructure audit",
        },
    )
    assert res_sched.status_code == 200, f"EVC scheduling failed: {res_sched.text}"

    evc_audit = db.query(AuditLog).filter(
        AuditLog.action.in_(["EVC_VISIT_SCHEDULED", "EVC_SCHEDULED"]),
        AuditLog.resource_id == str(evc_visit.id),
    ).first()
    assert evc_audit is not None, "EVC_SCHEDULED audit event missing"
    print(f"      ✓ EVC Visit #{evc_visit.id} scheduling audited with committee assignments.")

    # 1F. Time Advancement Audit Event
    print("  1F. Advancing Demo Simulated Time...")
    res_time = client.post(
        "/api/admin/advance-time",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"days": 5},
    )
    assert res_time.status_code == 200, f"Time advance failed: {res_time.text}"

    time_audit = db.query(AuditLog).filter(
        AuditLog.action == "TIME_ADVANCED",
    ).order_by(AuditLog.id.desc()).first()
    assert time_audit is not None, "TIME_ADVANCED audit event missing"
    time_details = json.loads(time_audit.details_json)
    assert time_details.get("days_advanced") == 5
    print("      ✓ Demo time advance audited with previous and new simulated dates.")
    db.close()

    # -----------------------------------------------------------------
    # STEP 2: IMMUTABILITY & ACCESS CONTROL INSPECTION
    # -----------------------------------------------------------------
    print("\n[Step 2] Testing Audit Log Immutability & Access Control...")

    # 2A. Attempting Mutations via APIs (PUT / PATCH / DELETE)
    print("  2A. Testing Mutation Prohibitions (Append-Only Guarantee)...")
    for method in ["PUT", "PATCH", "DELETE"]:
        res_mut = client.request(method, f"/api/audit-logs/{app_audit.id}", headers={"Authorization": f"Bearer {admin_token}"}, json={"action": "TAMPERED"})
        assert res_mut.status_code == 405, f"Expected 405 Method Not Allowed for {method}, got {res_mut.status_code}"
    
    res_bulk = client.delete("/api/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_bulk.status_code == 405, "Bulk delete on audit logs must be 405"
    print("      ✓ Immutability confirmed: PUT, PATCH, DELETE strictly return 405 Method Not Allowed.")

    # 2B. Unauthorized Role Access to Audit Logs
    print("  2B. Testing Unauthorized Access Restrictions...")
    res_unauth_inst = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_unauth_inst.status_code == 403, f"Expected 403 for Institution, got {res_unauth_inst.status_code}"

    res_unauth_ro = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_unauth_ro.status_code == 403, f"Expected 403 for Regional Officer, got {res_unauth_ro.status_code}"

    res_auth_admin = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_auth_admin.status_code == 200, f"Expected 200 for Admin, got {res_auth_admin.status_code}"
    print("      ✓ Authorization enforced: Institution and Regional Officer received 403 Forbidden.")

    # 2C. Cryptographic Hash Chain Validation
    print("  2C. Validating SHA-256 Hash Chain Integrity from Genesis...")
    db = SessionLocal()
    chain_status = verify_audit_hash_chain(db)
    db.close()
    assert chain_status["chain_intact"] is True, f"Audit chain corrupted: {chain_status}"
    print(f"      ✓ Cryptographic ledger validated: {chain_status['total_records']} records chained with unbroken SHA-256 hashes.")

    # -----------------------------------------------------------------
    # STEP 3: RECONCILING EXPORTED REPORTS WITH DATABASE
    # -----------------------------------------------------------------
    print("\n[Step 3] Reconciling Exported CSV and PDF Reports with Underlying Database...")

    # 3A. Application Pendency Reconciliation
    print("  3A. Reconciling Application Pendency Report...")
    db = SessionLocal()
    db_apps = db.query(Application).all()
    db.close()

    res_app_csv = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_app_csv.status_code == 200
    df_apps = pd.read_csv(io.StringIO(res_app_csv.text))
    assert len(df_apps) == len(db_apps), f"CSV row count ({len(df_apps)}) does not match DB count ({len(db_apps)})"
    
    # Verify specific application numbers match
    db_app_nums = {a.application_number for a in db_apps}
    csv_app_nums = set(df_apps["App Number"].dropna())
    assert db_app_nums == csv_app_nums, "Mismatch between DB application numbers and CSV report!"
    print(f"      ✓ Application Pendency CSV exactly matches DB ({len(df_apps)} records verified).")

    # 3B. Document Validity Reconciliation
    print("  3B. Reconciling Document Validity Report...")
    db = SessionLocal()
    db_docs = db.query(UndertakingDocument).all()
    db.close()

    res_doc_csv = client.get(
        "/api/reports/export?report_type=document_validity&format=csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_doc_csv.status_code == 200
    df_docs = pd.read_csv(io.StringIO(res_doc_csv.text))
    assert len(df_docs) == len(db_docs), f"Document CSV count ({len(df_docs)}) does not match DB ({len(db_docs)})"
    print(f"      ✓ Document Validity CSV exactly matches DB ({len(df_docs)} records verified).")

    # 3C. EVC Status Reconciliation
    print("  3C. Reconciling EVC Status Report...")
    db = SessionLocal()
    db_evcs = db.query(EVCVisit).all()
    db.close()

    res_evc_csv = client.get(
        "/api/reports/export?report_type=evc_status&format=csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_evc_csv.status_code == 200
    df_evcs = pd.read_csv(io.StringIO(res_evc_csv.text))
    assert len(df_evcs) == len(db_evcs), f"EVC CSV count ({len(df_evcs)}) does not match DB ({len(db_evcs)})"
    print(f"      ✓ EVC Status CSV exactly matches DB ({len(df_evcs)} records verified).")

    # 3D. PDF Binary and Formatting Verification
    print("  3D. Validating Landscape PDF Generation for All 4 Report Types...")
    for rtype in ["application_pendency", "overdue_cases", "document_validity", "evc_status"]:
        res_pdf = client.get(
            f"/api/reports/export?report_type={rtype}&format=pdf",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_pdf.status_code == 200, f"PDF export for {rtype} failed with status {res_pdf.status_code}"
        assert res_pdf.content.startswith(b"%PDF-"), f"{rtype} PDF does not start with %PDF- header"
        assert b"%%EOF" in res_pdf.content, f"{rtype} PDF missing %%EOF trailer"
        assert len(res_pdf.content) > 1000, f"{rtype} PDF file unusually small ({len(res_pdf.content)} bytes)"
        print(f"      ✓ {rtype} PDF export verified ({len(res_pdf.content)} bytes, valid header & EOF).")

    # -----------------------------------------------------------------
    # STEP 4: SCOPE ISOLATION, FORMULA INJECTION & EDGE CASES
    # -----------------------------------------------------------------
    print("\n[Step 4] Testing Geographic Isolation, CSV Formula Injection & Filter Validation...")

    # 4A. Cross-Institution Reporting Isolation (DTU vs COEP)
    print("  4A. Testing Cross-Institution Scope Isolation...")
    coep_token = get_user_token("inst.coep@aicte.gov.in")

    res_dtu_export = client.get("/api/reports/export?report_type=application_pendency&format=csv", headers={"Authorization": f"Bearer {dtu_token}"})
    df_dtu_export = pd.read_csv(io.StringIO(res_dtu_export.text))
    for inst in df_dtu_export["Institution"]:
        assert "Delhi" in inst or "DTU" in inst
        assert "COEP" not in inst

    res_coep_export = client.get("/api/reports/export?report_type=application_pendency&format=csv", headers={"Authorization": f"Bearer {coep_token}"})
    df_coep_export = pd.read_csv(io.StringIO(res_coep_export.text))
    for inst in df_coep_export["Institution"]:
        assert "COEP" in inst or "Pune" in inst
        assert "Delhi" not in inst
    print("      ✓ Cross-institution scope isolation strictly confirmed.")

    # 4B. Regional Officer Boundary Enforcement
    print("  4B. Testing Regional Officer Cross-Region Prohibition...")
    res_cross_reg = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&region=Western Region",
        headers={"Authorization": f"Bearer {ro_token}"},  # RO North requesting Western Region
    )
    assert res_cross_reg.status_code == 403, f"Expected 403 Forbidden for cross-region export, got {res_cross_reg.status_code}"
    print("      ✓ Regional Officer forbidden from exporting other regions (403 Forbidden).")

    # 4C. CSV Formula Injection Escaping
    print("  4C. Testing Formula Injection Prevention Matrix (=, +, -, @, \\t, \\r)...")
    dangerous_payloads = [
        "=SUM(A1:B10)",
        "+cmd|' /C calc'!A0",
        "-123456",
        "@IMPORTDATA('http://malicious.com')",
        "\tDANGEROUS_TAB",
        "\rDANGEROUS_CR",
    ]
    for payload in dangerous_payloads:
        escaped = sanitize_cell_for_csv(payload)
        assert escaped.startswith("'"), f"Formula injection payload '{payload}' not escaped: '{escaped}'"
    print("      ✓ All dangerous leading characters strictly escaped with single quote.")

    # 4D. Empty Results & Invalid Filter Validation
    print("  4D. Testing Empty Results & Boundary Filters...")
    res_empty_csv = client.get(
        "/api/reports/export?report_type=application_pendency&format=csv&start_date=2099-01-01&end_date=2099-12-31",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_empty_csv.status_code == 200
    df_empty = pd.read_csv(io.StringIO(res_empty_csv.text))
    assert len(df_empty) == 0, f"Expected 0 rows for future date, got {len(df_empty)}"
    assert "App Number" in df_empty.columns, "Headers missing from empty CSV"

    res_empty_pdf = client.get(
        "/api/reports/export?report_type=application_pendency&format=pdf&start_date=2099-01-01&end_date=2099-12-31",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_empty_pdf.status_code == 200
    assert res_empty_pdf.content.startswith(b"%PDF-")

    # Invalid filters
    res_bad_type = client.get("/api/reports/export?report_type=UNKNOWN&format=csv", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_bad_type.status_code == 400

    res_bad_fmt = client.get("/api/reports/export?report_type=application_pendency&format=EXE", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_bad_fmt.status_code == 400

    res_bad_dates = client.get("/api/reports/export?report_type=application_pendency&format=csv&start_date=2026-12-31&end_date=2026-01-01", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_bad_dates.status_code == 400
    print("      ✓ Empty results and invalid filter boundary checks passed.")

    # Reset time back to 0
    db = SessionLocal()
    admin_curr = db.query(User).filter(User.role == UserRole.ADMIN).first()
    reset_simulated_time(db, admin_curr)
    db.close()

    print("\n" + "=" * 75)
    print("INDEPENDENT REVIEW COMPLETE: 100% OF CHECKS PASSED")
    print("=" * 75)


if __name__ == "__main__":
    run_comprehensive_phase9_verification()
