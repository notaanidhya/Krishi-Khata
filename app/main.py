"""
Agroo FastAPI application — entry point.

Run with: uvicorn app.main:app --reload

Includes a lifespan-managed background task that refreshes the
MandiPriceCache from data.gov.in every MANDI_CACHE_INTERVAL_HOURS.
"""

import asyncio
import logging
import os as _os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.models.base import Base
from app.routers import auth, mandi, khata, weather, crop, chat

logger = logging.getLogger(__name__)

# Dev convenience — create tables if they do not exist (keeps DB persistent across restarts)

# Create all tables (dev convenience — use Alembic in production)
Base.metadata.create_all(bind=engine)


# ── Seed dev database with initial farms ────────────────────────
def seed_development_data():
    from app.database import SessionLocal
    from app.models.farm import Farm

    db = SessionLocal()
    try:
        if db.query(Farm).count() == 0:
            farm1 = Farm(
                id=1,
                user_id="dev-user-001",
                name="Sukhdev Farm",
                area_acres=5.0,
                soil_type="Black",
                district="Indore",
                state="Madhya Pradesh",
            )
            farm2 = Farm(
                id=2,
                user_id="dev-user-001",
                name="Green Acres",
                area_acres=10.0,
                soil_type="Alluvial",
                district="Bhopal",
                state="Madhya Pradesh",
            )
            db.add(farm1)
            db.add(farm2)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


seed_development_data()


# ════════════════════════════════════════════════════════════════
#  BACKGROUND: Mandi Price Cache Scheduler (Daily at 6:00 AM IST)
# ════════════════════════════════════════════════════════════════

from datetime import datetime, timezone, time, timedelta

def get_seconds_until_next_6am_ist() -> float:
    """Calculate the number of seconds until the next 6:00 AM IST (00:30 UTC)."""
    now_utc = datetime.now(timezone.utc)
    target_today = datetime.combine(now_utc.date(), time(0, 30, 0), tzinfo=timezone.utc)
    if now_utc >= target_today:
        return (target_today + timedelta(days=1) - now_utc).total_seconds()
    return (target_today - now_utc).total_seconds()


def get_most_recent_6am_ist() -> datetime:
    """Get the timezone-aware UTC datetime of the most recent 6:00 AM IST (00:30 UTC)."""
    now_utc = datetime.now(timezone.utc)
    target_today = datetime.combine(now_utc.date(), time(0, 30, 0), tzinfo=timezone.utc)
    if now_utc < target_today:
        return target_today - timedelta(days=1)
    return target_today


async def _mandi_cache_loop():
    """
    Background cache manager for Mandi Prices.
    
    1. On startup: checks the local database. If the newest record was
       fetched after the most recent 6:00 AM IST, it reuse the cache
       and skips the external data.gov.in API call entirely.
    2. Then, calculates the exact duration until the next 6:00 AM IST
       and sleeps, ensuring it refreshes exactly once a day at 6:00 AM.
    """
    from app.services.mandi_api import fetch_and_cache_mandi_prices
    from app.database import SessionLocal
    from app.models.mandi import MandiPriceCache

    api_key = settings.DATAGOV_API_KEY
    if not api_key:
        logger.warning("DATAGOV_API_KEY not set — mandi cache scheduler disabled")
        return

    while True:
        try:
            # ── Check cache freshness on startup ────────────────
            db = SessionLocal()
            need_fetch = True
            try:
                # Find the newest record's fetched_at timestamp
                newest = (
                    db.query(MandiPriceCache)
                    .order_by(MandiPriceCache.fetched_at.desc())
                    .first()
                )
                if newest and newest.fetched_at:
                    most_recent_6am = get_most_recent_6am_ist()
                    # Make newest.fetched_at timezone-aware UTC for comparison
                    newest_fetched_utc = newest.fetched_at.replace(tzinfo=timezone.utc)
                    
                    if newest_fetched_utc >= most_recent_6am:
                        logger.info(
                            "📦 Local Mandi Cache is fresh! (Last fetched: %s, Threshold: %s). Skipping API call.",
                            newest_fetched_utc.isoformat(),
                            most_recent_6am.isoformat(),
                        )
                        need_fetch = False
                    else:
                        logger.info("📦 Mandi Cache is stale. Initiating refresh.")
                else:
                    logger.info("📦 No cached Mandi data found. Initiating first-time fetch.")
            except Exception as e:
                logger.error("Failed to check cache age: %s. Defaulting to fetching.", e)
            finally:
                db.close()

            # ── Run the fetch only if not fresh ──────────────────
            if need_fetch:
                logger.info("🔄 Mandi cache refresh starting...")
                result = await fetch_and_cache_mandi_prices(api_key=api_key)
                logger.info(
                    "✅ Mandi cache refresh done: fetched=%d  upserted=%d  errors=%d  status=%s",
                    result.get("fetched", 0),
                    result.get("upserted", 0),
                    result.get("errors", 0),
                    result.get("status", "unknown"),
                )

        except Exception as exc:
            logger.exception("❌ Mandi cache refresh crashed: %s", exc)

        # ── Sleep until the next 6:00 AM IST ────────────────────
        seconds_to_sleep = get_seconds_until_next_6am_ist()
        hours_to_sleep = seconds_to_sleep / 3600.0
        logger.info(
            "😴 Mandi scheduler sleeping for %.2f hours (until next 6:00 AM IST / 00:30 UTC)",
            hours_to_sleep,
        )
        await asyncio.sleep(seconds_to_sleep)


# ── FastAPI Lifespan (startup + shutdown) ───────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the mandi cache background task across the app lifecycle.
    """
    task = asyncio.create_task(_mandi_cache_loop())
    logger.info("Mandi cache scheduler initialized (Target: Daily at 6:00 AM IST)")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Mandi cache scheduler stopped")


# ════════════════════════════════════════════════════════════════
#  APP FACTORY
# ════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Krishi Khata API",
    description="Mobile-first PWA backend for Indian farmers",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    "http://localhost:5173", # So your local testing still works
    "https://krishi-khata-frontend.vercel.app", # Your live Vercel app
]
# CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
# Temporary Nuclear CORS config for debugging
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # <-- THIS IS THE CHANGE (Allows literally any website)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Include routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(mandi.router, prefix=f"{settings.API_V1_STR}/mandi", tags=["Mandi Prices"])
app.include_router(khata.router, prefix=f"{settings.API_V1_STR}/khata", tags=["Kisan Khata"])
app.include_router(weather.router, prefix=f"{settings.API_V1_STR}/weather", tags=["Weather"])
app.include_router(crop.router, prefix=settings.API_V1_STR, tags=["Farms & Crops"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["Community Chat"])

# Serve uploaded images as static files
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "agroo-fastapi"}
