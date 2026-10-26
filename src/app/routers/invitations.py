"""Endpoints under /invitations.

The preview, the password activation and the acceptance of Tenant and Manager
invitations are implemented (accepting a Tenant invitation answers 501); the
Google activation is declared in the contract and answers 501.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.db import SessionDep
from app.email import EmailSender, get_email_sender
from app.schemas.auth import AuthSession, TokenInput
from app.schemas.invitations import (
    InvitationAcceptancePreview,
    InvitationGoogleActivationInput,
    InvitationPasswordActivationInput,
    InvitationPreview,
)
from app.security import CurrentUser, get_verified_user
from app.services import activation

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/previews")
def preview_invitation(body: TokenInput, db: SessionDep) -> InvitationPreview:
    """Report what an invitation link is for and whether it is still valid."""
    return activation.preview_invitation(db, body.token)


@router.post("/activations/password", status_code=status.HTTP_201_CREATED)
def activate_invitation_with_password(
    body: InvitationPasswordActivationInput,
    db: SessionDep,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> AuthSession:
    """Consume an invitation link, create the account with a password and start a session."""
    return activation.activate_with_password(db, body, sender)


@router.post("/activations/google", status_code=status.HTTP_201_CREATED)
def activate_invitation_with_google(
    body: InvitationGoogleActivationInput,
) -> AuthSession:
    """Consume an invitation link, create the account with Google and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/acceptance-previews")
def preview_invitation_acceptance(
    body: TokenInput,
    db: SessionDep,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
) -> InvitationAcceptancePreview:
    """Check whether the caller's account can accept an invitation."""
    return activation.preview_acceptance(db, body.token, current.user)


@router.post(
    "/acceptances",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def accept_invitation(
    body: TokenInput,
    db: SessionDep,
    current: Annotated[CurrentUser, Depends(get_verified_user)],
) -> None:
    """Accept an invitation with the caller's existing account."""
    activation.accept_invitation(db, body.token, current.user)
