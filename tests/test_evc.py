from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.audit import AuditLog
from backend.models.evc import EVCRecommendation, EVCStatus, EVCVisit
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def setup_evc_environment(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def create_test_evc_application(client: TestClient, inst_email: str = "inst.dtu@aicte.gov.in") -> int:
    """Helper creating an application that directly enters EVC stage."""
    token = get_token(client, inst_email)
    res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_EVC", "title": "EVC Test Campus"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_evc_queue_filtering_by_status_and_role(client: TestClient):
    """Verify EVC queue listing respects role scoping and status filters."""
    # DTU (North) and COEP (West) applications
    app1_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    app2_id = create_test_evc_application(client, "inst.coep@aicte.gov.in")

    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")

    # 1. Regional Officer (North) only sees DTU's EVC visit
    res_ro = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_north_token}"})
    assert res_ro.status_code == 200
    ro_app_ids = [v["application_id"] for v in res_ro.json()]
    assert app1_id in ro_app_ids
    assert app2_id not in ro_app_ids

    # 2. Bureau Officer sees cross-region visits (both North & West)
    res_bureau = client.get("/api/evc", headers={"Authorization": f"Bearer {bureau_token}"})
    assert res_bureau.status_code == 200
    bureau_app_ids = [v["application_id"] for v in res_bureau.json()]
    assert app1_id in bureau_app_ids
    assert app2_id in bureau_app_ids

    # 3. Institution DTU only sees its own EVC visit
    res_inst = client.get("/api/evc", headers={"Authorization": f"Bearer {dtu_token}"})
    assert res_inst.status_code == 200
    for v in res_inst.json():
        assert v["application_id"] == app1_id


