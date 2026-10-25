from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.security import create_access_token, hash_password
from backend.models.user import Institution, User, UserRole
from backend.seed import DEFAULT_DEMO_PASSWORD, seed_demo_data


@pytest.fixture(autouse=True)
def seed_data_for_auth_tests(db_session: Session):
    """Seed base demo accounts before running auth tests."""
    seed_demo_data(session=db_session, verbose=False)


def get_token_for_user(client: TestClient, email: str, password: str = DEFAULT_DEMO_PASSWORD) -> str:
    """Helper to authenticate and return bearer token."""
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, f"Login failed for {email}: {response.text}"
    return response.json()["access_token"]


def test_login_success_all_roles(client: TestClient):
    """Verify all 4 platform roles can authenticate successfully."""
    roles_and_emails = [
        ("ADMIN", "admin@aicte.gov.in"),
        ("BUREAU_OFFICER", "bureau@aicte.gov.in"),
        ("REGIONAL_OFFICER", "ro.north@aicte.gov.in"),
        ("INSTITUTION", "inst.dtu@aicte.gov.in"),
    ]
    for expected_role, email in roles_and_emails:
        response = client.post("/api/auth/login", json={"email": email, "password": DEFAULT_DEMO_PASSWORD})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == email
        assert data["user"]["role"] == expected_role
        # Security check: Password hash must never be returned in API response
        assert "hashed_password" not in data["user"]
        assert "password" not in data["user"]


def test_login_endpoint_v1_and_api_prefix(client: TestClient):
    """Verify both /api/auth/login and /api/v1/auth/login work identically."""
    for path in ["/api/auth/login", "/api/v1/auth/login"]:
        response = client.post(path, json={"email": "admin@aicte.gov.in", "password": DEFAULT_DEMO_PASSWORD})
        assert response.status_code == 200
        assert "access_token" in response.json()


def test_login_invalid_password_rejected(client: TestClient):
    """Verify wrong password returns HTTP 401 Unauthorized."""
    response = client.post("/api/auth/login", json={"email": "admin@aicte.gov.in", "password": "WrongPassword!"})
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_nonexistent_user_rejected(client: TestClient):
    """Verify non-existent user returns HTTP 401 Unauthorized."""
    response = client.post("/api/auth/login", json={"email": "nobody@aicte.gov.in", "password": DEFAULT_DEMO_PASSWORD})
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_get_current_user_profile_me(client: TestClient):
    """Verify GET /api/v1/auth/me returns current authenticated user details."""
    token = get_token_for_user(client, "bureau@aicte.gov.in")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == "bureau@aicte.gov.in"
    assert user_data["role"] == "BUREAU_OFFICER"
    assert "hashed_password" not in user_data


def test_missing_and_invalid_tokens_rejected(client: TestClient):
    """Verify unauthenticated requests return HTTP 401 Unauthorized."""
    # No header
    res1 = client.get("/api/v1/auth/me")
    assert res1.status_code == 401

    # Malformed token
    res2 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert res2.status_code == 401


def test_expired_token_rejected(client: TestClient, db_session: Session):
    """Verify expired token returns HTTP 401 Unauthorized."""
    user = db_session.query(User).filter(User.email == "admin@aicte.gov.in").first()
    # Generate token already expired 1 hour ago
    expired_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role.value},
        expires_delta=timedelta(hours=-1),
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401


def test_role_authorization_admin_users_list(client: TestClient):
    """Verify Admin can list users, while other roles receive HTTP 403 Forbidden."""
    admin_token = get_token_for_user(client, "admin@aicte.gov.in")
    ro_token = get_token_for_user(client, "ro.north@aicte.gov.in")
    inst_token = get_token_for_user(client, "inst.dtu@aicte.gov.in")

    # Admin access succeeds
    admin_res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    assert len(admin_res.json()) >= 4

    # Regional Officer access forbidden
    ro_res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {ro_token}"})
    assert ro_res.status_code == 403
    assert "Access forbidden" in ro_res.json()["detail"]

    # Institution access forbidden
    inst_res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {inst_token}"})
    assert inst_res.status_code == 403


