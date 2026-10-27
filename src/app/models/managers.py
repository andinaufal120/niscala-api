"""The record of a manager working for one owner."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Manager(Base):
    """An owner's record of a manager account; its own id is the manager id of the API.

    One account may work for several owners, each with a record holding the
    owner's own nickname and phone.
    """

    __tablename__ = "managers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    nickname: Mapped[str | None]
    phone: Mapped[str]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# An owner has at most one live record per manager account.
Index(
    "uq_managers_owner_user",
    Manager.owner_id,
    Manager.user_id,
    unique=True,
    postgresql_where=Manager.deleted_at.is_(None),
)
