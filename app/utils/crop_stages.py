"""
Crop growth stage intervals — maps common Indian crops to their
stage boundaries in days-after-planting.

Usage:
    from app.utils.crop_stages import calculate_stage

    stage, days = calculate_stage("Wheat", planting_date)
    # stage = "Vegetative", days = 37
"""

from datetime import date
from app.database import SessionLocal
from app.models.dynamic_crop import DynamicCrop


# ── Growth stage intervals (cumulative days from planting) ──────
# Each crop maps stage names to the day the stage ENDS.
# The current stage is the first interval whose end-day >= days_since_planting.
CROP_STAGE_MAP: dict[str, dict[str, int]] = {
    "Wheat": {
        "Seedling": 15,
        "Vegetative": 60,
        "Flowering": 90,
        "Ready to Harvest": 120,
    },
    "Rice": {
        "Seedling": 25,
        "Vegetative": 65,
        "Flowering": 95,
        "Ready to Harvest": 130,
    },
    "Maize": {
        "Seedling": 14,
        "Vegetative": 50,
        "Flowering": 75,
        "Ready to Harvest": 110,
    },
    "Soybean": {
        "Seedling": 12,
        "Vegetative": 45,
        "Flowering": 75,
        "Ready to Harvest": 105,
    },
    "Cotton": {
        "Seedling": 20,
        "Vegetative": 60,
        "Flowering": 100,
        "Ready to Harvest": 160,
    },
    "Tomato": {
        "Seedling": 14,
        "Vegetative": 40,
        "Flowering": 65,
        "Ready to Harvest": 90,
    },
    "Brinjal": {
        "Seedling": 15,
        "Vegetative": 45,
        "Flowering": 70,
        "Ready to Harvest": 100,
    },
    "Chilli": {
        "Seedling": 15,
        "Vegetative": 45,
        "Flowering": 75,
        "Ready to Harvest": 110,
    },
    "Onion": {
        "Seedling": 20,
        "Vegetative": 60,
        "Flowering": 90,
        "Ready to Harvest": 120,
    },
    "Potato": {
        "Seedling": 15,
        "Vegetative": 45,
        "Flowering": 70,
        "Ready to Harvest": 100,
    },
    "Mustard": {
        "Seedling": 12,
        "Vegetative": 40,
        "Flowering": 70,
        "Ready to Harvest": 110,
    },
    "Groundnut": {
        "Seedling": 14,
        "Vegetative": 45,
        "Flowering": 70,
        "Ready to Harvest": 110,
    },
    "Sugarcane": {
        "Seedling": 30,
        "Vegetative": 120,
        "Flowering": 270,
        "Ready to Harvest": 365,
    },
    "Chickpea": {
        "Seedling": 15,
        "Vegetative": 50,
        "Flowering": 80,
        "Ready to Harvest": 110,
    },
    "Bajra": {
        "Seedling": 10,
        "Vegetative": 35,
        "Flowering": 55,
        "Ready to Harvest": 80,
    },
}

# Default fallback intervals for unknown/custom crop names
DEFAULT_STAGES: dict[str, int] = {
    "Seedling": 15,
    "Vegetative": 50,
    "Flowering": 75,
    "Ready to Harvest": 110,
}

# Ordered stage keys for iteration
STAGE_ORDER = ["Seedling", "Vegetative", "Flowering", "Ready to Harvest"]


def get_crop_presets() -> list[str]:
    """Return sorted list of all known crop names."""
    presets = list(CROP_STAGE_MAP.keys())
    try:
        db = SessionLocal()
        dynamic_crops = db.query(DynamicCrop).all()
        for dc in dynamic_crops:
            if dc.crop_name not in presets:
                presets.append(dc.crop_name)
        db.close()
    except Exception:
        pass
    return sorted(presets)


def get_stages_for_crop(crop_name: str) -> dict[str, int]:
    """Return stage intervals for a crop, falling back to defaults."""
    if crop_name in CROP_STAGE_MAP:
        return CROP_STAGE_MAP[crop_name]
    
    try:
        db = SessionLocal()
        dynamic_crop = db.query(DynamicCrop).filter(DynamicCrop.crop_name == crop_name).first()
        db.close()
        if dynamic_crop:
            return dynamic_crop.to_dict()
    except Exception:
        pass

    return DEFAULT_STAGES


def get_gdd_stages_for_crop(crop_name: str) -> dict[str, float]:
    """Return GDD stage intervals for a crop, assuming ~15 GDD/day from the original day map."""
    stages_in_days = CROP_STAGE_MAP.get(crop_name, DEFAULT_STAGES)
    return {k: v * 15.0 for k, v in stages_in_days.items()}


def calculate_stage(crop_name: str, planting_date: date) -> tuple[str, int]:
    """Calculate the current growth stage and days-since-planting.

    Args:
        crop_name: Name of the crop (case-sensitive lookup in CROP_STAGE_MAP).
        planting_date: The date the crop was planted.

    Returns:
        Tuple of (current_stage_name, days_since_planting).
        If the crop has exceeded the last stage boundary, returns
        "Ready to Harvest" with the actual day count.
    """
    days = (date.today() - planting_date).days
    if days < 0:
        return ("Seedling", 0)

    stages = get_stages_for_crop(crop_name)

    for stage_name in STAGE_ORDER:
        boundary = stages.get(stage_name)
        if boundary and days <= boundary:
            return (stage_name, days)

    # Past the last boundary — still "Ready to Harvest"
    return ("Ready to Harvest", days)


def calculate_stage_by_gdd(crop_name: str, cumulative_gdd: float) -> str:
    if cumulative_gdd <= 0:
        return "Seedling"

    stages = get_gdd_stages_for_crop(crop_name)

    for stage_name in STAGE_ORDER:
        boundary = stages.get(stage_name)
        if boundary and cumulative_gdd <= boundary:
            return stage_name

    return "Ready to Harvest"
