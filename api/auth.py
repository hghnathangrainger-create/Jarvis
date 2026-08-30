"""
auth.py

JWT authentication for the Jarvis API.

Responsibilities:
    - Generate and validate JWT access tokens.
    - Provide a FastAPI dependency that extracts the current user from a
      Bearer token.
    - Store admin credentials from environment variables.

Does NOT:
    - Implement login UI or session management.
    - Persist user records (single admin user from env vars).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from jose import JWTError, jwt
except ImportError:  # pragma: no cover
    JWTError = Exception  # type: ignore[misc,assignment]

    class jwt:  # type: ignore[no-redef]
        """Stub when python-jose is not installed."""

        @staticmethod
        def encode(*a: Any, **kw: Any) -> str:
            raise RuntimeError("python-jose is not installed")

        @staticmethod
        def decode(*a: Any, **kw: Any) -> dict[str, Any]:
            raise RuntimeError("python-jose is not installed")


logger = logging.getLogger(__name__)

# JWT configuration
SECRET_KEY = "jarvis-api-secret-change-in-production"  # noqa: S105
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Security scheme for OpenAPI docs
security = HTTPBearer(auto_error=False)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a JWT access token.

    Args:
        data: Claims to encode in the token (must include "sub").
        expires_delta: Optional custom expiry. Defaults to 24 hours.

    Returns:
        The encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Args:
        token: The raw JWT string.

    Returns:
        The decoded claims dict.

    Raises:
        HTTPException: If the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """FastAPI dependency that extracts the current user from a Bearer token.

    Args:
        credentials: The bearer credentials from the Authorization header.

    Returns:
        The decoded user claims dict.

    Raises:
        HTTPException: If no token is provided or it is invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(credentials.credentials)
