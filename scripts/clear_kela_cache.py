"""Clear stale kela task cache and reset its validation flags so retry works."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.ai_cache import AICropTaskCache
from app.models.crop import CropCycle
from sqlalchemy import text

db = SessionLocal()
try:
    # Clear ALL task caches (stale status data)
    deleted = db.query(AICropTaskCache).delete()
    print(f"Cleared {deleted} cached task entries")

    # Fix kela: reset ai_validated=False so is_processing shows correctly during retry
    # (it was backfilled to True but validation actually failed)
    kela_crops = db.query(CropCycle).filter(
        CropCycle.crop_name.in_(["kela", "Kela", "kela ", "Banana"])
    ).all()
    for c in kela_crops:
        print(f"Found crop: id={c.id} name='{c.crop_name}' ai_validated={c.ai_validated} ai_validation_failed={c.ai_validation_failed}")
        if c.ai_validation_failed:
            # Reset so user can press Retry and it works
            c.ai_validation_failed = True  # keep failed so button shows
            c.ai_validated = False  # clear so processing badge can show on retry

    db.commit()
    print("Done.")
finally:
    db.close()
