import logging
from typing import Optional, Dict, Any
import httpx
from cachetools import cached, TTLCache
from app.config import settings

logger = logging.getLogger(__name__)

GOV_API_URL = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"

# We must use a valid User-Agent to prevent WAF blocking
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

# Cache up to 100 distinct queries for 4 hours (14400 seconds)
mandi_cache = TTLCache(maxsize=100, ttl=14400)

@cached(cache=mandi_cache)
def fetch_mandi_prices(state: Optional[str] = None, district: Optional[str] = None, commodity: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch mandi prices from data.gov.in API synchronously, caching the result.
    This function blocks, so it should ideally be run in a threadpool if it's slow,
    but FastAPI handles standard defs in a threadpool automatically.
    """
    api_key = settings.DATAGOV_API_KEY
    if not api_key:
        logger.warning("DATAGOV_API_KEY is not set. Mandi API will fail or return empty.")
        return {"records": []}

    params = {
        "api-key": api_key,
        "format": "json",
        "limit": "500",
    }
    
    if state:
        params["filters[State]"] = state
    if district:
        params["filters[District]"] = district
    if commodity:
        params["filters[Commodity]"] = commodity

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(GOV_API_URL, params=params, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            return data
    except Exception as e:
        logger.error(f"Error fetching mandi prices: {e}")
        return {"records": [], "error": str(e)}

def normalize_date(date_str: str) -> str:
    """Normalize date_str to YYYY-MM-DD format."""
    if not date_str:
        return ""
    if "-" in date_str and len(date_str) == 10:
        return date_str
    if "/" in date_str:
        parts = date_str.split("/")
        if len(parts) == 3:
            day, month, year = parts
            if len(year) == 4:
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str

def upsert_prices_to_db(records: list):
    """Upserts prices into MandiPriceHistory using a new DB session."""
    if not records:
        return
        
    from app.database import SessionLocal
    from app.models.mandi import MandiPriceHistory
    
    db = SessionLocal()
    try:
        for r in records:
            comm = r.get("commodity") or r.get("Commodity")
            state = r.get("state") or r.get("State")
            dist = r.get("district") or r.get("District")
            raw_price = r.get("modal_price") or r.get("Modal_Price") or 0
            arr_date = r.get("arrival_date") or r.get("Arrival_Date")
            
            if not comm or not state or not dist or not arr_date:
                continue
                
            try:
                price = float(raw_price)
            except (ValueError, TypeError):
                continue
                
            arr_date = normalize_date(arr_date)
            if not arr_date:
                continue
                
            existing = db.query(MandiPriceHistory).filter(
                MandiPriceHistory.commodity == comm,
                MandiPriceHistory.state == state,
                MandiPriceHistory.district == dist,
                MandiPriceHistory.arrival_date == arr_date
            ).first()
            
            if existing:
                existing.price = price
            else:
                db.add(MandiPriceHistory(
                    commodity=comm,
                    state=state,
                    district=dist,
                    price=price,
                    arrival_date=arr_date
                ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error in upsert_prices_to_db: {e}")
    finally:
        db.close()
