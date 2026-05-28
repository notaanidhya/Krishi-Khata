"""
Khata (ledger) routes — full CRUD with farm-aware filtering.

All endpoints assume user_id is injected via Firebase auth middleware.
The farm_id query param filters transactions to a specific farm.
If farm_id is omitted, all transactions for the user are returned.
"""

from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import get_current_user
from app.models.khata import KhataTransaction
from app.schemas.khata import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    KhataSummary,
)

router = APIRouter()


# ── Helper: get user_id from Firebase token ────────────────────
def _uid(current_user: dict) -> str:
    return current_user.get("uid", "dev-user-001")


# ── GET /transactions — List with optional filters ─────────────
@router.get("/transactions", response_model=List[TransactionResponse])
async def list_transactions(
    farm_id: Optional[int] = Query(None, description="Filter by farm. Null = all farms."),
    laborer_id: Optional[int] = Query(None, description="Filter by laborer. Returns only their labor_wage/labor_payment transactions."),
    type: Optional[str] = Query(None, description="Filter by 'income' or 'expense'"),
    from_date: Optional[date] = Query(None, description="Start date (inclusive)"),
    to_date: Optional[date] = Query(None, description="End date (inclusive)"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List transactions for the authenticated user.
    Supports filtering by farm_id, laborer_id, type, and date range.
    Results are ordered by transaction_date descending (newest first).
    """
    query = db.query(KhataTransaction).filter(
        KhataTransaction.user_id == _uid(current_user)
    )

    # Apply optional filters
    if farm_id is not None:
        query = query.filter(KhataTransaction.farm_id == farm_id)
    if laborer_id is not None:
        query = query.filter(KhataTransaction.laborer_id == laborer_id)
    if type is not None:
        query = query.filter(KhataTransaction.type == type)
    if from_date is not None:
        query = query.filter(KhataTransaction.transaction_date >= from_date)
    if to_date is not None:
        query = query.filter(KhataTransaction.transaction_date <= to_date)

    transactions = query.order_by(KhataTransaction.transaction_date.desc()).all()
    return [TransactionResponse(**t.to_dict()) for t in transactions]


# ── POST /transactions — Create a new entry ────────────────────
@router.post("/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: TransactionCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new income or expense entry in the Khata."""
    txn = KhataTransaction(
        user_id=_uid(current_user),
        farm_id=payload.farm_id,
        laborer_id=payload.laborer_id,
        type=payload.type,
        amount=payload.amount,
        category=payload.category,
        description=payload.description,
        transaction_date=payload.transaction_date,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return TransactionResponse(**txn.to_dict())


# ── PATCH /transactions/{id} — Update an existing entry ────────
@router.patch("/transactions/{id}", response_model=TransactionResponse)
async def update_transaction(
    id: int,
    payload: TransactionUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing transaction. Only provided fields are changed."""
    txn = db.query(KhataTransaction).filter(
        KhataTransaction.id == id,
        KhataTransaction.user_id == _uid(current_user),
    ).first()

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(txn, field, value)

    db.commit()
    db.refresh(txn)
    return TransactionResponse(**txn.to_dict())


# ── DELETE /transactions/{id} — Remove an entry ────────────────
@router.delete("/transactions/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a transaction. Returns 204 on success."""
    txn = db.query(KhataTransaction).filter(
        KhataTransaction.id == id,
        KhataTransaction.user_id == _uid(current_user),
    ).first()

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    db.delete(txn)
    db.commit()
    return None


# ── GET /summary — Aggregated totals ──────────────────────────
@router.get("/summary", response_model=KhataSummary)
async def get_summary(
    farm_id: Optional[int] = Query(None, description="Filter by farm"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Aggregate income/expense summary for the user.
    Queries against transaction_date, not created_at.
    """
    base_query = db.query(KhataTransaction).filter(
        KhataTransaction.user_id == _uid(current_user)
    )
    if farm_id is not None:
        base_query = base_query.filter(KhataTransaction.farm_id == farm_id)

    income = base_query.filter(KhataTransaction.type == "income").with_entities(
        func.coalesce(func.sum(KhataTransaction.amount), 0)
    ).scalar()

    expense = base_query.filter(
        KhataTransaction.type.in_(["expense", "labor_wage"])
    ).with_entities(func.coalesce(func.sum(KhataTransaction.amount), 0)).scalar()


    count = base_query.count()

    return KhataSummary(
        total_income=float(income),
        total_expense=float(expense),
        net_profit=float(income) - float(expense),
        transaction_count=count,
    )
