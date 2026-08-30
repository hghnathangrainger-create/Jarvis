"""
routes.py

Dashboard routes for the Jarvis API.

Responsibilities:
    - GET / — serve the main index.html template (login if no token).
    - GET /login — serve the login page.
    - Mount /dashboard/static as a static files directory.

Does NOT:
    - Implement any business logic (all data comes from API endpoints).
    - Require JWT for the dashboard pages (the JS handles auth client-side).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

router = APIRouter(tags=["dashboard"])

# Resolve the dashboard directory relative to this file.
_DASHBOARD_DIR = Path(__file__).parent
_STATIC_DIR = _DASHBOARD_DIR / "static"
_TEMPLATES_DIR = _DASHBOARD_DIR / "templates"


def mount_dashboard(app: Any) -> None:
    """Mount the dashboard static files and routes on the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """
    # Mount static files (CSS, JS) before adding routes so they take priority.
    app.mount(
        "/dashboard/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="dashboard_static",
    )

    app.include_router(router)


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> HTMLResponse:
    """Serve the main dashboard page.

    The page is a single HTML file that handles authentication client-side
    via the JS app. If no JWT token is found, the JS redirects to /login.
    """
    template = _TEMPLATES_DIR / "index.html"
    content = template.read_text(encoding="utf-8")
    return HTMLResponse(content=content)


@router.get("/login", response_class=HTMLResponse)
async def dashboard_login(request: Request) -> HTMLResponse:
    """Serve the login page.

    A simple form that authenticates against /api/auth/login and stores
    the JWT token in localStorage before redirecting to the dashboard.
    """
    login_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jarvis — Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0f;
            color: #e0e0e0;
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .login-box {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 40px;
            width: 380px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .login-box h1 {
            color: #00d4aa;
            font-size: 24px;
            margin-bottom: 8px;
            text-align: center;
        }
        .login-box p {
            color: #888;
            text-align: center;
            margin-bottom: 24px;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 16px;
        }
        .form-group label {
            display: block;
            color: #aaa;
            font-size: 13px;
            margin-bottom: 6px;
        }
        .form-group input {
            width: 100%;
            padding: 10px 14px;
            background: #0d0d1a;
            border: 1px solid #2a2a4a;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        .form-group input:focus {
            border-color: #00d4aa;
        }
        .login-btn {
            width: 100%;
            padding: 12px;
            background: #00d4aa;
            color: #0a0a0f;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
            margin-top: 8px;
        }
        .login-btn:hover {
            background: #00b892;
        }
        .error {
            color: #ff6b6b;
            font-size: 13px;
            text-align: center;
            margin-top: 12px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>&#9881; Jarvis</h1>
        <p>AI Operating System Dashboard</p>
        <form id="loginForm">
            <div class="form-group">
                <label>Username</label>
                <input type="text" id="username" autocomplete="username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" id="password" autocomplete="current-password" required>
            </div>
            <button type="submit" class="login-btn">Sign In</button>
            <div class="error" id="error"></div>
        </form>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const errorEl = document.getElementById('error');
            errorEl.style.display = 'none';
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            try {
                const resp = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                if (resp.ok) {
                    const data = await resp.json();
                    localStorage.setItem('jarvis_token', data.access_token);
                    window.location.href = '/';
                } else {
                    errorEl.textContent = 'Invalid credentials';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = 'Connection failed';
                errorEl.style.display = 'block';
            }
        });
        // If already logged in, redirect to dashboard.
        if (localStorage.getItem('jarvis_token')) {
            window.location.href = '/';
        }
    </script>
</body>
</html>"""
    return HTMLResponse(content=login_html)
