"""Locking an email after repeated failed logins."""

from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import LoginFailure

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)


def ensure_not_locked(
    db: Session, email: str, code: str = "TOO_MANY_LOGIN_ATTEMPTS"
) -> None:
    """Raise 429 with the code and Retry-After while the email is locked."""
    row = db.get(LoginFailure, email)
    if row is None or row.locked_until is None:
        return
    remaining = (row.locked_until - datetime.now(UTC)).total_seconds()
    if remaining > 0:
        raise ApiError(
            429,
            code,
            headers={"Retry-After": str(ceil(remaining))},
        )


def record_failure(db: Session, email: str) -> None:
    """Count a failed login; the fifth in a row locks the email. Flushes only."""
    now = datetime.now(UTC)
    row = db.get(LoginFailure, email)
    if row is None:
        row = LoginFailure(email=email, failed_attempts=0)
        db.add(row)
    elif row.locked_until is not None and row.locked_until <= now:
        row.failed_attempts = 0
        row.locked_until = None
    row.failed_attempts += 1
    if row.failed_attempts >= MAX_FAILED_ATTEMPTS:
        row.locked_until = now + LOCK_DURATION
    db.flush()


def clear_failures(db: Session, email: str) -> None:
    """Forget the failed logins of the email. Flushes only."""
    row = db.get(LoginFailure, email)
    if row is not None:
        db.delete(row)
        db.flush()
