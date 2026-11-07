"""Endpoints for the caller's own account under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.db import SessionDep
from app.google import GoogleVerifier, get_google_verifier
from app.schemas.auth import Account, AddLocalPasswordInput, LinkGoogleInput
from app.security import CurrentUser, get_current_user, get_verified_user
from app.services import sign_in_methods

router = APIRouter(prefix="/me", tags=["account"])


@router.get("")
def get_my_account(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> Account:
    """Return the caller's account and sign-in methods."""
    return Account.from_user(current.user)


@router.post("/local-password")
def add_local_password(
    body: AddLocalPasswordInput,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
    db: SessionDep,
    verifier: Annotated[GoogleVerifier, Depends(get_google_verifier)],
) -> Account:
    """Add a password to a Google account, proven with a fresh Google ID token."""
    sign_in_methods.add_local_password(
        db, current, verifier, body.google_id_token, body.password
    )
    return Account.from_user(current.user)


@router.post("/google-link")
def link_google(
    body: LinkGoogleInput,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
    db: SessionDep,
    verifier: Annotated[GoogleVerifier, Depends(get_google_verifier)],
) -> Account:
    """Link a Google account to an account that has a password."""
    sign_in_methods.link_google(db, current, verifier, body.id_token)
    return Account.from_user(current.user)
