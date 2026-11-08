"""Endpoints for re-authenticating the caller under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.db import SessionDep
from app.google import GoogleVerifier, get_google_verifier
from app.schemas.reauthentication import (
    Reauthentication,
    ReauthenticationGoogleInput,
    ReauthenticationPasswordInput,
)
from app.security import CurrentUser, get_verified_user
from app.services import reauthentication

router = APIRouter(prefix="/me/reauthentication", tags=["account"])


@router.post("/password")
def reauthenticate_with_password(
    body: ReauthenticationPasswordInput,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
    db: SessionDep,
) -> Reauthentication:
    """Confirm the caller's identity with their password."""
    until = reauthentication.reauthenticate_with_password(db, current, body.password)
    return Reauthentication(reauthenticated_until=until)


@router.post("/google")
def reauthenticate_with_google(
    body: ReauthenticationGoogleInput,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
    db: SessionDep,
    verifier: Annotated[GoogleVerifier, Depends(get_google_verifier)],
) -> Reauthentication:
    """Confirm the caller's identity with a Google ID token."""
    until = reauthentication.reauthenticate_with_google(
        db, current, verifier, body.id_token
    )
    return Reauthentication(reauthenticated_until=until)
