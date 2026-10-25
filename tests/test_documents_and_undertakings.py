import io
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
def setup_test_environment(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_application_helper(client: TestClient, inst_email: str = "inst.dtu@aicte.gov.in") -> int:
    token = get_token(client, inst_email)
    res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Compliance Campus Expansion"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    return res.json()["id"]


# ==============================================================================
# A. FILE SECURITY & DOCUMENT UPLOAD TESTS
# ==============================================================================

def test_valid_pdf_and_image_uploads(client: TestClient, db_session: Session):
    """Verify authorized upload of valid PDF, PNG, and JPEG documents with SHA-256 integrity."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")

    # 1. Valid PDF upload
    pdf_bytes = b"%PDF-1.4\n%Valid minimal PDF content for AICTE test\n%%EOF"
    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={
            "doc_type": "LAND_LEASE",
            "title": "30-Year Campus Land Lease Deed",
            "issue_date": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),
            "expiry_date": (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat(),
        },
        files={"file": ("land_lease.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["doc_type"] == "LAND_LEASE"
    assert data["title"] == "30-Year Campus Land Lease Deed"
    assert data["file_name"] == "land_lease.pdf"
    assert data["file_size_bytes"] == len(pdf_bytes)
    assert data["status"] == "ACTIVE"
    assert data["verification_status"] == "PENDING"
    doc_id = data["id"]

    # Verify physical file on disk matches hash
    doc = db_session.query(UndertakingDocument).filter(UndertakingDocument.id == doc_id).first()
    assert doc is not None
    stored_path = Path(settings.UPLOAD_DIR).resolve() / doc.stored_file_path
    assert stored_path.exists()
    assert stored_path.read_bytes() == pdf_bytes

    # 2. Valid PNG upload
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    res_png = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "FIRE_SAFETY", "title": "Fire Department NOC"},
        files={"file": ("fire_noc.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert res_png.status_code == 201
    assert res_png.json()["file_name"] == "fire_noc.png"


def test_invalid_file_extension_rejected(client: TestClient):
    """Verify non-permitted file extensions (.exe, .sh, .txt) are rejected with HTTP 400."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    bad_bytes = b"echo 'Malicious Script'"

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "OTHER", "title": "Suspicious Executable"},
        files={"file": ("payload.exe", io.BytesIO(bad_bytes), "application/x-msdownload")},
    )
    assert res.status_code == 400
    assert "not permitted" in res.json()["detail"].lower()


def test_file_signature_mismatch_rejected(client: TestClient):
    """Verify spoofed files (e.g. text/exe file named fake.pdf) are rejected via magic byte validation."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    fake_pdf = b"This is plain ASCII text pretending to be a PDF."

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "BUILDING_COMPLETION", "title": "Fake Plan"},
        files={"file": ("fake_plan.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert res.status_code == 400
    assert "does not match" in res.json()["detail"].lower()


def test_oversized_file_rejected(client: TestClient, monkeypatch):
    """Verify files exceeding MAX_UPLOAD_SIZE_BYTES are rejected with HTTP 413."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    # Temporarily set upload limit to 100 bytes for test
    from backend.services import document_service
    monkeypatch.setattr(document_service.settings, "MAX_UPLOAD_SIZE_BYTES", 50)

    oversized_bytes = b"%PDF-1.4\n" + b"A" * 100
    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "OTHER", "title": "Oversized Document"},
        files={"file": ("big.pdf", io.BytesIO(oversized_bytes), "application/pdf")},
    )
    assert res.status_code in (413, 400)
    assert "exceeds" in res.json()["detail"].lower()


