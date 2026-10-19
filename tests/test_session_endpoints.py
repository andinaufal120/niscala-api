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


def used_hashes(database, session_id) -> set[str]:
    from sqlalchemy import select

    from app.models import UsedRefreshToken

    with Session(database) as db:
        return set(
            db.scalars(
                select(UsedRefreshToken.token_hash).where(
                    UsedRefreshToken.session_id == session_id
                )
            )
        )


def rotate(client, first_token: str, times: int) -> list[str]:
    """Refresh `times` in a row and return every token, oldest first."""
    tokens = [first_token]
    for _ in range(times):
        response = refresh(client, tokens[-1])
        assert response.status_code == 200
        tokens.append(response.json()["refreshToken"])
    return tokens


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


def test_refresh_stores_the_new_hash_and_records_the_old_one_as_used(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    old = signed_in.tokens.refresh_token
    new = refresh(client, old).json()["refreshToken"]
    row = read_session(signed_in.session_id)
    assert row.refresh_token_hash == sha256(new)
    assert used_hashes(database, signed_in.session_id) == {sha256(old)}
    assert row.revoked_at is None


def test_every_rotated_token_is_recorded_and_the_current_one_is_not(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 4)
    assert used_hashes(database, signed_in.session_id) == {
        sha256(token) for token in tokens[:-1]
    }
    assert read_session(signed_in.session_id).refresh_token_hash == sha256(tokens[-1])


def test_rotation_stamps_the_time_it_was_recorded(client, database, make_user, sign_in):
    from sqlalchemy import select

    from app.models import UsedRefreshToken

    signed_in = sign_in(make_user())
    refresh(client, signed_in.tokens.refresh_token)
    with Session(database) as db:
        row = db.scalars(select(UsedRefreshToken)).one()
    assert row.token_hash == sha256(signed_in.tokens.refresh_token)
    assert row.session_id == signed_in.session_id
    assert row.rotated_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - row.rotated_at) < timedelta(minutes=1)


