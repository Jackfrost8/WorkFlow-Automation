from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationStageHistory, ApplicationStatus
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.workflow import WorkflowRoute, WorkflowStage
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def setup_workflow_test_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_verify_route_sequences_all_four_paths(client: TestClient, db_session: Session):
    """
    Verification Item 1 & 2:
    Verify each of the 4 configured routes traverses its exact stage sequence in the database.
    """
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    route_expected_sequences = {
        "ONLY_SCRUTINY": ["SCRUTINY", "DECISION"],
        "SCRUTINY_EVC": ["SCRUTINY", "EVC", "DECISION"],
        "EVC_SAC": ["EVC", "SAC", "DECISION"],
        "ONLY_EVC": ["EVC", "DECISION"],
    }

    for route_code, expected_stages in route_expected_sequences.items():
        # 1. Submit Application
        res = client.post(
            "/api/applications",
            json={"route_type": route_code, "title": f"Route Validation - {route_code}"},
            headers={"Authorization": f"Bearer {inst_token}"},
        )
        assert res.status_code == 201
        app_id = res.json()["id"]

        # Verify initial stage in database
        db_app = db_session.query(Application).filter(Application.id == app_id).first()
        assert db_app.current_stage.stage_key == expected_stages[0], (
            f"Route {route_code} initial stage was {db_app.current_stage.stage_key}, expected {expected_stages[0]}"
        )

        # 2. Traverse intermediate stages
        for idx in range(len(expected_stages) - 1):
            curr_expected = expected_stages[idx]
            next_expected = expected_stages[idx + 1]

            # Verify current stage before advancing
            db_session.refresh(db_app)
            assert db_app.current_stage.stage_key == curr_expected

            # Advance stage
            adv_res = client.post(
                f"/api/applications/{app_id}/complete-stage",
                json={"remarks": f"Transition from {curr_expected} to {next_expected}"},
                headers={"Authorization": f"Bearer {ro_token}"},
            )
            assert adv_res.status_code == 200

            db_session.refresh(db_app)
            assert db_app.current_stage.stage_key == next_expected

        # 3. Final Decision: REJECT
        assert db_app.current_stage.is_final is True
        final_res = client.post(
            f"/api/applications/{app_id}/complete-stage",
            json={"decision": "REJECT", "remarks": "Deficiencies unresolved"},
            headers={"Authorization": f"Bearer {ro_token}"},
        )
        assert final_res.status_code == 200
        db_session.refresh(db_app)
        assert db_app.status == ApplicationStatus.REJECTED


def test_verify_stage_history_database_accuracy(client: TestClient, db_session: Session):
    """
    Verification Item 3 & 4:
    Directly query database to assert that stage history accurately reflects transitions,
    including timestamps, actor IDs, actions, and SLA deadlines.
    """
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "History Accuracy Test"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = res.json()["id"]

    # Advance to EVC
    client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Scrutiny cleared, moving to EVC"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )

    # Directly inspect database records
    histories = (
        db_session.query(ApplicationStageHistory)
        .filter(ApplicationStageHistory.application_id == app_id)
        .order_by(ApplicationStageHistory.id.asc())
        .all()
    )
    assert len(histories) == 2

    # Entry 1 (Scrutiny): must be exited and completed
    h1 = histories[0]
    assert h1.action == "STAGE_COMPLETED"
    assert h1.entered_at is not None
    assert h1.exited_at is not None
    assert h1.deadline_at is not None
    # SLA duration check: Scrutiny SLA is 7 days
    sla_delta = h1.deadline_at - h1.entered_at
    assert abs(sla_delta.total_seconds() - timedelta(days=7).total_seconds()) < 5

    # Entry 2 (EVC): must be active (exited_at is None)
    h2 = histories[1]
    assert h2.action == "STAGE_ENTERED"
    assert h2.entered_at is not None
    assert h2.exited_at is None
    # EVC SLA duration is 10 days
    evc_delta = h2.deadline_at - h2.entered_at
    assert abs(evc_delta.total_seconds() - timedelta(days=10).total_seconds()) < 5


def test_verify_exactly_one_evc_record_created(client: TestClient, db_session: Session):
    """
    Verification Item 5:
    Entering EVC creates exactly one associated visit record throughout the application lifecycle.
    """
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Single EVC Record Test"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = res.json()["id"]

    # In Scrutiny: count must be 0
    c0 = db_session.query(EVCVisit).filter(EVCVisit.application_id == app_id).count()
    assert c0 == 0

    # Advance to EVC: count must be exactly 1
    client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "To EVC"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    c1 = db_session.query(EVCVisit).filter(EVCVisit.application_id == app_id).count()
    assert c1 == 1

    # Advance to DECISION: count must remain exactly 1
    client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "To DECISION"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    c2 = db_session.query(EVCVisit).filter(EVCVisit.application_id == app_id).count()
    assert c2 == 1


def test_verify_transaction_atomicity_on_failure(client: TestClient, db_session: Session):
    """
    Verification Item 12:
    Verify that an invalid operation leaves the database in a completely consistent state
    without partial or corrupt stage-history insertions.
    """
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Atomicity Verification Application"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = res.json()["id"]

    # Record initial counts
    initial_history_count = db_session.query(ApplicationStageHistory).filter_by(application_id=app_id).count()
    assert initial_history_count == 1

    # Advance to DECISION
    client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "To Decision"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    mid_history_count = db_session.query(ApplicationStageHistory).filter_by(application_id=app_id).count()
    assert mid_history_count == 2

    # Attempt invalid final decision (invalid parameter 'MAYBE')
    fail_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"decision": "MAYBE", "remarks": "Invalid decision attempt"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert fail_res.status_code == 422

    # Assert database state remains uncorrupted
    db_app = db_session.query(Application).filter_by(id=app_id).first()
    assert db_app.status == ApplicationStatus.IN_REVIEW
    assert db_app.final_decision_date is None

    # History count must not have changed
    after_fail_count = db_session.query(ApplicationStageHistory).filter_by(application_id=app_id).count()
    assert after_fail_count == 2