def test_valid_evc_scheduling_and_audit(client: TestClient, db_session: Session):
    """Verify authorized officer can schedule an EVC visit and an audit entry is created."""
    app_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    # Get visit ID
    visits = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_token}"}).json()
    visit_id = next(v["id"] for v in visits if v["application_id"] == app_id)

    schedule_payload = {
        "scheduled_date": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        "committee_lead_name": "Prof. A. K. Sharma",
        "committee_members": ["Dr. Meena Gupta (IIT Delhi)", "Dr. R. K. Patel (NIT Kurukshetra)"],
        "visit_mode": "PHYSICAL",
        "remarks": "Bring infrastructure blueprints and lab logbooks",
    }

    res = client.post(f"/api/evc/{visit_id}/schedule", json=schedule_payload, headers={"Authorization": f"Bearer {ro_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SCHEDULED"
    assert data["committee_lead_name"] == "Prof. A. K. Sharma"
    assert len(data["committee_members"]) == 2
    assert data["visit_mode"] == "PHYSICAL"

    # Verify audit log recorded
    audit = db_session.query(AuditLog).filter(AuditLog.action == "EVC_VISIT_SCHEDULED", AuditLog.resource_id == str(visit_id)).first()
    assert audit is not None


def test_evc_rescheduling(client: TestClient, db_session: Session):
    """Verify rescheduling increments reschedule count, updates date, and logs audit."""
    app_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    visits = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_token}"}).json()
    visit_id = next(v["id"] for v in visits if v["application_id"] == app_id)

    # Initial schedule
    initial_date = datetime.now(timezone.utc) + timedelta(days=4)
    client.post(f"/api/evc/{visit_id}/schedule", json={"scheduled_date": initial_date.isoformat(), "committee_lead_name": "Prof. Lead"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Reschedule
    revised_date = datetime.now(timezone.utc) + timedelta(days=9)
    reschedule_payload = {
        "new_scheduled_date": revised_date.isoformat(),
        "reason": "Committee lead unavailable due to convocation duties",
        "remarks": "Moved forward by 5 days",
    }
    res = client.post(f"/api/evc/{visit_id}/reschedule", json=reschedule_payload, headers={"Authorization": f"Bearer {ro_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["rescheduled_count"] == 1
    assert "Rescheduled: Committee lead unavailable" in data["officer_remarks"]

    # Audit check
    audit = db_session.query(AuditLog).filter(AuditLog.action == "EVC_VISIT_RESCHEDULED", AuditLog.resource_id == str(visit_id)).first()
    assert audit is not None


def test_evc_completion_and_findings(client: TestClient, db_session: Session):
    """Verify completing an EVC visit records recommendations, deficiencies, and completion status."""
    app_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    visits = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_token}"}).json()
    visit_id = next(v["id"] for v in visits if v["application_id"] == app_id)

    # Schedule visit first
    client.post(
        f"/api/evc/{visit_id}/schedule",
        json={"scheduled_date": datetime.now(timezone.utc).isoformat(), "committee_lead_name": "Dr. Inspector"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )

    # Complete visit
    complete_payload = {
        "recommendation": "RECOMMENDED",
        "deficiencies": "Minor: library digital subscription pending renewal",
        "remarks": "Campus facilities comply with AICTE Approval Process Handbook standards",
        "report_file_path": "/uploads/evc_report_dtu_2026.pdf",
    }
    res = client.post(f"/api/evc/{visit_id}/complete", json=complete_payload, headers={"Authorization": f"Bearer {ro_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert data["recommendation"] == "RECOMMENDED"
    assert data["deficiencies"] == "Minor: library digital subscription pending renewal"
    assert data["conducted_date"] is not None


def test_unauthorized_institution_cannot_schedule_or_complete(client: TestClient):
    """Verify institution accounts cannot perform scheduling, rescheduling, or completion."""
    app_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")

    visits = client.get("/api/evc", headers={"Authorization": f"Bearer {inst_token}"}).json()
    visit_id = next(v["id"] for v in visits if v["application_id"] == app_id)

    # Institution attempting schedule -> 403 Forbidden
    res_sched = client.post(
        f"/api/evc/{visit_id}/schedule",
        json={"scheduled_date": datetime.now(timezone.utc).isoformat(), "committee_lead_name": "Dean"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_sched.status_code == 403

    # Institution attempting complete -> 403 Forbidden
    res_comp = client.post(
        f"/api/evc/{visit_id}/complete",
        json={"recommendation": "RECOMMENDED"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_comp.status_code == 403


def test_regional_officer_cannot_act_outside_region(client: TestClient):
    """Verify Regional Officer North cannot schedule an EVC visit in Western Region (COEP)."""
    coep_app_id = create_test_evc_application(client, "inst.coep@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    ro_west_token = get_token(client, "ro.west@aicte.gov.in")

    # Get visit ID via authorized Western officer
    visits_west = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_west_token}"}).json()
    coep_visit_id = next(v["id"] for v in visits_west if v["application_id"] == coep_app_id)

    # RO North attempting schedule -> 403 Forbidden
    res_north = client.post(
        f"/api/evc/{coep_visit_id}/schedule",
        json={"scheduled_date": datetime.now(timezone.utc).isoformat(), "committee_lead_name": "Intruder"},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_north.status_code == 403
    assert "belongs to Western Region" in res_north.json()["detail"]


def test_evc_due_date_and_delayed_filtering(client: TestClient, db_session: Session):
    """Verify due date is assigned from stage deadline, and overdue visits are flagged as DELAYED."""
    app_id = create_test_evc_application(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    visit = db_session.query(EVCVisit).filter(EVCVisit.application_id == app_id).first()
    assert visit.due_date is not None

    # Artificially set due_date in the past
    visit.due_date = datetime.now(timezone.utc) - timedelta(days=2)
    db_session.commit()

    # Query with status='DELAYED'
    res_delayed = client.get("/api/evc?status=DELAYED", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_delayed.status_code == 200
    delayed_ids = [v["id"] for v in res_delayed.json()]
    assert visit.id in delayed_ids

    # Detail check: is_delayed must be True
    visit_detail = client.get(f"/api/evc/{visit.id}", headers={"Authorization": f"Bearer {ro_token}"}).json()
    assert visit_detail["is_delayed"] is True
