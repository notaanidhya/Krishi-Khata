"""
Shared FastAPI dependencies — Auth verification & DB session injection.

In development mode (FLASK_ENV=development), auth is bypassed entirely
and a mock user is returned so the frontend can be tested without Firebase.
"""

from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings

# ── Mock user for local development ────────────────────────────
DEV_USER = {
    "uid": "dev-user-001",
    "phone_number": "+919876543210",
    "name": "Dev Farmer",
}


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Dependency that verifies the Firebase ID token from the
    Authorization: Bearer <token> header.

    In development mode, skips verification entirely and returns
    a mock user so the app is fully usable without Firebase.
    """
    # ── Dev bypass — no token needed ──────────────────────────
    if settings.FLASK_ENV == "development":
        return DEV_USER

    # ── Production: extract and verify Bearer token ───────────
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.split("Bearer ")[1]
    try:
        from app.services import firebase_auth
        decoded_token = firebase_auth.verify_id_token(token)
        return decoded_token
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
