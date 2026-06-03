"""
User model — device-based ghost auth with optional PIN.
PK is the device UUID (string), not an auto-incrementing integer.
PIN is hashed via bcrypt before storage.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship
import bcrypt

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    # Device UUID as primary key
    id = Column(String(128), primary_key=True)

    display_name = Column(String(100), nullable=False, default="Farmer")
    pin_hash = Column(
        String(255), nullable=True,
        comment="bcrypt hash of the user's 4-digit PIN",
    )
    phone_number = Column(
        String(20), unique=True, nullable=True, index=True,
        comment="E.164 format, e.g. +919876543210 (optional, for future OTP upgrade)",
    )
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
        lazy="selectin",
    )
    transactions = relationship(
        "KhataTransaction", back_populates="user",
        cascade="all, delete-orphan",
    )

    # ── PIN helpers ────────────────────────────────────────────────
    def set_pin(self, raw_pin: str):
        # Generates a secure salt and hashes the PIN directly with bcrypt
        salt = bcrypt.gensalt()
        self.pin_hash = bcrypt.hashpw(raw_pin.encode('utf-8'), salt).decode('utf-8')

    def verify_pin(self, raw_pin: str) -> bool:
        # Securely checks the raw PIN against the stored hash
        if not self.pin_hash:
            return False
        return bcrypt.checkpw(raw_pin.encode('utf-8'), self.pin_hash.encode('utf-8'))

    def __repr__(self):
        return f"<User {self.display_name} ({self.id[:8]}...)>"

    def to_dict(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "phone_number": self.phone_number,
            "preferred_language": self.preferred_language,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
