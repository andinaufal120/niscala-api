"""Complaints and their status history."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.complaints import (
    ComplaintClassificationState,
    ComplaintStatus,
    ComplaintUrgency,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Complaint(Base):
    """A complaint a tenant filed about their room, with any AI classification."""

    __tablename__ = "complaints"
    __table_args__ = (
        CheckConstraint(_in_list("status", ComplaintStatus), name="status"),
        CheckConstraint(
            "classification_state IS NULL OR "
            + _in_list("classification_state", ComplaintClassificationState),
            name="classification_state",
        ),
        CheckConstraint(
            "ai_urgency IS NULL OR " + _in_list("ai_urgency", ComplaintUrgency),
            name="ai_urgency",
        ),
        CheckConstraint(
            "manual_urgency IS NULL OR " + _in_list("manual_urgency", ComplaintUrgency),
            name="manual_urgency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.user_id"))
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    description: Mapped[str]
    status: Mapped[str]
    classification_state: Mapped[str | None]
    ai_category: Mapped[str | None]
    ai_urgency: Mapped[str | None]
    ai_suggested_action: Mapped[str | None]
    manual_category: Mapped[str | None]
    manual_urgency: Mapped[str | None]
    classified_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_accounts.id")
    )
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ComplaintStatusChange(Base):
    """A move of a complaint to a status, with the handling note given."""

    __tablename__ = "complaint_status_changes"
    __table_args__ = (
        CheckConstraint(_in_list("status", ComplaintStatus), name="status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    complaint_id: Mapped[UUID] = mapped_column(ForeignKey("complaints.id"))
    status: Mapped[str]
    handling_note: Mapped[str | None]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
