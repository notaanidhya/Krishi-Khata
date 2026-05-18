"""
Auth routes — Firebase token verification and user profile management.
POST /verify-token performs an upsert: creates the user if they don't exist.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()


@router.post("/verify-token")
async def verify_token(db: Session = Depends(get_db)):
    """
    Verify Firebase ID token.
    Logic: Check if User.id (UID) exists in DB.
    If not, automatically create the User record.
    Return the user profile.
    """
    # TODO: Implement in Phase 1
    return {"message": "verify-token stub"}


@router.get("/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user profile."""
    # TODO: Implement in Phase 1
    return {"message": "get-profile stub"}


@router.patch("/me")
async def update_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update display name or language preference."""
    # TODO: Implement in Phase 1
    return {"message": "update-profile stub"}
