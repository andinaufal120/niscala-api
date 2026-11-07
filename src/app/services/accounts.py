"""Registering owners and checking login credentials."""

from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.google import GoogleIdentity, GoogleVerifier, verify_google_token
from app.models import UserAccount
from app.schemas.auth import (
    LoginInput,
    Password,
    PersonName,
    RegisterOwnerInput,
    UserRole,
)
from app.schemas.user_accounts import EditableAccountStatus
from app.services.passwords import (
    check_password_allowed,
    hash_password,
    verify_password,
)
from app.services.user_accounts import is_deleted


def find_by_email(db: Session, email: str) -> UserAccount | None:
    """Return the account with this email, ignoring case and surrounding spaces."""
    return db.scalars(
        select(UserAccount).where(UserAccount.email == email.strip().lower())
    ).one_or_none()


def create_owner(db: Session, data: RegisterOwnerInput) -> UserAccount:
    """Create an owner with an unverified email; flushes, never commits.

    Raises 422 PASSWORD_TOO_COMMON for a guessable password, then 409
    EMAIL_ALREADY_REGISTERED when the email is taken.
    """
    check_password_allowed(data.password, name=data.name, email=data.email)
    if find_by_email(db, data.email) is not None:
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")
    user = UserAccount(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=UserRole.OWNER,
        email_verified=False,
    )
    db.add(user)
    db.flush()
    return user


def require_new_google_identity(db: Session, identity: GoogleIdentity) -> None:
    """Check that an identity may start a new account.

    Raises 422 GOOGLE_EMAIL_UNVERIFIED (field `idToken`) for an unverified
    email, 409 GOOGLE_ACCOUNT_ALREADY_REGISTERED when the subject is linked to
    an account, then 409 EMAIL_ALREADY_REGISTERED (field `email`) when the
    email belongs to an account, deleted or not.
    """
    if not identity.email_verified:
        raise ApiError(422, "GOOGLE_EMAIL_UNVERIFIED", field="idToken")
    if find_by_google_subject(db, identity.subject) is not None:
        raise ApiError(409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    if find_by_email(db, identity.email) is not None:
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")


def find_by_google_subject(db: Session, subject: str) -> UserAccount | None:
    """Return the account linked to this Google subject, deleted ones included."""
    return db.scalars(
        select(UserAccount).where(UserAccount.google_subject == subject)
    ).one_or_none()


def create_google_owner(
    db: Session, verifier: GoogleVerifier, id_token: str
) -> UserAccount:
    """Create an owner with a verified email and no password; flushes, never commits.

    The name is the token's name, or the part of the email before the @. Raises
    the errors of `verify_google_token` and `require_new_google_identity`.
    """
    identity = verify_google_token(verifier, id_token)
    require_new_google_identity(db, identity)
    email = identity.email.strip().lower()
    user = UserAccount(
        name=(identity.name or "").strip() or email.split("@")[0],
        email=email,
        password_hash=None,
        role=UserRole.OWNER,
        email_verified=True,
        google_subject=identity.subject,
        google_email=identity.email,
    )
    db.add(user)
    db.flush()
    return user


def authenticate_google(
    db: Session, verifier: GoogleVerifier, id_token: str
) -> UserAccount:
    """Return the account linked to the token's Google subject.

    The email is never used to find the account. Raises 401 GOOGLE_TOKEN_INVALID,
    401 INVALID_CREDENTIALS for an unknown or deleted identity, then 403
    ACCOUNT_INACTIVE.
    """
    identity = verify_google_token(verifier, id_token)
    user = find_by_google_subject(db, identity.subject)
    if user is None or is_deleted(db, user):
        raise ApiError(401, "INVALID_CREDENTIALS")
    if user.status == EditableAccountStatus.INACTIVE:
        raise ApiError(403, "ACCOUNT_INACTIVE")
    return user


def _validated(annotation: Any, value: str, field: str) -> str:
    try:
        return TypeAdapter(annotation).validate_python(value)
    except ValidationError as error:
        # The error's string form would repeat the rejected value.
        raise ApiError(
            422, "VALIDATION_FAILED", error.errors()[0]["msg"], field=field
        ) from None


def create_admin(db: Session, name: str, email: str, password: str) -> UserAccount:
    """Create an admin with a verified email; flushes, never commits.

    Raises 422 VALIDATION_FAILED for a blank or too long name or a password
    outside 8 to 128 characters, 422 PASSWORD_TOO_COMMON for a guessable
    password, then 409 EMAIL_ALREADY_REGISTERED when the email is taken. Error
    messages never contain the password.
    """
    name = _validated(PersonName, name, "name")
    _validated(Password, password, "password")
    check_password_allowed(password, name=name, email=email)
    if find_by_email(db, email) is not None:
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")
    user = UserAccount(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, data: LoginInput) -> UserAccount:
    """Return the account matching the email and password.

    Raises 401 INVALID_CREDENTIALS for an unknown email, a wrong password, an
    account without a password or a deleted account, then 403 ACCOUNT_INACTIVE
    for an inactive account whose password was right.
    """
    user = find_by_email(db, data.email)
    if (
        user is None
        or is_deleted(db, user)
        or user.password_hash is None
        or not verify_password(data.password, user.password_hash)
    ):
        raise ApiError(401, "INVALID_CREDENTIALS")
    if user.status == EditableAccountStatus.INACTIVE:
        raise ApiError(403, "ACCOUNT_INACTIVE")
    return user
