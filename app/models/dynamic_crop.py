from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from app.models.base import Base

class DynamicCrop(Base):
    """Stores crops added dynamically by users via Gemini."""
    __tablename__ = "dynamic_crops"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crop_name = Column(String(100), unique=True, nullable=False, index=True)
    
    # Growth stage boundaries in days (similar to DEFAULT_STAGES)
    seedling_days = Column(Integer, nullable=False)
    vegetative_days = Column(Integer, nullable=False)
    flowering_days = Column(Integer, nullable=False)
    harvest_days = Column(Integer, nullable=False)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "Seedling": self.seedling_days,
            "Vegetative": self.vegetative_days,
            "Flowering": self.flowering_days,
            "Ready to Harvest": self.harvest_days,
        }
