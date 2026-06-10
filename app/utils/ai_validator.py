import json
import logging
import google.generativeai as genai
from sqlalchemy.orm import Session
from app.config import settings
from app.models.dynamic_crop import DynamicCrop
from app.models.crop import CropCycle
from app.utils.crop_stages import get_crop_presets

logger = logging.getLogger(__name__)

VALIDATOR_SYSTEM_PROMPT = """
You are an expert Indian agronomist data cleaner. A farmer has typed a crop name: '{crop_name}'.
The currently known valid crops in our system are: {known_crops}.

Determine if the input is:
1. "corrected": It is a clear misspelling, local variation, or Hindi translation of one of the known crops.
2. "new": It is a genuinely valid crop that is NOT in the known crops list.
3. "gibberish": It is not a real crop, is random letters, or is completely invalid.

If "corrected", you must provide the 'standard_name' exactly as it appears in the known crops list.
If "new", you must provide the standard English name as 'standard_name', and provide a 'stages_in_days' object with exact integer days for "Seedling", "Vegetative", "Flowering", and "Ready to Harvest" boundaries.

Output ONLY a valid JSON object matching this schema without markdown:
{
  "status": "gibberish" | "corrected" | "new",
  "standard_name": "string or null",
  "stages_in_days": {
    "Seedling": int,
    "Vegetative": int,
    "Flowering": int,
    "Ready to Harvest": int
  } | null
}
"""

from app.database import SessionLocal

async def async_validate_crop(crop_id: int, crop_name: str):
    """Background task to validate, correct, or learn new crops via Gemini."""
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set — skipping crop validation")
        return

    known_crops = get_crop_presets()
    if crop_name in known_crops:
        # Already perfectly standard
        return

    db = SessionLocal()
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest")
        
        prompt = VALIDATOR_SYSTEM_PROMPT.format(crop_name=crop_name, known_crops=known_crops)
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            response_text = response_text[start_idx:end_idx+1]
            
        result = json.loads(response_text)
        status = result.get("status")
        standard_name = result.get("standard_name")

        # Fetch the crop cycle from db
        crop_cycle = db.query(CropCycle).filter(CropCycle.id == crop_id).first()
        if not crop_cycle:
            return  # Already deleted or not found

        if status == "gibberish":
            logger.info(f"Deleting gibberish crop: '{crop_name}'")
            db.delete(crop_cycle)
            db.commit()

        elif status == "corrected" and standard_name in known_crops:
            logger.info(f"Correcting crop '{crop_name}' -> '{standard_name}'")
            crop_cycle.crop_name = standard_name
            db.commit()

        elif status == "new" and standard_name:
            logger.info(f"Learned new crop: '{standard_name}' from '{crop_name}'")
            # Update the crop cycle to the clean standard name
            crop_cycle.crop_name = standard_name
            
            # Check if we already have it in dynamic crops (maybe added by concurrent request)
            existing_dynamic = db.query(DynamicCrop).filter(DynamicCrop.crop_name == standard_name).first()
            if not existing_dynamic:
                stages = result.get("stages_in_days", {})
                new_dynamic = DynamicCrop(
                    crop_name=standard_name,
                    seedling_days=stages.get("Seedling", 15),
                    vegetative_days=stages.get("Vegetative", 45),
                    flowering_days=stages.get("Flowering", 75),
                    harvest_days=stages.get("Ready to Harvest", 100),
                )
                db.add(new_dynamic)
            db.commit()

    except Exception as e:
        logger.error(f"Crop validation failed for '{crop_name}': {e}")
    finally:
        db.close()
