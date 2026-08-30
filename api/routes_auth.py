"""
routes_auth.py

Authentication endpoints for the Jarvis API.

Responsibilities:
    - POST /api/auth/login — authenticate and return a JWT token.

Does NOT:
    - Implement JWT generation (see auth.py).
    - Require authentication for the login endpoint itself.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from api.auth import create_access_token
from api.models import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest) -> TokenResponse:
    """Authenticate and return a JWT token."""
    expected_user = os.environ.get("API_USERNAME", "admin")
    expected_pass = os.environ.get("API_PASSWORD", "changeme")

    if credentials.username == expected_user and credentials.password == expected_pass:
        token = create_access_token(data={"sub": credentials.username})
        return TokenResponse(access_token=token)

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid credentials"},
    )
