"""
Import all models so Alembic and the app can discover them in one import.
"""

from app.models.base import Base
from app.models.user import User
from app.models.farm import Farm
from app.models.khata import KhataTransaction
from app.models.laborer import Laborer
from app.models.mandi import MandiPriceHistory
from app.models.crop import CropCycle, CropLog
from app.models.chat import CommunityMessage
from app.models.ai_cache import AICropTaskCache
from app.models.dynamic_crop import DynamicCrop

__all__ = [
    "Base", "User", "Farm", "KhataTransaction", "Laborer",
    "MandiPriceHistory",
    "CropCycle", "CropLog", "CommunityMessage", "AICropTaskCache",
    "DynamicCrop"
]
