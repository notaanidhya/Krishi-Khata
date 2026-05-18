"""
Pydantic schemas for Crop Tracking — CropCycle CRUD & CropLog CRUD.

The response schema includes dynamically calculated fields:
  - days_since_planting (int)
  - current_stage (str)
These are computed by the backend from planting_date, NOT stored in DB.
"""

from datetime import date, datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field


# ── CropLog ─────────────────────────────────────────────────────

class CropLogCreate(BaseModel):
    """Schema for creating a new Farm Diary log entry."""

    log_date: date = Field(default_factory=date.today)
    input_type: Literal["text", "audio", "image"] = "text"
    raw_content: str = Field(..., min_length=1, max_length=5000, description="User text or media URL")


class CropLogResponse(BaseModel):
    """Schema for returning a CropLog entry to the client."""

    id: int
    crop_cycle_id: int
    log_date: date
    input_type: str
    raw_content: str
    ai_extracted_stage: Optional[str] = None
    ai_health_notes: Optional[str] = None
    ai_analysis_failed: bool = False
    created_at: str

    class Config:
        from_attributes = True


# ── CropCycle ───────────────────────────────────────────────────

class CropCycleCreate(BaseModel):
    """Schema for planting a new crop cycle."""

    crop_name: str = Field(..., min_length=1, max_length=100, description="e.g. Wheat, Brinjal, Tomato")
    planting_date: date = Field(default_factory=date.today, description="Date the crop was planted/sown")


class CropCycleResponse(BaseModel):
    """Schema for returning a CropCycle with calculated stage info."""

    id: int
    farm_id: int
    crop_name: str
    planting_date: date
    status: str
    days_since_planting: int
    current_stage: str
    created_at: str
    updated_at: str
    logs: List[CropLogResponse] = []

    class Config:
        from_attributes = True