def test_admin_create_user(client: TestClient, db_session: Session):
    """Verify Admin can provision a new user, and duplicate emails are rejected."""
    admin_token = get_token_for_user(client, "admin@aicte.gov.in")
    new_user_payload = {
        "email": "new.officer@aicte.gov.in",
        "full_name": "New Inspection Officer",
        "role": "REGIONAL_OFFICER",
        "region": "Southern Region",
        "password": "Password123!",
    }

    # Create new user
    res = client.post("/api/v1/users", json=new_user_payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 201
    created = res.json()
    assert created["email"] == "new.officer@aicte.gov.in"
    assert created["role"] == "REGIONAL_OFFICER"
    assert "hashed_password" not in created

    # Duplicate rejection
    dup_res = client.post("/api/v1/users", json=new_user_payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]


def test_user_cannot_change_own_role(client: TestClient, db_session: Session):
    """Verify ordinary users cannot escalate their privilege or change their role."""
    inst_user = db_session.query(User).filter(User.email == "inst.dtu@aicte.gov.in").first()
    inst_token = get_token_for_user(client, "inst.dtu@aicte.gov.in")

    # Attempt to change role to ADMIN
    res = client.patch(
        f"/api/v1/users/{inst_user.id}",
        json={"role": "ADMIN"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res.status_code == 403
    assert "Non-administrators are not permitted to change user roles" in res.json()["detail"]


def test_inactive_user_cannot_login(client: TestClient, db_session: Session):
    """Verify deactivated accounts cannot log in."""
    user = db_session.query(User).filter(User.email == "ro.west@aicte.gov.in").first()
    user.is_active = False
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "ro.west@aicte.gov.in", "password": DEFAULT_DEMO_PASSWORD})
    assert res.status_code == 401
    assert "Account is inactive" in res.json()["detail"]


def test_seed_demo_data_idempotency(db_session: Session):
    """Verify running seed_demo_data repeatedly does not fail or duplicate."""
    res1 = seed_demo_data(session=db_session, verbose=False)
    res2 = seed_demo_data(session=db_session, verbose=False)
    assert res1["users"] == res2["users"]
    assert res1["institutions"] == res2["institutions"]


def test_institution_accessing_officer_functionality_rejected(client: TestClient):
    """Security check: Institution role attempting to access officer-only endpoint receives 403 Forbidden."""
    inst_token = get_token_for_user(client, "inst.dtu@aicte.gov.in")
    response = client.get("/api/v1/auth/officer-check", headers={"Authorization": f"Bearer {inst_token}"})
    assert response.status_code == 403
    assert "Access forbidden: requires one of [REGIONAL_OFFICER, BUREAU_OFFICER]" in response.json()["detail"]


def test_regional_officer_accessing_admin_functionality_rejected(client: TestClient):
    """Security check: Regional Officer attempting to access admin user provisioning receives 403 Forbidden."""
    ro_token = get_token_for_user(client, "ro.north@aicte.gov.in")
    # GET users
    res_get = client.get("/api/v1/users", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_get.status_code == 403
    assert "Access forbidden" in res_get.json()["detail"]

    # POST users
    res_post = client.post(
        "/api/v1/users",
        json={"email": "hacker@test.com", "full_name": "Fake", "role": "ADMIN", "password": "Password123!"},
        headers={"Authorization": f"Bearer {ro_token}"},
    )
    assert res_post.status_code == 403
    assert "Access forbidden" in res_post.json()["detail"]


def test_authorized_access_by_correct_role(client: TestClient):
    """Verify authorized users can access the endpoints intended for their role."""
    ro_token = get_token_for_user(client, "ro.north@aicte.gov.in")
    bureau_token = get_token_for_user(client, "bureau@aicte.gov.in")
    admin_token = get_token_for_user(client, "admin@aicte.gov.in")

    # Regional officer accessing officer endpoint
    res_ro = client.get("/api/v1/auth/officer-check", headers={"Authorization": f"Bearer {ro_token}"})
    assert res_ro.status_code == 200
    assert res_ro.json()["role"] == "REGIONAL_OFFICER"

    # Bureau officer accessing officer endpoint
    res_bureau = client.get("/api/v1/auth/officer-check", headers={"Authorization": f"Bearer {bureau_token}"})
    assert res_bureau.status_code == 200
    assert res_bureau.json()["role"] == "BUREAU_OFFICER"

    # Admin accessing admin endpoint
    res_admin = client.get("/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200


def test_password_hash_storage_and_response_sanitization(client: TestClient, db_session: Session):
    """
    Security check:
    1. Database never stores plaintext passwords; bcrypt hashes with $2b$ prefix are used.
    2. API responses across all endpoints sanitize and omit password hashes.
    """
    admin_user = db_session.query(User).filter(User.email == "admin@aicte.gov.in").first()
    assert admin_user.hashed_password != DEFAULT_DEMO_PASSWORD
    assert admin_user.hashed_password.startswith("$2b$12$")

    # 1. Login endpoint response check
    login_res = client.post("/api/auth/login", json={"email": "admin@aicte.gov.in", "password": DEFAULT_DEMO_PASSWORD})
    login_user = login_res.json()["user"]
    assert "hashed_password" not in login_user
    assert "password" not in login_user

    # 2. /me profile endpoint response check
    admin_token = login_res.json()["access_token"]
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    me_user = me_res.json()
    assert "hashed_password" not in me_user
    assert "password" not in me_user

    # 3. Users list endpoint response check
    users_res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"})
    for u in users_res.json():
        assert "hashed_password" not in u
        assert "password" not in u

