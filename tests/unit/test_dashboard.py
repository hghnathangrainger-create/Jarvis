"""
test_dashboard.py

Unit tests for the Jarvis Dashboard.

Covers:
    - Dashboard index route returns HTML
    - Static files (CSS, JS) are served correctly
    - Login page renders
    - API endpoints still work with the dashboard mounted
    - WebSocket endpoint is accessible

Run with:
    pytest tests/unit/test_dashboard.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a test FastAPI app with dashboard mounted."""
    import os
    os.environ["API_USERNAME"] = "testuser"
    os.environ["API_PASSWORD"] = "testpass"

    from api.app import create_app
    from api.routes_system import set_lifecycle_manager

    # Clear any lifecycle manager set by other test modules.
    set_lifecycle_manager(None)

    app = create_app(orchestrator=None)
    return app


@pytest.fixture()
def client(app):
    """Create a TestClient from the app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dashboard route tests
# ---------------------------------------------------------------------------


class TestDashboardRoutes:
    """Tests for dashboard page routes."""

    def test_index_returns_html(self, client):
        """GET / returns the dashboard HTML page."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Jarvis" in response.text
        assert "dashboard" in response.text.lower() or "Dashboard" in response.text

    def test_index_contains_sections(self, client):
        """The dashboard HTML contains all expected section divs."""
        response = client.get("/")
        content = response.text
        assert "section-today" in content
        assert "section-tasks" in content
        assert "section-memory" in content
        assert "section-knowledge" in content
        assert "section-audit" in content
        assert "section-providers" in content
        assert "section-goals" in content
        assert "section-settings" in content

    def test_index_contains_sidebar_nav(self, client):
        """The dashboard HTML contains sidebar navigation."""
        response = client.get("/")
        content = response.text
        assert "sidebar-nav" in content
        assert "nav-item" in content

    def test_login_page_returns_html(self, client):
        """GET /login returns the login page HTML."""
        response = client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Login" in response.text or "login" in response.text.lower()

    def test_login_page_contains_form(self, client):
        """The login page contains a login form."""
        response = client.get("/login")
        content = response.text
        assert "loginForm" in content or "login-form" in content
        assert "username" in content.lower()
        assert "password" in content.lower()


# ---------------------------------------------------------------------------
# Static file tests
# ---------------------------------------------------------------------------


class TestStaticFiles:
    """Tests for static file serving."""

    def test_css_served(self, client):
        """CSS file is served correctly."""
        response = client.get("/dashboard/static/css/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
        assert "--bg-primary" in response.text or "#0a0a0f" in response.text

    def test_js_served(self, client):
        """JavaScript file is served correctly."""
        response = client.get("/dashboard/static/js/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"] or "application/javascript" in response.headers["content-type"]
        assert "Jarvis" in response.text or "dashboard" in response.text.lower()

    def test_css_contains_dark_theme(self, client):
        """CSS contains the dark theme colors."""
        response = client.get("/dashboard/static/css/style.css")
        content = response.text
        assert "#0a0a0f" in content
        assert "#1a1a2e" in content
        assert "#00d4aa" in content

    def test_js_contains_auth_handling(self, client):
        """JavaScript contains JWT authentication handling."""
        response = client.get("/dashboard/static/js/app.js")
        content = response.text
        assert "localStorage" in content
        assert "Bearer" in content
        assert "401" in content

    def test_js_contains_websocket(self, client):
        """JavaScript contains WebSocket connection logic."""
        response = client.get("/dashboard/static/js/app.js")
        content = response.text
        assert "WebSocket" in content
        assert "/api/ws" in content


# ---------------------------------------------------------------------------
# API still works with dashboard mounted
# ---------------------------------------------------------------------------


class TestAPIWithDashboard:
    """Tests that API endpoints still work with the dashboard mounted."""

    def test_health_check(self, client):
        """System status endpoint still works."""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_login(self, client):
        """Login endpoint still works."""
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_protected_endpoint(self, client):
        """Protected endpoints still require auth."""
        response = client.get("/api/memory")
        assert response.status_code == 401

    def test_404_for_unknown_route(self, client):
        """Unknown routes still return 404."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_dashboard_and_api_coexist(self, client):
        """Dashboard at / and API at /api/* don't conflict."""
        # Dashboard root
        r1 = client.get("/")
        assert r1.status_code == 200

        # API health
        r2 = client.get("/api/system/status")
        assert r2.status_code == 200

        # Login
        r3 = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )
        assert r3.status_code == 200
