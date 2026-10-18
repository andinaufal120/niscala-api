"""The pending email verification code of a user."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class EmailVerificationCode(Base):
    """The latest emailed code of a user, stored as a hash."""

    __tablename__ = "email_verification_codes"
    __table_args__ = (
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_not_negative"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id"), primary_key=True
    )
    code_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(default=0)
