"""Endpoints for re-authenticating the caller under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
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
    db: Annotated[Session, Depends(get_session)],
) -> Reauthentication:
    """Confirm the caller's identity with their password."""
    until = reauthentication.reauthenticate_with_password(db, current, body.password)
    return Reauthentication(reauthenticated_until=until)


@router.post("/google")
def reauthenticate_with_google(body: ReauthenticationGoogleInput) -> Reauthentication:
    """Confirm the caller's identity with a Google ID token."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
