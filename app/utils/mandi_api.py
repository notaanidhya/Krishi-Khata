import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
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
    api_key = settings.DATAGOV_API_KEY
    if not api_key:
        logger.warning("DATAGOV_API_KEY is not set. Mandi API will fail or return empty.")
        return {"records": []}

    params = {
        "api-key": api_key,
        "format": "json",
        "limit": "500",
        "sort[Arrival_Date]": "desc",
    }
    
    if state:
        params["filters[State]"] = state.title()
    if district:
        params["filters[District]"] = district.title()
    if commodity:
        params["filters[Commodity]"] = commodity.title()

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(GOV_API_URL, params=params, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        return data
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching mandi prices: {e.response.status_code} - {e}")
        return {"records": [], "error": f"API Error: {e.response.status_code}"}
    except httpx.RequestError as e:
        logger.error(f"Network error fetching mandi prices: {e}")
        return {"records": [], "error": "Network Error"}
    except Exception as e:
        logger.error(f"Unexpected error fetching mandi prices: {e}")
        return {"records": [], "error": str(e)}

def normalize_date(date_str: str) -> str:
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
    if not records:
        return
        
    from app.database import SessionLocal
    from app.models.mandi import MandiPriceHistory
    
    db = SessionLocal()
    try:
        db_records_map = {}
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
                
            key = (comm, state, dist, arr_date)
            db_records_map[key] = {
                "commodity": comm,
                "state": state,
                "district": dist,
                "price": price,
                "arrival_date": arr_date
            }
            
        db_records = list(db_records_map.values())
        if not db_records:
            return

        dialect_name = db.bind.dialect.name
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
            
            stmt = insert(MandiPriceHistory).values(db_records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['commodity', 'state', 'district', 'arrival_date']
            )
            db.execute(stmt)
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            
            stmt = sqlite_insert(MandiPriceHistory).values(db_records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['commodity', 'state', 'district', 'arrival_date']
            )
            db.execute(stmt)
        else:
            # Fallback for other database dialects
            for record_data in db_records:
                existing = db.query(MandiPriceHistory).filter(
                    MandiPriceHistory.commodity == record_data["commodity"],
                    MandiPriceHistory.state == record_data["state"],
                    MandiPriceHistory.district == record_data["district"],
                    MandiPriceHistory.arrival_date == record_data["arrival_date"]
                ).first()
                if existing:
                    existing.price = record_data["price"]
                else:
                    db.add(MandiPriceHistory(**record_data))
                    
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error in upsert_prices_to_db: {e}")
    finally:
        db.close()


#  JIT HISTORICAL BACKFILL
def _parse_date_safe(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def fetch_historical_mandi_prices(
    state: str,
    district: str,
    commodity: str,
    days_back: int = 30,
) -> int:
    api_key = settings.DATAGOV_API_KEY
    if not api_key:
        logger.warning("DATAGOV_API_KEY not set — skipping historical backfill.")
        return 0

    params = {
        "api-key": api_key,
        "format": "json",
        "limit": "1000",                     # pull as many as the API allows
        "filters[State]": state.title(),
        "filters[District]": district.title(),
        "filters[Commodity]": commodity.title(),
        "sort[Arrival_Date]": "desc",
    }

    all_records: List[dict] = []

    try:
        with httpx.Client(timeout=60.0) as client:
            # Page through results (offset-based) to maximise coverage
            for offset in range(0, 2000, 1000):
                params["offset"] = str(offset)
                resp = client.get(GOV_API_URL, params=params, headers=HEADERS)
                resp.raise_for_status()
                page = resp.json()
                batch = page.get("records", [])
                if not batch:
                    break
                all_records.extend(batch)
                # If we received fewer than the limit, there are no more pages
                if len(batch) < 1000:
                    break
    except httpx.HTTPStatusError as e:
        logger.error(f"Historical backfill API error: {e.response.status_code} - {e}")
        return 0
    except httpx.RequestError as e:
        logger.error(f"Historical backfill Network error: {e}")
        return 0
    except Exception as e:
        logger.error(f"Historical backfill API error: {e}")
        return 0

    if not all_records:
        logger.info(
            f"No historical records returned for {commodity} / {district} / {state}"
        )
        return 0

    cutoff = datetime.now() - timedelta(days=days_back)
    filtered: List[dict] = []
    for r in all_records:
        raw_date = r.get("Arrival_Date") or r.get("arrival_date") or ""
        norm = normalize_date(raw_date)
        dt = _parse_date_safe(norm)
        if dt and dt >= cutoff:
            filtered.append(r)

    logger.info(
        f"Historical backfill: {len(all_records)} fetched, "
        f"{len(filtered)} within last {days_back} days for "
        f"{commodity}/{district}/{state}"
    )

    if filtered:
        upsert_prices_to_db(filtered)

    return len(filtered)
