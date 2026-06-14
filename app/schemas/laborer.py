from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class LaborerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, description="Laborer's full name")
    phone_number: Optional[str] = Field(
        None, max_length=20,
        description="Contact phone number (optional)",
    )

    is_active: bool = Field(True, description="Whether the laborer is currently active")


class LaborerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    phone_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class LaborerResponse(BaseModel):
    id: int
    farm_id: int
    name: str
    phone_number: Optional[str]
    is_active: bool
    created_at: str  # ISO string from to_dict()
    current_balance: float = Field(
        0.0,
        description="Net balance: SUM(labor_wage) - SUM(labor_payment). Positive = owed to laborer.",
    )
    transaction_count: int = Field(
        0,
        description="Total number of transactions (wages + payments) for this laborer.",
    )

    class Config:
        from_attributes = True
