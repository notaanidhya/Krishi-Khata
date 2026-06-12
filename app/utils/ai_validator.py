import json
import logging
import google.generativeai as genai
from sqlalchemy.orm import Session
from app.config import settings
from app.models.dynamic_crop import DynamicCrop
from app.models.crop import CropCycle
from app.models.ai_cache import AICropTaskCache
from app.utils.crop_stages import get_crop_presets

logger = logging.getLogger(__name__)

VALIDATOR_SYSTEM_PROMPT = """You are an expert Indian agronomist data cleaner.

A farmer has typed a crop name. Your job is to classify it.

Rules:
1. "corrected": It is a misspelling, regional name, or Hindi/regional translation of a crop that IS in the known crops list. Provide the exact match from the known list.
2. "new": It is a real, valid agricultural crop NOT in the known crops list. Provide its standard English name and growth stage boundaries in days.
3. "gibberish": It is completely invalid (random letters, nonsense).

Important: Hindi crop names like "kela" (banana), "gehu" (wheat), "chawal" (rice), "tamatar" (tomato), "aalu" (potato), etc. should be handled correctly.

Output ONLY a valid JSON object, no markdown:
{
  "status": "corrected" | "new" | "gibberish",
  "standard_name": "string or null",
  "stages_in_days": {
    "Seedling": int,
    "Vegetative": int,
    "Flowering": int,
    "Ready to Harvest": int
  }
}
Note: stages_in_days is required when status is "new", null otherwise."""

from app.database import SessionLocal

async def async_validate_crop(crop_id: int, crop_name: str):
    """Background task to validate, correct, or learn new crops via Gemini.
    Tries up to 3 times before marking as failed. On success, clears any
    stale AI task cache entries so fresh schedules are generated.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set — skipping crop validation")
        return

    known_crops = get_crop_presets()
    if crop_name in known_crops:
        # Already perfectly standard — mark as validated
        db = SessionLocal()
        try:
            crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
            if crop_cycle and not crop_cycle.ai_validated:
                crop_cycle.ai_validated = True
                db.commit()
        finally:
            db.close()
        return

    db = SessionLocal()
    result = None
    last_error = None

    # Try up to 3 times for robustness
    for attempt in range(3):
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                "gemini-flash-latest",
                system_instruction=VALIDATOR_SYSTEM_PROMPT,
            )

            user_message = (
                f"Crop name entered by farmer: '{crop_name}'\n"
                f"Known crops in system: {known_crops}\n"
                f"Classify this crop name and provide the JSON response."
            )

            response = model.generate_content(user_message)
            response_text = response.text.strip()

            # Extract JSON from response (handles markdown fences)
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                response_text = response_text[start_idx:end_idx + 1]

            result = json.loads(response_text)
            break  # Success — stop retrying

        except Exception as e:
            last_error = e
            logger.warning(f"Validation attempt {attempt + 1} failed for '{crop_name}': {e}")

    try:
        crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
        if not crop_cycle:
            return  # Already deleted

        if result is None:
            # All attempts failed
            logger.error(f"All validation attempts failed for '{crop_name}': {last_error}")
            crop_cycle.ai_validation_failed = True
            db.commit()
            return

        status = result.get("status")
        standard_name = result.get("standard_name")

        if status == "gibberish":
            logger.info(f"Deleting gibberish crop: '{crop_name}'")
            db.delete(crop_cycle)
            db.commit()

        elif status == "corrected" and standard_name in known_crops:
            logger.info(f"Correcting crop '{crop_name}' -> '{standard_name}'")
            _clear_task_cache(db, crop_name)
            crop_cycle.crop_name = standard_name
            crop_cycle.ai_validated = True
            db.commit()

        elif status == "new" and standard_name:
            logger.info(f"Learned new crop: '{standard_name}' from '{crop_name}'")
            _clear_task_cache(db, crop_name)
            # Update the crop cycle to the clean standard name
            crop_cycle.crop_name = standard_name
            crop_cycle.ai_validated = True

            # Save to DynamicCrop table so future lookups use correct stage boundaries
            existing_dynamic = db.query(DynamicCrop).filter(
                DynamicCrop.crop_name == standard_name
            ).first()
            if not existing_dynamic:
                stages = result.get("stages_in_days") or {}
                new_dynamic = DynamicCrop(
                    crop_name=standard_name,
                    seedling_days=int(stages.get("Seedling", 30)),
                    vegetative_days=int(stages.get("Vegetative", 90)),
                    flowering_days=int(stages.get("Flowering", 200)),
                    harvest_days=int(stages.get("Ready to Harvest", 300)),
                )
                db.add(new_dynamic)
            db.commit()

        else:
            logger.warning(f"Unexpected status '{status}' for '{crop_name}'")
            crop_cycle.ai_validation_failed = True
            db.commit()

    except Exception as e:
        logger.error(f"Crop validation DB write failed for '{crop_name}': {e}")
        try:
            crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
            if crop_cycle:
                crop_cycle.ai_validation_failed = True
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to set validation_failed flag: {inner_e}")
    finally:
        db.close()


def _clear_task_cache(db: Session, crop_name: str):
    """Delete any cached AI task schedules for this crop name so fresh,
    correctly-staged schedules are generated after validation."""
    try:
        db.query(AICropTaskCache).filter(
            AICropTaskCache.crop_name == crop_name
        ).delete()
        logger.info(f"Cleared task cache for '{crop_name}'")
    except Exception as e:
        logger.warning(f"Failed to clear task cache for '{crop_name}': {e}")
