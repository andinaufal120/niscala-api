"""Endpoints for the caller's own account under /me. Declared in the contract; not implemented yet."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.auth import Account, AddLocalPasswordInput, LinkGoogleInput
from app.security import CurrentUser, get_current_user

router = APIRouter(prefix="/me", tags=["account"])


@router.get("")
def get_my_account(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> Account:
    """Return the caller's account and sign-in methods."""
    user = current.user
    return Account(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        email_verified=user.email_verified,
        has_password=user.password_hash is not None,
        google_email=None,
    )


@router.post("/local-password")
def add_local_password(body: AddLocalPasswordInput) -> Account:
    """Add a password to a Google account, proven with a fresh Google ID token."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/google-link")
def link_google(body: LinkGoogleInput) -> Account:
    """Link a Google account to an account that has a password."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