def test_path_traversal_in_filename_sanitized(client: TestClient, db_session: Session):
    """Verify directory traversal attempts in filename (../../etc/passwd.pdf) are neutralized."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nTraversal Safety Check\n%%EOF"

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "AFFIDAVIT_UNDERTAKING", "title": "Security Check Affidavit"},
        files={"file": ("../../../../etc/passwd.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201
    data = res.json()
    # The file_name must NOT contain path separators
    assert "/" not in data["file_name"]
    assert "\\" not in data["file_name"]
    assert ".." not in data["file_name"]

    # Stored file on disk must be inside UPLOAD_DIR
    doc = db_session.query(UndertakingDocument).filter(UndertakingDocument.id == data["id"]).first()
    dest = (Path(settings.UPLOAD_DIR).resolve() / doc.stored_file_path).resolve()
    assert dest.is_relative_to(Path(settings.UPLOAD_DIR).resolve())


# ==============================================================================
# B. DOCUMENT DOWNLOAD & RBAC TESTS
# ==============================================================================

def test_document_download_ownership_isolation(client: TestClient):
    """Verify institution ownership isolation on document download."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")

    pdf_bytes = b"%PDF-1.4\nDTU Confidential Land Agreement\n%%EOF"
    upload_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "LAND_LEASE", "title": "DTU Proprietary Deed"},
        files={"file": ("dtu_deed.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 1. DTU downloads its own document -> Success
    res_dtu = client.get(
        f"/api/documents/{doc_id}/download",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_dtu.status_code == 200
    assert res_dtu.content == pdf_bytes
    assert "attachment" in res_dtu.headers.get("Content-Disposition", "")

    # 2. COEP attempts to download DTU's document -> HTTP 403 Forbidden
    res_coep = client.get(
        f"/api/documents/{doc_id}/download",
        headers={"Authorization": f"Bearer {coep_token}"},
    )
    assert res_coep.status_code == 403
    assert "Access denied" in res_coep.json()["detail"]


def test_regional_officer_boundary_document_access(client: TestClient):
    """Verify regional officers can access in-region documents but not cross-region."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")  # Northern Region
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")

    pdf_bytes = b"%PDF-1.4\nNorthern Region Safety Report\n%%EOF"
    upload_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "BUILDING_COMPLETION", "title": "Northern Campus Plan"},
        files={"file": ("north_plan.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # RO North can download
    res_ro = client.get(
        f"/api/documents/{doc_id}/download",
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_ro.status_code == 200
    assert res_ro.content == pdf_bytes

    # Bureau officer can download nationwide
    res_bureau = client.get(
        f"/api/documents/{doc_id}/download",
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    assert res_bureau.status_code == 200


def test_unauthenticated_download_rejected(client: TestClient):
    """Verify unauthenticated download request is rejected with HTTP 401."""
    res = client.get("/api/documents/1/download")
    assert res.status_code == 401


# ==============================================================================
# C. EXPIRY DATE VALIDATION & MONITORING
# ==============================================================================

def test_expiry_date_before_issue_date_rejected(client: TestClient):
    """Verify expiry date strictly before issue date is rejected."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nInvalid Date Doc\n%%EOF"

    issue_date = datetime.now(timezone.utc)
    expiry_date = issue_date - timedelta(days=30)  # Expired before issue!

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={
            "doc_type": "LAND_LEASE",
            "title": "Invalid Date Document",
            "issue_date": issue_date.isoformat(),
            "expiry_date": expiry_date.isoformat(),
        },
        files={"file": ("invalid_date.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 400
    assert "later than issue date" in res.json()["detail"].lower()


def test_document_status_expired_calculation(client: TestClient):
    """Verify documents with past expiry date are flagged EXPIRED automatically."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nExpired Lease\n%%EOF"

    past_expiry = datetime.now(timezone.utc) - timedelta(days=10)
    past_issue = past_expiry - timedelta(days=365)

    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={
            "doc_type": "LAND_LEASE",
            "title": "Expired Historical Lease",
            "issue_date": past_issue.isoformat(),
            "expiry_date": past_expiry.isoformat(),
        },
        files={"file": ("expired.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201
    assert res.json()["status"] == "EXPIRED"


def test_document_expiring_within_days_filter(client: TestClient):
    """Verify querying documents with expiring_within_days filter."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    pdf_bytes = b"%PDF-1.4\nExpiring Soon Lease\n%%EOF"

    # Expires in 15 days
    near_expiry = datetime.now(timezone.utc) + timedelta(days=15)
    res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={
            "doc_type": "FIRE_SAFETY",
            "title": "Fire Certificate Expiring in 15 Days",
            "expiry_date": near_expiry.isoformat(),
        },
        files={"file": ("near_expiry.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201

    # Filter within 30 days should return it
    filter_res = client.get(
        "/api/documents?expiring_within_days=30",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert filter_res.status_code == 200
    titles = [d["title"] for d in filter_res.json()]
    assert "Fire Certificate Expiring in 15 Days" in titles


# ==============================================================================
# D. DOCUMENT VERIFICATION TESTS
# ==============================================================================

def test_document_verification_lifecycle(client: TestClient, db_session: Session):
    """Verify officer can verify or reject document and audit log records it."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")

    pdf_bytes = b"%PDF-1.4\nVerification Target\n%%EOF"
    upload_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "BUILDING_COMPLETION", "title": "Building Blueprint"},
        files={"file": ("blueprint.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # 1. Institution cannot verify its own document
    inst_verif_res = client.post(
        f"/api/documents/{doc_id}/verify",
        json={"status": "VERIFIED", "remarks": "I verify myself"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert inst_verif_res.status_code == 403

    # 2. Regional Officer verifies document
    officer_res = client.post(
        f"/api/documents/{doc_id}/verify",
        json={"status": "VERIFIED", "remarks": "Approved by Regional Inspection Authority"},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert officer_res.status_code == 200
    data = officer_res.json()
    assert data["verification_status"] == "VERIFIED"
    assert data["verification_remarks"] == "Approved by Regional Inspection Authority"

    # Verify audit log recorded
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.resource_type == "DOCUMENT", AuditLog.resource_id == str(doc_id))
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.action == "DOCUMENT_VERIFIED"


# ==============================================================================
# E. UNDERTAKINGS LIFECYCLE & RESUBMISSION TESTS
# ==============================================================================

def test_undertaking_creation_by_authorized_officer(client: TestClient):
    """Verify only authorized officers can create undertakings within their regional jurisdiction."""
    app_id = create_application_helper(client, "inst.dtu@aicte.gov.in")

    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    # 1. Institution cannot create undertakings
    res_inst = client.post(
        "/api/undertakings",
        json={"application_id": app_id, "description": "Mandatory Barrier-Free Ramp", "due_date": due_date},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_inst.status_code == 403

    # 2. Regional Officer (North) can create undertaking for DTU (North)
    res_ro = client.post(
        "/api/undertakings",
        json={
            "application_id": app_id,
            "description": "Construct barrier-free accessible ramp for Block C",
            "due_date": due_date,
        },
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_ro.status_code == 201
    data = res_ro.json()
    assert data["status"] == "PENDING"
    assert data["application_id"] == app_id
    assert data["description"] == "Construct barrier-free accessible ramp for Block C"


def test_undertaking_listing_and_isolation(client: TestClient):
    """Verify institutions only see their own undertakings; officers see region."""
    app_dtu_id = create_application_helper(client, "inst.dtu@aicte.gov.in")
    app_coep_id = create_application_helper(client, "inst.coep@aicte.gov.in")

    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    # Bureau officer creates 1 undertaking for DTU and 1 for COEP
    client.post(
        "/api/undertakings",
        json={"application_id": app_dtu_id, "description": "DTU Undertaking 1", "due_date": due_date},
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    client.post(
        "/api/undertakings",
        json={"application_id": app_coep_id, "description": "COEP Undertaking 1", "due_date": due_date},
        headers={"Authorization": f"Bearer {bureau_token}"},
    )

    # 1. DTU list only contains DTU
    res_dtu = client.get("/api/undertakings", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_dtu.status_code == 200
    assert len(res_dtu.json()) == 1
    assert res_dtu.json()[0]["description"] == "DTU Undertaking 1"

    # 2. COEP list only contains COEP
    res_coep = client.get("/api/undertakings", headers={"Authorization": f"Bearer {coep_token}"})
    assert res_coep.status_code == 200
    assert len(res_coep.json()) == 1
    assert res_coep.json()[0]["description"] == "COEP Undertaking 1"

    # 3. RO North only sees DTU (North region)
    res_ro = client.get("/api/undertakings", headers={"Authorization": f"Bearer {ro_north_token}"})
    assert res_ro.status_code == 200
    descs = [u["description"] for u in res_ro.json()]
    assert "DTU Undertaking 1" in descs
    assert "COEP Undertaking 1" not in descs


def test_undertaking_evidence_submission_and_verification(client: TestClient, db_session: Session):
    """Verify happy path: PENDING -> SUBMITTED -> VERIFIED."""
    app_id = create_application_helper(client, "inst.dtu@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    create_res = client.post(
        "/api/undertakings",
        json={"application_id": app_id, "description": "Install fire alarm system", "due_date": due_date},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    u_id = create_res.json()["id"]

    # 1. Upload proof document
    pdf_bytes = b"%PDF-1.4\nFire Alarm Installation Certificate\n%%EOF"
    doc_res = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {dtu_token}"},
        data={"doc_type": "FIRE_SAFETY", "title": "Fire Alarm Installation Report"},
        files={"file": ("fire_report.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    doc_id = doc_res.json()["id"]

    # 2. Submit evidence: PENDING -> SUBMITTED
    submit_res = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={
            "submitted_proof_reference": "NOC-DELHI-FIRE-2026-9921",
            "proof_document_id": doc_id,
            "submission_remarks": "Completed installation across all 4 floors.",
        },
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "SUBMITTED"
    assert submit_res.json()["submitted_proof_reference"] == "NOC-DELHI-FIRE-2026-9921"
    assert submit_res.json()["proof_document_id"] == doc_id

    # 3. Verify evidence: SUBMITTED -> VERIFIED
    verify_res = client.post(
        f"/api/undertakings/{u_id}/verify",
        json={"remarks": "Fire alarm certificate verified against municipal records."},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "VERIFIED"
    assert verify_res.json()["verification_remarks"] == "Fire alarm certificate verified against municipal records."


def test_undertaking_rejection_and_resubmission_lifecycle(client: TestClient):
    """
    Verify rejection with mandatory reason and subsequent resubmission:
    PENDING -> SUBMITTED -> REJECTED -> SUBMITTED -> VERIFIED.
    """
    app_id = create_application_helper(client, "inst.dtu@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    u_res = client.post(
        "/api/undertakings",
        json={"application_id": app_id, "description": "Install Chemistry Lab Fume Hoods", "due_date": due_date},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    u_id = u_res.json()["id"]

    # Initial submission: PENDING -> SUBMITTED
    client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={"submitted_proof_reference": "REF-FUME-01", "submission_remarks": "Installed 1 hood"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )

    # 1. Missing rejection reason rejected with 422
    bad_reject = client.post(
        f"/api/undertakings/{u_id}/reject",
        json={"rejection_reason": "  "},  # Blank reason
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert bad_reject.status_code == 422

    # 2. Reject with substantive reason: SUBMITTED -> REJECTED
    reject_res = client.post(
        f"/api/undertakings/{u_id}/reject",
        json={
            "rejection_reason": "AICTE standards mandate at least 3 fume hoods for 60-seat capacity.",
            "remarks": "Please install remaining 2 hoods and upload photographic proof.",
        },
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "REJECTED"
    assert "at least 3 fume hoods" in reject_res.json()["rejection_reason"]

    # 3. Resubmission by institution: REJECTED -> SUBMITTED
    resubmit_res = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={
            "submitted_proof_reference": "REF-FUME-02-FINAL",
            "submission_remarks": "Installed additional 2 hoods. Attached invoice and photo.",
        },
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert resubmit_res.status_code == 200
    data = resubmit_res.json()
    assert data["status"] == "SUBMITTED"
    assert data["rejection_reason"] is None  # Previous rejection cleared!
    assert data["submitted_proof_reference"] == "REF-FUME-02-FINAL"

    # 4. Officer verifies resubmitted proof: SUBMITTED -> VERIFIED
    final_verif = client.post(
        f"/api/undertakings/{u_id}/verify",
        json={"remarks": "Compliance satisfied with 3 certified hoods."},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert final_verif.status_code == 200
    assert final_verif.json()["status"] == "VERIFIED"


def test_invalid_undertaking_transitions(client: TestClient):
    """Verify invalid state transitions are rejected with HTTP 400."""
    app_id = create_application_helper(client, "inst.dtu@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    u_res = client.post(
        "/api/undertakings",
        json={"application_id": app_id, "description": "Install library Braille section", "due_date": due_date},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    u_id = u_res.json()["id"]

    # 1. Attempting to verify PENDING directly without submission -> 400
    res1 = client.post(
        f"/api/undertakings/{u_id}/verify",
        json={"remarks": "Premature verification"},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res1.status_code == 400
    assert "Must be 'SUBMITTED'" in res1.json()["detail"]

    # 2. Attempting to reject PENDING directly without submission -> 400
    res2 = client.post(
        f"/api/undertakings/{u_id}/reject",
        json={"rejection_reason": "Nothing submitted yet"},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res2.status_code == 400

    # Submit evidence
    client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={"submitted_proof_reference": "BRAILLE-SECTION-01"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )

    # 3. Submitting evidence again while already SUBMITTED -> 400
    res3 = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={"submitted_proof_reference": "DUPLICATE-SUBMISSION"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res3.status_code == 400
    assert "awaiting" in res3.json()["detail"].lower()

    # Officer verifies
    client.post(
        f"/api/undertakings/{u_id}/verify",
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )

    # 4. Submitting evidence on already VERIFIED undertaking -> 400
    res4 = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={"submitted_proof_reference": "POST-VERIFIED-ATTEMPT"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res4.status_code == 400
    assert "already been verified" in res4.json()["detail"].lower()


def test_unauthorized_institution_cannot_submit_or_verify(client: TestClient):
    """Verify COEP cannot submit evidence or view DTU undertaking, and institution cannot verify."""
    app_id = create_application_helper(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")

    due_date = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    u_res = client.post(
        "/api/undertakings",
        json={"application_id": app_id, "description": "DTU Specific Undertaking", "due_date": due_date},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    u_id = u_res.json()["id"]

    # 1. COEP cannot view DTU undertaking -> 403
    view_res = client.get(f"/api/undertakings/{u_id}", headers={"Authorization": f"Bearer {coep_token}"})
    assert view_res.status_code == 403

    # 2. COEP cannot submit evidence for DTU undertaking -> 403
    submit_res = client.post(
        f"/api/undertakings/{u_id}/submit-evidence",
        json={"submitted_proof_reference": "COEP-IMPERSONATION"},
        headers={"Authorization": f"Bearer {coep_token}"},
    )
    assert submit_res.status_code == 403

    # 3. DTU cannot verify its own undertaking -> 403
    verif_res = client.post(
        f"/api/undertakings/{u_id}/verify",
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert verif_res.status_code == 403
