"""
Crop & Farm routes — farm management, dynamic crop cycle tracking,
and AI-powered farm diary logs.

Key endpoints:
  POST /farms/{farm_id}/crops       — Plant a new crop
  GET  /farms/{farm_id}/active_crop — Get current active crop with calculated stage
  POST /crops/{crop_id}/harvest     — Mark crop as harvested
  GET  /crop-presets                — List known crop names for dropdown
"""

import json
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from app.main import limiter
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.dependencies import get_current_user
from app.models.crop import CropCycle, CropLog
from app.schemas.crop import (
    CropCycleCreate,
    CropLogCreate,
    CropLogResponse,
    CropCycleResponse,
)
from app.utils.crop_stages import calculate_stage, get_crop_presets
from app.models.farm import Farm
from app.schemas.farm import FarmCreate, FarmResponse
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ── AI Crop Doctor Request Model ───────────────────────────────
class CropAIQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="The farmer's question about their crop")


# ── Gemini AI System Prompt ─────────────────────────────────────
GEMINI_SYSTEM_PROMPT = (
    "You are an agricultural API. Analyze the farmer's observation. "
    "Determine the crop's current growth stage and any mentioned health issues. "
    "Respond ONLY with a valid JSON object matching this schema: "
    '{"stage": "string (one of: Planned, Active, Vegetative, Flowering, Fruiting, Mature, Harvested)", '
    '"health_notes": "string or null"}. '
    "Do not include markdown formatting."
)


def _analyze_with_gemini(raw_content: str, crop_name: str) -> dict | None:
    """Call Gemini 1.5 Flash to extract growth stage and health notes.

    Returns a dict with 'stage' and 'health_notes' keys, or None if
    the API call fails or returns invalid JSON.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set — skipping AI analysis")
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            "gemini-flash-latest",
            system_instruction=GEMINI_SYSTEM_PROMPT,
        )

        user_prompt = f"Crop: {crop_name}\nFarmer's observation: {raw_content}"

        response = model.generate_content(user_prompt)
        response_text = response.text.strip()

        # Strip markdown code fences if Gemini wraps the JSON
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines).strip()

        result = json.loads(response_text)

        VALID_STAGES = {
            "Planned", "Active", "Vegetative", "Flowering",
            "Fruiting", "Mature", "Harvested",
        }
        stage = result.get("stage")
        health_notes = result.get("health_notes")

        if stage not in VALID_STAGES:
            logger.warning(f"Gemini returned invalid stage: '{stage}' — ignoring")
            stage = None

        return {
            "stage": stage,
            "health_notes": health_notes if health_notes else None,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return None


# ── Helpers ─────────────────────────────────────────────────────
def _verify_farm_ownership(farm_id: int, user_id: str, db: Session) -> Farm:
    """Verify the farm exists and belongs to the user. Returns the Farm or raises 403."""
    farm = db.query(Farm).filter(Farm.id == farm_id).first()
    if not farm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    if farm.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this farm")
    return farm


def _verify_crop_ownership(crop_id: int, user_id: str, db: Session) -> CropCycle:
    """Verify the crop exists and its farm belongs to the user. Returns the CropCycle or raises 403."""
    crop = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
    if not crop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Crop cycle {crop_id} not found")
    _verify_farm_ownership(crop.farm_id, user_id, db)
    return crop


def _crop_to_response(crop: CropCycle) -> dict:
    """Convert a CropCycle ORM object to a response dict
    with dynamically calculated stage fields."""
    current_stage, days = calculate_stage(crop.crop_name, crop.planting_date)

    d = crop.to_dict()
    d["days_since_planting"] = days
    d["current_stage"] = current_stage
    d["logs"] = [log.to_dict() for log in (crop.logs or [])]
    return d


# ── Crop Presets (for frontend dropdown) ────────────────────────
@router.get("/crop-presets")
async def list_crop_presets():
    """Return sorted list of known Indian crop names for the Add Crop modal."""
    return get_crop_presets()


# ── Farm CRUD ──────────────────────────────────────────────────
@router.get("/farms", response_model=list[FarmResponse])
async def list_farms(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all farms owned by the current user."""
    user_id = current_user.get("uid")
    farms = (
        db.query(Farm)
        .filter(Farm.user_id == user_id)
        .order_by(Farm.created_at.desc())
        .all()
    )
    return [farm.to_dict() for farm in farms]


