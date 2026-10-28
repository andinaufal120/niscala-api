"""Registering owners and checking login credentials."""

from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Manager, Tenant, UserAccount
from app.schemas.auth import (
    LoginInput,
    Password,
    PersonName,
    RegisterOwnerInput,
    UserRole,
)
from app.services.passwords import (
    check_password_allowed,
    hash_password,
    verify_password,
)


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
    account without a password, a deleted tenant or a manager whose records are
    all deleted.
    """
    user = find_by_email(db, data.email)
    if user is not None and user.role == UserRole.TENANT:
        tenant = db.get(Tenant, user.id)
        if tenant is not None and tenant.deleted_at is not None:
            user = None
    if user is not None and user.role == UserRole.MANAGER:
        deletions = db.scalars(
            select(Manager.deleted_at).where(Manager.user_id == user.id)
        ).all()
        if deletions and all(deleted is not None for deleted in deletions):
            user = None
    if (
        user is None
        or user.password_hash is None
        or not verify_password(data.password, user.password_hash)
    ):
        raise ApiError(401, "INVALID_CREDENTIALS")
    return user
