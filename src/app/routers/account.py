"""Endpoints for the caller's own account under /me. Declared in the contract; not implemented yet."""

from fastapi import APIRouter, HTTPException, status

from app.schemas.auth import Account, AddLocalPasswordInput, LinkGoogleInput

router = APIRouter(prefix="/me", tags=["account"])


@router.get("")
def get_my_account() -> Account:
    """Return the caller's account and sign-in methods."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/local-password")
def add_local_password(body: AddLocalPasswordInput) -> Account:
    """Add a password to a Google account, proven with a fresh Google ID token."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/google-link")
def link_google(body: LinkGoogleInput) -> Account:
    """Link a Google account to an account that has a password."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
