"""Starting a session stores it and returns an access and a refresh token."""

import base64
import hashlib
from datetime import timedelta
from uuid import UUID

import jwt
from sqlalchemy import select


def device(name: str = "Pixel 8", platform: str = "Android 14"):
    from app.schemas.auth import DeviceInfo

    return DeviceInfo(name=name, platform=platform)


def start(db_session, user, *, method=None, **device_fields):
    from app.schemas.sessions import LoginMethod

    login_method = method or LoginMethod.PASSWORD
    from app.services.sessions import start_session

    return start_session(db_session, user, device(**device_fields), login_method)


def claims_of(tokens) -> dict:
    from app.config import get_settings

    return jwt.decode(
        tokens.access_token, get_settings().jwt_secret, algorithms=["HS256"]
    )


def stored_sessions(db_session, user):
    from app.models import UserSession

    return db_session.scalars(
        select(UserSession).where(UserSession.user_id == user.id)
    ).all()


def test_start_session_returns_a_bearer_token_pair(db_session, make_user):
    tokens = start(db_session, make_user())
    assert tokens.token_type == "bearer"
    assert tokens.expires_in == 900
    assert tokens.access_token
    assert tokens.refresh_token


def test_start_session_inserts_one_row_with_the_device_and_login_method(
    db_session, make_user
):
    from app.schemas.sessions import LoginMethod

    user = make_user()
    start(
        db_session,
        user,
        method=LoginMethod.GOOGLE,
        name="Galaxy S24",
        platform="Android 15",
    )
    (row,) = stored_sessions(db_session, user)
    assert row.device_name == "Galaxy S24"
    assert row.platform == "Android 15"
    assert row.login_method == LoginMethod.GOOGLE
    assert row.revoked_at is None


def test_start_session_records_no_used_refresh_token(db_session, make_user):
    from app.models import UsedRefreshToken

    start(db_session, make_user())
    assert db_session.scalars(select(UsedRefreshToken)).all() == []


def test_start_session_records_the_password_login_method(db_session, make_user):
    from app.schemas.sessions import LoginMethod

    user = make_user()
    start(db_session, user, method=LoginMethod.PASSWORD)
    (row,) = stored_sessions(db_session, user)
    assert row.login_method == LoginMethod.PASSWORD


def test_start_session_last_active_matches_creation_time(db_session, make_user):
    user = make_user()
    start(db_session, user)
    (row,) = stored_sessions(db_session, user)
    assert abs(row.last_active_at - row.created_at) < timedelta(seconds=5)


def test_start_session_flushes_without_committing(db_session, make_user, database):
    from sqlalchemy.orm import Session

    from app.models import UserSession

    user = make_user()
    tokens = start(db_session, user)
    session_id = UUID(claims_of(tokens)["sid"])
    assert db_session.get(UserSession, session_id) is not None
    with Session(database) as other:
        assert other.get(UserSession, session_id) is None


def test_access_token_is_an_hs256_jwt_signed_with_the_configured_secret(
    db_session, make_user
):
    tokens = start(db_session, make_user())
    assert jwt.get_unverified_header(tokens.access_token)["alg"] == "HS256"
    claims_of(tokens)


def test_access_token_carries_user_id_and_session_id(db_session, make_user):
    user = make_user()
    tokens = start(db_session, user)
    (row,) = stored_sessions(db_session, user)
    claims = claims_of(tokens)
    assert claims["sub"] == str(user.id)
    assert claims["sid"] == str(row.id)


def test_access_token_lives_for_900_seconds(db_session, make_user):
    claims = claims_of(start(db_session, make_user()))
    assert claims["exp"] - claims["iat"] == 900


def test_access_token_is_issued_now(db_session, make_user):
    import time

    claims = claims_of(start(db_session, make_user()))
    assert abs(claims["iat"] - time.time()) < 30


def test_refresh_token_is_stored_only_as_a_sha256_hex_digest(db_session, make_user):
    user = make_user()
    tokens = start(db_session, user)
    (row,) = stored_sessions(db_session, user)
    expected = hashlib.sha256(tokens.refresh_token.encode()).hexdigest()
    assert row.refresh_token_hash == expected
    assert row.refresh_token_hash != tokens.refresh_token


def test_refresh_token_is_opaque_and_has_at_least_32_bytes_of_randomness(
    db_session, make_user
):
    tokens = start(db_session, make_user())
    token = tokens.refresh_token
    assert token.count(".") != 2
    padded = token + "=" * (-len(token) % 4)
    assert len(base64.urlsafe_b64decode(padded)) >= 32


def test_two_sessions_of_one_user_are_independent(db_session, make_user):
    user = make_user()
    first = start(db_session, user, name="Phone")
    second = start(db_session, user, name="Tablet")
    assert first.refresh_token != second.refresh_token
    assert first.access_token != second.access_token
    assert claims_of(first)["sid"] != claims_of(second)["sid"]
    assert claims_of(first)["sub"] == claims_of(second)["sub"]


def test_a_user_can_have_several_sessions(db_session, make_user):
    user = make_user()
    for _ in range(3):
        start(db_session, user)
    assert len(stored_sessions(db_session, user)) == 3


def test_sessions_of_different_users_belong_to_their_own_user(db_session, make_user):
    first, second = make_user(), make_user()
    start(db_session, first)
    start(db_session, second)
    assert len(stored_sessions(db_session, first)) == 1
    assert len(stored_sessions(db_session, second)) == 1
