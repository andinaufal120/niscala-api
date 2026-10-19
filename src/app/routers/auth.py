"""Endpoints under /auth. Declared in the contract; not implemented yet."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.db import SessionDep
from app.email import EmailSender, get_email_sender
from app.errors import ApiError
from app.models import UserAccount
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
from app.schemas.sessions import LoginMethod
from app.security import CurrentUser, bearer_scheme, get_current_user
from app.services.accounts import authenticate, create_owner
from app.services.email_verification import RESEND_INTERVAL, confirm_code, send_code
from app.services.login_attempts import (
    clear_failures,
    ensure_not_locked,
    record_failure,
)
from app.services.sessions import end_session, refresh_session, start_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_unverified(user: UserAccount) -> None:
    if user.email_verified:
        raise ApiError(409, "EMAIL_ALREADY_VERIFIED")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_owner(
    body: RegisterOwnerInput,
    db: SessionDep,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> AuthSession:
    """Sign up an Owner with a password and start a session."""
    user = create_owner(db, body)
    tokens = start_session(db, user, body.device, LoginMethod.PASSWORD)
    send_code(db, user, sender)
    return AuthSession(**tokens.model_dump(), account=Account.from_user(user))


@router.post("/register/google", status_code=status.HTTP_201_CREATED)
def register_owner_with_google(body: GoogleAuthInput) -> AuthSession:
    """Sign up an Owner with Google and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/login")
def login(body: LoginInput, db: SessionDep) -> AuthSession:
    """Log in with email and password and start a session."""
    email = body.email.strip().lower()
    ensure_not_locked(db, email)
    try:
        user = authenticate(db, body)
    except ApiError as error:
        if error.code == "INVALID_CREDENTIALS":
            record_failure(db, email)
            db.commit()
        raise
    clear_failures(db, email)
    tokens = start_session(db, user, body.device, LoginMethod.PASSWORD)
    return AuthSession(**tokens.model_dump(), account=Account.from_user(user))


@router.post("/login/google")
def login_with_google(body: GoogleAuthInput) -> AuthSession:
    """Log in with Google and start a session."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/refresh")
def refresh_tokens(body: RefreshInput, db: SessionDep) -> AuthTokens:
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
    db: SessionDep,
) -> None:
    """End the current session."""
    end_session(db, current.session)


@router.post(
    "/email-verification",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(bearer_scheme)],
)
def send_email_verification(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: SessionDep,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> EmailVerificationSent:
    """Email a new 6-digit verification code to the caller's account."""
    _require_unverified(current.user)
    row = send_code(db, current.user, sender)
    return EmailVerificationSent(resend_available_at=row.created_at + RESEND_INTERVAL)


@router.post("/email-verification/confirmation", dependencies=[Depends(bearer_scheme)])
def confirm_email(
    body: EmailConfirmationInput,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: SessionDep,
) -> Account:
    """Confirm the caller's email with the code that was sent."""
    _require_unverified(current.user)
    confirm_code(db, current.user, body.code)
    return Account.from_user(current.user)


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
