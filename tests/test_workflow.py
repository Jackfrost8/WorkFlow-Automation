import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationStatus
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.user import Institution, User
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def seed_environment(db_session: Session):
    """Seed base demo accounts and default workflow routes before tests."""
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)


def get_token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def test_submit_application_all_four_routes(client: TestClient):
    """Verify an institution can submit applications for each of the 4 configured routes."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    routes = ["ONLY_SCRUTINY", "SCRUTINY_EVC", "EVC_SAC", "ONLY_EVC"]

    for r_code in routes:
        payload = {
            "route_type": r_code,
            "title": f"Expansion Application - {r_code}",
            "description": f"Testing submission for route {r_code}",
            "academic_year": "2026-2027",
        }
        res = client.post("/api/applications", json=payload, headers={"Authorization": f"Bearer {inst_token}"})
        assert res.status_code == 201, f"Route {r_code} submission failed: {res.text}"
        data = res.json()

        assert data["route_type"] == r_code
        assert data["status"] == "SUBMITTED"
        assert data["application_number"].startswith("AICTE/")
        assert data["current_stage"] is not None
        assert data["current_stage_deadline"] is not None
        assert len(data["stage_history"]) >= 1
        assert data["stage_history"][0]["action"] == "SUBMIT"

        # Check initial stage alignment per route
        if r_code in ["ONLY_SCRUTINY", "SCRUTINY_EVC"]:
            assert data["current_stage"]["stage_key"] == "SCRUTINY"
        else:
            assert data["current_stage"]["stage_key"] == "EVC"


def test_evc_record_created_on_entering_evc_stage(client: TestClient, db_session: Session):
    """Verify an EVCVisit record is automatically generated when an application enters EVC."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")

    # 1. Direct EVC route: created immediately on submission
    res_direct = client.post(
        "/api/applications",
        json={"route_type": "ONLY_EVC", "title": "Direct EVC Campus"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_direct.status_code == 201
    direct_app_id = res_direct.json()["id"]

    evc_visit = db_session.query(EVCVisit).filter(EVCVisit.application_id == direct_app_id).first()
    assert evc_visit is not None
    assert evc_visit.status == EVCStatus.PENDING_SCHEDULE

    # 2. Scrutiny-to-EVC route: created when transitioning into EVC
    res_scrutiny = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Scrutiny to EVC Campus"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_scrutiny.status_code == 201
    scrutiny_app_id = res_scrutiny.json()["id"]

    # In scrutiny, no EVC visit yet
    assert db_session.query(EVCVisit).filter(EVCVisit.application_id == scrutiny_app_id).first() is None

    # Advance stage from SCRUTINY to EVC
    ro_token = get_token(client, "ro.north@aicte.gov.in")
    complete_res = client.post(
        f"/api/applications/{scrutiny_app_id}/complete-stage",
        json={"remarks": "Scrutiny documents verified, moving to inspection"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["current_stage"]["stage_key"] == "EVC"

    # Now EVC visit must exist
    evc_visit_adv = db_session.query(EVCVisit).filter(EVCVisit.application_id == scrutiny_app_id).first()
    assert evc_visit_adv is not None
    assert evc_visit_adv.status == EVCStatus.PENDING_SCHEDULE


def test_valid_stage_transitions_end_to_end_only_scrutiny(client: TestClient):
    """
    Test full lifecycle of ONLY_SCRUTINY:
    SUBMIT (Institution) -> SCRUTINY (RO North) -> DECISION (RO North APPROVE) -> Final Status APPROVED
    """
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    # 1. Submit
    sub_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Full Cycle Test Application"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]
    scrutiny_stage_id = sub_res.json()["current_stage"]["id"]

    # 2. Complete Scrutiny -> Advances to DECISION
    adv_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Scrutiny cleared successfully", "expected_stage_id": scrutiny_stage_id},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert adv_res.status_code == 200
    data = adv_res.json()
    assert data["current_stage"]["stage_key"] == "DECISION"
    assert data["current_stage"]["is_final"] is True
    assert data["status"] == "IN_REVIEW"

    # 3. Final Decision: APPROVE
    decision_stage_id = data["current_stage"]["id"]
    approve_res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"decision": "APPROVE", "remarks": "Approved by Regional Committee", "expected_stage_id": decision_stage_id},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert approve_res.status_code == 200
    app_final = approve_res.json()
    assert app_final["status"] == "APPROVED"
    assert app_final["final_decision_date"] is not None
    assert app_final["final_decision_remarks"] == "Approved by Regional Committee"


def test_final_decision_requires_explicit_decision(client: TestClient):
    """Verify completing the final decision stage without APPROVE or REJECT is rejected."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    sub_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Decision Validation Test"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]

    # Advance to DECISION
    client.post(f"/api/applications/{app_id}/complete-stage", json={"remarks": "Forwarded"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Call complete-stage on DECISION stage without decision parameter
    res = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Attempting without decision"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res.status_code == 422
    assert "Final decision requires an explicit decision parameter" in res.json()["detail"]


def test_return_application_without_reason_rejected(client: TestClient):
    """Verify returning an application without a substantive reason is rejected with HTTP 422."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    sub_res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Return Test Application"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]

    # Empty reason
    res_empty = client.post(
        f"/api/applications/{app_id}/return",
        json={"reason": ""},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_empty.status_code == 422

    # Whitespace only
    res_ws = client.post(
        f"/api/applications/{app_id}/return",
        json={"reason": "   "},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_ws.status_code == 422


def test_return_application_moves_stage_and_sets_action_required(client: TestClient):
    """Verify returning an application sets status to ACTION_REQUIRED and tracks reason in history."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    # 1. Advance to EVC (Stage 2)
    sub_res = client.post(
        "/api/applications",
        json={"route_type": "SCRUTINY_EVC", "title": "Deficiency Return Test"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]
    client.post(f"/api/applications/{app_id}/complete-stage", json={"remarks": "To EVC"}, headers={"Authorization": f"Bearer {ro_token}"})

    # 2. Return from EVC back to Scrutiny
    ret_res = client.post(
        f"/api/applications/{app_id}/return",
        json={"reason": "Fire safety certificate expired, please resubmit valid compliance document."},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert ret_res.status_code == 200
    returned_app = ret_res.json()
    assert returned_app["status"] == "ACTION_REQUIRED"
    assert returned_app["current_stage"]["stage_key"] == "SCRUTINY"

    # Verify return history entry
    histories = returned_app["stage_history"]
    assert any("Fire safety certificate expired" in (h["remarks"] or "") for h in histories)


def test_institution_ownership_isolation(client: TestClient):
    """Verify Institution A cannot view or access Institution B's applications."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")

    # DTU creates application
    res_dtu = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "DTU Proprietary Expansion"},
        headers={"Authorization": f"Bearer {dtu_token}"},
    )
    dtu_app_id = res_dtu.json()["id"]

    # COEP attempts to view DTU application
    res_coep = client.get(f"/api/applications/{dtu_app_id}", headers={"Authorization": f"Bearer {coep_token}"})
    assert res_coep.status_code == 403
    assert "do not have permission" in res_coep.json()["detail"]

    # COEP lists applications: DTU application must not be in list
    res_coep_list = client.get("/api/applications", headers={"Authorization": f"Bearer {coep_token}"})
    coep_app_ids = [a["id"] for a in res_coep_list.json()]
    assert dtu_app_id not in coep_app_ids


def test_regional_officer_boundary_enforcement(client: TestClient):
    """Verify Regional Officer North cannot process applications from Western Region (COEP)."""
    coep_token = get_token(client, "inst.coep@aicte.gov.in")
    ro_north_token = get_token(client, "ro.north@aicte.gov.in")
    ro_west_token = get_token(client, "ro.west@aicte.gov.in")

    # COEP (Western Region) submits application
    res_coep = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "COEP Pune Expansion"},
        headers={"Authorization": f"Bearer {coep_token}"},
    )
    coep_app_id = res_coep.json()["id"]

    # RO North attempts to view COEP application -> 403 Forbidden
    res_north_view = client.get(f"/api/applications/{coep_app_id}", headers={"Authorization": f"Bearer {ro_north_token}"})
    assert res_north_view.status_code == 403
    assert "Application belongs to Western Region" in res_north_view.json()["detail"]

    # RO North attempts to complete stage on COEP application -> 403 Forbidden
    res_north_trans = client.post(
        f"/api/applications/{coep_app_id}/complete-stage",
        json={"remarks": "Unauthorized scrutiny attempt"},
        headers={"Authorization": f"Bearer {ro_north_token}"},
    )
    assert res_north_trans.status_code == 403

    # RO West (authorized jurisdiction) can complete stage successfully
    res_west_trans = client.post(
        f"/api/applications/{coep_app_id}/complete-stage",
        json={"remarks": "Western Regional Scrutiny Approved"},
        headers={"Authorization": f"Bearer {ro_west_token}"},
    )
    assert res_west_trans.status_code == 200


