"""Properties and the managers assigned to them."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Property(Base):
    """A rental building owned by one user."""

    __tablename__ = "properties"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    name: Mapped[str]
    address: Mapped[str]
    view_only: Mapped[bool]
    bank_name: Mapped[str | None]
    bank_account_number: Mapped[str | None]
    bank_account_holder_name: Mapped[str | None]
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def __init__(self, **fields: Any) -> None:
        # Defaulted here, not on the column, so an explicit None still reaches
        # the database and violates NOT NULL.
        fields.setdefault("view_only", False)
        super().__init__(**fields)


# An owner's live properties have distinct names, ignoring case.
Index(
    "uq_properties_owner_name",
    Property.owner_id,
    func.lower(Property.name),
    unique=True,
    postgresql_where=Property.deleted_at.is_(None),
)


class ManagerAssignment(Base):
    """The permission of a manager to work on a property."""

    __tablename__ = "manager_assignments"

    manager_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
