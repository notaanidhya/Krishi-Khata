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
from fastapi import APIRouter, Depends, HTTPException, status
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
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

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


# ── Farm CRUD (stubs) ──────────────────────────────────────────
@router.get("/farms")
async def list_farms(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"message": "list-farms stub"}


@router.post("/farms")
async def create_farm(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"message": "create-farm stub"}


@router.patch("/farms/{id}")
async def update_farm(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"message": "update-farm stub"}


@router.delete("/farms/{id}")
async def delete_farm(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"message": "delete-farm stub"}


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
    """
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
    """
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
    """Delete a crop cycle."""
    crop = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Crop cycle {crop_id} not found",
        )

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
    """
    query = (
        db.query(CropCycle)
        .options(joinedload(CropCycle.logs))
        .filter(CropCycle.farm_id == farm_id)
    )
    if status_filter:
        query = query.filter(CropCycle.status == status_filter)

    crops = query.order_by(CropCycle.planting_date.desc()).all()
    return [_crop_to_response(c) for c in crops]


# ── Crop Logs (Smart Farm Diary) ────────────────────────────────
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
    """Add a new diary log entry for a crop cycle.

    1. Sends the farmer's observation to Gemini 1.5 Flash for analysis.
    2. Extracts growth stage and health notes from the AI response.
    3. Saves the CropLog with raw + AI-extracted data.

    If Gemini fails or returns invalid data, the log is saved anyway
    with null AI fields and an ai_analysis_failed flag.
    """
    # Verify the crop cycle exists
    crop = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Crop cycle {crop_id} not found",
        )

    # ── Call Gemini for AI analysis ───────────────────────────
    ai_result = _analyze_with_gemini(payload.raw_content, crop.crop_name)
    ai_failed = ai_result is None

    extracted_stage = ai_result["stage"] if ai_result else None
    health_notes = ai_result["health_notes"] if ai_result else None

    # ── Create the log entry ─────────────────────────────────
    log = CropLog(
        crop_cycle_id=crop_id,
        log_date=payload.log_date,
        input_type=payload.input_type,
        raw_content=payload.raw_content,
        ai_extracted_stage=extracted_stage,
        ai_health_notes=health_notes,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Build response with the extra flag
    response = log.to_dict()
    response["ai_analysis_failed"] = ai_failed
    return response


@router.get("/crops/{crop_id}/logs", response_model=list[CropLogResponse])
async def get_crop_logs(
    crop_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all diary logs for a crop cycle, newest first."""
    logs = (
        db.query(CropLog)
        .filter(CropLog.crop_cycle_id == crop_id)
        .order_by(CropLog.log_date.desc(), CropLog.created_at.desc())
        .all()
    )
    return [log.to_dict() for log in logs]
