"""Starting, refreshing and ending sessions, and issuing their tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import UsedRefreshToken, UserAccount, UserSession
from app.schemas.auth import AuthTokens, DeviceInfo
from app.schemas.sessions import LoginMethod, SessionList
from app.schemas.sessions import Session as SessionSchema
from app.security import CurrentUser

ACCESS_TOKEN_LIFETIME = timedelta(seconds=900)
SESSION_IDLE_LIMIT = timedelta(days=90)
SESSION_MAX_AGE = timedelta(days=365)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_tokens(db: Session, user_id: UUID, session: UserSession) -> AuthTokens:
    """Make an access token and a new refresh token, storing the refresh hash.

    The token being replaced, if any, is recorded as used.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "sid": str(session.id),
        "iat": now,
        "exp": now + ACCESS_TOKEN_LIFETIME,
    }
    refresh_token = secrets.token_urlsafe(32)
    if session.refresh_token_hash:
        db.add(
            UsedRefreshToken(
                token_hash=session.refresh_token_hash,
                session_id=session.id,
                rotated_at=now,
            )
        )
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
    tokens = _issue_tokens(db, user.id, session)
    db.add(session)
    db.flush()
    return tokens


def end_session(db: Session, session: UserSession) -> None:
    """Revoke the session unless it already is, and forget its used refresh tokens."""
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
    db.execute(
        delete(UsedRefreshToken).where(UsedRefreshToken.session_id == session.id)
    )
    db.flush()


def end_all_sessions(db: Session, user_id: UUID) -> None:
    """Revoke every session of the user that is not revoked yet."""
    open_sessions = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
    ).all()
    for session in open_sessions:
        end_session(db, session)


def _active_sessions_of(user_id: UUID) -> Select[tuple[UserSession]]:
    """Select the user's sessions that are not revoked, idle too long or too old."""
    now = datetime.now(UTC)
    return select(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.last_active_at >= now - SESSION_IDLE_LIMIT,
        UserSession.created_at >= now - SESSION_MAX_AGE,
    )


def has_other_active_sessions(db: Session, current: CurrentUser) -> bool:
    """Return whether the caller has an active session besides the current one."""
    return (
        db.scalars(
            _active_sessions_of(current.user.id)
            .where(UserSession.id != current.session.id)
            .limit(1)
        ).first()
        is not None
    )


def list_sessions(db: Session, current: CurrentUser) -> SessionList:
    """List the caller's active sessions, most recently active first."""
    rows = db.scalars(
        _active_sessions_of(current.user.id).order_by(
            UserSession.last_active_at.desc(), UserSession.id
        )
    )
    return SessionList(
        items=[
            SessionSchema(
                id=row.id,
                device_name=row.device_name,
                platform=row.platform,
                login_method=row.login_method,
                last_active_at=row.last_active_at,
                is_current=row.id == current.session.id,
            )
            for row in rows
        ]
    )


def end_other_session(db: Session, current: CurrentUser, session_id: UUID) -> None:
    """End one of the caller's active sessions other than the current one.

    Raises 404 SESSION_NOT_FOUND when the caller has no such active session and
    409 SESSION_IS_CURRENT when it is the session making the request.
    """
    session = db.scalars(
        _active_sessions_of(current.user.id).where(UserSession.id == session_id)
    ).one_or_none()
    if session is None:
        raise ApiError(404, "SESSION_NOT_FOUND")
    if session.id == current.session.id:
        raise ApiError(409, "SESSION_IS_CURRENT")
    end_session(db, session)


def end_other_sessions(db: Session, current: CurrentUser) -> None:
    """End every active session of the caller except the current one."""
    others = db.scalars(
        _active_sessions_of(current.user.id).where(UserSession.id != current.session.id)
    ).all()
    for session in others:
        end_session(db, session)


def _fail_and_end(db: Session, session: UserSession) -> ApiError:
    """End the session and commit it, because the request will answer 401."""
    end_session(db, session)
    db.commit()
    return ApiError(401, "REFRESH_TOKEN_INVALID")


def refresh_session(db: Session, refresh_token: str) -> AuthTokens:
    """Rotate the refresh token of its session and return a new token pair.

    Raises 401 REFRESH_TOKEN_INVALID for an unknown token or a revoked session.
    Presenting any token the session has rotated away from, an idle session or an expired session
    ends the session, and that revocation is committed before raising.
    """
    token_hash = _hash(refresh_token)
    session = db.scalars(
        select(UserSession)
        .where(UserSession.refresh_token_hash == token_hash)
        .with_for_update()
    ).one_or_none()
    if session is None:
        used = db.get(UsedRefreshToken, token_hash)
        if used is None:
            raise ApiError(401, "REFRESH_TOKEN_INVALID")
        reused = db.get(UserSession, used.session_id, with_for_update=True)
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
    return _issue_tokens(db, session.user_id, session)
