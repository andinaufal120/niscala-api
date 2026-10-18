"""Confirming the caller's identity again before a sensitive change."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.security import CurrentUser
from app.services.login_attempts import (
    clear_failures,
    ensure_not_locked,
    record_failure,
)
from app.services.passwords import verify_password

REAUTHENTICATION_WINDOW = timedelta(minutes=5)


def reauthenticate_with_password(
    db: Session, current: CurrentUser, password: str
) -> datetime:
    """Mark the session as re-authenticated and return when that stops counting.

    Shares the failed-login counter of the account's email. Raises 429
    TOO_MANY_LOGIN_ATTEMPTS while locked, 409 PASSWORD_NOT_SET for an account
    without a password, and 422 PASSWORD_INCORRECT (field `password`) for a
    wrong one, after committing the recorded failure.
    """
    user = current.user
    email = user.email
    if email is not None:
        ensure_not_locked(db, email)
    if user.password_hash is None:
        raise ApiError(409, "PASSWORD_NOT_SET")
    if not verify_password(password, user.password_hash):
        if email is not None:
            record_failure(db, email)
            db.commit()
        raise ApiError(422, "PASSWORD_INCORRECT", field="password")
    if email is not None:
        clear_failures(db, email)
    now = datetime.now(UTC)
    current.session.reauthenticated_at = now
    return now + REAUTHENTICATION_WINDOW
