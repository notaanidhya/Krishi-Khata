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
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
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
from app.utils.crop_stages import calculate_stage, calculate_stage_by_gdd, get_crop_presets
from app.utils.gdd_calculator import fetch_historical_gdd, get_todays_gdd
from app.utils.ai_validator import async_validate_crop
from app.models.ai_cache import AICropTaskCache
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


async def _crop_to_response(crop: CropCycle) -> dict:
    """Convert a CropCycle ORM object to a response dict
    with dynamically calculated stage fields using GDD."""
    days = (date.today() - crop.planting_date).days
    
    # Add today's live GDD (forecast) to the cumulative total
    today_gdd = await get_todays_gdd(crop.farm.latitude, crop.farm.longitude)
    total_gdd = crop.cumulative_gdd + today_gdd
    
    current_stage = calculate_stage_by_gdd(crop.crop_name, total_gdd)
    known_crops = get_crop_presets()

    d = crop.to_dict()
    d["days_since_planting"] = days
    d["current_stage"] = current_stage
    d["cumulative_gdd"] = total_gdd
    # A crop is 'processing' while background AI validation is still pending:
    # not yet validated AND not a known-preset crop AND not failed.
    is_custom_crop = crop.crop_name not in known_crops
    d["is_processing"] = is_custom_crop and not crop.ai_validated and not crop.ai_validation_failed
    d["validation_failed"] = bool(crop.ai_validation_failed)
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
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Plant a new crop cycle on a farm.
    Only one ACTIVE crop is allowed per farm at a time.
    Verifies farm ownership before creating.
    """
    _verify_farm_ownership(farm_id, current_user.get("uid"), db)

    farm = db.query(Farm).get(farm_id)
    
    # Calculate initial cumulative GDD from planting date to yesterday
    yesterday = date.today()
    initial_gdd = 0.0
    if payload.planting_date < yesterday:
        initial_gdd = await fetch_historical_gdd(farm.latitude, farm.longitude, payload.planting_date, yesterday)

    crop = CropCycle(
        farm_id=farm_id,
        crop_name=payload.crop_name,
        planting_date=payload.planting_date,
        status="ACTIVE",
        cumulative_gdd=int(initial_gdd),
        gdd_last_updated=yesterday if payload.planting_date < yesterday else payload.planting_date
    )
    db.add(crop)
    db.commit()
    db.refresh(crop)

    # Load logs relationship (empty for new crop)
    crop.logs = []
    
    # Trigger background AI validation for custom crops
    background_tasks.add_task(async_validate_crop, crop.id, crop.crop_name)

    return await _crop_to_response(crop)

# ── Crop Cycle — Retry Validation ──────────────────────────────
@router.post(
    "/crops/{crop_id}/retry_validation",
    response_model=CropCycleResponse,
)
async def retry_crop_validation(
    crop_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retry AI validation for a crop that failed processing."""
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)

    # Reset both flags — ai_validated must also be cleared so the
    # processing badge re-appears while the background task runs
    crop.ai_validation_failed = False
    crop.ai_validated = False

    # Clear stale task cache so the schedule regenerates after successful validation
    db.query(AICropTaskCache).filter(
        AICropTaskCache.crop_name == crop.crop_name
    ).delete()
    db.commit()

    # Re-trigger background task
    background_tasks.add_task(async_validate_crop, crop.id, crop.crop_name)

    return await _crop_to_response(crop)


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

    return await _crop_to_response(crop)


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
    responses = []
    for c in crops:
        responses.append(await _crop_to_response(c))
    return responses





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

    # Extract requested language for AI
    accept_lang = request.headers.get("Accept-Language", "en").lower()
    target_language = "Hindi (using natural, conversational Devanagari script)" if "hi" in accept_lang else "English"

    system_prompt = (
        f"You are an expert Indian agronomist and crop doctor. "
        f"The user is growing {crop.crop_name}, planted {days_since_planting} days ago "
        f"(current growth stage: {current_stage}). "
        f"Provide practical, concise advice in simple language. "
        f"If the issue sounds like a disease or pest, suggest both organic and chemical remedies. "
        f"You MUST respond natively in {target_language}. Avoid overly formal or academic terms; "
        f"use vocabulary easily understood by a typical Indian farmer."
    )

    answer: str
    try:
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY is not configured - degrading gracefully.")
            return {
                "advice": "AI Agronomist is currently offline. Please consult standard local farming practices."
            }

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

    return await _crop_to_response(crop_with_logs)


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


