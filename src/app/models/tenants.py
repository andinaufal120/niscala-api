"""Tenants, their emergency contacts, leases and invitations."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.tenants import BillingCycle


def _now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    """The tenant profile of a user account; shares the account's id."""

    __tablename__ = "tenants"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    phone: Mapped[str]
    occupation: Mapped[str | None]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EmergencyContact(Base):
    """A person to contact about a tenant, kept in the order it was given."""

    __tablename__ = "emergency_contacts"
    __table_args__ = (UniqueConstraint("tenant_id", "position"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.user_id"))
    name: Mapped[str]
    relationship: Mapped[str]
    phone: Mapped[str]
    position: Mapped[int]


class Lease(Base):
    """A tenant's occupation of a room; active while `ended_at` is empty."""

    __tablename__ = "leases"
    __table_args__ = (
        CheckConstraint(
            "billing_cycle IN ("
            + ", ".join(repr(cycle.value) for cycle in BillingCycle)
            + ")",
            name="billing_cycle",
        ),
        CheckConstraint("rent > 0", name="rent_positive"),
        CheckConstraint(
            "grace_period_days >= 0", name="grace_period_days_not_negative"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.user_id"))
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    billing_cycle: Mapped[str]
    rent: Mapped[int]
    grace_period_days: Mapped[int]
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# A room and a tenant each have at most one active lease.
Index(
    "uq_leases_active_room",
    Lease.room_id,
    unique=True,
    postgresql_where=Lease.ended_at.is_(None),
)
Index(
    "uq_leases_active_tenant",
    Lease.tenant_id,
    unique=True,
    postgresql_where=Lease.ended_at.is_(None),
)


class Invitation(Base):
    """A single-use link a tenant activates their account with."""

    __tablename__ = "invitations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.user_id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    token_encrypted: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
