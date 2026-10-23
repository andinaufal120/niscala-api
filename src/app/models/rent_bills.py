"""Rent bills, their status history and their transfer receipts."""

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.payments import PaymentMethod, PaymentStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class RentBill(Base):
    """The rent due for one billing period of a lease, with its payment state."""

    __tablename__ = "rent_bills"
    __table_args__ = (
        UniqueConstraint("lease_id", "period_start"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            _in_list("payment_status", PaymentStatus), name="payment_status"
        ),
        CheckConstraint(
            "payment_method IS NULL OR " + _in_list("payment_method", PaymentMethod),
            name="payment_method",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lease_id: Mapped[UUID] = mapped_column(ForeignKey("leases.id"))
    period_start: Mapped[date]
    period_end: Mapped[date]
    due_date: Mapped[date]
    amount: Mapped[int]
    payment_status: Mapped[str]
    payment_method: Mapped[str | None]
    paid_on: Mapped[date | None]
    rejection_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RentBillStatusChange(Base):
    """A move of a rent bill to a payment status; the actor is empty for the system."""

    __tablename__ = "rent_bill_status_changes"
    __table_args__ = (
        CheckConstraint(_in_list("status", PaymentStatus), name="status"),
        CheckConstraint(
            "method IS NULL OR " + _in_list("method", PaymentMethod), name="method"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rent_bill_id: Mapped[UUID] = mapped_column(ForeignKey("rent_bills.id"))
    status: Mapped[str]
    method: Mapped[str | None]
    reason: Mapped[str | None]
    manual: Mapped[bool]
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RentBillReceipt(Base):
    """The image a tenant uploaded as proof of a transfer; one per rent bill."""

    __tablename__ = "rent_bill_receipts"

    rent_bill_id: Mapped[UUID] = mapped_column(
        ForeignKey("rent_bills.id"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str]
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
