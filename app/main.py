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

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import engine
from app.models.base import Base

logger = logging.getLogger(__name__)




async def _mandi_cache_worker():
    from app.utils.mandi_api import fetch_mandi_prices, upsert_prices_to_db
    from app.database import SessionLocal
    from app.models.crop import CropCycle
    from sqlalchemy import func

    interval_seconds = settings.MANDI_CACHE_INTERVAL_HOURS * 3600
    while True:
        top_crops = []
        try:
            db = SessionLocal()
            results = (
                db.query(CropCycle.crop_name, func.count(CropCycle.id))
                .filter(CropCycle.status == "ACTIVE")
                .group_by(CropCycle.crop_name)
                .order_by(func.count(CropCycle.id).desc())
                .limit(7)
                .all()
            )
            top_crops = [row[0] for row in results]
        except Exception:
            logger.exception("[MandiCacheWorker] Failed to query top crops.")
        finally:
            if 'db' in locals():
                db.close()

        # Fallback if the database has no active crops yet
        if not top_crops:
            top_crops = ["Wheat", "Soybean", "Onion", "Cotton", "Tomato", "Rice", "Maize"]

        logger.info(
            "[MandiCacheWorker] Starting cache refresh for top %d crops: %s "
            "(next run in %sh).",
            len(top_crops),
            ", ".join(top_crops),
            settings.MANDI_CACHE_INTERVAL_HOURS,
        )

        for crop in top_crops:
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda c=crop: fetch_mandi_prices(
                        state=None,  
                        district=None, 
                        commodity=c,
                    ),
                )
                records = data.get("records", [])
                if records:
                    await loop.run_in_executor(None, upsert_prices_to_db, records)
                    logger.info(
                        "[MandiCacheWorker] Upserted %d overview records for crop: %s.",
                        len(records),
                        crop,
                    )
                else:
                    logger.warning(
                        "[MandiCacheWorker] No records returned for crop: %s — skipping upsert.",
                        crop,
                    )
            except Exception:
                logger.exception(
                    "[MandiCacheWorker] Unhandled error for crop %s.", crop
                )
        logger.info("[MandiCacheWorker] Refresh complete. Sleeping for %sh.", settings.MANDI_CACHE_INTERVAL_HOURS)
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown.

    Startup:
      - Create DB tables in development (Alembic handles production migrations).
      - Seed demo data in development.
      - Launch the background Mandi cache-warming worker.

    Shutdown:
      - Cancel the background task cleanly.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    if settings.ENVIRONMENT == "development":
        Base.metadata.create_all(bind=engine)
        seed_development_data()
    else:
        logger.info("Production mode — skipping table auto-create and dev seed.")

    worker_task = asyncio.create_task(_mandi_cache_worker())
    logger.info("[Lifespan] MandiCacheWorker started.")

    yield 
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        logger.info("[Lifespan] MandiCacheWorker stopped cleanly.")



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

        from app.models.mandi import MandiPriceHistory
        if db.query(MandiPriceHistory).count() == 0:
            from datetime import date, timedelta
            import random
            
            seeds = [
                {"commodity": "Wheat", "state": "Madhya Pradesh", "district": "Indore", "base": 2300.0},
                {"commodity": "Wheat", "state": "Madhya Pradesh", "district": "Bhopal", "base": 2200.0},
                {"commodity": "Rice", "state": "Haryana", "district": "Karnal", "base": 4000.0},
                {"commodity": "Onion", "state": "Maharashtra", "district": "Nashik", "base": 1100.0},
                {"commodity": "Tomato", "state": "Karnataka", "district": "Kolar", "base": 900.0},
                {"commodity": "Soybean", "state": "Maharashtra", "district": "Latur", "base": 4500.0},
                {"commodity": "Cotton", "state": "Gujarat", "district": "Rajkot", "base": 6600.0},
            ]
            
            today = date.today()
            for s in seeds:
                price = s["base"]
                for days_ago in range(30, -1, -1):
                    current_date = today - timedelta(days=days_ago)
                    change_pct = random.uniform(-0.015, 0.015)
                    price = round(price * (1.0 + change_pct), 2)
                    
                    db.add(MandiPriceHistory(
                        commodity=s["commodity"],
                        state=s["state"],
                        district=s["district"],
                        price=price,
                        arrival_date=current_date
                    ))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()





app = FastAPI(
    title="Krishi Khata API",
    description="Mobile-first PWA backend for Indian farmers",
    version="1.0.0",
    lifespan=lifespan,
)

from app.dependencies import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

from app.routers import auth, mandi, khata, weather, crop, chat, laborers


@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api") and request.method == "GET":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(mandi.router, prefix=f"{settings.API_V1_STR}/mandi", tags=["Mandi Prices"])
app.include_router(khata.router, prefix=f"{settings.API_V1_STR}/khata", tags=["Kisan Khata"])
app.include_router(weather.router, prefix=f"{settings.API_V1_STR}/weather", tags=["Weather"])
app.include_router(crop.router, prefix=settings.API_V1_STR, tags=["Farms & Crops"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["Community Chat"])
app.include_router(laborers.router, prefix=settings.API_V1_STR, tags=["Labor Management"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get('/')
@app.get('/api/health')
@app.head("/api/health")    
def health_check():
    return {"status": "ok", "service": "agroo-fastapi"}
