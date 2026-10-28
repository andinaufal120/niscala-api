"""Requesting, checking and completing password resets."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.email import EmailSender
from app.errors import ApiError
from app.models import PasswordResetToken, UserAccount
from app.schemas.user_accounts import UserAccountStatus
from app.services import sessions
from app.services.accounts import find_by_email
from app.services.invitations import password_reset_url
from app.services.login_attempts import clear_failures
from app.services.passwords import check_password_allowed, hash_password
from app.services.user_accounts import is_deleted

RESET_LIFETIME = timedelta(minutes=30)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _is_eligible(db: Session, user: UserAccount) -> bool:
    return (
        user.password_hash is not None
        and user.status == UserAccountStatus.ACTIVE
        and not is_deleted(db, user)
    )


def _replace_open_tokens(db: Session, user_id: UUID) -> None:
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.replaced_at.is_(None),
        )
        .values(replaced_at=datetime.now(UTC))
    )


def request_reset(db: Session, email: str, sender: EmailSender) -> None:
    """Email a reset link when the email belongs to an account that can log in.

    An account can log in when it has a password, is active and is not deleted.
    The link replaces the account's earlier open links and lasts 30 minutes.
    Anything else does nothing, so the caller cannot tell whether the email is
    registered. Flushes, never commits.
    """
    user = find_by_email(db, email)
    if user is None or not _is_eligible(db, user):
        return
    _replace_open_tokens(db, user.id)
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash(token),
            created_at=now,
            expires_at=now + RESET_LIFETIME,
        )
    )
    db.flush()
    sender.send_password_reset_link(user.email, password_reset_url(token))


def _open_token(db: Session, token: str) -> tuple[PasswordResetToken, UserAccount]:
    row = db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(token))
    ).one_or_none()
    user = row and db.get(UserAccount, row.user_id)
    if user is None or not _is_eligible(db, user):
        raise ApiError(404, "PASSWORD_RESET_NOT_FOUND")
    if row.used_at is not None or row.replaced_at is not None:
        raise ApiError(409, "PASSWORD_RESET_USED")
    if row.expires_at <= datetime.now(UTC):
        raise ApiError(409, "PASSWORD_RESET_EXPIRED")
    return row, user


def preview_reset(db: Session, token: str) -> str:
    """Return the email of the account a reset link belongs to.

    Raises 404 PASSWORD_RESET_NOT_FOUND for an unknown link or an account that
    can no longer log in, 409 PASSWORD_RESET_USED for a link already used or
    replaced, then 409 PASSWORD_RESET_EXPIRED for an old link.
    """
    _, user = _open_token(db, token)
    return user.email


def reset_password(db: Session, token: str, new_password: str) -> None:
    """Set a new password with a reset link, ending every session of the account.

    Raises the same errors as `preview_reset`, then 422 PASSWORD_TOO_COMMON for
    a guessable password; a refusal consumes nothing. The link is used up, the
    account's other open links are replaced, its failed logins are forgotten and
    its email counts as verified. Flushes, never commits.
    """
    row, user = _open_token(db, token)
    check_password_allowed(
        new_password, name=user.name, email=user.email, field="newPassword"
    )
    user.password_hash = hash_password(new_password)
    user.email_verified = True
    row.used_at = datetime.now(UTC)
    db.flush()
    _replace_open_tokens(db, user.id)
    sessions.end_all_sessions(db, user.id)
    clear_failures(db, user.email)
    db.flush()
