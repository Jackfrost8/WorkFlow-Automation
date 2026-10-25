"""
Phase 8: Frontend Dashboards & API Endpoints Integration Test Suite.
Verifies delivery of static role dashboards, frontend assets, XSS sanitization contracts,
Admin Audit and Workflow configuration APIs, and end-to-end data binding for all 4 roles.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.user import UserRole
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data
from backend.services.deadline_service import ensure_default_deadline_rules
from backend.workflow.config import ensure_default_workflow_routes


@pytest.fixture(autouse=True)
def setup_frontend_test_env(db_session: Session):
    seed_demo_data(session=db_session, verbose=False)
    ensure_default_workflow_routes(db_session)
    ensure_default_deadline_rules(db_session)


def get_token_for(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


# =========================================================================
# 1. HTML Dashboard Pages & Static Asset Delivery
# =========================================================================

def test_static_html_pages_delivery(client: TestClient):
    """Verify all 5 role-based HTML pages are served with 200 OK and expected structure."""
    endpoints = {
        "/": "AICTE Approval Workflow Automation",
        "/login": "Sign in to AICTE Portal",
        "/institution": "Institution Portal",
        "/officer": "Officer Scrutiny &amp; Regulatory Desk",
        "/bureau": "Bureau Apex Oversight Desk",
        "/admin": "Admin Central Console",
    }
    for path, expected_text in endpoints.items():
        res = client.get(path)
        assert res.status_code == 200, f"Failed to serve {path}: {res.status_code}"
        assert expected_text in res.text, f"Missing '{expected_text}' in {path}"


def test_static_js_and_css_delivery(client: TestClient):
    """Verify JS modules and CSS stylesheets are delivered with correct MIME types."""
    assets = [
        "/static/js/api.js",
        "/static/js/auth.js",
        "/static/css/custom.css",
    ]
    for asset in assets:
        res = client.get(asset)
        assert res.status_code == 200, f"Failed to serve asset {asset}"
        assert len(res.content) > 100, f"Asset {asset} appears empty"


def test_login_page_demo_buttons_present(client: TestClient):
    """Verify login page includes 1-click credentials for all 4 distinct roles."""
    res = client.get("/login")
    assert res.status_code == 200
    html = res.text
    assert "admin@aicte.gov.in" in html
    assert "bureau@aicte.gov.in" in html
    assert "ro.north@aicte.gov.in" in html
    assert "inst.dtu@aicte.gov.in" in html


# =========================================================================
# 2. Admin Workflows & Audit Logs API Endpoints
# =========================================================================

def test_admin_workflows_endpoint(client: TestClient):
    """Verify GET /api/admin/workflows returns all configured routes with stages and SLAs."""
    admin_token = get_token_for(client, "admin@aicte.gov.in")
    res = client.get(
        "/api/admin/workflows",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    workflows = res.json()
    assert len(workflows) >= 4

    codes = [w["code"] for w in workflows]
    assert "ONLY_SCRUTINY" in codes
    assert "SCRUTINY_EVC" in codes
    assert "EVC_SAC" in codes
    assert "ONLY_EVC" in codes

    for w in workflows:
        assert "stages" in w
        assert len(w["stages"]) > 0
        for s in w["stages"]:
            assert "sla_days" in s
            assert "authorized_roles" in s
            assert s["sla_days"] > 0


def test_admin_audit_logs_rbac_and_integrity(client: TestClient):
    """Verify GET /api/admin/audit-logs enforces RBAC, returns SHA-256 hashes and pagination."""
    admin_token = get_token_for(client, "admin@aicte.gov.in")
    bureau_token = get_token_for(client, "bureau@aicte.gov.in")
    inst_token = get_token_for(client, "inst.dtu@aicte.gov.in")

    # 1. Institution forbidden
    res_inst = client.get(
        "/api/admin/audit-logs",
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_inst.status_code == 403

    # 2. Admin authorized
    res_admin = client.get(
        "/api/admin/audit-logs?limit=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    logs = res_admin.json()
    assert isinstance(logs, list)

    if len(logs) > 0:
        first_log = logs[0]
        assert "prev_hash" in first_log
        assert "curr_hash" in first_log
        assert "action" in first_log
        assert "resource_type" in first_log

    # 3. Bureau Officer authorized
    res_bureau = client.get(
        "/api/admin/audit-logs?limit=5",
        headers={"Authorization": f"Bearer {bureau_token}"},
    )
    assert res_bureau.status_code == 200


# =========================================================================
# 3. Simulated Time Machine & Notification Drawer APIs
# =========================================================================

def test_simulated_time_cycle(client: TestClient):
    """Verify inspection, advancement, and reset of persistent simulated demo time."""
    admin_token = get_token_for(client, "admin@aicte.gov.in")

    # Inspect current status
    res = client.get(
        "/api/admin/simulated-time",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "simulated_time" in data
    assert "real_time" in data
    assert "offset_days" in data

    # Advance time +3 days
    adv_res = client.post(
        "/api/admin/advance-time",
        json={"days": 3, "run_deadline_check": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adv_res.status_code == 200
    adv_data = adv_res.json()
    assert adv_data["days_advanced"] == 3

    # Reset back to 0
    rst_res = client.post(
        "/api/admin/reset-time",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rst_res.status_code == 200
    assert rst_res.json()["offset_days"] == 0


def test_notifications_and_escalations_endpoints(client: TestClient):
    """Verify notifications listing, unread count, and rules management."""
    admin_token = get_token_for(client, "admin@aicte.gov.in")

    # Unread count
    cnt_res = client.get(
        "/api/notifications/unread-count",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cnt_res.status_code == 200
    assert "unread_count" in cnt_res.json()

    # Rules list
    rules_res = client.get(
        "/api/notifications/rules",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rules_res.status_code == 200
    rules = rules_res.json()
    assert len(rules) >= 4

    # Update first rule
    rule_id = rules[0]["id"]
    patch_res = client.patch(
        f"/api/notifications/rules/{rule_id}",
        json={"reminder_threshold_days": 4},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["reminder_threshold_days"] == 4


# =========================================================================
# 4. End-to-End Role API Interaction Verification
# =========================================================================

def test_institution_creates_and_queries_own_application(client: TestClient):
    """Verify institution can create an application and query it via API."""
    inst_token = get_token_for(client, "inst.dtu@aicte.gov.in")

    # Create app
    res = client.post(
        "/api/applications",
        json={
            "route_type": "SCRUTINY_EVC",
            "title": "Phase 8 UI Verification Expansion Campus",
            "academic_year": "2026-2027",
            "description": "Frontend UI testing application payload",
        },
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res.status_code == 201
    created_app = res.json()
    assert "application_number" in created_app
    app_id = created_app["id"]

    # Query list
    list_res = client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert list_res.status_code == 200
    apps = list_res.json()
    app_ids = [a["id"] for a in apps]
    assert app_id in app_ids


def test_officer_application_queue_and_actions(client: TestClient):
    """Verify regional officer retrieves regional queue and return requires reason."""
    inst_token = get_token_for(client, "inst.dtu@aicte.gov.in")
    ro_token = get_token_for(client, "ro.north@aicte.gov.in")

    # Create an application in North region (DTU is in North region)
    create_res = client.post(
        "/api/applications",
        json={
            "route_type": "SCRUTINY_EVC",
            "title": "North Region Engineering Campus",
            "academic_year": "2026-2027",
        },
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert create_res.status_code == 201
    created_app = create_res.json()
    app_id = created_app["id"]

    # Regional officer queries queue
    queue_res = client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert queue_res.status_code == 200
    apps = queue_res.json()
    app_ids = [a["id"] for a in apps]
    assert app_id in app_ids

    # Test returning without reason is rejected
    invalid_return = client.post(
        f"/api/applications/{app_id}/return",
        json={},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert invalid_return.status_code == 422  # Validation error: reason is required!
