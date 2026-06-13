from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from app.models.base import Base

class CropDataCache(Base):
    """Unified cache for all AI-generated crop data.
    One entry per unique crop — stores standard names, about text,
    growth stage boundaries, and smart schedule milestones.
    All Hindi fields are always in Hindi regardless of user language.
    """
    __tablename__ = "crop_data_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crop_key = Column(String(100), unique=True, nullable=False, index=True,
                      comment="Lowercase English identifier, e.g. 'banana', 'wheat'")
    standard_name_en = Column(String(200), nullable=False,
                              comment="English standard name, e.g. 'Banana'")
    standard_name_hi = Column(String(200), nullable=False,
                              comment="Hindi standard name, e.g. 'केला'")
    about_hi = Column(Text, nullable=False,
                      comment="Short Hindi description (2-3 sentences)")
    day_stages = Column(JSON, nullable=False,
                        comment='{"Seedling": 15, "Vegetative": 60, "Flowering": 90, "Ready to Harvest": 120}')
    gdd_stages = Column(JSON, nullable=False,
                        comment='GDD boundaries derived from day_stages')
    smart_schedule_hi = Column(JSON, nullable=False,
                               comment='[{"task": "...", "icon": "emoji", "day": int}, ...]')
    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "crop_key": self.crop_key,
            "standard_name_en": self.standard_name_en,
            "standard_name_hi": self.standard_name_hi,
            "about_hi": self.about_hi,
            "day_stages": self.day_stages,
            "gdd_stages": self.gdd_stages,
            "smart_schedule_hi": self.smart_schedule_hi,
        }
