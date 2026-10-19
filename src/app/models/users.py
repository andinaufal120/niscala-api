"""User accounts and their signed-in sessions."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base
from app.schemas.auth import UserRole
from app.schemas.sessions import LoginMethod


def _now() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: type[UserRole | LoginMethod]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class UserAccount(Base):
    """A person who can sign in."""

    __tablename__ = "user_accounts"
    __table_args__ = (CheckConstraint(_in_list("role", UserRole), name="role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(unique=True)
    password_hash: Mapped[str | None]
    role: Mapped[UserRole] = mapped_column(String)
    email_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("email")
    def _normalize_email(self, key: str, value: str | None) -> str | None:
        return None if value is None else value.strip().lower()


class UserSession(Base):
    """A signed-in device of a user."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(_in_list("login_method", LoginMethod), name="login_method"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    refresh_token_hash: Mapped[str] = mapped_column(unique=True)
    device_name: Mapped[str]
    platform: Mapped[str]
    login_method: Mapped[LoginMethod] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reauthenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsedRefreshToken(Base):
    """A refresh token a session has rotated away from, kept as a hash."""

    __tablename__ = "used_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
