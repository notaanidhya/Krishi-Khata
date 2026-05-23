"""
Environment-aware application configuration using Pydantic Settings.

SQLite is the default for rapid local development.
To switch to PostgreSQL, set DATABASE_URL in your .env:
    DATABASE_URL=postgresql://user:pass@localhost:5432/agroo
"""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Sentinel value — used to detect if JWT_SECRET_KEY was never set.
_JWT_SECRET_NOT_SET = "__NOT_SET__"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Agroo"
    API_V1_STR: str = "/api/v1"
    FLASK_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"

    # JWT — used for device-ID + PIN authentication
    # No usable default — MUST be provided via .env or environment variable.
    JWT_SECRET_KEY: str = _JWT_SECRET_NOT_SET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_DAYS: int = 90  # Long-lived for rural/offline users

    # Dev auth bypass — explicit opt-in, defaults to OFF.
    # Set ENABLE_DEV_BYPASS=true in .env for local testing without JWT.
    ENABLE_DEV_BYPASS: bool = False

    # Database — defaults to SQLite in server/instance/agroo.db
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'instance' / 'agroo.db'}"

    # CORS — allow Vite dev server
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Firebase (legacy — kept for future OTP upgrade)
    FIREBASE_SERVICE_ACCOUNT_PATH: str = str(BASE_DIR / "firebase-service-account.json")

    # Mock data toggle — set to False to hit live APIs
    USE_MOCK_DATA: bool = True

    # Gemini AI — for Smart Farm Diary analysis
    GEMINI_API_KEY: str = ""

    # data.gov.in — Mandi Price Daily Cache
    DATAGOV_API_KEY: str = ""
    MANDI_CACHE_INTERVAL_HOURS: int = 12

    @model_validator(mode="after")
    def _validate_jwt_secret(self):
        if self.JWT_SECRET_KEY == _JWT_SECRET_NOT_SET:
            raise ValueError(
                "\n\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  FATAL: JWT_SECRET_KEY is not set!                      ║\n"
                "║                                                         ║\n"
                "║  Add JWT_SECRET_KEY=<random-64-char-string> to your     ║\n"
                "║  .env file or Render environment variables.             ║\n"
                "║                                                         ║\n"
                "║  Generate one with:                                     ║\n"
                "║    python -c \"import secrets; print(secrets.token_urlsafe(64))\"  ║\n"
                "╚══════════════════════════════════════════════════════════╝\n"
            )
        return self

    class Config:
        env_file = ".env"


settings = Settings()
