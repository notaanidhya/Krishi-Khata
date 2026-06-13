import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

url = os.getenv('DATABASE_URL')
if url and url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg2://")

engine = create_engine(url)

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE khata_transactions ADD COLUMN laborer_id INTEGER REFERENCES laborers(id) ON DELETE SET NULL;"))
    print("✅ Successfully added 'laborer_id' column to 'khata_transactions' table!")
except Exception as e:
    if "already exists" in str(e).lower():
        print("✅ Column 'laborer_id' already exists.")
    else:
        print("❌ Error:", e)
