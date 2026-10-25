"""
Demo user, institution, and workflow seeding script for AICTE Workflow Automation Platform.
Provides repeatable, idempotent generation of fictional demo data covering all supported roles,
workflow routes, stages, deadline states, EVC inspection visits, statutory undertakings,
documents, in-app notifications, SLA escalations, and cryptographically verified audit trails.

Usage:
    python -m backend.seed            # Idempotently seed/update demo data
    python -m backend.seed --reset    # Reset disposable demo data and reseed
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.security import hash_password
from backend.core.time_service import get_effective_time, reset_simulated_time
from backend.database import Base, SessionLocal, init_db
from backend.models.application import (
    Application,
    ApplicationStageHistory,
    ApplicationStatus,
)
from backend.models.audit import AuditLog
from backend.models.document import (
    DocType,
    DocumentStatus,
    UndertakingDocument,
    VerificationStatus,
)
from backend.models.evc import EVCRecommendation, EVCStatus, EVCVisit
from backend.models.notification import (
    DeadlineRule,
    EscalationLevel,
    EscalationRecord,
    Notification,
    NotificationType,
    TrackableEntityType,
)
from backend.models.setting import SystemSetting
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.models.workflow import WorkflowRoute, WorkflowStage
from backend.services.audit_service import log_audit_event
from backend.services.deadline_service import ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes

settings = get_settings()

DEFAULT_DEMO_PASSWORD = "Demo@AICTE2026!"

# =============================================================================
# 1. DEMO INSTITUTIONS (Clearly fictional, covering multiple regions)
# =============================================================================
DEMO_INSTITUTIONS = [
    {
        "name": "Delhi Technological University",
        "code": "DTU-DEL-001",
        "region": "Northern Region",
        "address": "Shahbad Daulatpur, Bawana Road, Delhi - 110042",
        "contact_email": "registrar@dtu.ac.in",
        "contact_phone": "+91-11-27871018",
        "establishment_year": 1941,
    },
    {
        "name": "College of Engineering Pune",
        "code": "COEP-MAH-002",
        "region": "Western Region",
        "address": "Wellesley Road, Shivajinagar, Pune, Maharashtra - 411005",
        "contact_email": "admin@coep.ac.in",
        "contact_phone": "+91-20-25507000",
        "establishment_year": 1854,
    },
    {
        "name": "Apex Institute of Technology & Management",
        "code": "APEX-DEL-003",
        "region": "Northern Region",
        "address": "Plot 12, Institutional Area, Sector 62, Noida, Delhi NCR - 201301",
        "contact_email": "registrar@apex-demo.edu",
        "contact_phone": "+91-11-29990001",
        "establishment_year": 2005,
    },
    {
        "name": "Horizon Academy of Engineering & Technology",
        "code": "HORIZON-MUM-004",
        "region": "Western Region",
        "address": "Survey 45, Vidyanagar, Navi Mumbai, Maharashtra - 400703",
        "contact_email": "principal@horizon-demo.edu",
        "contact_phone": "+91-22-27770002",
        "establishment_year": 2010,
    },
    {
        "name": "Zenith Institute of Polytechnic Studies",
        "code": "ZENITH-BLR-005",
        "region": "Southern Region",
        "address": "Campus 8, Electronic City Phase 1, Bengaluru, Karnataka - 560100",
        "contact_email": "dean@zenith-demo.edu",
        "contact_phone": "+91-80-28880003",
        "establishment_year": 2015,
    },
    {
        "name": "Vanguard College of Engineering & Research",
        "code": "VANGUARD-KOL-006",
        "region": "Eastern Region",
        "address": "Salt Lake Sector V, Bidhannagar, Kolkata, West Bengal - 700091",
        "contact_email": "admin@vanguard-demo.edu",
        "contact_phone": "+91-33-26660004",
        "establishment_year": 2018,
    },
]

# =============================================================================
# 2. DEMO USERS (Covering all 4 supported roles + multiple officers/institutions)
# =============================================================================
DEMO_USERS = [
    {
        "email": "admin@aicte.gov.in",
        "full_name": "AICTE Platform Administrator",
        "role": UserRole.ADMIN,
        "region": None,
        "institution_code": None,
    },
    {
        "email": "bureau@aicte.gov.in",
        "full_name": "Bureau Officer - Approvals",
        "role": UserRole.BUREAU_OFFICER,
        "region": "HQ - New Delhi",
        "institution_code": None,
    },
    {
        "email": "bureau.chair@aicte.gov.in",
        "full_name": "Bureau Committee Chair",
        "role": UserRole.BUREAU_OFFICER,
        "region": "HQ - New Delhi",
        "institution_code": None,
    },
    {
        "email": "ro.north@aicte.gov.in",
        "full_name": "Regional Officer (North)",
        "role": UserRole.REGIONAL_OFFICER,
        "region": "Northern Region",
        "institution_code": None,
    },
    {
        "email": "ro.west@aicte.gov.in",
        "full_name": "Regional Officer (West)",
        "role": UserRole.REGIONAL_OFFICER,
        "region": "Western Region",
        "institution_code": None,
    },
    {
        "email": "ro.south@aicte.gov.in",
        "full_name": "Regional Officer (South)",
        "role": UserRole.REGIONAL_OFFICER,
        "region": "Southern Region",
        "institution_code": None,
    },
    {
        "email": "inst.dtu@aicte.gov.in",
        "full_name": "Principal / Dean - DTU",
        "role": UserRole.INSTITUTION,
        "region": "Northern Region",
        "institution_code": "DTU-DEL-001",
    },
    {
        "email": "inst.coep@aicte.gov.in",
        "full_name": "Principal / Dean - COEP",
        "role": UserRole.INSTITUTION,
        "region": "Western Region",
        "institution_code": "COEP-MAH-002",
    },
    {
        "email": "inst.apex@aicte.gov.in",
        "full_name": "Dean - Apex Institute",
        "role": UserRole.INSTITUTION,
        "region": "Northern Region",
        "institution_code": "APEX-DEL-003",
    },
    {
        "email": "inst.horizon@aicte.gov.in",
        "full_name": "Principal - Horizon Academy",
        "role": UserRole.INSTITUTION,
        "region": "Western Region",
        "institution_code": "HORIZON-MUM-004",
    },
    {
        "email": "inst.zenith@aicte.gov.in",
        "full_name": "Director - Zenith Polytechnic",
        "role": UserRole.INSTITUTION,
        "region": "Southern Region",
        "institution_code": "ZENITH-BLR-005",
    },
    {
        "email": "inst.vanguard@aicte.gov.in",
        "full_name": "Dean - Vanguard College",
        "role": UserRole.INSTITUTION,
        "region": "Eastern Region",
        "institution_code": "VANGUARD-KOL-006",
    },
]


def create_demo_file_on_disk(filename: str, title: str) -> Tuple[str, str, int]:
    """
    Generate a valid sample PDF file in the uploads directory with %PDF-1.4 header.
    Returns (stored_relative_path, sha256_hash, file_size_bytes).
    """
    upload_dir = settings.UPLOAD_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 55 >> stream\n"
        b"BT /F1 12 Tf 72 712 Td (" + title.encode("utf-8") + b") Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
        b"0000000115 00000 n \n0000000214 00000 n \n"
        b"trailer << /Size 5 /Root 1 0 R >>\nstartxref\n320\n%%EOF\n"
    )

    with open(file_path, "wb") as f:
        f.write(pdf_content)

    file_size = len(pdf_content)
    sha256 = hashlib.sha256(pdf_content).hexdigest()
    return str(file_path), sha256, file_size


def reset_disposable_demo_data(session: Session, verbose: bool = True) -> int:
    """
    Remove all disposable demo applications and their cascades without affecting
    unrelated real records. Also resets the simulated demo time offset.
    """
    if verbose:
        print("\n--> Resetting disposable demo dataset...")

    # Find demo applications
    demo_apps = (
        session.query(Application)
        .filter(Application.application_number.like("APP-2026-DEMO-%"))
        .all()
    )
    demo_app_ids = [a.id for a in demo_apps]

    # Delete notifications & escalations linked to demo applications
    if demo_app_ids:
        session.query(Notification).filter(Notification.application_id.in_(demo_app_ids)).delete(
            synchronize_session=False
        )
        session.query(EscalationRecord).filter(
            EscalationRecord.application_id.in_(demo_app_ids)
        ).delete(synchronize_session=False)

    # Delete demo notifications with DEMO event keys
    session.query(Notification).filter(Notification.event_key.like("DEMO-%")).delete(
        synchronize_session=False
    )
    session.query(EscalationRecord).filter(EscalationRecord.event_key.like("DEMO-%")).delete(
        synchronize_session=False
    )

    # Delete undertakings linked to demo apps
    if demo_app_ids:
        session.query(Undertaking).filter(Undertaking.application_id.in_(demo_app_ids)).delete(
            synchronize_session=False
        )
        session.query(EVCVisit).filter(EVCVisit.application_id.in_(demo_app_ids)).delete(
            synchronize_session=False
        )
        session.query(ApplicationStageHistory).filter(
            ApplicationStageHistory.application_id.in_(demo_app_ids)
        ).delete(synchronize_session=False)

    # Delete demo documents
    session.query(UndertakingDocument).filter(
        (UndertakingDocument.file_name.like("demo_%"))
        | (UndertakingDocument.application_id.in_(demo_app_ids))
    ).delete(synchronize_session=False)

    # Delete applications
    deleted_count = 0
    for app in demo_apps:
        session.delete(app)
        deleted_count += 1

    # Reset simulated demo time to 0
    admin_user = session.query(User).filter(User.role == UserRole.ADMIN).first()
    if admin_user:
        reset_simulated_time(session, admin_user)

    session.commit()

    # Clean demo uploaded files on disk
    upload_dir = settings.UPLOAD_DIR
    if upload_dir.exists():
        for f in upload_dir.glob("demo_*.pdf"):
            try:
                f.unlink()
            except OSError:
                pass

    if verbose:
        print(f"--> Cleaned {deleted_count} demo application(s) and associated entities.")
    return deleted_count


def seed_demo_data(
    session: Optional[Session] = None,
    verbose: bool = True,
    reset: bool = False,
    full_demo: bool = True,
) -> Dict[str, int]:
    """
    Execute repeatable, idempotent seed operation for AICTE Platform.
    Ensures valid relational foreign keys, distinct roles, diverse workflow stages,
    deadline conditions, EVC visits, undertakings, documents, notifications, and escalations.
    """
    close_session = False
    if session is None:
        init_db()
        session = SessionLocal()
        close_session = True

    try:
        # Reset if requested
        if reset:
            reset_disposable_demo_data(session, verbose=verbose)

        # 1. Seed Institutions
        inst_map: Dict[str, Institution] = {}
        inst_count = 0
        for inst_data in DEMO_INSTITUTIONS:
            existing = session.query(Institution).filter(Institution.code == inst_data["code"]).first()
            if existing:
                for k, v in inst_data.items():
                    setattr(existing, k, v)
                inst_map[inst_data["code"]] = existing
            else:
                new_inst = Institution(**inst_data)
                session.add(new_inst)
                session.flush()
                inst_map[inst_data["code"]] = new_inst
                inst_count += 1
        session.commit()

        # 2. Seed Users
        hashed_pwd = hash_password(DEFAULT_DEMO_PASSWORD)
        user_map: Dict[str, User] = {}
        user_count = 0
        for user_data in DEMO_USERS:
            email = user_data["email"].lower().strip()
            inst_code = user_data["institution_code"]
            inst_id = inst_map[inst_code].id if inst_code and inst_code in inst_map else None

            existing_user = session.query(User).filter(User.email == email).first()
            if existing_user:
                existing_user.full_name = user_data["full_name"]
                existing_user.role = user_data["role"]
                existing_user.region = user_data["region"]
                existing_user.institution_id = inst_id
                existing_user.hashed_password = hashed_pwd
                existing_user.is_active = True
                user_map[email] = existing_user
            else:
                new_user = User(
                    email=email,
                    hashed_password=hashed_pwd,
                    full_name=user_data["full_name"],
                    role=user_data["role"],
                    region=user_data["region"],
                    institution_id=inst_id,
                    is_active=True,
                )
                session.add(new_user)
                session.flush()
                user_map[email] = new_user
                user_count += 1
        session.commit()

        # 3. Seed Routes and Deadline Rules
        routes_map = ensure_default_workflow_routes(session)
        ensure_default_deadline_rules(session)

        counts = {
            "institutions": len(DEMO_INSTITUTIONS),
            "users": len(DEMO_USERS),
            "applications": 0,
            "evc_visits": 0,
            "undertakings": 0,
            "documents": 0,
            "notifications": 0,
            "escalations": 0,
        }

        if not full_demo:
            return counts

        # Reference objects
        now = get_effective_time(session)
        admin = user_map.get("admin@aicte.gov.in")
        bureau = user_map.get("bureau@aicte.gov.in")
        ro_north = user_map.get("ro.north@aicte.gov.in")
        ro_west = user_map.get("ro.west@aicte.gov.in")
        ro_south = user_map.get("ro.south@aicte.gov.in")

        inst_apex = inst_map.get("APEX-DEL-003")
        inst_horizon = inst_map.get("HORIZON-MUM-004")
        inst_zenith = inst_map.get("ZENITH-BLR-005")
        inst_vanguard = inst_map.get("VANGUARD-KOL-006")
        inst_dtu = inst_map.get("DTU-DEL-001")

        # 4. Seed Compliance Documents
        # File A: Valid Land Lease Deed (Apex)
        path_a, hash_a, size_a = create_demo_file_on_disk(
            "demo_land_lease_apex.pdf", "Land Lease Deed - Apex Institute (30 Yrs)"
        )
        doc_a = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_land_lease_apex.pdf")
            .first()
        )
        if not doc_a:
            doc_a = UndertakingDocument(
                institution_id=inst_apex.id,
                doc_type=DocType.LAND_LEASE,
                title="Registered Land Lease Deed - 30 Years",
                file_name="demo_land_lease_apex.pdf",
                stored_file_path=path_a,
                file_size_bytes=size_a,
                file_hash_sha256=hash_a,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=365 * 2),
                expiry_date=now + timedelta(days=365 * 28),
                status=DocumentStatus.ACTIVE,
                verification_status=VerificationStatus.VERIFIED,
                verified_by_user_id=ro_north.id,
            )
            session.add(doc_a)
            session.flush()

        # File B: Building Completion Certificate (Apex)
        path_b, hash_b, size_b = create_demo_file_on_disk(
            "demo_building_completion_apex.pdf", "Building Completion Certificate - Apex"
        )
        doc_b = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_building_completion_apex.pdf")
            .first()
        )
        if not doc_b:
            doc_b = UndertakingDocument(
                institution_id=inst_apex.id,
                doc_type=DocType.BUILDING_COMPLETION,
                title="Municipal Building Completion & Occupancy Certificate",
                file_name="demo_building_completion_apex.pdf",
                stored_file_path=path_b,
                file_size_bytes=size_b,
                file_hash_sha256=hash_b,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=180),
                expiry_date=now + timedelta(days=365 * 8),
                status=DocumentStatus.ACTIVE,
                verification_status=VerificationStatus.VERIFIED,
                verified_by_user_id=ro_north.id,
            )
            session.add(doc_b)
            session.flush()

        # File C: Active Fire Safety NOC (Horizon)
        path_c, hash_c, size_c = create_demo_file_on_disk(
            "demo_fire_safety_horizon.pdf", "Fire Safety NOC - Horizon Academy"
        )
        doc_c = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_fire_safety_horizon.pdf")
            .first()
        )
        if not doc_c:
            doc_c = UndertakingDocument(
                institution_id=inst_horizon.id,
                doc_type=DocType.FIRE_SAFETY,
                title="State Fire Services Department NOC",
                file_name="demo_fire_safety_horizon.pdf",
                stored_file_path=path_c,
                file_size_bytes=size_c,
                file_hash_sha256=hash_c,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=90),
                expiry_date=now + timedelta(days=275),  # Future expiry (healthy)
                status=DocumentStatus.ACTIVE,
                verification_status=VerificationStatus.VERIFIED,
                verified_by_user_id=ro_west.id,
            )
            session.add(doc_c)
            session.flush()

        # File D: Expired Fire NOC (Horizon)
        path_d, hash_d, size_d = create_demo_file_on_disk(
            "demo_expired_fire_horizon.pdf", "Expired Fire Safety NOC (2025)"
        )
        doc_d = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_expired_fire_horizon.pdf")
            .first()
        )
        if not doc_d:
            doc_d = UndertakingDocument(
                institution_id=inst_horizon.id,
                doc_type=DocType.FIRE_SAFETY,
                title="Previous Term Fire Safety NOC (Expired)",
                file_name="demo_expired_fire_horizon.pdf",
                stored_file_path=path_d,
                file_size_bytes=size_d,
                file_hash_sha256=hash_d,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=400),
                expiry_date=now - timedelta(days=35),  # Expired 35 days ago
                status=DocumentStatus.EXPIRED,
                verification_status=VerificationStatus.REJECTED,
                verified_by_user_id=ro_west.id,
            )
            session.add(doc_d)
            session.flush()

        # File E: Expired PCB Consent (Zenith)
        path_e, hash_e, size_e = create_demo_file_on_disk(
            "demo_expired_pcb_zenith.pdf", "State PCB Consent to Operate (Expired)"
        )
        doc_e = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_expired_pcb_zenith.pdf")
            .first()
        )
        if not doc_e:
            doc_e = UndertakingDocument(
                institution_id=inst_zenith.id,
                doc_type=DocType.OTHER,
                title="Pollution Control Board Consent to Operate (Expired)",
                file_name="demo_expired_pcb_zenith.pdf",
                stored_file_path=path_e,
                file_size_bytes=size_e,
                file_hash_sha256=hash_e,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=380),
                expiry_date=now - timedelta(days=15),  # Expired 15 days ago
                status=DocumentStatus.EXPIRED,
                verification_status=VerificationStatus.PENDING,
            )
            session.add(doc_e)
            session.flush()

        # File F: Undertaking Evidence Proof (Apex)
        path_f, hash_f, size_f = create_demo_file_on_disk(
            "demo_faculty_proof_apex.pdf", "Faculty Cadre Rectification Affidavit - Apex"
        )
        doc_f = (
            session.query(UndertakingDocument)
            .filter(UndertakingDocument.file_name == "demo_faculty_proof_apex.pdf")
            .first()
        )
        if not doc_f:
            doc_f = UndertakingDocument(
                institution_id=inst_apex.id,
                doc_type=DocType.UNDERTAKING_EVIDENCE,
                title="Affidavit & Appointment Orders for Associate Professors",
                file_name="demo_faculty_proof_apex.pdf",
                stored_file_path=path_f,
                file_size_bytes=size_f,
                file_hash_sha256=hash_f,
                mime_type="application/pdf",
                issue_date=now - timedelta(days=5),
                expiry_date=now + timedelta(days=365),
                status=DocumentStatus.ACTIVE,
                verification_status=VerificationStatus.PENDING,
            )
            session.add(doc_f)
            session.flush()

        session.commit()

        # 5. Helper to fetch stage IDs by route and stage key
        def get_stage(route_code: str, stage_key: str) -> Optional[WorkflowStage]:
            route = routes_map.get(route_code)
            if not route:
                return None
            return (
                session.query(WorkflowStage)
                .filter(WorkflowStage.route_id == route.id, WorkflowStage.stage_key == stage_key)
                .first()
            )

        # 6. Seed Applications covering different routes, stages & deadline conditions
        demo_apps_def = [
            # 1. Healthy / In Scrutiny (Apex)
            {
                "number": "APP-2026-DEMO-001",
                "institution": inst_apex,
                "route_code": "SCRUTINY_EVC",
                "stage_key": "SCRUTINY",
                "status": ApplicationStatus.SUBMITTED,
                "title": "Establishment of New Technical Campus - Apex Institute",
                "submitted_days_ago": 2,
                "deadline_delta_days": 8,  # Healthy future deadline
            },
            # 2. In EVC Stage / Approaching Deadline (Apex)
            {
                "number": "APP-2026-DEMO-002",
                "institution": inst_apex,
                "route_code": "SCRUTINY_EVC",
                "stage_key": "EVC",
                "status": ApplicationStatus.IN_REVIEW,
                "title": "Expansion of Intake in Computer Engineering - Apex Institute",
                "submitted_days_ago": 15,
                "deadline_delta_days": 2,  # Inside reminder threshold (3 days)
            },
            # 3. Decision Stage / Due Today (Horizon)
            {
                "number": "APP-2026-DEMO-003",
                "institution": inst_horizon,
                "route_code": "SCRUTINY_EVC",
                "stage_key": "DECISION",
                "status": ApplicationStatus.IN_REVIEW,
                "title": "Introduction of New Postgraduate Program - Horizon Academy",
                "submitted_days_ago": 28,
                "deadline_delta_days": 0,  # Due today!
            },
            # 4. In SAC Hearing Stage (Zenith)
            {
                "number": "APP-2026-DEMO-004",
                "institution": inst_zenith,
                "route_code": "EVC_SAC",
                "stage_key": "SAC",
                "status": ApplicationStatus.IN_REVIEW,
                "title": "Standing Appeal Review for Laboratory Deficiencies - Zenith",
                "submitted_days_ago": 20,
                "deadline_delta_days": 6,
            },
            # 5. Final Approved Application (Horizon)
            {
                "number": "APP-2026-DEMO-005",
                "institution": inst_horizon,
                "route_code": "ONLY_SCRUTINY",
                "stage_key": "DECISION",
                "status": ApplicationStatus.APPROVED,
                "title": "Annual Extension of Approval (EoA) 2026-27 - Horizon Academy",
                "submitted_days_ago": 30,
                "deadline_delta_days": -10,
                "decision": "APPROVE",
                "decision_by": bureau,
                "decision_remarks": "All statutory parameters, faculty cadres, and financial reserves verified and approved.",
            },
            # 6. Final Rejected Application (Vanguard)
            {
                "number": "APP-2026-DEMO-006",
                "institution": inst_vanguard,
                "route_code": "ONLY_SCRUTINY",
                "stage_key": "DECISION",
                "status": ApplicationStatus.REJECTED,
                "title": "Establishment of New Polytechnic Division - Vanguard College",
                "submitted_days_ago": 25,
                "deadline_delta_days": -8,
                "decision": "REJECT",
                "decision_by": bureau,
                "decision_remarks": "Rejected: Disputed encumbrance certificate on educational land parcel.",
            },
            # 7. Overdue Application Stage (Vanguard)
            {
                "number": "APP-2026-DEMO-007",
                "institution": inst_vanguard,
                "route_code": "SCRUTINY_EVC",
                "stage_key": "SCRUTINY",
                "status": ApplicationStatus.OVERDUE,
                "title": "Closure of Obsolete Diploma Stream - Vanguard College",
                "submitted_days_ago": 13,
                "deadline_delta_days": -3,  # Overdue by 3 days
            },
            # 8. Overdue & Escalated Application (Vanguard)
            {
                "number": "APP-2026-DEMO-008",
                "institution": inst_vanguard,
                "route_code": "SCRUTINY_EVC",
                "stage_key": "SCRUTINY",
                "status": ApplicationStatus.OVERDUE,
                "title": "Increase in Intake for AI & Data Science - Vanguard College",
                "submitted_days_ago": 21,
                "deadline_delta_days": -7,  # Overdue by 7 days (escalated)
                "is_escalated": True,
            },
        ]

        app_map: Dict[str, Application] = {}
        for a_def in demo_apps_def:
            app = (
                session.query(Application)
                .filter(Application.application_number == a_def["number"])
                .first()
            )
            route = routes_map[a_def["route_code"]]
            stage = get_stage(a_def["route_code"], a_def["stage_key"])
            stage_deadline = now + timedelta(days=a_def["deadline_delta_days"])
            sub_date = now - timedelta(days=a_def["submitted_days_ago"])

            if not app:
                app = Application(
                    application_number=a_def["number"],
                    institution_id=a_def["institution"].id,
                    route_id=route.id,
                    route_type=route.code,
                    current_stage_id=stage.id if stage else None,
                    status=a_def["status"],
                    academic_year="2026-2027",
                    title=a_def["title"],
                    description=f"Automated demo institutional approval application: {a_def['title']}",
                    submission_date=sub_date,
                    current_stage_deadline=stage_deadline,
                )
                session.add(app)
                session.flush()

                # Add stage history
                history = ApplicationStageHistory(
                    application_id=app.id,
                    stage_id=stage.id if stage else None,
                    from_stage_id=None,
                    to_stage_id=stage.id if stage else None,
                    action="STAGE_ENTERED",
                    remarks=f"Entered stage {stage.name if stage else 'N/A'}",
                    actor_user_id=admin.id,
                    entered_at=sub_date,
                    deadline_at=stage_deadline,
                    was_overdue=a_def["deadline_delta_days"] < 0,
                )
                session.add(history)

            # If application has a final decision
            if a_def.get("decision"):
                app.final_decision_date = now - timedelta(days=abs(a_def["deadline_delta_days"]))
                app.final_decision_by_user_id = a_def["decision_by"].id
                app.final_decision_remarks = a_def["decision_remarks"]

            app_map[a_def["number"]] = app
        session.commit()

        # 7. Seed EVC Visits with diverse statuses
        # A. PENDING_SCHEDULE (on APP-2026-DEMO-002)
        app_002 = app_map["APP-2026-DEMO-002"]
        evc_a = session.query(EVCVisit).filter(EVCVisit.application_id == app_002.id).first()
        if not evc_a:
            evc_a = EVCVisit(
                application_id=app_002.id,
                due_date=now + timedelta(days=5),
                status=EVCStatus.PENDING_SCHEDULE,
                visit_mode="PHYSICAL",
            )
            session.add(evc_a)

        # B. SCHEDULED (on APP-2026-DEMO-004)
        app_004 = app_map["APP-2026-DEMO-004"]
        evc_b = session.query(EVCVisit).filter(EVCVisit.application_id == app_004.id).first()
        if not evc_b:
            evc_b = EVCVisit(
                application_id=app_004.id,
                due_date=now + timedelta(days=10),
                scheduled_date=now + timedelta(days=4),
                status=EVCStatus.SCHEDULED,
                committee_lead_name="Dr. Sunita Deshmukh (IIT Bombay)",
                committee_members_json=json.dumps(
                    ["Prof. Arvind Kumar (IIT Roorkee)", "Dr. Meena Iyer (NIT Warangal)"]
                ),
                visit_mode="PHYSICAL",
            )
            session.add(evc_b)

        # C. COMPLETED (on APP-2026-DEMO-003)
        app_003 = app_map["APP-2026-DEMO-003"]
        evc_c = session.query(EVCVisit).filter(EVCVisit.application_id == app_003.id).first()
        if not evc_c:
            evc_c = EVCVisit(
                application_id=app_003.id,
                due_date=now - timedelta(days=5),
                scheduled_date=now - timedelta(days=8),
                conducted_date=now - timedelta(days=7),
                status=EVCStatus.COMPLETED,
                committee_lead_name="Prof. Anand Joshi (COEP Pune)",
                committee_members_json=json.dumps(
                    ["Dr. R. K. Sen (VJTI Mumbai)", "Dr. S. Nair (Sardar Patel COE)"]
                ),
                visit_mode="PHYSICAL",
                report_file_path=path_c,
                report_file_hash=hash_c,
                report_uploaded_at=now - timedelta(days=6),
                recommendation=EVCRecommendation.RECOMMENDED,
                remarks="All physical laboratories, fire exists, and faculty requirements confirmed compliant.",
                officer_remarks="Verified report against regional verification norms.",
            )
            session.add(evc_c)

        # D. CONDUCTED (Inspection completed, report pending upload)
        app_007 = app_map["APP-2026-DEMO-007"]
        evc_d = session.query(EVCVisit).filter(EVCVisit.application_id == app_007.id).first()
        if not evc_d:
            evc_d = EVCVisit(
                application_id=app_007.id,
                due_date=now + timedelta(days=2),
                scheduled_date=now - timedelta(days=2),
                conducted_date=now - timedelta(days=2),
                status=EVCStatus.CONDUCTED,
                committee_lead_name="Dr. B. C. Roy (NIT Durgapur)",
                committee_members_json=json.dumps(["Prof. P. K. Banerjee (Jadavpur Univ)"]),
                visit_mode="PHYSICAL",
            )
            session.add(evc_d)

        # E. CANCELLED
        app_001 = app_map["APP-2026-DEMO-001"]
        evc_e = (
            session.query(EVCVisit)
            .filter(
                EVCVisit.application_id == app_001.id,
                EVCVisit.status == EVCStatus.CANCELLED,
            )
            .first()
        )
        if not evc_e:
            evc_e = EVCVisit(
                application_id=app_001.id,
                due_date=now - timedelta(days=1),
                status=EVCStatus.CANCELLED,
                rescheduled_count=1,
                remarks="Cancelled due to administrative rescheduling; fresh committee to be constituted.",
            )
            session.add(evc_e)
        session.commit()

        # 8. Seed Statutory Undertakings with various lifecycle statuses
        # A. PENDING (Issued by officer, awaiting institution evidence)
        und_a = (
            session.query(Undertaking)
            .filter(
                Undertaking.application_id == app_001.id,
                Undertaking.description.like("%Barrier-Free Campus%"),
            )
            .first()
        )
        if not und_a:
            und_a = Undertaking(
                application_id=app_001.id,
                institution_id=inst_apex.id,
                description="Submit Barrier-Free Campus Access and Ramp Certification for Academic Block B.",
                due_date=now + timedelta(days=10),
                status=UndertakingStatus.PENDING,
            )
            session.add(und_a)

        # B. SUBMITTED (Evidence uploaded, awaiting officer verification)
        und_b = (
            session.query(Undertaking)
            .filter(
                Undertaking.application_id == app_002.id,
                Undertaking.description.like("%Faculty Cadre Ratio%"),
            )
            .first()
        )
        if not und_b:
            und_b = Undertaking(
                application_id=app_002.id,
                institution_id=inst_apex.id,
                description="Submit Faculty Cadre Ratio Rectification Undertaking and Proof of Appointment.",
                due_date=now + timedelta(days=5),
                status=UndertakingStatus.SUBMITTED,
                submitted_proof_reference="DOC-REF-APEX-FACULTY-2026",
                proof_document_id=doc_f.id if doc_f else None,
                submitted_at=now - timedelta(days=1),
                submission_remarks="Formal appointment orders of 4 Associate Professors attached for review.",
            )
            session.add(und_b)

        # C. VERIFIED (Officer verified with positive remarks)
        und_c = (
            session.query(Undertaking)
            .filter(
                Undertaking.application_id == app_003.id,
                Undertaking.description.like("%Sewage Treatment%"),
            )
            .first()
        )
        if not und_c:
            und_c = Undertaking(
                application_id=app_003.id,
                institution_id=inst_horizon.id,
                description="Submit Sewage Treatment Plant (STP) Operational Clearance Certificate.",
                due_date=now - timedelta(days=5),
                status=UndertakingStatus.VERIFIED,
                submitted_proof_reference="DOC-REF-HORIZON-STP-01",
                submitted_at=now - timedelta(days=7),
                submission_remarks="Certified STP inspection letter from MPCB.",
                verified_by_user_id=ro_west.id,
                verified_at=now - timedelta(days=6),
                verification_remarks="Document verified against Maharashtra Pollution Control Board registry.",
            )
            session.add(und_c)

        # D. REJECTED (Officer rejected with reason, returned for resubmission)
        und_d = (
            session.query(Undertaking)
            .filter(
                Undertaking.application_id == app_004.id,
                Undertaking.description.like("%Structural Stability%"),
            )
            .first()
        )
        if not und_d:
            und_d = Undertaking(
                application_id=app_004.id,
                institution_id=inst_zenith.id,
                description="Submit Structural Stability Certificate for Engineering Workshop Block.",
                due_date=now + timedelta(days=7),
                status=UndertakingStatus.REJECTED,
                submitted_proof_reference="DOC-REF-ZENITH-STRUCT-2024",
                submitted_at=now - timedelta(days=3),
                submission_remarks="Attached 2024 structural survey certificate.",
                verified_by_user_id=ro_south.id,
                verified_at=now - timedelta(days=2),
                rejection_reason="Certificate expired in 2024. Please obtain and submit a fresh certificate from a licensed chartered structural engineer.",
                verification_remarks="Rejected for resubmission.",
            )
            session.add(und_d)
        session.commit()

        # 9. Seed In-App Notifications and Escalations
        # A. Upcoming Reminder (Institution)
        user_apex = user_map.get("inst.apex@aicte.gov.in")
        if user_apex:
            notif_a = (
                session.query(Notification)
                .filter(Notification.event_key == "DEMO-NOTIF-UPCOMING-002")
                .first()
            )
            if not notif_a:
                session.add(
                    Notification(
                        user_id=user_apex.id,
                        application_id=app_002.id,
                        title="Upcoming Stage SLA Reminder",
                        message=f"Application {app_002.application_number} is scheduled for EVC stage completion within 2 days.",
                        notification_type=NotificationType.UPCOMING,
                        entity_type="APPLICATION_STAGE",
                        entity_id=app_002.id,
                        event_key="DEMO-NOTIF-UPCOMING-002",
                        is_read=False,
                    )
                )

        # B. Due Today Notification (Regional Officer West)
        if ro_west:
            notif_b = (
                session.query(Notification)
                .filter(Notification.event_key == "DEMO-NOTIF-DUETODAY-003")
                .first()
            )
            if not notif_b:
                session.add(
                    Notification(
                        user_id=ro_west.id,
                        application_id=app_003.id,
                        title="Decision Action Due Today",
                        message=f"Application {app_003.application_number} reaches its SLA deadline today.",
                        notification_type=NotificationType.DUE_TODAY,
                        entity_type="APPLICATION_STAGE",
                        entity_id=app_003.id,
                        event_key="DEMO-NOTIF-DUETODAY-003",
                        is_read=False,
                    )
                )

        # C. Overdue Alert (Regional Officer North)
        app_008 = app_map["APP-2026-DEMO-008"]
        if ro_north:
            notif_c = (
                session.query(Notification)
                .filter(Notification.event_key == "DEMO-NOTIF-OVERDUE-008")
                .first()
            )
            if not notif_c:
                session.add(
                    Notification(
                        user_id=ro_north.id,
                        application_id=app_008.id,
                        title="Application Stage Overdue Alert",
                        message=f"Application {app_008.application_number} is overdue by 7 days in stage Scrutiny.",
                        notification_type=NotificationType.OVERDUE,
                        entity_type="APPLICATION_STAGE",
                        entity_id=app_008.id,
                        event_key="DEMO-NOTIF-OVERDUE-008",
                        is_read=True,
                        read_at=now - timedelta(hours=5),
                    )
                )

        # D. Escalation Record & Notification to Bureau Officer
        if bureau:
            notif_d = (
                session.query(Notification)
                .filter(Notification.event_key == "DEMO-NOTIF-ESCALATE-008")
                .first()
            )
            if not notif_d:
                session.add(
                    Notification(
                        user_id=bureau.id,
                        application_id=app_008.id,
                        title="Critical SLA Escalation Notice",
                        message=f"ESCALATION: Application {app_008.application_number} exceeded SLA by 7 days. Escalated for Bureau review.",
                        notification_type=NotificationType.ESCALATION,
                        entity_type="APPLICATION_STAGE",
                        entity_id=app_008.id,
                        event_key="DEMO-NOTIF-ESCALATE-008",
                        is_read=False,
                    )
                )

            # Corresponding EscalationRecord
            esc_rec = (
                session.query(EscalationRecord)
                .filter(EscalationRecord.event_key == "DEMO-ESC-REC-008")
                .first()
            )
            if not esc_rec:
                session.add(
                    EscalationRecord(
                        application_id=app_008.id,
                        stage_id=app_008.current_stage_id,
                        entity_type="APPLICATION",
                        entity_id=app_008.id,
                        event_key="DEMO-ESC-REC-008",
                        escalation_level=EscalationLevel.LEVEL_2_REGIONAL,
                        recipient_user_id=ro_north.id if ro_north else bureau.id,
                        reason="Application stage SLA deadline exceeded by 7 days.",
                        trigger_time=now - timedelta(days=2),
                        acknowledged=False,
                    )
                )

        # E. System-Wide Portal Notification (Admin)
        if admin:
            notif_e = (
                session.query(Notification)
                .filter(Notification.event_key == "DEMO-NOTIF-SYSTEM-PORTAL")
                .first()
            )
            if not notif_e:
                session.add(
                    Notification(
                        user_id=admin.id,
                        title="Portal Readiness & Academic Cycle Initialized",
                        message="AICTE 2026-2027 Academic Approval Cycle workflow rules and role queues are online.",
                        notification_type=NotificationType.SYSTEM,
                        entity_type="SYSTEM",
                        entity_id=1,
                        event_key="DEMO-NOTIF-SYSTEM-PORTAL",
                        is_read=True,
                        read_at=now,
                    )
                )
        session.commit()

        # Update summary counts
        counts["applications"] = session.query(Application).count()
        counts["evc_visits"] = session.query(EVCVisit).count()
        counts["undertakings"] = session.query(Undertaking).count()
        counts["documents"] = session.query(UndertakingDocument).count()
        counts["notifications"] = session.query(Notification).count()
        counts["escalations"] = session.query(EscalationRecord).count()

        if verbose:
            print("\n=======================================================")
            print("  AICTE Workflow Platform - Demo Data Seed Summary")
            print("=======================================================")
            print(f"Institutions Seeded/Updated : {counts['institutions']}")
            print(f"Users Seeded/Updated        : {counts['users']}")
            print(f"Applications Registered     : {counts['applications']}")
            print(f"EVC Inspection Visits       : {counts['evc_visits']}")
            print(f"Statutory Undertakings      : {counts['undertakings']}")
            print(f"Compliance Documents        : {counts['documents']}")
            print(f"In-App Notifications        : {counts['notifications']}")
            print(f"SLA Escalation Records      : {counts['escalations']}")
            print(f"Standard Demo Password      : {DEFAULT_DEMO_PASSWORD}")
            print("-------------------------------------------------------")
            print(f"{'Role':<18} {'Email':<28} {'Region / Link'}")
            print("-------------------------------------------------------")
            for u in DEMO_USERS:
                link = u["region"] or u["institution_code"] or "HQ"
                print(f"{u['role'].value:<18} {u['email']:<28} {link}")
            print("=======================================================\n")

        return counts

    finally:
        if close_session:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="AICTE Workflow Platform - Demo Data Seeder")
    parser.add_argument(
        "--reset",
        "--reset-demo",
        dest="reset",
        action="store_true",
        help="Reset disposable demo data and reseed afresh",
    )
    args = parser.parse_args()
    seed_demo_data(reset=args.reset, verbose=True, full_demo=True)


if __name__ == "__main__":
    main()
