"""Rooms of a property."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Room(Base):
    """A rentable room of a property."""

    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("base_rate > 0", name="base_rate_positive"),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="length_m_positive"),
        CheckConstraint("width_m IS NULL OR width_m > 0", name="width_m_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    number: Mapped[str]
    base_rate: Mapped[int]
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    width_m: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    facilities: Mapped[list[str]] = mapped_column(ARRAY(Text))
    view_only: Mapped[bool]
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def __init__(self, **fields: Any) -> None:
        # Defaulted here, not on the columns, so an explicit None still reaches
        # the database and violates NOT NULL.
        fields.setdefault("facilities", [])
        fields.setdefault("view_only", False)
        super().__init__(**fields)


# A property's live rooms have distinct numbers, ignoring case.
Index(
    "uq_rooms_property_number",
    Room.property_id,
    func.lower(Room.number),
    unique=True,
    postgresql_where=Room.deleted_at.is_(None),
)
