from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationStatus
from backend.models.evc import EVCRecommendation, EVCStatus, EVCVisit
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def setup_review_environment(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_full_evc_lifecycle_and_db_relationships(client: TestClient, db_session: Session):
    """
    1. Automatic creation upon workflow entry.
    2. Scheduling by authorized regional officer.
    3. Rescheduling with counter increment.
    4. Completion with recommendation and findings.
    5. Database relationships and integrity assertions.
    """
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    # Step 1: Submit application entering EVC
    res_app = client.post(
        "/api/applications",
        json={"route_type": "ONLY_EVC", "title": "Lifecycle Review Campus"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    assert res_app.status_code == 201
    app_id = res_app.json()["id"]

    # Assert automatic visit record creation in DB
    db_visit = db_session.query(EVCVisit).filter(EVCVisit.application_id == app_id).first()
    assert db_visit is not None
    assert db_visit.status == EVCStatus.PENDING_SCHEDULE
    assert db_visit.due_date is not None
    # Relationship checks
    assert db_visit.application.id == app_id
    assert db_visit.application.institution.name == "Delhi Technological University"

    # Step 2: Schedule visit
    sched_time = datetime.now(timezone.utc) + timedelta(days=6)
    sched_res = client.post(
        f"/api/evc/{db_visit.id}/schedule",
        json={
            "scheduled_date": sched_time.isoformat(),
            "committee_lead_name": "Prof. N. K. Goyal",
            "committee_members": ["Dr. S. Roy", "Dr. P. Sen"],
            "visit_mode": "PHYSICAL",
            "remarks": "Check laboratory compliance",
        },
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert sched_res.status_code == 200
    db_session.refresh(db_visit)
    assert db_visit.status == EVCStatus.SCHEDULED
    assert db_visit.committee_lead_name == "Prof. N. K. Goyal"

    # Step 3: Reschedule visit
    resched_time = datetime.now(timezone.utc) + timedelta(days=10)
    resched_res = client.post(
        f"/api/evc/{db_visit.id}/reschedule",
        json={
            "new_scheduled_date": resched_time.isoformat(),
            "reason": "Severe weather conditions at regional airport",
        },
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert resched_res.status_code == 200
    db_session.refresh(db_visit)
    assert db_visit.rescheduled_count == 1
    assert "Severe weather conditions" in db_visit.officer_remarks

    # Step 4: Complete visit
    comp_res = client.post(
        f"/api/evc/{db_visit.id}/complete",
        json={
            "recommendation": "RECOMMENDED",
            "remarks": "Infrastructure norms fully satisfied",
        },
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert comp_res.status_code == 200
    db_session.refresh(db_visit)
    assert db_visit.status == EVCStatus.COMPLETED
    assert db_visit.recommendation == EVCRecommendation.RECOMMENDED
    assert db_visit.conducted_date is not None


def test_invalid_status_transitions_rejected(client: TestClient, db_session: Session):
    """
    Verify invalid transitions on completed or cancelled visits are rejected with HTTP 400.
    """
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res_app = client.post(
        "/api/applications",
        json={"route_type": "ONLY_EVC", "title": "Transition Guard Campus"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    app_id = res_app.json()["id"]
    visit = db_session.query(EVCVisit).filter_by(application_id=app_id).first()

    # Complete the visit
    client.post(
        f"/api/evc/{visit.id}/complete",
        json={"recommendation": "RECOMMENDED", "remarks": "Done"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    db_session.refresh(visit)
    assert visit.status == EVCStatus.COMPLETED

    # 1. Attempting to schedule a COMPLETED visit -> 400 Bad Request
    res_sched = client.post(
        f"/api/evc/{visit.id}/schedule",
        json={"scheduled_date": datetime.now(timezone.utc).isoformat(), "committee_lead_name": "Lead"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_sched.status_code == 400
    assert "Cannot schedule inspection" in res_sched.json()["detail"]

    # 2. Attempting to reschedule a COMPLETED visit -> 400 Bad Request
    res_resched = client.post(
        f"/api/evc/{visit.id}/reschedule",
        json={"new_scheduled_date": datetime.now(timezone.utc).isoformat(), "reason": "Late reschedule attempt"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_resched.status_code == 400
    assert "terminal status" in res_resched.json()["detail"]

    # 3. Attempting to cancel a COMPLETED visit -> 400 Bad Request
    res_cancel = client.post(
        f"/api/evc/{visit.id}/cancel",
        json={"reason": "Cannot cancel completed"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_cancel.status_code == 400
    assert "Cannot cancel an already completed" in res_cancel.json()["detail"]


def test_cancellation_workflow(client: TestClient, db_session: Session):
    """
    Verify visit cancellation flow and that cancelled visits cannot be scheduled or completed.
    """
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res_app = client.post(
        "/api/applications",
        json={"route_type": "ONLY_EVC", "title": "Cancellation Test Campus"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    app_id = res_app.json()["id"]
    visit = db_session.query(EVCVisit).filter_by(application_id=app_id).first()

    # Cancel the visit
    res_cancel = client.post(
        f"/api/evc/{visit.id}/cancel",
        json={"reason": "Institution requested withdrawal of application"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_cancel.status_code == 200
    db_session.refresh(visit)
    assert visit.status == EVCStatus.CANCELLED

    # Attempt to complete cancelled visit -> 400 Bad Request
    res_comp = client.post(
        f"/api/evc/{visit.id}/complete",
        json={"recommendation": "RECOMMENDED"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_comp.status_code == 400


def test_queue_separation_by_region(client: TestClient):
    """
    Verify Northern Officer only sees Northern visits and Western Officer only sees Western visits.
    """
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    ro_west_token = get_token(client, "ro.west@aicte.gov.in")

    res1 = client.post("/api/applications", json={"route_type": "ONLY_EVC", "title": "North EVC"}, headers={"Authorization": f"Bearer {dtu_token}"})
    res2 = client.post("/api/applications", json={"route_type": "ONLY_EVC", "title": "West EVC"}, headers={"Authorization": f"Bearer {coep_token}"})
    id1, id2 = res1.json()["id"], res2.json()["id"]

    # North queue
    q_north = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_north_token}"}).json()
    north_apps = [v["application_id"] for v in q_north]
    assert id1 in north_apps
    assert id2 not in north_apps

    # West queue
    q_west = client.get("/api/evc", headers={"Authorization": f"Bearer {ro_west_token}"}).json()
    west_apps = [v["application_id"] for v in q_west]
    assert id2 in west_apps
    assert id1 not in west_apps


def test_duplicate_prevention_on_repeated_transitions(client: TestClient, db_session: Session):
    """
    Verify duplicate visits are strictly prevented even when stage transitions are retried.
    """
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res_app = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Scrutiny EVC Duplication Test"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    app_id = res_app.json()["id"]

    # Advance to EVC
    client.post(f"/api/applications/{app_id}/complete-stage", json={"remarks": "To EVC"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Count EVC visits in database
    count1 = db_session.query(EVCVisit).filter_by(application_id=app_id).count()
    assert count1 == 1

    # Return to Scrutiny
    client.post(f"/api/applications/{app_id}/return", json={"reason": "Need missing document"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Re-advance to EVC a second time
    client.post(f"/api/applications/{app_id}/complete-stage", json={"remarks": "To EVC again"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Assert exactly 1 visit record exists (no duplicate created!)
    count2 = db_session.query(EVCVisit).filter_by(application_id=app_id).count()
    assert count2 == 1
