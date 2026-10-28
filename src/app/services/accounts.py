"""Registering owners and checking login credentials."""

from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
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
