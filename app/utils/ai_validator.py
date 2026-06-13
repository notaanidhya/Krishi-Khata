import json
import logging
from google import genai
from google.genai import types
from sqlalchemy.orm import Session
from app.config import settings
from app.models.crop_data_cache import CropDataCache
from app.models.crop import CropCycle
from app.utils.crop_stages import get_crop_presets

logger = logging.getLogger(__name__)

UNIFIED_CROP_PROMPT = """You are an expert Indian agronomist data system.

A farmer has entered a crop name. Your job is to:
1. Determine if it's a real agricultural crop (accept Hindi names, English names, regional names, misspellings)
2. If valid, return ALL crop data in a single response
3. If gibberish/not a real crop, return status "gibberish"

IMPORTANT: ALL text fields (about, schedule tasks) MUST be in Hindi (Devanagari script). Always.
CRITICAL: Use very simple, easy-to-understand conversational Hindi words suitable for a farmer in an Indian village. Do NOT use overly formal, academic, or complex Hindi words. Write it as if you are talking to a 5th grader.

Output ONLY a valid JSON object, no markdown fences:
{
  "status": "valid" | "gibberish",
  "standard_name_en": "English name like Banana",
  "standard_name_hi": "Hindi name like केला",
  "about_hi": "2-3 sentences about the crop in Hindi, mentioning key facts and a farming tip",
  "day_stages": {
    "Seedling": int (days from planting when seedling stage ends),
    "Vegetative": int (cumulative days when vegetative ends),
    "Flowering": int (cumulative days when flowering ends),
    "Ready to Harvest": int (cumulative days when ready to harvest)
  },
  "smart_schedule_hi": [
    {"task": "Hindi task description", "icon": "single emoji", "day": 0},
    ... (exactly 6-8 milestones covering full lifecycle, days are cumulative from planting)
  ]
}

For "gibberish" status, only include: {"status": "gibberish"}"""

from app.database import SessionLocal

async def async_validate_crop(crop_id: int, crop_name: str):
    """Background task: validate crop via Gemini, save ALL data to CropDataCache.
    If the crop already exists in CropDataCache (by standard_name_en), reuse it.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set — skipping crop validation")
        return

    db = SessionLocal()
    try:
        # Check if this crop already exists in cache (exact match or by standard name)
        existing = db.query(CropDataCache).filter(
            CropDataCache.crop_key == crop_name.lower().strip()
        ).first()
        
        if not existing:
            # Also check by standard_name_en (e.g., user typed "Wheat" and it exists)
            existing = db.query(CropDataCache).filter(
                CropDataCache.standard_name_en == crop_name
            ).first()

        if existing:
            # Crop already known — just update the crop cycle name and mark validated
            crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
            if crop_cycle:
                crop_cycle.crop_name = existing.standard_name_en
                crop_cycle.ai_validated = True
                db.commit()
            return

        # Not in cache — call Gemini
        result = await _call_gemini_unified(crop_name)
        
        crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
        if not crop_cycle:
            return  # Already deleted

        if result is None:
            # All attempts failed
            crop_cycle.ai_validation_failed = True
            db.commit()
            return

        status = result.get("status")

        if status == "gibberish":
            logger.info(f"Deleting gibberish crop: '{crop_name}'")
            db.delete(crop_cycle)
            db.commit()
            return

        if status == "valid":
            standard_en = result.get("standard_name_en", crop_name)
            standard_hi = result.get("standard_name_hi", standard_en)
            about_hi = result.get("about_hi", "")
            day_stages = result.get("day_stages", {
                "Seedling": 15, "Vegetative": 50,
                "Flowering": 75, "Ready to Harvest": 110
            })
            schedule = result.get("smart_schedule_hi", [])
            
            # Compute GDD stages from day stages (approx 15 GDD per day)
            gdd_stages = {k: v * 15.0 for k, v in day_stages.items()}

            # Check if standard name already exists in cache
            # (another user might have added the same crop with a different spelling)
            existing_by_name = db.query(CropDataCache).filter(
                CropDataCache.standard_name_en == standard_en
            ).first()
            
            if not existing_by_name:
                new_cache = CropDataCache(
                    crop_key=standard_en.lower().strip(),
                    standard_name_en=standard_en,
                    standard_name_hi=standard_hi,
                    about_hi=about_hi,
                    day_stages=day_stages,
                    gdd_stages=gdd_stages,
                    smart_schedule_hi=schedule,
                )
                db.add(new_cache)
            
            crop_cycle.crop_name = standard_en
            crop_cycle.ai_validated = True
            db.commit()
            logger.info(f"Validated crop '{crop_name}' -> '{standard_en}' ('{standard_hi}')")
        else:
            logger.warning(f"Unexpected status '{status}' for '{crop_name}'")
            crop_cycle.ai_validation_failed = True
            db.commit()

    except Exception as e:
        logger.error(f"Crop validation failed for '{crop_name}': {e}")
        try:
            crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
            if crop_cycle:
                crop_cycle.ai_validation_failed = True
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to set validation_failed flag: {inner_e}")
    finally:
        db.close()


async def _call_gemini_unified(crop_name: str) -> dict | None:
    """Call Gemini with unified prompt. Retries up to 3 times."""
    import asyncio
    
    known_crops = get_crop_presets()
    result = None
    last_error = None

    for attempt in range(3):
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)

            user_message = (
                f"Crop name provided by farmer: '{crop_name}'\n"
                f"Already known crops: {', '.join(known_crops)}\n"
            )

            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=UNIFIED_CROP_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            )

            # Fix for Gemini returning json code block
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            result = json.loads(raw_text.strip())
            return result
        except Exception as e:
            last_error = e
            logger.error(f"Gemini valid attempt {attempt+1} failed: {e}")
            await asyncio.sleep(1)

    logger.error(f"All Gemini valid attempts failed for '{crop_name}'. Last error: {last_error}")
    return None
