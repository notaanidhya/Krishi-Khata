"""
Crop growth stage calculations — reads from CropDataCache.
No hardcoded crop data. All crop info comes from the database
(seeded for common crops, AI-generated for new crops).
"""

from datetime import date
from app.database import SessionLocal
from app.models.crop_data_cache import CropDataCache

# Default fallback intervals for unknown crops (before AI validation completes)
DEFAULT_STAGES: dict[str, int] = {
    "Seedling": 15,
    "Vegetative": 50,
    "Flowering": 75,
    "Ready to Harvest": 110,
}

DEFAULT_GDD_STAGES: dict[str, float] = {
    "Seedling": 225.0,
    "Vegetative": 750.0,
    "Flowering": 1125.0,
    "Ready to Harvest": 1650.0,
}

# Ordered stage keys for iteration
STAGE_ORDER = ["Seedling", "Vegetative", "Flowering", "Ready to Harvest"]


def get_crop_presets() -> list[str]:
    """Return sorted list of all known crop names from CropDataCache.
    This starts empty and grows as users add crops."""
    presets = []
    try:
        db = SessionLocal()
        cached_crops = db.query(CropDataCache.standard_name_en).all()
        presets = [row[0] for row in cached_crops]
        db.close()
    except Exception:
        pass
    return sorted(presets)


def get_stages_for_crop(crop_name: str) -> dict[str, int]:
    """Return day-based stage intervals for a crop from CropDataCache."""
    try:
        db = SessionLocal()
        cached = db.query(CropDataCache).filter(
            CropDataCache.standard_name_en == crop_name
        ).first()
        db.close()
        if cached and cached.day_stages:
            return cached.day_stages
    except Exception:
        pass
    return DEFAULT_STAGES


def get_gdd_stages_for_crop(crop_name: str) -> dict[str, float]:
    """Return GDD stage intervals for a crop from CropDataCache."""
    try:
        db = SessionLocal()
        cached = db.query(CropDataCache).filter(
            CropDataCache.standard_name_en == crop_name
        ).first()
        db.close()
        if cached and cached.gdd_stages:
            return cached.gdd_stages
    except Exception:
        pass
    return DEFAULT_GDD_STAGES


def calculate_stage(crop_name: str, planting_date: date) -> tuple[str, int]:
    """Calculate the current growth stage and days-since-planting."""
    days = (date.today() - planting_date).days
    if days < 0:
        return ("Seedling", 0)

    stages = get_stages_for_crop(crop_name)

    for stage_name in STAGE_ORDER:
        boundary = stages.get(stage_name)
        if boundary and days <= boundary:
            return (stage_name, days)

    return ("Ready to Harvest", days)


def calculate_stage_by_gdd(crop_name: str, cumulative_gdd: float) -> str:
    """Calculate growth stage based on cumulative GDD."""
    if cumulative_gdd <= 0:
        return "Seedling"

    stages = get_gdd_stages_for_crop(crop_name)

    for stage_name in STAGE_ORDER:
        boundary = stages.get(stage_name)
        if boundary and cumulative_gdd <= boundary:
            return stage_name

    return "Ready to Harvest"
