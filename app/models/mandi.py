"""
Mandi models:
  SavedMandi     — bookmarked commodity + mandi combinations (user preference).
  MandiPriceCache — locally cached rows from the data.gov.in Daily Price API.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Float, String, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from app.models.base import Base


# ═══════════════════════════════════════════════════════════════
#  USER BOOKMARKS (existing)
# ═══════════════════════════════════════════════════════════════

class SavedMandi(Base):
    __tablename__ = "saved_mandis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    commodity = Column(String(100), nullable=False, comment="e.g. Wheat, Rice, Onion, Tomato")
    mandi_name = Column(String(150), nullable=False)
    state = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    user = relationship("User", back_populates="saved_mandis")

    # Prevent duplicate bookmarks
    __table_args__ = (
        UniqueConstraint(
            "user_id", "commodity", "mandi_name",
            name="uq_user_commodity_mandi",
        ),
    )

    def __repr__(self):
        return f"<SavedMandi {self.commodity}@{self.mandi_name}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "commodity": self.commodity,
            "mandi_name": self.mandi_name,
            "state": self.state,
            "district": self.district,
            "created_at": self.created_at.isoformat(),
        }

# ═══════════════════════════════════════════════════════════════
#  HISTORICAL PRICES (Local tracking)
# ═══════════════════════════════════════════════════════════════

class MandiPriceHistory(Base):
    __tablename__ = "mandi_price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    commodity = Column(String(100), nullable=False, index=True)
    state = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False, index=True)
    price = Column(Float, nullable=False)  # price per quintal (modal price)
    arrival_date = Column(String(50), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "commodity", "state", "district", "arrival_date",
            name="uq_mandi_price_history_item",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "commodity": self.commodity,
            "state": self.state,
            "district": self.district,
            "price": self.price,
            "arrival_date": self.arrival_date,
        }
