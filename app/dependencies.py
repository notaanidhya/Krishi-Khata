"""
Shared FastAPI dependencies — Auth verification & DB session injection.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

from app.database import get_db
from app.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """
    Dependency that verifies the JWT token from the
    Authorization: Bearer <token> header.
    Returns the decoded token dict (contains 'uid').
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        
        # Verify the user actually exists in the DB to handle DB wipes/switches
        from app.models.user import User
        uid = payload.get("uid")
        if not db.query(User).filter(User.id == uid).first():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer exists",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return payload
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
