"""
Farm model — each user can own multiple farms.
Geolocation fields enable weather & mandi lookups by proximity.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Farm(Base):
    __tablename__ = "farms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    name = Column(String(150), nullable=False)
    area_acres = Column(Float, nullable=False)
    soil_type = Column(
        String(50), nullable=True,
        comment="e.g. alluvial, black, red, laterite",
    )

    # Location
    district = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    owner = relationship("User", back_populates="farms")
    crop_cycles = relationship(
        "CropCycle", back_populates="farm",
        cascade="all, delete-orphan",
    )
    laborers = relationship(
        "Laborer", back_populates="farm",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Farm {self.name} ({self.district}, {self.state})>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "area_acres": self.area_acres,
            "soil_type": self.soil_type,
            "district": self.district,
            "state": self.state,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": self.created_at.isoformat(),
        }
