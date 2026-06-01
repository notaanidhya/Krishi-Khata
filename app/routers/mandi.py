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

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user

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
#  METADATA (Searchable Dropdowns)
# ════════════════════════════════════════════════════════════════

TOP_CROPS = [
    "Wheat", "Soybean", "Mustard", "Onion", "Tomato", "Cotton", "Rice", "Maize", 
    "Gram", "Potato", "Garlic", "Ginger", "Turmeric", "Chana", "Moong", "Urad", 
    "Toor", "Jowar", "Bajra", "Ragi", "Groundnut", "Sesame", "Sunflower", "Safflower", 
    "Castor Seed", "Linseed", "Coriander", "Cumin", "Fennel", "Fenugreek"
]

TOP_DISTRICTS = [
    "Indore", "Ujjain", "Bhopal", "Pune", "Nashik", "Ahmednagar", "Nagpur", "Jalgaon", 
    "Rajkot", "Surat", "Ahmedabad", "Jaipur", "Jodhpur", "Kota", "Bikaner", "Ludhiana", 
    "Amritsar", "Karnal", "Panipat", "Agra", "Aligarh", "Kanpur", "Lucknow", "Varanasi", 
    "Patna", "Muzaffarpur", "Raipur", "Bhilai", "Ranchi", "Guwahati"
]

@router.get("/metadata")
async def get_mandi_metadata(db: Session = Depends(get_db)):
    """
    Returns unique commodities and districts for searchable dropdowns.
    Combines hardcoded popular lists with actual history entries in the DB.
    """
    from app.models.mandi import MandiPriceHistory
    
    # Get distinct from DB
    db_commodities = [row[0] for row in db.query(MandiPriceHistory.commodity).distinct().all()]
    db_districts = [row[0] for row in db.query(MandiPriceHistory.district).distinct().all()]
    
    # Merge and deduplicate (case insensitive)
    commodity_set = {c.title() for c in TOP_CROPS + db_commodities if c}
    district_set = {d.title() for d in TOP_DISTRICTS + db_districts if d}
    
    return {
        "commodities": sorted(list(commodity_set)),
        "districts": sorted(list(district_set))
    }

# ════════════════════════════════════════════════════════════════
#  LIVE CACHE (data.gov.in → in-memory TTLCache)
# ════════════════════════════════════════════════════════════════

from app.main import limiter
from fastapi import Request
from app.models.farm import Farm
from app.utils.mandi_api import fetch_mandi_prices, upsert_prices_to_db, fetch_historical_mandi_prices, normalize_date
from app.models.mandi import MandiPriceHistory

@router.get("/latest")
@limiter.limit("20/minute")
def get_latest_prices(
    request: Request,
    commodity: Optional[str] = Query(None, description="Filter by commodity name"),
    district: Optional[str] = Query(None, description="Filter by district"),
    state: Optional[str]    = Query(None, description="Filter by state"),
    db: Session             = Depends(get_db),
    current_user: dict      = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Latest mandi prices from data.gov.in with in-memory caching.
    Uses smart defaulting to pull the active farmer's state/district.
    """
    if not district and not state:
        user_id = current_user.get("uid")
        farm = db.query(Farm).filter(Farm.user_id == user_id).first()
        
        if (farm and farm.state and farm.district 
            and farm.state != "N/A" and farm.district != "N/A" 
            and farm.district.lower() != "madhya pradesh"
            and farm.state.lower() != "n/a"
            and farm.district.lower() != "n/a"):
            state = farm.state
            district = farm.district
        else:
            # Fallback
            state = "Madhya Pradesh"
            district = "Indore"

    data = fetch_mandi_prices(state=state, district=district, commodity=commodity)
    records = data.get("records", [])
    
    if records:
        background_tasks.add_task(upsert_prices_to_db, records)
        
        # Deduplicate records by commodity, keeping only the one with the latest arrival_date
        records_sorted = sorted(
            records,
            key=lambda r: normalize_date(r.get("arrival_date") or r.get("Arrival_Date") or ""),
            reverse=True
        )
        
        seen_commodities = set()
        deduped_records = []
        for r in records_sorted:
            comm = r.get("commodity") or r.get("Commodity")
            if not comm:
                continue
            comm_lower = comm.lower()
            if comm_lower not in seen_commodities:
                seen_commodities.add(comm_lower)
                deduped_records.append(r)
                
        records = deduped_records
    
    return {
        "count": len(records),
        "last_fetched": datetime.now(timezone.utc).isoformat(),
        "prices": records,
    }


# ════════════════════════════════════════════════════════════════
#  HISTORY — with JIT backfill for cold-start markets
# ════════════════════════════════════════════════════════════════

# Minimum number of local records before we skip the live backfill.
_MIN_LOCAL_RECORDS = 7


def _resolve_state_for_district(district: str, db: Session) -> str:
    """
    Try to infer the state from an existing MandiPriceHistory row for this
    district.  Falls back to 'Madhya Pradesh' which covers the majority of
    the current user-base.
    """
    existing = (
        db.query(MandiPriceHistory.state)
        .filter(MandiPriceHistory.district.ilike(district))
        .first()
    )
    return existing[0] if existing else "Madhya Pradesh"


@router.get("/history")
def get_mandi_history(
    commodity: str = Query(..., description="Commodity name"),
    district: str = Query(..., description="District name"),
    db: Session = Depends(get_db),
):
    """
    Get the last 30 days of historical prices for a given commodity+district.

    JIT backfill: if the local DB has fewer than 7 records for this query,
    we pull real history from data.gov.in, upsert it, and then return.
    First-time requests may take 2-4 s while the government API responds.
    """
    # ── Step 1: query local DB ───────────────────────────────────────
    records = (
        db.query(MandiPriceHistory)
        .filter(
            MandiPriceHistory.commodity.ilike(commodity),
            MandiPriceHistory.district.ilike(district),
        )
        .order_by(desc(MandiPriceHistory.arrival_date))
        .limit(30)
        .all()
    )

    # ── Step 2: check sufficiency ────────────────────────────────────
    backfilled = False

    if len(records) < _MIN_LOCAL_RECORDS:
        # ── Step 3 (JIT Trigger): live backfill from govt API ────────
        state = _resolve_state_for_district(district, db)
        inserted = fetch_historical_mandi_prices(
            state=state,
            district=district,
            commodity=commodity,
            days_back=30,
        )
        logger.info(
            f"JIT backfill for {commodity}/{district}: "
            f"{inserted} records upserted"
        )

        if inserted > 0:
            backfilled = True
            # ── Step 4: re-query after backfill ──────────────────────
            records = (
                db.query(MandiPriceHistory)
                .filter(
                    MandiPriceHistory.commodity.ilike(commodity),
                    MandiPriceHistory.district.ilike(district),
                )
                .order_by(desc(MandiPriceHistory.arrival_date))
                .limit(30)
                .all()
            )

    # Return chronological order for charting (earliest → latest)
    records_chronological = sorted(records, key=lambda x: x.arrival_date)

    return {
        "records": [r.to_dict() for r in records_chronological],
        "backfilled": backfilled,
    }


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
