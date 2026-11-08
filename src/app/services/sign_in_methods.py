"""Adding a local password to, and linking Google to, the caller's account."""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.google import GoogleVerifier, verify_google_token
from app.schemas.sessions import LoginMethod
from app.security import CurrentUser
from app.services.accounts import find_by_google_subject
from app.services.passwords import check_password_allowed, hash_password


def add_local_password(
    db: Session,
    current: CurrentUser,
    verifier: GoogleVerifier,
    google_id_token: str,
    password: str,
) -> None:
    """Give a Google account a password; flushes, never commits.

    Raises 409 PASSWORD_ALREADY_SET, 401 GOOGLE_TOKEN_INVALID (field
    `googleIdToken`), 409 GOOGLE_NOT_LINKED, 422 GOOGLE_ACCOUNT_MISMATCH (field
    `googleIdToken`) for a token of another identity, then 422
    PASSWORD_TOO_COMMON. Nothing counts as a failed login and no session ends.
    """
    user = current.user
    if user.password_hash is not None:
        raise ApiError(409, "PASSWORD_ALREADY_SET")
    identity = verify_google_token(verifier, google_id_token, field="googleIdToken")
    if user.google_subject is None:
        raise ApiError(409, "GOOGLE_NOT_LINKED")
    if identity.subject != user.google_subject:
        raise ApiError(422, "GOOGLE_ACCOUNT_MISMATCH", field="googleIdToken")
    check_password_allowed(password, name=user.name, email=user.email or "")
    user.password_hash = hash_password(password)
    db.flush()


def link_google(
    db: Session, current: CurrentUser, verifier: GoogleVerifier, id_token: str
) -> None:
    """Link a Google identity to the caller's account; flushes, never commits.

    Raises 403 PASSWORD_LOGIN_REQUIRED unless the current session started with a
    password login, 401 GOOGLE_TOKEN_INVALID (field `idToken`), 422
    GOOGLE_EMAIL_UNVERIFIED (field `idToken`), 409 GOOGLE_ALREADY_LINKED, then
    409 GOOGLE_ACCOUNT_ALREADY_REGISTERED when the identity belongs to any
    account, deleted or not. Stores the token's email as sent; the account's
    email, name, password and status do not change.
    """
    user = current.user
    if current.session.login_method != LoginMethod.PASSWORD:
        raise ApiError(403, "PASSWORD_LOGIN_REQUIRED")
    identity = verify_google_token(verifier, id_token)
    if not identity.email_verified:
        raise ApiError(422, "GOOGLE_EMAIL_UNVERIFIED", field="idToken")
    if user.google_subject is not None:
        raise ApiError(409, "GOOGLE_ALREADY_LINKED")
    if find_by_google_subject(db, identity.subject) is not None:
        raise ApiError(409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    user.google_subject = identity.subject
    user.google_email = identity.email
    db.flush()
