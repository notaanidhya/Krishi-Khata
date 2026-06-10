from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.models.base import Base

class AICropTaskCache(Base):
    __tablename__ = "ai_crop_task_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crop_name = Column(String(100), nullable=False, index=True)
    stage = Column(String(100), nullable=False, index=True)
    weather_profile = Column(String(50), nullable=False, index=True)
    
    tasks_json = Column(JSON, nullable=False)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
