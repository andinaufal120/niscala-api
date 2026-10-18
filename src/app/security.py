"""Bearer authentication: the scheme declared in the contract and the caller lookup."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import UserAccount, UserSession

bearer_scheme = HTTPBearer(
    scheme_name="bearerAuth", bearerFormat="JWT", auto_error=False
)


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller and the session their access token belongs to."""

    user: UserAccount
    session: UserSession


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_session)],
) -> CurrentUser:
    """Resolve a bearer access token to its user and an unrevoked session.

    Raises 401 ACCESS_TOKEN_INVALID for any token that is missing, malformed,
    expired, forged, or whose session is unknown or revoked.
    """
    invalid = ApiError(401, "ACCESS_TOKEN_INVALID")
    if credentials is None:
        raise invalid
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "sid"]},
        )
        user_id = UUID(claims["sub"])
        session_id = UUID(claims["sid"])
    except jwt.InvalidTokenError, ValueError, TypeError, AttributeError:
        raise invalid from None
    session = db.get(UserSession, session_id)
    user = db.get(UserAccount, user_id)
    if session is None or session.revoked_at is not None or user is None:
        raise invalid
    return CurrentUser(user=user, session=session)


def get_verified_user(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Like `get_current_user`, but raises 403 EMAIL_NOT_VERIFIED for an unverified email."""
    if not current.user.email_verified:
        raise ApiError(403, "EMAIL_NOT_VERIFIED")
    return current
