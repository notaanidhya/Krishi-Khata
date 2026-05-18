"""
Pydantic schemas for Community Chat — validation for messages.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ChatMessageCreate(BaseModel):
    """Incoming WebSocket message payload."""
    device_id: str = Field(..., min_length=1, max_length=64)
    sender_name: str = Field(..., min_length=1, max_length=100)
    content: Optional[str] = None
    image_url: Optional[str] = None


class ChatMessageResponse(BaseModel):
    """Outgoing message shape — broadcast to all clients."""
    id: int
    device_id: str
    sender_name: str
    content: Optional[str] = None
    image_url: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
