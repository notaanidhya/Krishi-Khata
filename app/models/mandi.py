"""
Mandi models:
  SavedMandi     — bookmarked commodity + mandi combinations (user preference).
  MandiPriceCache — locally cached rows from the data.gov.in Daily Price API.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Date,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from app.models.base import Base


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
    arrival_date = Column(Date, nullable=False, index=True)

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
            "arrival_date": self.arrival_date.isoformat() if hasattr(self.arrival_date, "isoformat") else str(self.arrival_date) if self.arrival_date else None,
        }
