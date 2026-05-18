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
#  DAILY PRICE CACHE (data.gov.in)
# ═══════════════════════════════════════════════════════════════

class MandiPriceCache(Base):
    """
    Local cache of commodity price records fetched from the
    data.gov.in Daily Price API.

    Upserted every 12 hours by the background scheduler.
    The composite unique key (state + district + market + commodity +
    variety + arrival_date) prevents duplicate rows.
    """
    __tablename__ = "mandi_price_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Location
    state    = Column(String(150), nullable=False, index=True)
    district = Column(String(150), nullable=False, index=True)
    market   = Column(String(200), nullable=False)

    # Commodity info
    commodity = Column(String(150), nullable=False, index=True)
    variety   = Column(String(150), nullable=True)

    # Prices (INR per quintal) — nullable because gov data can have blanks
    min_price   = Column(Float, nullable=True)
    max_price   = Column(Float, nullable=True)
    modal_price = Column(Float, nullable=True)

    # Arrival date as reported by the API (string "dd/mm/yyyy" or "yyyy-mm-dd")
    arrival_date = Column(String(30), nullable=True)

    # Metadata
    fetched_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When this row was last fetched/upserted from the API",
    )

    __table_args__ = (
        UniqueConstraint(
            "state", "district", "market", "commodity", "variety", "arrival_date",
            name="uq_mandi_price_record",
        ),
        Index("ix_mandi_state_district", "state", "district"),
    )

    def __repr__(self):
        return f"<MandiPriceCache {self.commodity} @ {self.market} ({self.arrival_date})>"

    def to_dict(self):
        """Serialize to a frontend-friendly dict."""
        return {
            "id":           self.id,
            "state":        self.state,
            "district":     self.district,
            "market":       self.market,
            "commodity":    self.commodity,
            "variety":      self.variety or "",
            "min_price":    self.min_price,
            "max_price":    self.max_price,
            "modal_price":  self.modal_price,
            "arrival_date": self.arrival_date,
            "fetched_at":   self.fetched_at.isoformat() if self.fetched_at else None,
        }
