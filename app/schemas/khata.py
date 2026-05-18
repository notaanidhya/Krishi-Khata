"""
Pydantic schemas for Kisan Khata — request/response validation.
"""

from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ── Valid Categories ────────────────────────────────────────────
EXPENSE_CATEGORIES = ["seeds", "fertilizer", "pesticide", "labor", "tractor_rent", "equipment", "irrigation", "transport", "other_expense"]
INCOME_CATEGORIES = ["mandi_sale", "subsidy", "other_income"]
ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES


class TransactionCreate(BaseModel):
    """Schema for creating a new Khata transaction."""

    type: Literal["income", "expense"]
    amount: float = Field(..., gt=0, description="Transaction amount in INR, must be positive")
    category: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)
    farm_id: Optional[int] = Field(None, description="Nullable — if null, applies to whole operation")
    transaction_date: date = Field(default_factory=date.today)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v, info):
        if v not in ALL_CATEGORIES:
            raise ValueError(f"Invalid category '{v}'. Must be one of: {ALL_CATEGORIES}")
        return v

    @field_validator("category")
    @classmethod
    def validate_category_matches_type(cls, v, info):
        """Ensure expense categories aren't used for income and vice versa."""
        txn_type = info.data.get("type")
        if txn_type == "expense" and v in INCOME_CATEGORIES:
            raise ValueError(f"Category '{v}' is an income category, but type is 'expense'")
        if txn_type == "income" and v in EXPENSE_CATEGORIES:
            raise ValueError(f"Category '{v}' is an expense category, but type is 'income'")
        return v


class TransactionUpdate(BaseModel):
    """Schema for partially updating an existing transaction."""

    type: Optional[Literal["income", "expense"]] = None
    amount: Optional[float] = Field(None, gt=0)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)
    farm_id: Optional[int] = None
    transaction_date: Optional[date] = None


class TransactionResponse(BaseModel):
    """Schema for returning a transaction to the client."""

    id: int
    user_id: str
    farm_id: Optional[int]
    type: str
    amount: float
    category: str
    description: Optional[str]
    transaction_date: date
    created_at: str  # ISO string from to_dict()

    class Config:
        from_attributes = True


class KhataSummary(BaseModel):
    """Aggregated income/expense summary."""

    total_income: float
    total_expense: float
    net_profit: float
    transaction_count: int
