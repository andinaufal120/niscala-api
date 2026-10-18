"""Starting, refreshing and ending sessions, and issuing their tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import UserAccount, UserSession
from app.schemas.auth import AuthTokens, DeviceInfo
from app.schemas.sessions import LoginMethod

ACCESS_TOKEN_LIFETIME = timedelta(seconds=900)
SESSION_IDLE_LIMIT = timedelta(days=90)
SESSION_MAX_AGE = timedelta(days=365)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_tokens(user_id: UUID, session: UserSession) -> AuthTokens:
    """Make an access token and a new refresh token, storing the refresh hash."""
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "sid": str(session.id),
        "iat": now,
        "exp": now + ACCESS_TOKEN_LIFETIME,
    }
    refresh_token = secrets.token_urlsafe(32)
    session.previous_refresh_token_hash = session.refresh_token_hash
    session.refresh_token_hash = _hash(refresh_token)
    return AuthTokens(
        access_token=jwt.encode(claims, get_settings().jwt_secret, "HS256"),
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
    )


def start_session(
    db: Session, user: UserAccount, device: DeviceInfo, login_method: LoginMethod
) -> AuthTokens:
    """Create a session for the user and return its tokens; flushes, never commits."""
    session = UserSession(
        id=uuid4(),
        user_id=user.id,
        refresh_token_hash="",
        device_name=device.name,
        platform=device.platform,
        login_method=login_method,
    )
    tokens = _issue_tokens(user.id, session)
    session.previous_refresh_token_hash = None
    db.add(session)
    db.flush()
    return tokens


def end_session(db: Session, session: UserSession) -> None:
    """Revoke the session unless it already is."""
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        db.flush()


def _fail_and_end(db: Session, session: UserSession) -> ApiError:
    """End the session and commit it, because the request will answer 401."""
    end_session(db, session)
    db.commit()
    return ApiError(401, "REFRESH_TOKEN_INVALID")


def refresh_session(db: Session, refresh_token: str) -> AuthTokens:
    """Rotate the refresh token of its session and return a new token pair.

    Raises 401 REFRESH_TOKEN_INVALID for an unknown token or a revoked session.
    Presenting an already rotated token, an idle session or an expired session
    ends the session, and that revocation is committed before raising.
    """
    token_hash = _hash(refresh_token)
    session = db.scalars(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    ).one_or_none()
    if session is None:
        reused = db.scalars(
            select(UserSession).where(
                UserSession.previous_refresh_token_hash == token_hash
            )
        ).one_or_none()
        if reused is None:
            raise ApiError(401, "REFRESH_TOKEN_INVALID")
        raise _fail_and_end(db, reused)
    if session.revoked_at is not None:
        raise ApiError(401, "REFRESH_TOKEN_INVALID")
    now = datetime.now(UTC)
    if (
        now - session.last_active_at > SESSION_IDLE_LIMIT
        or now - session.created_at > SESSION_MAX_AGE
    ):
        raise _fail_and_end(db, session)
    session.last_active_at = now
    return _issue_tokens(session.user_id, session)