@router.post("/farms", response_model=FarmResponse, status_code=status.HTTP_201_CREATED)
async def create_farm(
    payload: FarmCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new farm for the current user."""
    user_id = current_user.get("uid")
    farm = Farm(
        user_id=user_id,
        name=payload.name,
        area_acres=payload.area_acres,
        soil_type=payload.soil_type,
        district=payload.district or payload.state,
        state=payload.state,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    db.add(farm)
    db.commit()
    db.refresh(farm)
    return farm.to_dict()





# ── Crop Cycle — Plant New Crop ─────────────────────────────────
@router.post(
    "/farms/{farm_id}/crops",
    response_model=CropCycleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crop(
    farm_id: int,
    payload: CropCycleCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Plant a new crop cycle on a farm.
    Only one ACTIVE crop is allowed per farm at a time.
    Verifies farm ownership before creating.
    """
    _verify_farm_ownership(farm_id, current_user.get("uid"), db)

    crop = CropCycle(
        farm_id=farm_id,
        crop_name=payload.crop_name,
        planting_date=payload.planting_date,
        status="ACTIVE",
    )
    db.add(crop)
    db.commit()
    db.refresh(crop)

    # Load logs relationship (empty for new crop)
    crop.logs = []
    return _crop_to_response(crop)


# ── Crop Cycle — Get Active Crop ────────────────────────────────
@router.get(
    "/farms/{farm_id}/active_crop",
    response_model=CropCycleResponse,
)
async def get_active_crop(
    farm_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the currently ACTIVE crop for a farm with calculated stage.
    Returns 404 if no active crop exists (frontend shows empty state).
    Verifies farm ownership.
    """
    _verify_farm_ownership(farm_id, current_user.get("uid"), db)

    crop = (
        db.query(CropCycle)
        .options(joinedload(CropCycle.logs))
        .filter(CropCycle.farm_id == farm_id, CropCycle.status == "ACTIVE")
        .first()
    )
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active crop for this farm",
        )

    return _crop_to_response(crop)


# ── Crop Cycle — Delete ────────────────────────────────────────
@router.delete("/crops/{crop_id}")
async def delete_crop(
    crop_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a crop cycle. Verifies ownership via crop → farm → user."""
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)

    db.delete(crop)
    db.commit()

    return {"message": f"{crop.crop_name} deleted", "id": crop_id}


# ── List All Crops for a Farm ──────────────────────────────────
@router.get("/farms/{farm_id}/crops", response_model=list[CropCycleResponse])
async def list_crops(
    farm_id: int,
    status_filter: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all crop cycles for a farm, optionally filtered by status.
    Each cycle includes its diary logs (newest first).
    Verifies farm ownership.
    """
    _verify_farm_ownership(farm_id, current_user.get("uid"), db)

    query = (
        db.query(CropCycle)
        .options(joinedload(CropCycle.logs))
        .filter(CropCycle.farm_id == farm_id)
    )
    if status_filter:
        query = query.filter(CropCycle.status == status_filter)

    crops = query.order_by(CropCycle.planting_date.desc()).all()
    return [_crop_to_response(c) for c in crops]





# ── AI Crop Doctor ─────────────────────────────────────────────
@router.post("/crops/{crop_id}/ask_ai")
@limiter.limit("10/minute")
async def ask_crop_ai(
    request: Request,
    crop_id: int,
    payload: CropAIQuery,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask the AI Crop Doctor a question about a specific crop.

    Uses Gemini to provide agronomist-level advice based on the crop's
    current growth stage, days since planting, and the farmer's question.
    Responds in the same language as the user's query.
    """
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)

    days_since_planting = (date.today() - crop.planting_date).days
    current_stage, _ = calculate_stage(crop.crop_name, crop.planting_date)

    system_prompt = (
        f"You are an expert Indian agronomist and crop doctor. "
        f"The user is growing {crop.crop_name}, planted {days_since_planting} days ago "
        f"(current growth stage: {current_stage}). "
        f"Provide practical, concise advice in simple language. "
        f"If the issue sounds like a disease or pest, suggest both organic and chemical remedies. "
        f"Answer in the same language as the user's question."
    )

    answer: str
    try:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            "gemini-flash-latest",
            system_instruction=system_prompt,
        )

        response = model.generate_content(payload.query)
        answer = response.text.strip()

    except Exception as e:
        logger.error(f"AI Crop Doctor failed: {e}")
        answer = (
            "Sorry, the AI Crop Doctor is temporarily unavailable. "
            "Please try again in a few minutes. If the problem persists, "
            "consult your local agricultural extension officer."
        )

    return {
        "answer": answer,
        "crop_name": crop.crop_name,
        "days_since_planting": days_since_planting,
        "current_stage": current_stage,
    }


# ── Crop Cycle — Harvest ───────────────────────────────────────
@router.post(
    "/crops/{crop_id}/harvest",
    response_model=CropCycleResponse,
)
async def harvest_crop(
    crop_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an ACTIVE crop cycle as HARVESTED."""
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)

    if crop.status == "HARVESTED":
        raise HTTPException(status_code=400, detail="Crop is already harvested")

    crop.status = "HARVESTED"
    db.commit()
    
    crop_with_logs = (
        db.query(CropCycle)
        .options(joinedload(CropCycle.logs))
        .filter(CropCycle.id == crop_id)
        .first()
    )

    return _crop_to_response(crop_with_logs)


# ── Crop Diary Logs ────────────────────────────────────────────
@router.post(
    "/crops/{crop_id}/logs",
    response_model=CropLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_crop_log(
    crop_id: int,
    payload: CropLogCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new diary log (observation) to a crop cycle.
    Automatically calls the Gemini AI to extract growth stage and health notes.
    """
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)

    # Call AI
    ai_result = _analyze_with_gemini(payload.raw_content, crop.crop_name)
    
    stage = None
    health_notes = None
    ai_failed = True

    if ai_result:
        stage = ai_result.get("stage")
        health_notes = ai_result.get("health_notes")
        ai_failed = False

    new_log = CropLog(
        crop_cycle_id=crop.id,
        log_date=payload.log_date,
        input_type=payload.input_type,
        raw_content=payload.raw_content,
        ai_extracted_stage=stage,
        ai_health_notes=health_notes,
        ai_analysis_failed=ai_failed,
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return new_log.to_dict()
