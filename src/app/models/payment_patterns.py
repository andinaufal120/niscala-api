"""Stored summaries of how a tenant pays."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaymentPatternSummary(Base):
    """The generated summary of a lease's payment pattern; one per lease."""

    __tablename__ = "payment_pattern_summaries"

    lease_id: Mapped[UUID] = mapped_column(ForeignKey("leases.id"), primary_key=True)
    summary: Mapped[str]
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
