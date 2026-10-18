"""The paid subscription of an owner."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.subscriptions import PaidPlanCode


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[PaidPlanCode]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Subscription(Base):
    """The paid plan an owner holds until `ends_at`; at most one per owner."""

    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint(_in_list("plan", PaidPlanCode), name="plan"),)

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    plan: Mapped[str]
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
