from fastapi.testclient import TestClient


def test_health_endpoint_v1(client: TestClient):
    """Verify /api/v1/health returns HTTP 200 with healthy status and metadata."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "app_name" in data
    assert data["database_connected"] is True
    assert data["version"] == "1.0.0"


def test_health_endpoint_top_level(client: TestClient):
    """Verify convenience /api/health alias works identically."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_static_html_index_delivery(client: TestClient):
    """Verify the root endpoint serves index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "AICTE" in response.text
    assert "Institutional Approval Lifecycle Platform" in response.text


def test_static_html_role_pages(client: TestClient):
    """Verify role-specific frontend landing pages are served."""
    for path in ["/login", "/institution", "/officer", "/admin"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "AICTE" in response.text


def test_static_css_and_js_delivery(client: TestClient):
    """Verify static assets are properly served from /static."""
    css_res = client.get("/static/css/custom.css")
    assert css_res.status_code == 200
    assert "--aicte-navy" in css_res.text

    js_res = client.get("/static/js/api.js")
    assert js_res.status_code == 200
    assert "getHealth" in js_res.text
