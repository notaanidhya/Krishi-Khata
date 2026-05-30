"""
Import all models so Alembic and the app can discover them in one import.
"""

from app.models.base import Base
from app.models.user import User
from app.models.farm import Farm
from app.models.khata import KhataTransaction
from app.models.laborer import Laborer
from app.models.mandi import SavedMandi, MandiPriceHistory
from app.models.crop import CropCycle, CropLog
from app.models.chat import CommunityMessage

__all__ = [
    "Base", "User", "Farm", "KhataTransaction", "Laborer",
    "SavedMandi", "MandiPriceHistory",
    "CropCycle", "CropLog", "CommunityMessage",
]
