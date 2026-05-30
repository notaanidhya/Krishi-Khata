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

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import engine
from app.models.base import Base

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
                        arrival_date=current_date.strftime("%Y-%m-%d")
                    ))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# Only seed mock data in local development — never in production
if settings.FLASK_ENV == "development":
    seed_development_data()
else:
    logger.info("Skipping dev seed — FLASK_ENV=%s", settings.FLASK_ENV)





# ════════════════════════════════════════════════════════════════
#  APP FACTORY
# ════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Krishi Khata API",
    description="Mobile-first PWA backend for Indian farmers",
    version="1.0.0",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

from app.routers import auth, mandi, khata, weather, crop, chat, laborers

origins = [
    "http://localhost:5173", # So your local testing still works
    "https://krishi-khata-frontend.vercel.app", # Your live Vercel app
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://krishi-khata-frontend(-[a-z0-9]+)?\.vercel\.app",
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
app.include_router(laborers.router, prefix=settings.API_V1_STR, tags=["Labor Management"])

# Serve uploaded images as static files
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
@app.head("/api/health")    
def health_check():
    return {"status": "ok", "service": "agroo-fastapi"}
