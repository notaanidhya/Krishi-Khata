from sqlalchemy import Column, String, Integer, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime
from app.models.base import Base

class TranslationCache(Base):
    __tablename__ = "translation_cache"

    id = Column(Integer, primary_key=True, index=True)
    original_text = Column(String, index=True, nullable=False)
    lang_code = Column(String(10), index=True, nullable=False)
    translated_text = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("original_text", "lang_code", name="_original_lang_uc"),
    )
