"""Endpoints under /auth. Declared in the contract; not implemented yet."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.auth import (
    Account,
    AuthSession,
    AuthTokens,
    EmailConfirmationInput,
    EmailVerificationSent,
    GoogleAuthInput,
    LoginInput,
    PasswordResetInput,
    PasswordResetPreview,
    PasswordResetRequestInput,
    RefreshInput,
    RegisterOwnerInput,
    TokenInput,
)
from app.security import CurrentUser, bearer_scheme, get_current_user
from app.services.sessions import end_session, refresh_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_owner(body: RegisterOwnerInput) -> AuthSession:
    """Sign up an Owner with a password and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/register/google", status_code=status.HTTP_201_CREATED)
def register_owner_with_google(body: GoogleAuthInput) -> AuthSession:
    """Sign up an Owner with Google and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/login")
def login(body: LoginInput) -> AuthSession:
    """Log in with email and password and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/login/google")
def login_with_google(body: GoogleAuthInput) -> AuthSession:
    """Log in with Google and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/refresh")
def refresh_tokens(
    body: RefreshInput, db: Annotated[Session, Depends(get_session)]
) -> AuthTokens:
    """Exchange a refresh token for a new token pair; the old one stops working."""
    return refresh_session(db, body.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(bearer_scheme)],
)
def logout(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> None:
    """End the current session."""
    end_session(db, current.session)


@router.post(
    "/email-verification",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(bearer_scheme)],
)
def send_email_verification() -> EmailVerificationSent:
    """Email a new 6-digit verification code to the caller's account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/email-verification/confirmation", dependencies=[Depends(bearer_scheme)])
def confirm_email(body: EmailConfirmationInput) -> Account:
    """Confirm the caller's email with the code that was sent."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post(
    "/password-reset-requests",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
)
def request_password_reset(body: PasswordResetRequestInput) -> None:
    """Email a password-reset link; answers the same whether or not the email is registered."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/password-reset-previews")
def preview_password_reset(body: TokenInput) -> PasswordResetPreview:
    """Check a password-reset link and return the account email."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post(
    "/password-resets",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def reset_password(body: PasswordResetInput) -> None:
    """Set a new password with a reset link and end every session of the account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
