"""
User model — maps to Firebase Auth users.
PK is the Firebase UID (string), not an auto-incrementing integer.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship
from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    # Firebase UID as primary key
    id = Column(String(128), primary_key=True)

    phone_number = Column(
        String(20), unique=True, nullable=False, index=True,
        comment="E.164 format, e.g. +919876543210",
    )
    display_name = Column(String(100), nullable=True)
    preferred_language = Column(
        String(10), nullable=False, default="hi",
        comment="ISO 639-1 code: hi, en, ta, te, etc.",
    )

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    farms = relationship(
        "Farm", back_populates="owner",
        cascade="all, delete-orphan",
    )
    transactions = relationship(
        "KhataTransaction", back_populates="user",
        cascade="all, delete-orphan",
    )
    saved_mandis = relationship(
        "SavedMandi", back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User {self.phone_number}>"

    def to_dict(self):
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "display_name": self.display_name,
            "preferred_language": self.preferred_language,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
