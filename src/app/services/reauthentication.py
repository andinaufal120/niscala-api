"""Confirming the caller's identity again before a sensitive change."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.google import GoogleVerifier, verify_google_token
from app.schemas.sessions import PasswordChangeResult
from app.security import CurrentUser
from app.services.login_attempts import (
    clear_failures,
    ensure_not_locked,
    record_failure,
)
from app.services.passwords import (
    check_password_allowed,
    hash_password,
    verify_password,
)
from app.services.sessions import has_other_active_sessions

REAUTHENTICATION_WINDOW = timedelta(minutes=5)


def change_password(
    db: Session, current: CurrentUser, current_password: str, new_password: str
) -> PasswordChangeResult:
    """Replace the caller's password and report whether other sessions remain.

    Shares the failed-login counter of the account's email. Raises 409
    PASSWORD_NOT_SET for an account without a password, 429 TOO_MANY_ATTEMPTS
    while locked, 422 CURRENT_PASSWORD_INCORRECT (field `currentPassword`) for a
    wrong one, after committing the recorded failure, 422 PASSWORD_UNCHANGED and
    422 PASSWORD_TOO_COMMON (field `newPassword`). No session is ended.
    """
    user = current.user
    email = user.email
    if user.password_hash is None:
        raise ApiError(409, "PASSWORD_NOT_SET")
    if email is not None:
        ensure_not_locked(db, email, "TOO_MANY_ATTEMPTS")
    if not verify_password(current_password, user.password_hash):
        if email is not None:
            record_failure(db, email)
            db.commit()
        raise ApiError(422, "CURRENT_PASSWORD_INCORRECT", field="currentPassword")
    if new_password == current_password:
        raise ApiError(422, "PASSWORD_UNCHANGED", field="newPassword")
    check_password_allowed(
        new_password, name=user.name, email=email or "", field="newPassword"
    )
    user.password_hash = hash_password(new_password)
    if email is not None:
        clear_failures(db, email)
    db.flush()
    return PasswordChangeResult(
        has_other_sessions=has_other_active_sessions(db, current)
    )


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
    return _mark_reauthenticated(db, current)


def reauthenticate_with_google(
    db: Session, current: CurrentUser, verifier: GoogleVerifier, id_token: str
) -> datetime:
    """Mark the session as re-authenticated and return when that stops counting.

    Shares the failed-login counter of the account's email. Raises 429
    TOO_MANY_LOGIN_ATTEMPTS while locked, 401 GOOGLE_TOKEN_INVALID (field
    `idToken`, not counted), 409 GOOGLE_NOT_LINKED for an account without a
    Google identity (not counted), and 422 GOOGLE_ACCOUNT_MISMATCH (field
    `idToken`) for a token of another identity, after committing the recorded
    failure.
    """
    user = current.user
    email = user.email
    if email is not None:
        ensure_not_locked(db, email)
    identity = verify_google_token(verifier, id_token)
    if user.google_subject is None:
        raise ApiError(409, "GOOGLE_NOT_LINKED")
    if identity.subject != user.google_subject:
        if email is not None:
            record_failure(db, email)
            db.commit()
        raise ApiError(422, "GOOGLE_ACCOUNT_MISMATCH", field="idToken")
    return _mark_reauthenticated(db, current)


def _mark_reauthenticated(db: Session, current: CurrentUser) -> datetime:
    if current.user.email is not None:
        clear_failures(db, current.user.email)
    now = datetime.now(UTC)
    current.session.reauthenticated_at = now
    return now + REAUTHENTICATION_WINDOW
