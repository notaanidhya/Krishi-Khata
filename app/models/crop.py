"""
CropCycle model — tracks planting-to-harvest lifecycle per farm.
CropLog model  — farm-diary entries linked to a crop cycle,
                 designed to pipe into an LLM for stage extraction.
"""

from datetime import datetime, date as date_type, timezone
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base


class CropCycle(Base):
    __tablename__ = "crop_cycles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(
        Integer, ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    crop_name = Column(String(100), nullable=False)
    planting_date = Column(Date, nullable=False)
    status = Column(
        String(20), nullable=False, index=True, default="ACTIVE",
        comment="ACTIVE | HARVESTED",
    )
    cumulative_gdd = Column(
        Integer, nullable=False, default=0,
        comment="Cumulative Growing Degree Days since planting"
    )
    gdd_last_updated = Column(
        Date, nullable=True,
        comment="Date when cumulative_gdd was last updated"
    )

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    ai_validation_failed = Column(
        Boolean, nullable=True, default=False,
        comment="Whether the background AI validation failed for this crop"
    )
    ai_validated = Column(
        Boolean, nullable=True, default=False,
        comment="Whether the background AI validation completed successfully"
    )

    # ── Relationships ──────────────────────────────────────────────
    farm = relationship("Farm", back_populates="crop_cycles")
    logs = relationship(
        "CropLog", back_populates="crop_cycle",
        cascade="all, delete-orphan",
        order_by="CropLog.log_date.desc()",
    )

    def __repr__(self):
        return f"<CropCycle {self.crop_name} [{self.status}]>"

    def to_dict(self):
        return {
            "id": self.id,
            "farm_id": self.farm_id,
            "crop_name": self.crop_name,
            "planting_date": self.planting_date.isoformat(),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ai_validation_failed": self.ai_validation_failed,
            "ai_validated": self.ai_validated,
        }


class CropLog(Base):
    """Farm-diary entry attached to a crop cycle.
    Supports text, audio, and image inputs. AI fields are populated
    asynchronously by an LLM pipeline (placeholder for now).
    """
    __tablename__ = "crop_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crop_cycle_id = Column(
        Integer, ForeignKey("crop_cycles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    log_date = Column(
        Date, nullable=False,
        default=lambda: date_type.today(),
    )
    input_type = Column(
        String(20), nullable=False, default="text",
        comment="text | audio | image",
    )
    raw_content = Column(Text, nullable=False, comment="User text or media URL")

    # ── AI-populated fields (filled by LLM later) ─────────────────
    ai_extracted_stage = Column(
        String(50), nullable=True,
        comment="Growth stage inferred by LLM from raw_content",
    )
    ai_health_notes = Column(
        Text, nullable=True,
        comment="Health observations extracted by LLM",
    )
    ai_analysis_failed = Column(
        Boolean, nullable=False, default=False,
        comment="Whether the LLM failed to analyze this log",
    )

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    crop_cycle = relationship("CropCycle", back_populates="logs")

    def __repr__(self):
        return f"<CropLog {self.id} [{self.input_type}] {self.log_date}>"

    def to_dict(self):
        return {
            "id": self.id,
            "crop_cycle_id": self.crop_cycle_id,
            "log_date": self.log_date.isoformat(),
            "input_type": self.input_type,
            "raw_content": self.raw_content,
            "ai_extracted_stage": self.ai_extracted_stage,
            "ai_health_notes": self.ai_health_notes,
            "ai_analysis_failed": self.ai_analysis_failed,
            "created_at": self.created_at.isoformat(),
        }
