import hashlib
import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.application import Application
from backend.models.audit import AuditLog
from backend.models.document import DocType, DocumentStatus, UndertakingDocument, VerificationStatus
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.workflow.config import ensure_default_workflow_routes

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_review_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_auth_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_app_for_inst(client: TestClient, inst_email: str, title: str) -> int:
    token = get_auth_token(client, inst_email)
    res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ==============================================================================
# 1. UNDERTAKING COMPLETE LIFECYCLE & DATABASE INTEGRITY
# ==============================================================================

def test_undertaking_complete_lifecycle_and_db_assertions(client: TestClient, db_session: Session):
    """
    Independently verify full undertaking lifecycle with state & audit assertions:
    1. Officer creates undertaking -> PENDING
    2. Institution submits evidence -> SUBMITTED
    3. Officer rejects with reason -> REJECTED
    4. Institution resubmits -> SUBMITTED (rejection cleared)
    5. Officer verifies -> VERIFIED
    Verify SHA-256 hash chaining of audit entries.
    """
    app_id = create_app_for_inst(client, "inst.dtu@aicte.gov.in", "Lifecycle Verification App")
    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_auth_token(client, "ro.north@aicte.gov.in")

    # Step 1: Officer creates undertaking (PENDING)
    due_date = datetime.now(timezone.utc) + timedelta(days=21)
    create_res = client.post(
        "/api/undertakings",
        json={
            "application_id": app_id,
            "description": "Construct 500kL Rainwater Harvesting Reservoir",
            "due_date": due_date.isoformat(),
        },
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert create_res.status_code == 201, create_res.text
    u_id = create_res.json()["id"]

    db_u = db_session.query(Undertaking).filter(Undertaking.id == u_id).first()
    assert db_u is not None
    assert db_u.status == UndertakingStatus.PENDING
    assert db_u.application_id == app_id
    assert db_u.institution_id == db_u.application.institution_id

    # Step 2: Institution submits evidence (SUBMITTED)
    sub1_res = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={
            "submitted_proof_reference": "RWH-CIVIL-DWG-001",
            "submission_remarks": "Architectural drawings and tender work order submitted.",
        },
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert sub1_res.status_code == 200
    db_session.refresh(db_u)
    assert db_u.status == UndertakingStatus.SUBMITTED
    assert db_u.submitted_proof_reference == "RWH-CIVIL-DWG-001"
    assert db_u.submitted_at is not None

    # Step 3: Officer rejects evidence with substantive reason (REJECTED)
    rejection_msg = "Tender work order is missing the required municipal water board NOC."
    rej_res = client.post(
        f"/api/undertakings/{u_id}/reject",
        json={"rejection_reason": rejection_msg, "remarks": "Re-upload with board endorsement."},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert rej_res.status_code == 200
    db_session.refresh(db_u)
    assert db_u.status == UndertakingStatus.REJECTED
    assert db_u.rejection_reason == rejection_msg
    assert db_u.verified_by_user_id is not None
    assert db_u.verified_at is not None

    # Step 4: Institution resubmits evidence (SUBMITTED)
    sub2_res = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={
            "submitted_proof_reference": "RWH-CIVIL-DWG-002-WITH-NOC",
            "submission_remarks": "Municipal Water Board NOC attached as requested.",
        },
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert sub2_res.status_code == 200
    db_session.refresh(db_u)
    assert db_u.status == UndertakingStatus.SUBMITTED
    assert db_u.rejection_reason is None  # Rejection reason cleared on resubmission
    assert db_u.submitted_proof_reference == "RWH-CIVIL-DWG-002-WITH-NOC"

    # Step 5: Officer verifies evidence (VERIFIED)
    verif_res = client.post(
        f"/api/undertakings/{u_id}/verify",
        json={"remarks": "All municipal NOCs validated against registry."},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert verif_res.status_code == 200
    db_session.refresh(db_u)
    assert db_u.status == UndertakingStatus.VERIFIED
    assert db_u.verification_remarks == "All municipal NOCs validated against registry."

    # Verify Cryptographic Audit Trail for all 5 actions
    logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.resource_type == "UNDERTAKING", AuditLog.resource_id == str(u_id))
        .order_by(AuditLog.id.asc())
        .all()
    )
    assert len(logs) == 5  # CREATED, SUBMITTED (1), REJECTED, SUBMITTED (2), VERIFIED
    expected_actions = [
        "UNDERTAKING_CREATED",
        "UNDERTAKING_EVIDENCE_SUBMITTED",
        "UNDERTAKING_REJECTED",
        "UNDERTAKING_EVIDENCE_SUBMITTED",
        "UNDERTAKING_VERIFIED",
    ]
    actual_actions = [log.action for log in logs]
    assert actual_actions == expected_actions

    # Check hash-chain continuity across the actions
    for i in range(1, len(logs)):
        assert logs[i].prev_hash == logs[i - 1].curr_hash


# ==============================================================================
# 2. STRICT CROSS-INSTITUTION ISOLATION & ACCESS CONTROL
# ==============================================================================

def test_strict_cross_institution_isolation(client: TestClient):
    """
    Verify absolute isolation: DTU (North) and COEP (West) cannot view,
    download, or modify each other's documents or undertakings.
    """
    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_auth_token(client, "inst.coep@aicte.gov.in")
    bureau_token = get_auth_token(client, "bureau@aicte.gov.in")

    # DTU creates application and uploads document
    app_dtu_id = create_app_for_inst(client, "inst.dtu@aicte.gov.in", "DTU Isolated App")
    doc_dtu_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "LAND_LEASE", "title": "DTU Secret Land Lease", "application_id": app_dtu_id},
        files={"file": ("dtu_lease.pdf", io.BytesIO(b"%PDF-1.4\nDTU Secret Lease\n%%EOF"), "application/pdf")},
    )
    assert doc_dtu_res.status_code == 201
    dtu_doc_id = doc_dtu_res.json()["id"]
    dtu_inst_id = doc_dtu_res.json()["institution_id"]

    # COEP creates application and uploads document
    app_coep_id = create_app_for_inst(client, "inst.coep@aicte.gov.in", "COEP Isolated App")
    doc_coep_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {coep_token}"},
        data={"doc_type": "FIRE_SAFETY", "title": "COEP Secret Fire Report", "application_id": app_coep_id},
        files={"file": ("coep_fire.pdf", io.BytesIO(b"%PDF-1.4\nCOEP Secret Fire\n%%EOF"), "application/pdf")},
    )
    assert doc_coep_res.status_code == 201
    coep_doc_id = doc_coep_res.json()["id"]
    coep_inst_id = doc_coep_res.json()["institution_id"]

    # Bureau creates 1 undertaking for DTU and 1 for COEP
    due_date = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    u_dtu_res = client.post(
        "/api/undertakings",
        json={"application_id": app_dtu_id, "description": "DTU Confidential Undertaking", "due_date": due_date},
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    dtu_u_id = u_dtu_res.json()["id"]

    u_coep_res = client.post(
        "/api/undertakings",
        json={"application_id": app_coep_id, "description": "COEP Confidential Undertaking", "due_date": due_date},
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    coep_u_id = u_coep_res.json()["id"]

    # --- DOCUMENT ISOLATION CHECKS ---
    # 1. DTU list must not contain COEP's document
    res_dtu_docs = client.get("/api/documents", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_dtu_docs.status_code == 200
    dtu_doc_ids = [d["id"] for d in res_dtu_docs.json()]
    assert dtu_doc_id in dtu_doc_ids
    assert coep_doc_id not in dtu_doc_ids

    # 2. DTU querying COEP's institution_id explicitly -> 403 Forbidden
    res_expl = client.get(
        f"/api/documents?institution_id={coep_inst_id}",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_expl.status_code == 403

    # 3. DTU viewing COEP document metadata by ID -> 403 Forbidden
    res_view = client.get(f"/api/documents/{coep_doc_id}", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_view.status_code == 403

    # 4. DTU downloading COEP file by ID -> 403 Forbidden
    res_down = client.get(f"/api/documents/{coep_doc_id}/download", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_down.status_code == 403

    # --- UNDERTAKING ISOLATION CHECKS ---
    # 5. DTU list must not contain COEP's undertaking
    res_dtu_u = client.get("/api/undertakings", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_dtu_u.status_code == 200
    dtu_u_ids = [u["id"] for u in res_dtu_u.json()]
    assert dtu_u_id in dtu_u_ids
    assert coep_u_id not in dtu_u_ids

    # 6. DTU viewing COEP undertaking by ID -> 403 Forbidden
    res_view_u = client.get(f"/api/undertakings/{coep_u_id}", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_view_u.status_code == 403

    # 7. DTU attempting to submit evidence on COEP undertaking -> 403 Forbidden
    res_hack_u = client.post(
        f"/api/undertakings/{coep_u_id}/submit-evidence",
        json={"submitted_proof_reference": "ILLEGAL-EVIDENCE"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_hack_u.status_code == 403


# ==============================================================================
# 3. UPLOAD VALIDATION, EXTENSION SPOOFING & PATH TRAVERSAL RIGOR
# ==============================================================================

def test_file_type_magic_spoofing_matrix(client: TestClient):
    """
    Test matrix of extension vs magic byte mismatches:
    - .pdf with PNG magic
    - .png with PDF magic
    - .jpg with plain text
    - .exe disguised as .pdf
    """
    token = get_auth_token(client, "inst.dtu@aicte.gov.in")

    pdf_magic = b"%PDF-1.4 header"
    png_magic = b"\x89PNG\r\n\x1a\nheader"
    jpg_magic = b"\xff\xd8\xff\xe0header"
    bad_ascii = b"echo 'hacked'"

    test_matrix = [
        ("spoof_png_as_pdf.pdf", png_magic, "application/pdf"),
        ("spoof_pdf_as_png.png", pdf_magic, "image/png"),
        ("spoof_txt_as_jpg.jpg", bad_ascii, "image/jpeg"),
        ("spoof_exe_as_pdf.pdf", b"MZ\x90\x00\x03\x00\x00\x00", "application/pdf"),
    ]

    for fname, content, mime in test_matrix:
        res = client.post(
            "/api/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"doc_type": "OTHER", "title": f"Spoof Test {fname}"},
            files={"file": (fname, io.BytesIO(content), mime)},
        )
        assert res.status_code == 400, f"Expected 400 for {fname}, got {res.status_code}"
        assert "does not match" in res.json()["detail"].lower() or "not permitted" in res.json()["detail"].lower()


def test_empty_file_rejected(client: TestClient):
    """Verify 0-byte uploaded file is rejected with HTTP 400."""
    token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"doc_type": "OTHER", "title": "Zero Byte File"},
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_path_traversal_encoded_and_windows_separators(client: TestClient, db_session: Session):
    """Verify various directory traversal attempts are sanitized."""
    token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nSafe content\n%%EOF"

    traversal_names = [
        "....//....//etc//passwd.pdf",
        "..\\..\\Windows\\System32\\cmd.pdf",
        "sub/dir/../../document.pdf",
    ]

    for attack_name in traversal_names:
        res = client.post(
            "/api/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"doc_type": "OTHER", "title": f"Traversal Test {attack_name}"},
            files={"file": (attack_name, io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert res.status_code == 201
        data = res.json()
        assert "/" not in data["file_name"]
        assert "\\" not in data["file_name"]
        assert ".." not in data["file_name"]

        # Ensure server file is located safely within upload directory
        doc = db_session.query(UndertakingDocument).filter(UndertakingDocument.id == data["id"]).first()
        file_path = (Path(settings.UPLOAD_DIR).resolve() / doc.stored_file_path).resolve()
        assert file_path.is_relative_to(Path(settings.UPLOAD_DIR).resolve())
        assert file_path.exists()


# ==============================================================================
# 4. STATIC DIRECTORY ISOLATION
# ==============================================================================

def test_static_directory_does_not_expose_uploaded_files(client: TestClient):
    """
    Verify that uploaded private files are NOT directly accessible via
    the public static files mount (e.g. /static/... or /uploads/...).
    """
    token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nPrivate AICTE Statutory Affidavit\n%%EOF"

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"doc_type": "AFFIDAVIT_UNDERTAKING", "title": "Private Affidavit"},
        files={"file": ("affidavit.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201
    doc_id = res.json()["id"]

    # Retrieve internal stored filename via metadata
    meta = client.get(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"})
    assert meta.status_code == 200

    # Attempt public unauthenticated access via /static/uploads/...
    res_static = client.get("/static/uploads/affidavit.pdf")
    assert res_static.status_code == 404

    # Attempt access directly at /uploads/...
    res_root_uploads = client.get("/uploads/affidavit.pdf")
    assert res_root_uploads.status_code in (404, 405)


# ==============================================================================
# 5. DATA CONSISTENCY WITH ASSOCIATED APPLICATIONS
# ==============================================================================

def test_document_and_undertaking_application_consistency(client: TestClient):
    """
    Verify application-document-undertaking referential consistency:
    1. Institution DTU cannot upload a document linked to COEP's application.
    2. Institution DTU cannot submit an undertaking proof document that is linked to a different application.
    """
    app_dtu_1 = create_app_for_inst(client, "inst.dtu@aicte.gov.in", "DTU App 1")
    app_dtu_2 = create_app_for_inst(client, "inst.dtu@aicte.gov.in", "DTU App 2")
    app_coep = create_app_for_inst(client, "inst.coep@aicte.gov.in", "COEP App")

    dtu_token = get_auth_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_auth_token(client, "ro.north@aicte.gov.in")

    # 1. DTU attempts to upload document linking COEP's application_id -> 400 Bad Request
    pdf_bytes = b"%PDF-1.4\nInconsistent App Doc\n%%EOF"
    cross_app_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "LAND_LEASE", "title": "Cross App Lease", "application_id": app_coep},
        files={"file": ("cross.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert cross_app_res.status_code == 400
    assert "does not belong" in cross_app_res.json()["detail"].lower()

    # 2. Upload a valid document linked to DTU App 2
    doc_app2_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "FIRE_SAFETY", "title": "App 2 Fire Cert", "application_id": app_dtu_2},
        files={"file": ("app2_fire.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert doc_app2_res.status_code == 201
    doc_app2_id = doc_app2_res.json()["id"]

    # 3. Create an undertaking for DTU App 1
    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    u_res = client.post(
        "/api/undertakings",
        json={"application_id": app_dtu_1, "description": "DTU App 1 Undertaking", "due_date": due_date},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert u_res.status_code == 201
    u_app1_id = u_res.json()["id"]

    # 4. Attempt to submit App 2's document as proof for App 1's undertaking -> 400 Bad Request
    mismatched_sub = client.post(
        f"/api/undertakings/{u_app1_id}/submit-evidence",
        json={
            "submitted_proof_reference": "REF-CROSS-APP",
            "proof_document_id": doc_app2_id,
        },
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert mismatched_sub.status_code == 400
    assert "different application" in mismatched_sub.json()["detail"].lower()