def test_rotation_records_used_tokens_only_for_its_own_session(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    rotate(client, phone.tokens.refresh_token, 2)
    assert len(used_hashes(database, phone.session_id)) == 2
    assert used_hashes(database, tablet.session_id) == set()


def test_failed_refreshes_record_no_used_tokens(client, database, make_user, sign_in):
    signed_in = sign_in(make_user())
    refresh(client, "no-such-token")
    assert used_hashes(database, signed_in.session_id) == set()


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


def test_reusing_a_token_from_three_rotations_back_is_rejected_and_ends_the_session(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    assert_refresh_rejected(refresh(client, tokens[0]))
    assert read_session(signed_in.session_id).revoked_at is not None


def test_reusing_any_earlier_token_of_a_long_family_ends_the_session(
    client, make_user, sign_in, read_session
):
    for position in (0, 1, 3, 4):
        signed_in = sign_in(make_user())
        tokens = rotate(client, signed_in.tokens.refresh_token, 5)
        assert_refresh_rejected(refresh(client, tokens[position]))
        assert read_session(signed_in.session_id).revoked_at is not None


def test_reusing_an_old_token_kills_the_newest_refresh_token(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    refresh(client, tokens[0])
    assert_refresh_rejected(refresh(client, tokens[-1]))


def test_reusing_an_old_token_kills_the_sessions_access_tokens(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    refresh(client, tokens[0])
    assert_access_rejected(client.get(ME_URL, headers=signed_in.headers))


def test_reusing_the_immediately_previous_token_still_ends_the_session(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    assert_refresh_rejected(refresh(client, tokens[-2]))
    assert read_session(signed_in.session_id).revoked_at is not None
    assert_refresh_rejected(refresh(client, tokens[-1]))


def test_using_the_same_token_twice_in_a_row_ends_the_session_on_the_second_use(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    token = signed_in.tokens.refresh_token
    first = refresh(client, token)
    assert first.status_code == 200
    assert read_session(signed_in.session_id).revoked_at is None
    assert_refresh_rejected(refresh(client, token))
    assert read_session(signed_in.session_id).revoked_at is not None
    assert_refresh_rejected(refresh(client, first.json()["refreshToken"]))


def test_reuse_detection_does_not_touch_another_users_session(
    client, make_user, sign_in
):
    first, second = sign_in(make_user()), sign_in(make_user())
    tokens = rotate(client, first.tokens.refresh_token, 3)
    rotate(client, second.tokens.refresh_token, 1)
    refresh(client, tokens[0])
    assert client.get(ME_URL, headers=second.headers).status_code == 200


def test_replaying_a_token_of_an_already_revoked_session_is_rejected(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 2)
    client.post(LOGOUT_URL, headers=signed_in.headers)
    revoked_at = read_session(signed_in.session_id).revoked_at
    assert_refresh_rejected(refresh(client, tokens[0]))
    assert read_session(signed_in.session_id).revoked_at == revoked_at


def test_concurrent_refreshes_with_one_token_give_exactly_one_success(
    app, database, make_user, sign_in, read_session
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient

    signed_in = sign_in(make_user())
    token = signed_in.tokens.refresh_token
    workers = 4
    barrier = Barrier(workers)

    def attempt(_):
        barrier.wait()
        return refresh(TestClient(app), token)

    with ThreadPoolExecutor(workers) as pool:
        responses = list(pool.map(attempt, range(workers)))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] + [401] * (workers - 1)
    for response in responses:
        if response.status_code == 401:
            assert_refresh_rejected(response)
    winner = next(r for r in responses if r.status_code == 200).json()
    assert read_session(signed_in.session_id).revoked_at is not None
    assert_refresh_rejected(refresh(TestClient(app), winner["refreshToken"]))
    assert_access_rejected(
        TestClient(app).get(
            ME_URL, headers={"Authorization": f"Bearer {winner['accessToken']}"}
        )
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


def test_unknown_refresh_token_leaves_a_rotated_session_alive_and_unchanged(
    client, database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    before_hash = read_session(signed_in.session_id).refresh_token_hash
    before_used = used_hashes(database, signed_in.session_id)
    assert_refresh_rejected(refresh(client, "no-such-token"))
    row = read_session(signed_in.session_id)
    assert row.revoked_at is None
    assert row.refresh_token_hash == before_hash
    assert used_hashes(database, signed_in.session_id) == before_used
    assert refresh(client, tokens[-1]).status_code == 200


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
    assert used_hashes(database, signed_in.session_id) == set()


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


# Used refresh tokens are dropped when their session ends


def test_logout_deletes_the_sessions_used_tokens(client, database, make_user, sign_in):
    signed_in = sign_in(make_user())
    rotate(client, signed_in.tokens.refresh_token, 3)
    assert len(used_hashes(database, signed_in.session_id)) == 3
    client.post(LOGOUT_URL, headers=signed_in.headers)
    assert used_hashes(database, signed_in.session_id) == set()


def test_logout_keeps_the_used_tokens_of_other_sessions(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    rotate(client, phone.tokens.refresh_token, 2)
    latest = rotate(client, tablet.tokens.refresh_token, 2)[-1]
    access_token = refresh(client, latest).json()["accessToken"]
    client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {access_token}"})
    assert used_hashes(database, tablet.session_id) == set()
    assert len(used_hashes(database, phone.session_id)) == 2


def test_reuse_deletes_the_sessions_used_tokens(client, database, make_user, sign_in):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 3)
    refresh(client, tokens[0])
    assert used_hashes(database, signed_in.session_id) == set()


def test_reuse_keeps_the_used_tokens_of_other_sessions(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    tokens = rotate(client, phone.tokens.refresh_token, 2)
    rotate(client, tablet.tokens.refresh_token, 2)
    refresh(client, tokens[0])
    assert len(used_hashes(database, tablet.session_id)) == 2


def test_idle_session_failure_deletes_the_sessions_used_tokens(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 2)
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(91))
    assert_refresh_rejected(refresh(client, tokens[-1]))
    assert used_hashes(database, signed_in.session_id) == set()


def test_expired_session_failure_deletes_the_sessions_used_tokens(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 2)
    set_session_columns(database, signed_in.session_id, created_at=days_ago(366))
    assert_refresh_rejected(refresh(client, tokens[-1]))
    assert used_hashes(database, signed_in.session_id) == set()


def test_replay_after_the_session_failed_its_limits_is_still_rejected(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    tokens = rotate(client, signed_in.tokens.refresh_token, 2)
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(91))
    refresh(client, tokens[-1])
    assert_refresh_rejected(refresh(client, tokens[0]))
    assert_refresh_rejected(refresh(client, tokens[-1]))


def test_end_session_deletes_the_sessions_used_tokens_and_revokes_it(
    client, database, make_user, sign_in, read_session
):
    from app.models import UserSession
    from app.services.sessions import end_session

    signed_in = sign_in(make_user())
    other = sign_in(make_user())
    rotate(client, signed_in.tokens.refresh_token, 3)
    rotate(client, other.tokens.refresh_token, 1)
    with Session(database) as db:
        end_session(db, db.get(UserSession, signed_in.session_id))
        db.commit()
    assert read_session(signed_in.session_id).revoked_at is not None
    assert used_hashes(database, signed_in.session_id) == set()
    assert len(used_hashes(database, other.session_id)) == 1


def test_end_session_on_a_session_without_used_tokens_succeeds(
    database, make_user, sign_in, read_session
):
    from app.models import UserSession
    from app.services.sessions import end_session

    signed_in = sign_in(make_user())
    with Session(database) as db:
        end_session(db, db.get(UserSession, signed_in.session_id))
        db.commit()
    assert read_session(signed_in.session_id).revoked_at is not None
