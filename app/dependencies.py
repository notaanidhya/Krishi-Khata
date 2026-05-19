"""
Shared FastAPI dependencies — JWT-based auth verification & DB session.

Production: Validates the JWT from Authorization: Bearer <token> header.
Development: Falls back to a mock user if FLASK_ENV=development AND no token is provided.
"""

import jwt
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings

# ── Mock user for local development (only when no JWT is sent) ──
DEV_USER = {
    "uid": "dev-user-001",
    "name": "Dev Farmer",
}


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Dependency that verifies the JWT from the
    Authorization: Bearer <token> header.

    In development mode, if NO token is present, falls back to
    a mock user so the app can be tested without auth.
    If a token IS present (even in dev), it's validated normally.
    """
    auth_header = request.headers.get("Authorization")

    # ── Dev fallback — only if no token was sent ──────────────
    if not auth_header or not auth_header.startswith("Bearer "):
        if settings.FLASK_ENV == "development":
            return DEV_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Extract and verify JWT ────────────────────────────────
    token = auth_header.split("Bearer ")[1]
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        uid = payload.get("uid")
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return {"uid": uid}

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