def test_bureau_officer_cross_region_monitoring(client: TestClient):
    """Verify Bureau Officer has authorized cross-region access to all applications."""
    dtu_token = get_token(client, "inst.dtu@aicte.gov.in")
    coep_token = get_token(client, "inst.coep@aicte.gov.in")
    bureau_token = get_token(client, "bureau@aicte.gov.in")

    # Create applications in North and West
    res1 = client.post("/api/applications", json={"route_type": "ONLY_SCRUTINY", "title": "North App"}, headers={"Authorization": f"Bearer {dtu_token}"})
    res2 = client.post("/api/applications", json={"route_type": "ONLY_SCRUTINY", "title": "West App"}, headers={"Authorization": f"Bearer {coep_token}"})
    id1, id2 = res1.json()["id"], res2.json()["id"]

    # Bureau officer can view both
    b1 = client.get(f"/api/applications/{id1}", headers={"Authorization": f"Bearer {bureau_token}"})
    assert b1.status_code == 200

    b2 = client.get(f"/api/applications/{id2}", headers={"Authorization": f"Bearer {bureau_token}"})
    assert b2.status_code == 200

    # Bureau officer list includes both
    all_apps = client.get("/api/applications", headers={"Authorization": f"Bearer {bureau_token}"}).json()
    retrieved_ids = [a["id"] for a in all_apps]
    assert id1 in retrieved_ids
    assert id2 in retrieved_ids


