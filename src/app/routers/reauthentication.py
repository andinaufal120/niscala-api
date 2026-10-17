"""Endpoints for re-authenticating the caller under /me. Declared in the contract; not implemented yet."""

from fastapi import APIRouter, HTTPException, status

from app.schemas.reauthentication import (
    Reauthentication,
    ReauthenticationGoogleInput,
    ReauthenticationPasswordInput,
)

router = APIRouter(prefix="/me/reauthentication", tags=["account"])


@router.post("/password")
def reauthenticate_with_password(
    body: ReauthenticationPasswordInput,
) -> Reauthentication:
    """Confirm the caller's identity with their password."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/google")
def reauthenticate_with_google(body: ReauthenticationGoogleInput) -> Reauthentication:
    """Confirm the caller's identity with a Google ID token."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
