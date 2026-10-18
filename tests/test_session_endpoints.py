"""Reading the account, logging out and refreshing tokens."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

ME_URL = "/me"
LOGOUT_URL = "/auth/logout"
REFRESH_URL = "/auth/refresh"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def refresh(client, token: str, **kwargs):
    return client.post(REFRESH_URL, json={"refreshToken": token}, **kwargs)


def set_session_columns(database, session_id, **columns) -> None:
    from app.models import UserSession

    with Session(database) as db:
        row = db.get(UserSession, session_id)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def assert_access_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def assert_refresh_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "REFRESH_TOKEN_INVALID"
    assert body["field"] is None
    assert body["message"]


def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# GET /me


def test_me_returns_the_callers_account(client, make_user, sign_in):
    user = make_user(
        name="Rina Owner",
        email="rina@example.com",
        password_hash="hash",
        email_verified=True,
    )
    response = client.get(ME_URL, headers=sign_in(user).headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "name": "Rina Owner",
        "email": "rina@example.com",
        "role": "owner",
        "emailVerified": True,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_me_reports_no_password_when_the_account_has_none(client, make_user, sign_in):
    user = make_user(password_hash=None)
    body = client.get(ME_URL, headers=sign_in(user).headers).json()
    assert body["hasPassword"] is False


def test_me_reports_an_unverified_email(client, make_user, sign_in):
    user = make_user(email_verified=False)
    body = client.get(ME_URL, headers=sign_in(user).headers).json()
    assert body["emailVerified"] is False


@pytest.mark.parametrize("role", ["tenant", "owner", "manager", "admin"])
def test_me_reports_the_role_as_its_code_name(client, make_user, sign_in, role):
    from app.schemas.auth import UserRole

    user = make_user(role=UserRole(role))
    body = client.get(ME_URL, headers=sign_in(user).headers).json()
    assert body["role"] == role


def test_me_returns_the_account_of_the_token_not_another_user(
    client, make_user, sign_in
):
    first, second = make_user(name="First"), make_user(name="Second")
    sign_in(first)
    body = client.get(ME_URL, headers=sign_in(second).headers).json()
    assert body["id"] == str(second.id)
    assert body["name"] == "Second"


def test_me_without_a_token_is_rejected(client, database):
    assert_access_rejected(client.get(ME_URL))


def test_me_with_a_malformed_token_is_rejected(client, database):
    response = client.get(ME_URL, headers={"Authorization": "Bearer garbage"})
    assert_access_rejected(response)


# POST /auth/logout


def test_logout_responds_with_an_empty_204(client, make_user, sign_in):
    response = client.post(LOGOUT_URL, headers=sign_in(make_user()).headers)
    assert response.status_code == 204
    assert response.content == b""


def test_logout_revokes_the_callers_session(client, make_user, sign_in, read_session):
    signed_in = sign_in(make_user())
    assert read_session(signed_in.session_id).revoked_at is None
    client.post(LOGOUT_URL, headers=signed_in.headers)
    revoked_at = read_session(signed_in.session_id).revoked_at
    assert revoked_at is not None
    assert abs(datetime.now(UTC) - revoked_at) < timedelta(minutes=1)


def test_access_token_stops_working_after_logout(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    client.post(LOGOUT_URL, headers=signed_in.headers)
    assert_access_rejected(client.get(ME_URL, headers=signed_in.headers))


def test_refresh_token_stops_working_after_logout(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    client.post(LOGOUT_URL, headers=signed_in.headers)
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))


def test_second_logout_with_the_same_token_is_rejected(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    assert client.post(LOGOUT_URL, headers=signed_in.headers).status_code == 204
    assert_access_rejected(client.post(LOGOUT_URL, headers=signed_in.headers))


def test_logout_leaves_the_users_other_sessions_working(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.post(LOGOUT_URL, headers=phone.headers)
    assert client.get(ME_URL, headers=tablet.headers).status_code == 200
    assert read_session(tablet.session_id).revoked_at is None
    assert refresh(client, tablet.tokens.refresh_token).status_code == 200


def test_logout_leaves_other_users_sessions_working(
    client, make_user, sign_in, read_session
):
    first, second = sign_in(make_user()), sign_in(make_user())
    client.post(LOGOUT_URL, headers=first.headers)
    assert client.get(ME_URL, headers=second.headers).status_code == 200
    assert read_session(second.session_id).revoked_at is None


def test_logout_without_a_token_is_rejected(client, database):
    assert_access_rejected(client.post(LOGOUT_URL))


# POST /auth/refresh


def test_refresh_returns_a_new_token_pair(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    response = refresh(client, signed_in.tokens.refresh_token)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"accessToken", "refreshToken", "tokenType", "expiresIn"}
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 900
    assert body["refreshToken"] != signed_in.tokens.refresh_token
    assert body["accessToken"]


def test_refresh_works_without_an_authorization_header(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    assert "Authorization" not in client.headers
    assert refresh(client, signed_in.tokens.refresh_token).status_code == 200


def test_refresh_with_a_valid_bearer_header_is_also_fine(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    response = refresh(
        client, signed_in.tokens.refresh_token, headers=signed_in.headers
    )
    assert response.status_code == 200


def test_new_access_token_works_on_me(client, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    new = refresh(client, signed_in.tokens.refresh_token).json()
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {new['accessToken']}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_new_access_token_belongs_to_the_same_session(client, make_user, sign_in):
    import jwt

    signed_in = sign_in(make_user())
    new = refresh(client, signed_in.tokens.refresh_token).json()
    claims = jwt.decode(new["accessToken"], options={"verify_signature": False})
    assert claims["sid"] == str(signed_in.session_id)
    assert claims["exp"] - claims["iat"] == 900


def test_access_token_from_before_the_refresh_keeps_working(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    refresh(client, signed_in.tokens.refresh_token)
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200


def test_refresh_stores_the_new_hash_and_keeps_the_previous_one(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    old = signed_in.tokens.refresh_token
    new = refresh(client, old).json()["refreshToken"]
    row = read_session(signed_in.session_id)
    assert row.refresh_token_hash == sha256(new)
    assert row.previous_refresh_token_hash == sha256(old)
    assert row.revoked_at is None


def test_refresh_sets_last_active_to_now_and_keeps_created_at(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    created_at = read_session(signed_in.session_id).created_at
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(10))
    refresh(client, signed_in.tokens.refresh_token)
    row = read_session(signed_in.session_id)
    assert abs(datetime.now(UTC) - row.last_active_at) < timedelta(minutes=1)
    assert row.created_at == created_at


def test_refreshed_token_can_be_refreshed_again(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    second = refresh(client, signed_in.tokens.refresh_token).json()["refreshToken"]
    third = refresh(client, second)
    assert third.status_code == 200
    assert third.json()["refreshToken"] not in {
        second,
        signed_in.tokens.refresh_token,
    }


def test_presented_refresh_token_stops_working_at_once(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    refresh(client, signed_in.tokens.refresh_token)
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))


def test_reusing_a_rotated_refresh_token_ends_the_session(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    refresh(client, signed_in.tokens.refresh_token)
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))
    assert read_session(signed_in.session_id).revoked_at is not None


def test_reusing_a_rotated_refresh_token_kills_the_newer_refresh_token(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    newer = refresh(client, signed_in.tokens.refresh_token).json()["refreshToken"]
    refresh(client, signed_in.tokens.refresh_token)
    assert_refresh_rejected(refresh(client, newer))


def test_reusing_a_rotated_refresh_token_kills_the_sessions_access_tokens(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    newer = refresh(client, signed_in.tokens.refresh_token).json()
    refresh(client, signed_in.tokens.refresh_token)
    assert_access_rejected(client.get(ME_URL, headers=signed_in.headers))
    assert_access_rejected(
        client.get(ME_URL, headers={"Authorization": f"Bearer {newer['accessToken']}"})
    )


def test_reusing_a_rotated_refresh_token_leaves_other_sessions_working(
    client, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    refresh(client, phone.tokens.refresh_token)
    refresh(client, phone.tokens.refresh_token)
    assert client.get(ME_URL, headers=tablet.headers).status_code == 200
    assert refresh(client, tablet.tokens.refresh_token).status_code == 200


def test_unknown_refresh_token_is_rejected(client, database):
    assert_refresh_rejected(refresh(client, "no-such-token"))


def test_unknown_refresh_token_does_not_end_any_session(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    refresh(client, "no-such-token")
    assert read_session(signed_in.session_id).revoked_at is None
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200


def test_access_token_is_not_accepted_as_a_refresh_token(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    assert_refresh_rejected(refresh(client, signed_in.tokens.access_token))


def test_refresh_token_of_a_revoked_session_is_rejected(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, revoked_at=datetime.now(UTC))
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))


def test_refresh_token_of_a_revoked_session_does_not_issue_a_new_token(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, revoked_at=datetime.now(UTC))
    refresh(client, signed_in.tokens.refresh_token)
    row = read_session(signed_in.session_id)
    assert row.refresh_token_hash == sha256(signed_in.tokens.refresh_token)
    assert row.previous_refresh_token_hash is None


def test_session_idle_for_89_days_can_still_refresh(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(89))
    assert refresh(client, signed_in.tokens.refresh_token).status_code == 200


def test_session_idle_for_91_days_is_rejected(client, database, make_user, sign_in):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(91))
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))


def test_idle_session_is_ended_and_the_revocation_is_persisted(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(91))
    refresh(client, signed_in.tokens.refresh_token)
    assert read_session(signed_in.session_id).revoked_at is not None
    assert_access_rejected(client.get(ME_URL, headers=signed_in.headers))


def test_session_created_364_days_ago_can_still_refresh(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, created_at=days_ago(364))
    assert refresh(client, signed_in.tokens.refresh_token).status_code == 200


def test_session_older_than_a_year_is_rejected_even_when_recently_active(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_session_columns(
        database,
        signed_in.session_id,
        created_at=days_ago(366),
        last_active_at=datetime.now(UTC),
    )
    assert_refresh_rejected(refresh(client, signed_in.tokens.refresh_token))


def test_session_older_than_a_year_is_ended_and_the_revocation_is_persisted(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, created_at=days_ago(366))
    refresh(client, signed_in.tokens.refresh_token)
    assert read_session(signed_in.session_id).revoked_at is not None
    assert_access_rejected(client.get(ME_URL, headers=signed_in.headers))


def test_refreshing_never_extends_the_one_year_cap(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    set_session_columns(database, signed_in.session_id, created_at=days_ago(364))
    created_at = read_session(signed_in.session_id).created_at
    token = refresh(client, signed_in.tokens.refresh_token).json()["refreshToken"]
    assert read_session(signed_in.session_id).created_at == created_at
    set_session_columns(database, signed_in.session_id, created_at=days_ago(366))
    assert_refresh_rejected(refresh(client, token))


def test_failed_refresh_for_an_expired_session_leaves_other_sessions_working(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, phone.session_id, last_active_at=days_ago(91))
    refresh(client, phone.tokens.refresh_token)
    assert client.get(ME_URL, headers=tablet.headers).status_code == 200


@pytest.mark.parametrize("token", ["", None, 5])
def test_refresh_with_an_invalid_token_value_is_a_validation_failure(
    client, database, token
):
    response = client.post(REFRESH_URL, json={"refreshToken": token})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "refreshToken"


def test_refresh_without_a_body_field_is_a_validation_failure(client, database):
    response = client.post(REFRESH_URL, json={})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "refreshToken"
