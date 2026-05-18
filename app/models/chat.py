"""
CommunityMessage model — stores global chat messages (text + image).
Uses ghost auth (device_id) instead of traditional user accounts.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.models.base import Base


class CommunityMessage(Base):
    __tablename__ = "community_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    sender_name = Column(String(100), nullable=False)
    content = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "image_url": self.image_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
