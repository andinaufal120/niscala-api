"""In-app notifications and the push settings of each user."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.notifications import (
    NotificationCategory,
    NotificationType,
    NotificationUrgencyScope,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Notification(Base):
    """A notification for one recipient.

    `payload` holds the facts of the event as they were when it happened, keyed
    by the API field names in snake_case (`rent_bill`, `complaint`, `tenant`,
    `room`, `property`, `actor_name`) with plain JSON values; absent keys mean
    none. `property_id` ties it to a property so a Manager only sees it while
    assigned to that property.
    """

    __tablename__ = "notifications"
    __table_args__ = (CheckConstraint(_in_list("type", NotificationType), name="type"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recipient_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), index=True
    )
    type: Mapped[str] = mapped_column(String)
    property_id: Mapped[UUID | None] = mapped_column(ForeignKey("properties.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationSetting(Base):
    """The push switch of one category for one user; no row means the default."""

    __tablename__ = "notification_settings"
    __table_args__ = (
        CheckConstraint(_in_list("category", NotificationCategory), name="category"),
        CheckConstraint(
            "urgency_scope IS NULL OR "
            + _in_list("urgency_scope", NotificationUrgencyScope),
            name="urgency_scope",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String, primary_key=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean)
    urgency_scope: Mapped[str | None] = mapped_column(String)
