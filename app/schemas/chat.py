from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class ChatMessageResponse(BaseModel):
    id: int
    device_id: str
    sender_name: str
    content: Optional[str] = None
    image_url: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
