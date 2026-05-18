"""
Mandi price routes — live + cached commodity prices and user bookmarks.

Architecture:
  /prices      — serves from local mock JSON (legacy, for dashboard ticker)
  /latest      — serves from the MandiPriceCache SQLite table (data.gov.in)
  /commodities — unique commodity names from mock data
  /saved/*     — user bookmark stubs (requires auth)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.mandi import MandiPriceCache
from app.schemas.dashboard import MandiPricesResponse

logger = logging.getLogger(__name__)

router = APIRouter()

MOCK_DIR = Path(__file__).resolve().parent.parent.parent / "mockdata"


# ════════════════════════════════════════════════════════════════
#  MOCK DATA (legacy — kept for the dashboard ticker)
# ════════════════════════════════════════════════════════════════

def _load_mock_mandi() -> dict:
    """Load mandi price data from the local JSON mock file."""
    filepath = MOCK_DIR / "mandi.json"
    if not filepath.exists():
        raise HTTPException(status_code=503, detail="Mandi data not available")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/prices", response_model=MandiPricesResponse)
async def get_prices(
    commodity: Optional[str] = None,
    state: Optional[str] = None,
):
    """
    List mandi prices with optional commodity/state filters.

    Returns commodity prices with trend indicators (change_pct)
    for red/green display on the dashboard ticker.
    """
    data = _load_mock_mandi()
    prices = data["prices"]

    # Apply optional filters
    if commodity:
        prices = [p for p in prices if p["commodity"].lower() == commodity.lower()]
    if state:
        prices = [p for p in prices if p["state"].lower() == state.lower()]

    return {"last_updated": data["last_updated"], "prices": prices}


@router.get("/commodities")
async def get_commodities():
    """List available commodities from current mandi data."""
    data = _load_mock_mandi()
    commodities = sorted(set(p["commodity"] for p in data["prices"]))
    return {"commodities": commodities}


# ════════════════════════════════════════════════════════════════
#  LIVE CACHE (data.gov.in → local MandiPriceCache table)
# ════════════════════════════════════════════════════════════════

@router.get("/latest")
async def get_latest_prices(
    commodity: Optional[str] = Query(None, description="Filter by commodity name"),
    district: Optional[str] = Query(None, description="Filter by district"),
    market: Optional[str]   = Query(None, description="Filter by market name"),
    limit: int              = Query(100, ge=1, le=500, description="Max rows"),
    db: Session             = Depends(get_db),
):
    """
    Latest mandi prices from the local cache (populated by data.gov.in).

    This route **never** calls the external government API directly.
    It only queries the MandiPriceCache SQLite table that is
    refreshed by the background scheduler every 12 hours.

    Returns:
        {
          "count":        int,
          "last_fetched": "ISO datetime",
          "prices":       [ ... ]
        }
    """
    query = db.query(MandiPriceCache)

    # ── Optional filters (case-insensitive) ─────────────────────
    if commodity:
        query = query.filter(
            MandiPriceCache.commodity.ilike(f"%{commodity}%")
        )
    if district:
        query = query.filter(
            MandiPriceCache.district.ilike(f"%{district}%")
        )
    if market:
        query = query.filter(
            MandiPriceCache.market.ilike(f"%{market}%")
        )

    # Most recent records first, capped at limit
    rows = (
        query
        .order_by(desc(MandiPriceCache.fetched_at))
        .limit(limit)
        .all()
    )

    if not rows:
        return {
            "count": 0,
            "last_fetched": None,
            "prices": [],
            "message": "No cached mandi data yet. The background job may still be running.",
        }

    # Determine the most recent fetch timestamp
    last_fetched = max(
        (r.fetched_at for r in rows if r.fetched_at),
        default=datetime.now(timezone.utc),
    )

    return {
        "count": len(rows),
        "last_fetched": last_fetched.isoformat(),
        "prices": [row.to_dict() for row in rows],
    }


# ════════════════════════════════════════════════════════════════
#  USER BOOKMARK STUBS (require auth)
# ════════════════════════════════════════════════════════════════

@router.post("/saved")
async def save_mandi(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bookmark a mandi+commodity combination."""
    return {"message": "save-mandi stub"}


@router.get("/saved")
async def get_saved(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's bookmarked mandis."""
    return {"message": "get-saved stub"}


@router.delete("/saved/{id}")
async def delete_saved(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a bookmark."""
    return {"message": "delete-saved stub"}
