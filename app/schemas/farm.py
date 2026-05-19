"""
Farm Pydantic schemas — request/response validation for farm CRUD.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class FarmCreate(BaseModel):
    """Schema for creating a new farm."""
    name: str = Field(..., min_length=1, max_length=150)
    area_acres: float = Field(..., gt=0)
    state: str = Field(..., min_length=1, max_length=100)
    district: str = Field(default="", max_length=100)
    soil_type: Optional[str] = Field(default=None, max_length=50)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class FarmUpdate(BaseModel):
    """Schema for updating a farm (all fields optional)."""
    name: Optional[str] = Field(default=None, max_length=150)
    area_acres: Optional[float] = Field(default=None, gt=0)
    state: Optional[str] = Field(default=None, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    soil_type: Optional[str] = Field(default=None, max_length=50)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class FarmResponse(BaseModel):
    """Schema for farm response."""
    id: int
    user_id: str
    name: str
    area_acres: float
    soil_type: Optional[str]
    district: str
    state: str
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}
