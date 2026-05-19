"""
Auth routes — Device ID + PIN authentication with JWT tokens.

POST /register — Create a new user (device_id + PIN + name)
POST /login    — Authenticate and return a JWT
GET  /me       — Get current user profile (requires JWT)
"""

import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.config import settings

router = APIRouter()

# ── Common weak PINs to reject ─────────────────────────────────
WEAK_PINS = {
    "0000", "1111", "2222", "3333", "4444",
    "5555", "6666", "7777", "8888", "9999",
    "1234", "4321", "1122", "2580", "0852",
    "1212", "6969", "1010",
}


# ── Request Schemas ────────────────────────────────────────────
class RegisterRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=128)
    pin: str = Field(..., min_length=4, max_length=4)
    display_name: str = Field(default="Farmer", min_length=1, max_length=100)

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v):
        if not v.isdigit():
            raise ValueError("PIN must be exactly 4 digits")
        if v in WEAK_PINS:
            raise ValueError(f"PIN '{v}' is too common. Please choose a stronger PIN.")
        return v


class LoginRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=128)
    pin: str = Field(..., min_length=4, max_length=4)


class AuthResponse(BaseModel):
    token: str
    user: dict


# ── JWT Helper ─────────────────────────────────────────────────
def _create_jwt(user_id: str) -> str:
    """Create a signed JWT for the given user ID."""
    payload = {
        "uid": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRATION_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ── POST /register ─────────────────────────────────────────────
@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user with a device ID and 4-digit PIN.
    Returns a JWT for all subsequent API requests.
    """
    # Check if device already registered
    existing = db.query(User).filter(User.id == payload.device_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This device is already registered. Please use login instead.",
        )

    # Create user with hashed PIN
    user = User(
        id=payload.device_id,
        display_name=payload.display_name.strip(),
    )
    user.set_pin(payload.pin)

    db.add(user)
    db.commit()
    db.refresh(user)

    token = _create_jwt(user.id)
    return AuthResponse(token=token, user=user.to_dict())


# ── POST /login ────────────────────────────────────────────────
@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate with device ID + PIN. Returns a fresh JWT."""
    user = db.query(User).filter(User.id == payload.device_id).first()

    if not user or not user.verify_pin(payload.pin):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device ID or PIN.",
        )

    token = _create_jwt(user.id)
    return AuthResponse(token=token, user=user.to_dict())


# ── GET /me ────────────────────────────────────────────────────
@router.get("/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user profile from JWT."""
    user = db.query(User).filter(User.id == current_user.get("uid")).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()
