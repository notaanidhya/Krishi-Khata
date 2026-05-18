"""
Environment-aware application configuration using Pydantic Settings.

SQLite is the default for rapid local development.
To switch to PostgreSQL, set DATABASE_URL in your .env:
    DATABASE_URL=postgresql://user:pass@localhost:5432/agroo
"""

from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "Agroo"
    API_V1_STR: str = "/api/v1"
    FLASK_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"

    # Database — defaults to SQLite in server/instance/agroo.db
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'instance' / 'agroo.db'}"

    # CORS — allow Vite dev server
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_PATH: str = str(BASE_DIR / "firebase-service-account.json")

    # Mock data toggle — set to False to hit live APIs
    USE_MOCK_DATA: bool = True

    # Gemini AI — for Smart Farm Diary analysis
    GEMINI_API_KEY: str = ""

    # data.gov.in — Mandi Price Daily Cache
    DATAGOV_API_KEY: str = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
    MANDI_CACHE_INTERVAL_HOURS: int = 12

    class Config:
        env_file = ".env"


settings = Settings()
