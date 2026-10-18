"""Registering owners and checking login credentials."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import UserAccount
from app.schemas.auth import LoginInput, RegisterOwnerInput, UserRole
from app.services.passwords import hash_password, verify_password


def find_by_email(db: Session, email: str) -> UserAccount | None:
    """Return the account with this email, ignoring case and surrounding spaces."""
    return db.scalars(
        select(UserAccount).where(UserAccount.email == email.strip().lower())
    ).one_or_none()


def create_owner(db: Session, data: RegisterOwnerInput) -> UserAccount:
    """Create an owner with an unverified email; flushes, never commits.

    Raises 409 EMAIL_ALREADY_REGISTERED when the email is taken.
    """
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


def authenticate(db: Session, data: LoginInput) -> UserAccount:
    """Return the account matching the email and password.

    Raises 401 INVALID_CREDENTIALS for an unknown email, a wrong password or an
    account without a password.
    """
    user = find_by_email(db, data.email)
    if (
        user is None
        or user.password_hash is None
        or not verify_password(data.password, user.password_hash)
    ):
        raise ApiError(401, "INVALID_CREDENTIALS")
    return user