# ── Dynamic AI Tasks ───────────────────────────────────────────
@router.get("/crops/{crop_id}/tasks")
async def get_crop_tasks(
    request: Request,
    crop_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get dynamic crop schedule tasks based on current stage and weather."""
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)
    
    # Calculate days since planting — used for status override and prompt
    days_since_planting = (date.today() - crop.planting_date).days

    # Calculate current stage using GDD
    today_gdd = await get_todays_gdd(crop.farm.latitude, crop.farm.longitude)
    total_gdd = crop.cumulative_gdd + today_gdd
    current_stage = calculate_stage_by_gdd(crop.crop_name, total_gdd)
    
    # Simple weather profile estimation based on today's GDD (which roughly correlates to average temp)
    if today_gdd > 18:
        weather_profile = "HOT"
    elif today_gdd < 10:
        weather_profile = "COOL"
    else:
        weather_profile = "MODERATE"
        
    # Detect requested language for AI
    accept_lang = request.headers.get("Accept-Language", "en").lower()
    lang_code = "hi" if "hi" in accept_lang else "en"
    target_language = "Hindi (using Devanagari script)" if lang_code == "hi" else "English"

    def _recalculate_status(tasks: list, days: int) -> list:
        """Override AI-generated status with server-side calculation based on
        actual days since planting, so completion marks are always accurate."""
        sorted_tasks = sorted(tasks, key=lambda t: t.get('day', 0))
        found_current = False
        for task in sorted_tasks:
            day = task.get('day', 0)
            if day < days:
                task['status'] = 'completed'
            elif not found_current:
                task['status'] = 'current'
                found_current = True
            else:
                task['status'] = 'upcoming'
        # Edge case: if all tasks are past, mark the last one as current
        if not found_current and sorted_tasks:
            sorted_tasks[-1]['status'] = 'current'
        return sorted_tasks

    # Check Cache — include language so Hindi/English responses are stored separately
    cached = db.query(AICropTaskCache).filter(
        AICropTaskCache.crop_name == crop.crop_name,
        AICropTaskCache.stage == current_stage,
        AICropTaskCache.weather_profile == weather_profile,
        AICropTaskCache.language == lang_code,
    ).first()
    
    if cached:
        # Recalculate status from cache so it stays accurate as days progress
        tasks = _recalculate_status(list(cached.tasks_json), days_since_planting)
        return {"tasks": tasks, "source": "cache", "stage": current_stage}
        
    # Generate new tasks using Gemini
    
    system_prompt = (
        f"You are an expert Indian agronomist. Generate a timeline of exactly 6-8 key farming milestones "
        f"for {crop.crop_name} over its full growing cycle. "
        f"The crop was planted {days_since_planting} days ago and is currently in the '{current_stage}' stage "
        f"with a '{weather_profile}' weather profile. "
        f"Assign realistic cumulative 'day' values (days after planting date) for each milestone across the full crop lifecycle. "
        f"Output ONLY a valid JSON array of objects, with no markdown fences. "
        f'Each object must have "task" (string), "icon" (string, a single emoji), '
        f'"day" (integer, cumulative days after planting for that milestone), and "status" (string: any value, it will be recalculated). '
        f"Ensure the tasks are written in {target_language}."
    )
    
    tasks = []
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_prompt)
        
        response = model.generate_content(
            f"Generate full lifecycle milestones for {crop.crop_name}. "
            f"Current day: {days_since_planting}. Stage: {current_stage}."
        )
        response_text = response.text.strip()
        
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines).strip()
            
        tasks = json.loads(response_text)
        
        # Save raw tasks to cache (without status — it will be recalculated per request)
        new_cache = AICropTaskCache(
            crop_name=crop.crop_name,
            stage=current_stage,
            weather_profile=weather_profile,
            language=lang_code,
            tasks_json=tasks
        )
        db.add(new_cache)
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to generate dynamic tasks: {e}")
        tasks = [{"task": f"Check {crop.crop_name} health", "icon": "👀", "day": 0, "status": "current"}]

    # Always override status with server-side calculation
    tasks = _recalculate_status(tasks, days_since_planting)
    return {"tasks": tasks, "source": "ai", "stage": current_stage}


# ── About Crop ─────────────────────────────────────────────────
@router.get("/crops/{crop_id}/about")
async def get_crop_about(
    request: Request,
    crop_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a short AI summary about the crop factoring in live weather/GDD."""
    crop = _verify_crop_ownership(crop_id, current_user.get("uid"), db)
    
    today_gdd = await get_todays_gdd(crop.farm.latitude, crop.farm.longitude)
    total_gdd = crop.cumulative_gdd + today_gdd
    current_stage = calculate_stage_by_gdd(crop.crop_name, total_gdd)
    
    accept_lang = request.headers.get("Accept-Language", "en").lower()
    target_language = "Hindi (using Devanagari script)" if "hi" in accept_lang else "English"
    
    system_prompt = (
        f"You are an expert Indian agronomist. Write exactly 2-3 short, engaging sentences "
        f"about the '{crop.crop_name}' crop which is currently in the '{current_stage}' stage. "
        f"Mention a quick tip or fact relevant to its current stage. "
        f"Always write in {target_language}. Do not use markdown."
    )
    
    try:
        if not settings.GEMINI_API_KEY:
            return {"about": f"This is a {crop.crop_name} crop in the {current_stage} stage."}
            
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_prompt)
        
        response = model.generate_content(f"Tell me about {crop.crop_name}.")
        return {"about": response.text.strip()}
    except Exception as e:
        logger.error(f"Failed to generate about crop: {e}")
        return {"about": f"{crop.crop_name} is currently in the {current_stage} stage."}