def test_repeated_or_concurrent_transition_rejected(client: TestClient):
    """Verify repeated transition requests on an already transitioned or completed stage are rejected."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    sub_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Concurrency Protection Application"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]
    stage_id = sub_res.json()["current_stage"]["id"]

    # 1. Advance stage with expected_stage_id
    res1 = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "First transition call", "expected_stage_id": stage_id},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res1.status_code == 200

    # 2. Repeated transition call with old stage_id -> 409 Conflict
    res2 = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Duplicate transition call", "expected_stage_id": stage_id},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res2.status_code == 409
    assert "already transitioned" in res2.json()["detail"]


def test_transition_on_finalized_application_rejected(client: TestClient):
    """Verify attempting to complete stage or return on an already approved/rejected application fails."""
    inst_token = get_token(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token(client, "ro.north@aicte.gov.in")

    # Complete through to APPROVE
    sub_res = client.post(
        "/api/applications",
        json={"route_type": "ONLY_SCRUTINY", "title": "Terminal State Test"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    app_id = sub_res.json()["id"]
    client.post(f"/api/applications/{app_id}/complete-stage", json={"remarks": "Forward"}, headers={"Authorization": f"Bearer {ro_token}"})
    client.post(f"/api/applications/{app_id}/complete-stage", json={"decision": "APPROVE", "remarks": "Approved"}, headers={"Authorization": f"Bearer {ro_token}"})

    # Attempt to advance again -> 400 Bad Request
    res_post_final = client.post(
        f"/api/applications/{app_id}/complete-stage",
        json={"remarks": "Attempting transition on approved app"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_post_final.status_code == 400
    assert "already finalized" in res_post_final.json()["detail"]

    # Attempt to return -> 400 Bad Request
    res_ret_final = client.post(
        f"/api/applications/{app_id}/return",
        json={"reason": "Attempting return on approved app"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_ret_final.status_code == 400
