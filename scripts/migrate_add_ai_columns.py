"""
Migration: add ai_validated to crop_cycles, language to ai_crop_task_cache

Run with:
    cd server
    python scripts/migrate_add_ai_columns.py
"""

import sys
import os

# Ensure the server directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import engine
from sqlalchemy import text

def run_migration():
    with engine.connect() as conn:
        # 1. Add ai_validated column to crop_cycles
        try:
            conn.execute(text(
                "ALTER TABLE crop_cycles ADD COLUMN ai_validated BOOLEAN DEFAULT FALSE"
            ))
            conn.commit()
            print("Added ai_validated to crop_cycles")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("ai_validated already exists in crop_cycles -- skipping")
                conn.rollback()
            else:
                print(f"Failed to add ai_validated: {e}")
                conn.rollback()
                raise

        # 2. Add language column to ai_crop_task_cache
        try:
            conn.execute(text(
                "ALTER TABLE ai_crop_task_cache ADD COLUMN language VARCHAR(10) DEFAULT 'en'"
            ))
            conn.commit()
            print("Added language to ai_crop_task_cache")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("language already exists in ai_crop_task_cache -- skipping")
                conn.rollback()
            else:
                print(f"Failed to add language: {e}")
                conn.rollback()
                raise

        # 3. Backfill: mark all existing crops as ai_validated=true
        # (existing crops were planted before this feature, treat them as done)
        try:
            conn.execute(text(
                "UPDATE crop_cycles SET ai_validated = TRUE WHERE ai_validated IS NULL OR ai_validated = FALSE"
            ))
            conn.commit()
            print("Backfilled ai_validated for existing crops")
        except Exception as e:
            print(f"Backfill skipped: {e}")
            conn.rollback()

        # 4. Update ai_crop_task_cache existing rows to have language='en'
        try:
            conn.execute(text(
                "UPDATE ai_crop_task_cache SET language = 'en' WHERE language IS NULL"
            ))
            conn.commit()
            print("Backfilled language='en' for existing cache entries")
        except Exception as e:
            print(f"Cache language backfill skipped: {e}")
            conn.rollback()

    print("Migration complete!")

if __name__ == "__main__":
    run_migration()
