"""
SQLAlchemy engine, session factory, and DB dependency for FastAPI.

Production-ready pool configuration to prevent connection exhaustion
on Render's free PostgreSQL (max 97 connections).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Ensure instance folder exists for SQLite
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "instance"), exist_ok=True)

# Build engine kwargs based on database type
_is_sqlite = "sqlite" in settings.DATABASE_URL
_engine_kwargs = {}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: production-safe pool settings
    _engine_kwargs.update({
        "pool_size": 3,           # Conservative for Render free tier
        "max_overflow": 5,        # Burst capacity
        "pool_pre_ping": True,    # Auto-reconnect stale connections
        "pool_recycle": 300,      # Recycle connections every 5 minutes
    })

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
