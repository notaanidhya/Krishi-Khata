"""
Laborer model — Labor Management sub-ledger.

Each farm can register laborers. Laborer entries are linked
to KhataTransactions via the laborer_id foreign key, enabling
per-laborer balance tracking (wages owed vs. payments made).
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Laborer(Base):
    __tablename__ = "laborers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(
        Integer, ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    name = Column(String(150), nullable=False)
    phone_number = Column(String(20), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    farm = relationship("Farm", back_populates="laborers")
    transactions = relationship("KhataTransaction", back_populates="laborer")

    def __repr__(self):
        return f"<Laborer {self.name} (farm={self.farm_id})>"

    def to_dict(self):
        return {
            "id": self.id,
            "farm_id": self.farm_id,
            "name": self.name,
            "phone_number": self.phone_number,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }
