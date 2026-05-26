"""
Mandi API Service — Daily Cache fetcher for data.gov.in.

Fetches commodity prices from the official Government of India
Open Data API and upserts them into the local MandiPriceCache table.
Includes retry logic with exponential backoff for Render deployments
where cross-continent latency to Indian government servers is high.

Endpoint:
  https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24

Fallback:
  If the government API times out or is offline, and the database has
  0 records, we automatically seed the cache from our local high-quality
  mock data file `server/mockdata/mandi_prices.json` so the app always displays
  valid data out-of-the-box.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from app.database import SessionLocal
from app.models.mandi import MandiPriceCache

logger = logging.getLogger(__name__)

# ── data.gov.in endpoint ────────────────────────────────────────
GOV_API_URL = (
    "https://api.data.gov.in/resource/"
    "35985678-0d79-46b4-9ed6-6f13308a1d24"
)

# How long to wait for the government API (seconds)
# Render free-tier servers are in US/EU; api.data.gov.in is in India.
# Cross-continent latency + sluggish gov servers need a generous timeout.
TIMEOUT_SECONDS = 60.0

# Retry config — data.gov.in frequently returns 502/503 or times out
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # seconds; delays will be 5s, 10s, 20s

# Maximum rows to request per call
RESULT_LIMIT = 500

# User-Agent header is critical because data.gov.in (Citrix NetScaler WAF)
# silent-drops requests with default "python-httpx" User-Agent.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

MOCK_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "mockdata" / "mandi_prices.json"


def _safe_float(value) -> Optional[float]:
    """Convert a value to float, returning None for blanks / unparseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value, max_len: int = 200) -> Optional[str]:
    """Coerce to a stripped string; return None if blank."""
    if value is None:
        return None
    s = str(value).strip()
    return s[:max_len] if s else None


def _seed_fallback_cache(db) -> dict:
    """Seed the MandiPriceCache table from local mock JSON file."""
    stats = {"fetched": 0, "upserted": 0, "errors": 0, "status": "seeded_fallback"}
    
    if not MOCK_FILE_PATH.exists():
        logger.error("Fallback mock data file not found at %s", MOCK_FILE_PATH)
        return stats

    try:
        with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
        
        now = datetime.now(timezone.utc)
        for rec in records:
            # Map standard mock fields to cache fields
            state = _safe_str(rec.get("state"), 150) or "Madhya Pradesh"
            district = _safe_str(rec.get("district"), 150) or "Indore"
            market = _safe_str(rec.get("mandi") or rec.get("market"), 200) or "Indore"
            commodity = _safe_str(rec.get("commodity"), 150)
            variety = _safe_str(rec.get("variety"), 150) or "Regular"
            arrival_date = _safe_str(rec.get("arrival_date"), 30) or now.strftime("%Y-%m-%d")

            if not commodity:
                stats["errors"] += 1
                continue

            min_p = _safe_float(rec.get("min_price"))
            max_p = _safe_float(rec.get("max_price"))
            modal_p = _safe_float(rec.get("modal_price"))

            # Check if this record already exists
            existing = (
                db.query(MandiPriceCache)
                .filter(
                    MandiPriceCache.state == state,
                    MandiPriceCache.district == district,
                    MandiPriceCache.market == market,
                    MandiPriceCache.commodity == commodity,
                    MandiPriceCache.variety == variety,
                    MandiPriceCache.arrival_date == arrival_date,
                )
                .first()
            )

            if existing:
                existing.min_price = min_p
                existing.max_price = max_p
                existing.modal_price = modal_p
                existing.fetched_at = now
            else:
                db.add(MandiPriceCache(
                    state=state,
                    district=district,
                    market=market,
                    commodity=commodity,
                    variety=variety,
                    min_price=min_p,
                    max_price=max_p,
                    modal_price=modal_p,
                    arrival_date=arrival_date,
                    fetched_at=now,
                ))
            stats["upserted"] += 1
            stats["fetched"] += 1
        
        db.commit()
        logger.info("Successfully seeded local fallback mandi prices (%d records)", stats["upserted"])
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to seed fallback cache: %s", exc)
        stats["status"] = "seed_error"
        
    return stats


async def fetch_and_cache_mandi_prices(
    api_key: str,
    state: str = "Madhya Pradesh",
    district: str = "Indore",
) -> dict:
    """
    Fetch prices from data.gov.in and upsert them into MandiPriceCache.
    If the remote request fails and our local cache is empty, we fall back
    to seeding local data from mandi_prices.json so the app is immediately usable.
    """
    stats = {"fetched": 0, "upserted": 0, "errors": 0, "status": "ok"}
    use_fallback = False

    # ── 1) Fetch from the government API ────────────────────────
    params = {
        "api-key": api_key,
        "format":  "json",
        "limit":   str(RESULT_LIMIT),
        "filters[State]":    state,
        "filters[District]": district,
    }

    payload = None
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=15.0),
            ) as client:
                resp = await client.get(GOV_API_URL, params=params, headers=HEADERS)
                resp.raise_for_status()
                payload = resp.json()
                last_exc = None
                break  # success
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))  # 5s, 10s, 20s
                logger.warning(
                    "data.gov.in attempt %d/%d failed: %s — retrying in %ds",
                    attempt, MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "data.gov.in attempt %d/%d failed: %s — no retries left. Checking fallback.",
                    attempt, MAX_RETRIES, exc,
                )
    if last_exc is not None:
        use_fallback = True

    # Check if empty payload
    if not use_fallback and (not payload or not payload.get("records")):
        logger.warning("data.gov.in returned 0 records. Checking fallback seeding.")
        use_fallback = True

    db = SessionLocal()
    
    # ── 2) Trigger Fallback Seed if needed ──────────────────────
    if use_fallback:
        try:
            # Only seed mock data if the DB currently has no records
            count = db.query(MandiPriceCache).count()
            if count == 0:
                logger.info("Mandi cache database is empty. Seeding local mock data...")
                stats = _seed_fallback_cache(db)
            else:
                logger.info("Mandi cache database has %d existing records. Skipping fallback seeding.", count)
                stats["status"] = "using_stale_cache"
        finally:
            db.close()
        return stats

    # ── 3) Parse live records from data.gov.in ──────────────────
    records = payload.get("records", [])
    stats["fetched"] = len(records)
    logger.info("Fetched %d mandi price records for %s / %s", len(records), state, district)

    now = datetime.now(timezone.utc)
    try:
        for rec in records:
            try:
                row_state   = _safe_str(rec.get("state"),     150) or state
                row_dist    = _safe_str(rec.get("district"),  150) or district
                row_market  = _safe_str(rec.get("market"),    200) or "Unknown"
                row_comm    = _safe_str(rec.get("commodity"), 150)
                row_variety = _safe_str(rec.get("variety"),   150) or "Regular"
                row_arrival = _safe_str(rec.get("arrival_date"), 30)

                if not row_comm:
                    stats["errors"] += 1
                    continue

                row_min   = _safe_float(rec.get("min_price"))
                row_max   = _safe_float(rec.get("max_price"))
                row_modal = _safe_float(rec.get("modal_price"))

                # Look for an existing row by composite key
                existing = (
                    db.query(MandiPriceCache)
                    .filter(
                        MandiPriceCache.state        == row_state,
                        MandiPriceCache.district     == row_dist,
                        MandiPriceCache.market       == row_market,
                        MandiPriceCache.commodity    == row_comm,
                        MandiPriceCache.variety      == row_variety,
                        MandiPriceCache.arrival_date == row_arrival,
                    )
                    .first()
                )

                if existing:
                    existing.min_price   = row_min
                    existing.max_price   = row_max
                    existing.modal_price = row_modal
                    existing.fetched_at  = now
                else:
                    db.add(MandiPriceCache(
                        state=row_state,
                        district=row_dist,
                        market=row_market,
                        commodity=row_comm,
                        variety=row_variety,
                        min_price=row_min,
                        max_price=row_max,
                        modal_price=row_modal,
                        arrival_date=row_arrival,
                        fetched_at=now,
                    ))
                stats["upserted"] += 1
            except Exception as row_exc:
                logger.warning("Skipping bad mandi record: %s — %s", rec, row_exc)
                stats["errors"] += 1
                continue

        db.commit()
        logger.info("Mandi cache upsert complete: %d upserted, %d errors", stats["upserted"], stats["errors"])
    except Exception as db_exc:
        db.rollback()
        logger.exception("DB commit failed during mandi cache upsert: %s", db_exc)
        stats["status"] = "db_error"
    finally:
        db.close()

    return stats
