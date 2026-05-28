"""
Pydantic schemas for Kisan Khata — request/response validation.
"""

from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ── Valid Categories ────────────────────────────────────────────
EXPENSE_CATEGORIES = ["seeds", "fertilizer", "pesticide", "labor", "tractor_rent", "equipment", "irrigation", "transport", "other_expense"]
INCOME_CATEGORIES = ["mandi_sale", "subsidy", "other_income"]
LABOR_CATEGORIES = ["labor_wage", "labor_payment"]
ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES + LABOR_CATEGORIES

# ── Valid Transaction Types ─────────────────────────────────────
VALID_TYPES = Literal["income", "expense", "labor_wage", "labor_payment"]


class TransactionCreate(BaseModel):
    """Schema for creating a new Khata transaction."""

    type: VALID_TYPES
    amount: float = Field(..., gt=0, description="Transaction amount in INR, must be positive")
    category: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)
    farm_id: Optional[int] = Field(None, description="Nullable — if null, applies to whole operation")
    laborer_id: Optional[int] = Field(None, description="Required for labor_wage/labor_payment types")
    transaction_date: date = Field(default_factory=date.today)

    @field_validator("category")
    @classmethod
    def validate_category_matches_type(cls, v, info):
        """Ensure expense categories aren't used for income and vice versa."""
        txn_type = info.data.get("type")
        if txn_type == "expense" and v in INCOME_CATEGORIES:
            raise ValueError(f"Category '{v}' is an income category, but type is 'expense'")
        if txn_type == "income" and v in EXPENSE_CATEGORIES:
            raise ValueError(f"Category '{v}' is an expense category, but type is 'income'")
        # Labor types must use labor categories
        if txn_type in ("labor_wage", "labor_payment") and v not in LABOR_CATEGORIES:
            raise ValueError(f"Category '{v}' is not valid for type '{txn_type}'. Use one of: {LABOR_CATEGORIES}")
        return v

    @model_validator(mode="after")
    def validate_laborer_required_for_labor_types(self):
        """Ensure laborer_id is provided for labor_wage/labor_payment transactions."""
        if self.type in ("labor_wage", "labor_payment") and self.laborer_id is None:
            raise ValueError(f"laborer_id is required when type is '{self.type}'")
        return self


class TransactionUpdate(BaseModel):
    """Schema for partially updating an existing transaction."""

    type: Optional[VALID_TYPES] = None
    amount: Optional[float] = Field(None, gt=0)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)
    farm_id: Optional[int] = None
    laborer_id: Optional[int] = None
    transaction_date: Optional[date] = None


class TransactionResponse(BaseModel):
    """Schema for returning a transaction to the client."""

    id: int
    user_id: str
    farm_id: Optional[int]
    laborer_id: Optional[int]
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

