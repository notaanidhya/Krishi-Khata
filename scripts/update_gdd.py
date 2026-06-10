import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.crop import CropCycle
from app.models.farm import Farm
from app.utils.gdd_calculator import fetch_historical_gdd

async def update_all_active_crops():
    print("Starting nightly GDD update for active crops...")
    db = SessionLocal()
    
    try:
        active_crops = db.query(CropCycle).join(Farm).filter(CropCycle.status == "ACTIVE").all()
        yesterday = date.today() - timedelta(days=1)
        
        updated_count = 0
        for crop in active_crops:
            # Only update if not already updated for yesterday
            if crop.gdd_last_updated and crop.gdd_last_updated >= yesterday:
                continue
                
            # If last updated a long time ago, calculate missing range
            start_date = crop.gdd_last_updated + timedelta(days=1) if crop.gdd_last_updated else crop.planting_date
            
            if start_date <= yesterday:
                gdd_to_add = await fetch_historical_gdd(
                    crop.farm.latitude, 
                    crop.farm.longitude, 
                    start_date, 
                    yesterday
                )
                crop.cumulative_gdd += int(gdd_to_add)
                crop.gdd_last_updated = yesterday
                updated_count += 1
                print(f"Updated Crop ID {crop.id} ({crop.crop_name}): Added {int(gdd_to_add)} GDD.")
                
        db.commit()
        print(f"Finished. Updated {updated_count} active crops.")
    except Exception as e:
        print(f"Failed to update GDD: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(update_all_active_crops())
