"""Endpoints under /invitations. Declared in the contract; not implemented yet."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.schemas.auth import AuthSession, TokenInput
from app.schemas.invitations import (
    InvitationAcceptancePreview,
    InvitationGoogleActivationInput,
    InvitationPasswordActivationInput,
    InvitationPreview,
)
from app.security import bearer_scheme

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/previews")
def preview_invitation(body: TokenInput) -> InvitationPreview:
    """Report what an invitation link is for and whether it is still valid."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/activations/password", status_code=status.HTTP_201_CREATED)
def activate_invitation_with_password(
    body: InvitationPasswordActivationInput,
) -> AuthSession:
    """Consume an invitation link, create the account with a password and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


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
