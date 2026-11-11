"""The paid subscription of an owner, its purchase orders and its scheduled downgrade."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Uuid, false, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.subscriptions import (
    OrderStatus,
    PaidPlanCode,
    PlanCode,
    SubscriptionPeriod,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Subscription(Base):
    """The paid plan an owner holds until `ends_at`; at most one per owner."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(_in_list("plan", PaidPlanCode), name="plan"),
        CheckConstraint(
            _in_list("billing_period", SubscriptionPeriod), name="billing_period"
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    plan: Mapped[str]
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    billing_period: Mapped[str] = mapped_column(
        default=SubscriptionPeriod.MONTHLY.value,
        server_default=SubscriptionPeriod.MONTHLY.value,
    )
    auto_renew: Mapped[bool] = mapped_column(default=False, server_default=false())
    purchase_token: Mapped[str | None] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class SubscriptionOrder(Base):
    """An attempt to buy a paid plan; a purchase token is set once the app sends one."""

    __tablename__ = "subscription_orders"
    __table_args__ = (
        CheckConstraint(_in_list("plan", PaidPlanCode), name="plan"),
        CheckConstraint(
            _in_list("billing_period", SubscriptionPeriod), name="billing_period"
        ),
        CheckConstraint(_in_list("status", OrderStatus), name="status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    plan: Mapped[str]
    billing_period: Mapped[str]
    status: Mapped[str]
    purchase_token: Mapped[str | None] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScheduledDowngrade(Base):
    """The plan an owner confirmed to move to, and the properties and rooms to keep."""

    __tablename__ = "scheduled_downgrades"
    __table_args__ = (CheckConstraint(_in_list("plan", PlanCode), name="plan"),)

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    plan: Mapped[str]
    kept_property_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    kept_room_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
