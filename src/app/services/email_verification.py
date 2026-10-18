"""Issuing and confirming email verification codes."""

import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.email import EmailSender
from app.errors import ApiError
from app.models import EmailVerificationCode, UserAccount

CODE_LIFETIME = timedelta(minutes=10)
RESEND_INTERVAL = timedelta(seconds=60)
MAX_FAILED_ATTEMPTS = 5


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def send_code(
    db: Session, user: UserAccount, sender: EmailSender
) -> EmailVerificationCode:
    """Replace the user's code with a new one and email it; flushes, never commits.

    Raises 429 VERIFICATION_CODE_TOO_SOON, with a Retry-After header, when the
    previous code was created less than 60 seconds ago.
    """
    now = datetime.now(UTC)
    row = db.get(EmailVerificationCode, user.id)
    if row is not None:
        remaining = (row.created_at + RESEND_INTERVAL - now).total_seconds()
        if remaining > 0:
            raise ApiError(
                429,
                "VERIFICATION_CODE_TOO_SOON",
                headers={"Retry-After": str(math.ceil(remaining))},
            )
    else:
        row = EmailVerificationCode(user_id=user.id)
        db.add(row)
    code = f"{secrets.randbelow(10**6):06d}"
    row.code_hash = _hash(code)
    row.created_at = now
    row.expires_at = now + CODE_LIFETIME
    row.failed_attempts = 0
    db.flush()
    sender.send_verification_code(user.email, code)
    return row


def confirm_code(db: Session, user: UserAccount, code: str) -> None:
    """Mark the user's email as verified when the code is right.

    Raises 422 VERIFICATION_CODE_EXPIRED when there is no code, it is past its
    expiry or it has failed 5 times, and 422 VERIFICATION_CODE_INVALID for a
    wrong code; the failed attempt is committed before raising.
    """
    row = db.get(EmailVerificationCode, user.id)
    if (
        row is None
        or row.failed_attempts >= MAX_FAILED_ATTEMPTS
        or row.expires_at <= datetime.now(UTC)
    ):
        raise ApiError(422, "VERIFICATION_CODE_EXPIRED", field="code")
    if not hmac.compare_digest(row.code_hash, _hash(code)):
        row.failed_attempts += 1
        db.commit()
        raise ApiError(422, "VERIFICATION_CODE_INVALID", field="code")
    user.email_verified = True
    db.delete(row)
    db.flush()
