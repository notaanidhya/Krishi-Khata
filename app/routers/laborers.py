"""
Laborer routes — Labor Management sub-ledger.

Endpoints:
  POST /farms/{farm_id}/laborers       — Add a laborer to a farm
  GET  /farms/{farm_id}/laborers       — List laborers with calculated balances
  GET  /farms/{farm_id}/laborers/{id}  — Get single laborer with balance
  PATCH /farms/{farm_id}/laborers/{id} — Update laborer details

All endpoints verify farm ownership via the authenticated user.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.database import get_db
from app.dependencies import get_current_user
from app.models.farm import Farm
from app.models.laborer import Laborer
from app.models.khata import KhataTransaction
from app.schemas.laborer import LaborerCreate, LaborerUpdate, LaborerResponse

router = APIRouter()


# ── Helper: get user_id from JWT payload ────────────────────────
def _uid(current_user: dict) -> str:
    return current_user.get("uid", "dev-user-001")


def _verify_farm_ownership(farm_id: int, user_id: str, db: Session) -> Farm:
    """Verify the farm exists and belongs to the user. Returns the Farm or raises 403/404."""
    farm = db.query(Farm).filter(Farm.id == farm_id).first()
    if not farm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    if farm.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this farm")
    return farm


def _calculate_balance(laborer_id: int, db: Session) -> float:
    """
    Calculate the net balance for a laborer.

    current_balance = SUM(labor_wage amounts) - SUM(labor_payment amounts)

    Positive balance = money still owed to the laborer.
    Negative balance = laborer was overpaid.
    Zero = all settled.
    """
    result = db.query(
        func.coalesce(
            func.sum(
                case(
                    (KhataTransaction.type == "labor_wage", KhataTransaction.amount),
                    else_=0,
                )
            ), 0
        ) -
        func.coalesce(
            func.sum(
                case(
                    (KhataTransaction.type == "labor_payment", KhataTransaction.amount),
                    else_=0,
                )
            ), 0
        ),
        func.count(KhataTransaction.id)
    ).filter(
        KhataTransaction.laborer_id == laborer_id,
        KhataTransaction.type.in_(["labor_wage", "labor_payment"])
    ).first()

    if result:
        balance, count = result
        return float(balance) if balance else 0.0, int(count) if count else 0
    return 0.0, 0


# ── POST /farms/{farm_id}/laborers — Add a laborer ─────────────
@router.post(
    "/farms/{farm_id}/laborers",
    response_model=LaborerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_laborer(
    farm_id: int,
    payload: LaborerCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new laborer to a farm. Verifies user ownership of the farm."""
    _verify_farm_ownership(farm_id, _uid(current_user), db)

    laborer = Laborer(
        farm_id=farm_id,
        name=payload.name,
        phone_number=payload.phone_number,
        is_active=payload.is_active,
    )
    db.add(laborer)
    db.commit()
    db.refresh(laborer)

    response = laborer.to_dict()
    response["current_balance"] = 0.0  # New laborer has zero balance
    response["transaction_count"] = 0
    return LaborerResponse(**response)


# ── GET /farms/{farm_id}/laborers — List with balances ─────────
@router.get(
    "/farms/{farm_id}/laborers",
    response_model=List[LaborerResponse],
)
async def list_laborers(
    farm_id: int,
    active_only: bool = Query(True, description="If true, only return active laborers"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all laborers for a farm with their calculated balances.

    CRITICAL LOGIC:
      current_balance = SUM(amount WHERE type='labor_wage')
                      - SUM(amount WHERE type='labor_payment')

    Positive balance = money owed to the laborer.
    """
    _verify_farm_ownership(farm_id, _uid(current_user), db)

    query = db.query(Laborer).filter(Laborer.farm_id == farm_id)
    if active_only:
        query = query.filter(Laborer.is_active == True)

    laborers = query.order_by(Laborer.name).all()

    # Batch-calculate balances in a single query for efficiency
    if laborers:
        laborer_ids = [l.id for l in laborers]

        balance_query = (
            db.query(
                KhataTransaction.laborer_id,
                (
                    func.coalesce(
                        func.sum(
                            case(
                                (KhataTransaction.type == "labor_wage", KhataTransaction.amount),
                                else_=0,
                            )
                        ), 0
                    ) -
                    func.coalesce(
                        func.sum(
                            case(
                                (KhataTransaction.type == "labor_payment", KhataTransaction.amount),
                                else_=0,
                            )
                        ), 0
                    )
                ).label("balance"),
                func.count(KhataTransaction.id).label("tx_count"),
            )
            .filter(KhataTransaction.laborer_id.in_(laborer_ids))
            .filter(KhataTransaction.type.in_(["labor_wage", "labor_payment"]))
            .group_by(KhataTransaction.laborer_id)
            .all()
        )

        balance_map = {row[0]: {"balance": float(row[1]), "count": int(row[2])} for row in balance_query}
    else:
        balance_map = {}

    results = []
    for laborer in laborers:
        d = laborer.to_dict()
        stats = balance_map.get(laborer.id, {"balance": 0.0, "count": 0})
        d["current_balance"] = stats["balance"]
        d["transaction_count"] = stats["count"]
        results.append(LaborerResponse(**d))

    return results


# ── GET /farms/{farm_id}/laborers/{laborer_id} — Single laborer ─
@router.get(
    "/farms/{farm_id}/laborers/{laborer_id}",
    response_model=LaborerResponse,
)
async def get_laborer(
    farm_id: int,
    laborer_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single laborer's details with their calculated balance."""
    _verify_farm_ownership(farm_id, _uid(current_user), db)

    laborer = db.query(Laborer).filter(
        Laborer.id == laborer_id,
        Laborer.farm_id == farm_id,
    ).first()

    if not laborer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laborer not found")

    d = laborer.to_dict()
    bal, count = _calculate_balance(laborer.id, db)
    d["current_balance"] = bal
    d["transaction_count"] = count
    return LaborerResponse(**d)


# ── PATCH /farms/{farm_id}/laborers/{laborer_id} — Update ──────
@router.patch(
    "/farms/{farm_id}/laborers/{laborer_id}",
    response_model=LaborerResponse,
)
async def update_laborer(
    farm_id: int,
    laborer_id: int,
    payload: LaborerUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a laborer's details (name, phone, active status)."""
    _verify_farm_ownership(farm_id, _uid(current_user), db)

    laborer = db.query(Laborer).filter(
        Laborer.id == laborer_id,
        Laborer.farm_id == farm_id,
    ).first()

    if not laborer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laborer not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(laborer, field, value)

    db.commit()
    db.refresh(laborer)

    d = laborer.to_dict()
    bal, count = _calculate_balance(laborer.id, db)
    d["current_balance"] = bal
    d["transaction_count"] = count
    return LaborerResponse(**d)
