"""Endpoints under /invitations.

The preview and the password activation of a Tenant invitation are implemented;
the others are declared in the contract and answer 501.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.email import EmailSender, get_email_sender
from app.schemas.auth import AuthSession, TokenInput
from app.schemas.invitations import (
    InvitationAcceptancePreview,
    InvitationGoogleActivationInput,
    InvitationPasswordActivationInput,
    InvitationPreview,
)
from app.security import bearer_scheme
from app.services import activation

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/previews")
def preview_invitation(
    body: TokenInput, db: Annotated[Session, Depends(get_session)]
) -> InvitationPreview:
    """Report what an invitation link is for and whether it is still valid."""
    return activation.preview_invitation(db, body.token)


@router.post("/activations/password", status_code=status.HTTP_201_CREATED)
def activate_invitation_with_password(
    body: InvitationPasswordActivationInput,
    db: Annotated[Session, Depends(get_session)],
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


@router.post("/acceptance-previews", dependencies=[Depends(bearer_scheme)])
def preview_invitation_acceptance(body: TokenInput) -> InvitationAcceptancePreview:
    """Check whether the caller's account can accept an invitation."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post(
    "/acceptances",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(bearer_scheme)],
)
def accept_invitation(body: TokenInput) -> None:
    """Accept an invitation with the caller's existing account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
