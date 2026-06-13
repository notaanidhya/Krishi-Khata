"""
KhataTransaction model — Kisan Khata (farmer's ledger).
Tracks every income and expense entry with category classification.
Uses transaction_date (not created_at) for all aggregation queries.

Financial amounts use Numeric(12,2) to prevent floating-point rounding errors.

Transaction types:
  - 'income'        — money received (sales, subsidies, etc.)
  - 'expense'       — money spent (seeds, fertilizer, etc.)
  - 'labor_wage'    — money owed to a laborer (increases laborer balance)
  - 'labor_payment' — money paid to a laborer (decreases laborer balance)
"""

from datetime import date, datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class KhataTransaction(Base):
    __tablename__ = "khata_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    farm_id = Column(
        Integer, ForeignKey("farms.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    laborer_id = Column(
        Integer, ForeignKey("laborers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    laborer_id = Column(
        Integer, ForeignKey("laborers.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Links labor_wage/labor_payment transactions to a specific laborer",
    )

    type = Column(
        String(15), nullable=False,
        comment="'income', 'expense', 'labor_wage', or 'labor_payment'",
    )
    amount = Column(
        Numeric(12, 2), nullable=False,
        comment="Amount in INR with 2 decimal precision",
    )
    category = Column(
        String(50), nullable=False,
        comment="e.g. seeds, fertilizer, labour, pesticide, equipment, sale, subsidy",
    )
    transaction_date = Column(Date, nullable=False, index=True, default=date.today)
    description = Column(String(255), nullable=True)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──────────────────────────────────────────────
    user = relationship("User", back_populates="transactions")
    laborer = relationship("Laborer", back_populates="transactions")

    def __repr__(self):
        return f"<Khata {self.type} ₹{self.amount} [{self.category}]>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "farm_id": self.farm_id,
            "laborer_id": self.laborer_id,
            "type": self.type,
            "amount": float(self.amount),  # Serialize Decimal to float for JSON
            "category": self.category,
            "description": self.description,
            "transaction_date": self.transaction_date.isoformat(),
            "created_at": self.created_at.isoformat(),
        }
