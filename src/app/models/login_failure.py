"""The failed login counter of an email."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoginFailure(Base):
    """Consecutive failed logins of a normalized email and the lock they caused."""

    __tablename__ = "login_failures"
    __table_args__ = (
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_not_negative"),
    )

    email: Mapped[str] = mapped_column(primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
