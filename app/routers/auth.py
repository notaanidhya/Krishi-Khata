"""
Auth routes — Ghost Auth (Device ID + PIN) and user profile management.
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session
import bcrypt
import jwt

from app.database import get_db
from app.dependencies import get_current_user, limiter
from app.models.user import User
from app.models.farm import Farm
from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse
from app.config import settings

router = APIRouter()

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


from sqlalchemy import func

@router.get("/check-username")
async def check_username(name: str, db: Session = Depends(get_db)):
    """Check if a username is already taken."""
    user = db.query(User).filter(func.lower(User.display_name) == name.lower()).first()
    return {"exists": bool(user)}


@router.post("/register", response_model=AuthResponse)
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new device with a PIN."""
    # Check if device_id already exists (edge case)
    existing_device = db.query(User).filter(User.id == payload.device_id).first()
    if existing_device:
        raise HTTPException(status_code=400, detail="Device already registered")

    # Check if username already exists
    existing_user_by_name = db.query(User).filter(func.lower(User.display_name) == payload.display_name.lower()).first()
    if existing_user_by_name:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_pin = bcrypt.hashpw(payload.pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_user = User(
        id=payload.device_id,
        display_name=payload.display_name,
        pin_hash=hashed_pin
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Auto-create a default farm for the new user
    default_farm = Farm(
        user_id=new_user.id,
        name=f"{new_user.display_name} का खेत",
        area_acres=5.0,
        soil_type="Black",
        district="Indore",
        state="Madhya Pradesh"
    )
    db.add(default_farm)
    db.commit()

    access_token_expires = timedelta(days=settings.JWT_EXPIRATION_DAYS)
    access_token = create_access_token(
        data={"uid": new_user.id}, expires_delta=access_token_expires
    )

    return {"token": access_token, "user": new_user.to_dict()}


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    """Login with username and PIN."""
    user = db.query(User).filter(func.lower(User.display_name) == payload.username.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.pin_hash or not bcrypt.checkpw(payload.pin.encode('utf-8'), user.pin_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid PIN")

    access_token_expires = timedelta(days=settings.JWT_EXPIRATION_DAYS)
    access_token = create_access_token(
        data={"uid": user.id}, expires_delta=access_token_expires
    )

    return {"token": access_token, "user": user.to_dict(), "device_id": user.id}


@router.get("/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user profile."""
    uid = current_user.get("uid")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()


@router.patch("/me")
async def update_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update display name or language preference."""
    # TODO: Implement in Phase 1
    return {"message": "update-profile stub"}
