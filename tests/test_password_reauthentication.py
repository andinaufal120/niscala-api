"""Confirming the caller's identity again with their password."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

URL = "/me/reauthentication/password"
GOOGLE_URL = "/me/reauthentication/google"
LOGIN_URL = "/auth/login"
EMAIL = "rina@example.com"
PASSWORD = "correct horse battery"
WRONG = "wrong password"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
WINDOW = timedelta(minutes=5)
LOCK_SECONDS = 15 * 60


def reauthenticate(client, headers, password: str = PASSWORD):
    return client.post(URL, json={"password": password}, headers=headers)


def login(client, password: str = PASSWORD):
    body = {"email": EMAIL, "password": password, "device": DEVICE}
    return client.post(LOGIN_URL, json=body)


def read_failure(database, email: str = EMAIL):
    from app.models import LoginFailure

    with Session(database, expire_on_commit=False) as db:
        return db.get(LoginFailure, email)


def set_failure(database, email: str = EMAIL, **columns) -> None:
    from app.models import LoginFailure

    with Session(database) as db:
        row = db.get(LoginFailure, email)
        if row is None:
            db.add(LoginFailure(email=email, **columns))
        else:
            for name, value in columns.items():
                setattr(row, name, value)
        db.commit()


def set_reauthenticated_at(database, session_id, value) -> None:
    from app.models import UserSession

    with Session(database) as db:
        db.get(UserSession, session_id).reauthenticated_at = value
        db.commit()


def assert_locked(response) -> None:
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert body["field"] is None
    assert body["message"]
    assert 1 <= int(response.headers["Retry-After"]) <= LOCK_SECONDS


def assert_password_incorrect(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PASSWORD_INCORRECT"
    assert body["field"] == "password"
    assert body["message"]


def assert_access_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def recent_reauthentication_status(headers) -> int:
    from typing import Annotated

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app.access import require_recent_reauthentication
    from app.errors import register_error_handlers
    from app.security import CurrentUser

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/sensitive")
    def sensitive(
        current: Annotated[CurrentUser, Depends(require_recent_reauthentication)],
    ):
        return {}

    return TestClient(private).get("/sensitive", headers=headers).status_code


@pytest.fixture
def owner(make_user):
    from app.services.passwords import hash_password

    return make_user(email=EMAIL, password_hash=hash_password(PASSWORD))


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


# Success


def test_the_right_password_answers_with_the_end_of_the_window(
    client, database, signed_in, read_session
):
    before = datetime.now(UTC)
    response = reauthenticate(client, signed_in.headers)
    after = datetime.now(UTC)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"reauthenticatedUntil"}
    assert body["reauthenticatedUntil"].endswith("Z")
    until = datetime.fromisoformat(body["reauthenticatedUntil"])
    assert until.utcoffset() == timedelta(0)
    assert before + WINDOW - timedelta(seconds=1) <= until
    assert until <= after + WINDOW + timedelta(seconds=1)


def test_the_current_session_records_the_moment_of_re_authentication(
    client, database, signed_in, read_session
):
    before = datetime.now(UTC)
    response = reauthenticate(client, signed_in.headers)
    after = datetime.now(UTC)
    stored = read_session(signed_in.session_id).reauthenticated_at
    assert before <= stored <= after
    until = datetime.fromisoformat(response.json()["reauthenticatedUntil"])
    assert abs(until - (stored + WINDOW)) <= timedelta(seconds=1)


def test_other_sessions_of_the_user_are_untouched(
    client, database, owner, sign_in, read_session
):
    current = sign_in(owner)
    other = sign_in(owner, device_name="Galaxy")
    assert reauthenticate(client, current.headers).status_code == 200
    assert read_session(current.session_id).reauthenticated_at is not None
    assert read_session(other.session_id).reauthenticated_at is None
    assert recent_reauthentication_status(current.headers) == 200
    assert recent_reauthentication_status(other.headers) == 403


def test_other_users_sessions_are_untouched(
    client, database, signed_in, make_user, sign_in, read_session
):
    stranger = sign_in(make_user(email="budi@example.com"))
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_session(stranger.session_id).reauthenticated_at is None


def test_the_session_passes_the_recent_re_authentication_guard_afterwards(
    client, database, signed_in
):
    assert recent_reauthentication_status(signed_in.headers) == 403
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert recent_reauthentication_status(signed_in.headers) == 200


def test_the_guard_stops_passing_five_minutes_after_re_authentication(
    client, database, signed_in
):
    assert reauthenticate(client, signed_in.headers).status_code == 200
    set_reauthenticated_at(
        database,
        signed_in.session_id,
        datetime.now(UTC) - WINDOW - timedelta(seconds=1),
    )
    assert recent_reauthentication_status(signed_in.headers) == 403


def test_re_authenticating_again_refreshes_the_time(
    client, database, signed_in, read_session
):
    old = datetime.now(UTC) - timedelta(minutes=4)
    set_reauthenticated_at(database, signed_in.session_id, old)
    response = reauthenticate(client, signed_in.headers)
    assert response.status_code == 200
    stored = read_session(signed_in.session_id).reauthenticated_at
    assert stored > old + timedelta(minutes=3)
    until = datetime.fromisoformat(response.json()["reauthenticatedUntil"])
    assert until > old + WINDOW + timedelta(minutes=3)


def test_re_authenticating_after_the_window_lapsed_opens_it_again(
    client, database, signed_in
):
    set_reauthenticated_at(
        database, signed_in.session_id, datetime.now(UTC) - timedelta(hours=1)
    )
    assert recent_reauthentication_status(signed_in.headers) == 403
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert recent_reauthentication_status(signed_in.headers) == 200


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_with_a_password_can_re_authenticate(
    client, database, make_user, sign_in, read_session, role
):
    from app.schemas.auth import UserRole
    from app.services.passwords import hash_password

    user = make_user(
        email="role@example.com",
        password_hash=hash_password(PASSWORD),
        role=UserRole(role),
    )
    session = sign_in(user)
    assert reauthenticate(client, session.headers).status_code == 200
    assert read_session(session.session_id).reauthenticated_at is not None


@pytest.mark.parametrize("password", ["a very long password " * 10, " ", " padded "])
def test_the_password_is_compared_untrimmed_and_unbounded(
    client, database, make_user, sign_in, password
):
    from app.services.passwords import hash_password

    user = make_user(email="odd@example.com", password_hash=hash_password(password))
    session = sign_in(user)
    assert reauthenticate(client, session.headers, password).status_code == 200


def test_a_password_differing_only_by_surrounding_spaces_is_incorrect(
    client, database, signed_in
):
    assert_password_incorrect(reauthenticate(client, signed_in.headers, f" {PASSWORD}"))


def test_a_user_signed_in_by_google_but_with_a_password_can_re_authenticate(
    client, database, owner, sign_in
):
    from app.schemas.sessions import LoginMethod

    session = sign_in(owner, login_method=LoginMethod.GOOGLE)
    assert reauthenticate(client, session.headers).status_code == 200


def test_success_clears_the_failed_login_count(client, database, signed_in):
    set_failure(database, failed_attempts=3)
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None


def test_success_without_earlier_failures_leaves_no_failure_row(
    client, database, signed_in
):
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None


def test_success_after_failures_restarts_the_count(client, database, signed_in):
    for _ in range(4):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    assert reauthenticate(client, signed_in.headers).status_code == 200
    for _ in range(4):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    assert read_failure(database).locked_until is None
    assert reauthenticate(client, signed_in.headers).status_code == 200


def test_success_does_not_clear_the_count_of_other_emails(client, database, signed_in):
    set_failure(database, "other@example.com", failed_attempts=2)
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_failure(database, "other@example.com").failed_attempts == 2


# Wrong password


def test_a_wrong_password_is_rejected_on_the_password_field(
    client, database, signed_in
):
    assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))


def test_a_wrong_password_leaves_the_session_unchanged(
    client, database, signed_in, read_session
):
    reauthenticate(client, signed_in.headers, WRONG)
    assert read_session(signed_in.session_id).reauthenticated_at is None
    assert recent_reauthentication_status(signed_in.headers) == 403


def test_a_wrong_password_keeps_an_earlier_re_authentication_time(
    client, database, signed_in, read_session
):
    earlier = datetime.now(UTC) - timedelta(minutes=2)
    set_reauthenticated_at(database, signed_in.session_id, earlier)
    assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    assert read_session(signed_in.session_id).reauthenticated_at == earlier


@pytest.mark.parametrize("attempts", [1, 2, 3, 4])
def test_wrong_passwords_are_counted_and_persisted_without_locking(
    client, database, signed_in, attempts
):
    for _ in range(attempts):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    row = read_failure(database)
    assert row.failed_attempts == attempts
    assert row.locked_until is None


def test_the_fifth_wrong_password_still_answers_incorrect_and_locks_the_email(
    client, database, signed_in
):
    for _ in range(4):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    before = datetime.now(UTC)
    assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    after = datetime.now(UTC)
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert (
        before + timedelta(seconds=LOCK_SECONDS)
        <= row.locked_until
        <= after + timedelta(seconds=LOCK_SECONDS)
    )


def test_the_next_call_after_the_lock_is_answered_with_too_many_attempts(
    client, database, signed_in
):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, WRONG)
    assert_locked(reauthenticate(client, signed_in.headers, WRONG))


def test_a_locked_email_cannot_re_authenticate_with_the_right_password(
    client, database, signed_in, read_session
):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, WRONG)
    assert_locked(reauthenticate(client, signed_in.headers))
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_a_lock_from_re_authentication_blocks_login(client, database, signed_in):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, WRONG)
    assert_locked(login(client))
    assert_locked(login(client, WRONG))


def test_an_existing_lock_answers_before_the_password_is_checked(
    client, database, signed_in, read_session
):
    locked_until = datetime.now(UTC) + timedelta(seconds=100)
    set_failure(database, failed_attempts=5, locked_until=locked_until)
    assert_locked(reauthenticate(client, signed_in.headers))
    assert_locked(reauthenticate(client, signed_in.headers, WRONG))
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until == locked_until
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_the_lock_answer_reports_the_remaining_time_rounded_up(
    client, database, signed_in
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100.9),
    )
    response = reauthenticate(client, signed_in.headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "101"


def test_a_lapsed_lock_lets_the_right_password_through(client, database, signed_in):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None


def test_a_lapsed_lock_starts_the_count_again_on_a_wrong_password(
    client, database, signed_in
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    row = read_failure(database)
    assert row.failed_attempts == 1
    assert row.locked_until is None


def test_the_lock_of_another_email_does_not_block(client, database, signed_in):
    set_failure(
        database,
        "other@example.com",
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert reauthenticate(client, signed_in.headers).status_code == 200


# Shared counter with login


def test_failed_logins_and_failed_re_authentications_share_one_counter_login_first(
    client, database, signed_in
):
    for _ in range(2):
        assert login(client, WRONG).status_code == 401
    for _ in range(3):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_locked(reauthenticate(client, signed_in.headers))
    assert_locked(login(client))


def test_failed_logins_and_failed_re_authentications_share_one_counter_reauth_first(
    client, database, signed_in
):
    for _ in range(3):
        assert_password_incorrect(reauthenticate(client, signed_in.headers, WRONG))
    for _ in range(2):
        assert login(client, WRONG).status_code == 401
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_locked(login(client))
    assert_locked(reauthenticate(client, signed_in.headers))


def test_failed_logins_alone_lock_re_authentication(client, database, signed_in):
    for _ in range(5):
        assert login(client, WRONG).status_code in (401, 429)
    assert_locked(reauthenticate(client, signed_in.headers))


def test_a_successful_re_authentication_resets_login_failures(
    client, database, signed_in
):
    for _ in range(4):
        assert login(client, WRONG).status_code == 401
    assert reauthenticate(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None
    assert login(client, WRONG).status_code == 401
    assert read_failure(database).failed_attempts == 1


# No password on the account


def google_only_session(make_user, sign_in):
    from app.schemas.sessions import LoginMethod

    user = make_user(email="google@example.com", password_hash=None)
    return sign_in(user, login_method=LoginMethod.GOOGLE)


def test_an_account_without_a_password_gets_password_not_set(
    client, database, make_user, sign_in, read_session
):
    session = google_only_session(make_user, sign_in)
    response = reauthenticate(client, session.headers)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "PASSWORD_NOT_SET"
    assert body["field"] is None
    assert body["message"]
    assert read_session(session.session_id).reauthenticated_at is None


def test_an_account_without_a_password_is_not_counted_as_a_failure(
    client, database, make_user, sign_in
):
    session = google_only_session(make_user, sign_in)
    for _ in range(6):
        assert reauthenticate(client, session.headers).status_code == 409
    assert read_failure(database, "google@example.com") is None


def test_an_account_without_a_password_is_answered_locked_when_the_email_is_locked(
    client, database, make_user, sign_in
):
    session = google_only_session(make_user, sign_in)
    set_failure(
        database,
        "google@example.com",
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert_locked(reauthenticate(client, session.headers))


# Validation


@pytest.mark.parametrize("value", ["", None, 12345])
def test_an_unusable_password_value_is_a_validation_failure_and_not_counted(
    client, database, signed_in, value
):
    for _ in range(6):
        response = client.post(URL, json={"password": value}, headers=signed_in.headers)
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_FAILED"
        assert body["field"] == "password"
    assert read_failure(database) is None
    assert reauthenticate(client, signed_in.headers).status_code == 200


def test_a_missing_body_is_a_validation_failure(client, database, signed_in):
    response = client.post(URL, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert read_failure(database) is None


def test_a_validation_failure_does_not_count_towards_the_limit(
    client, database, signed_in
):
    for _ in range(4):
        reauthenticate(client, signed_in.headers, WRONG)
    client.post(URL, json={"password": ""}, headers=signed_in.headers)
    row = read_failure(database)
    assert row.failed_attempts == 4
    assert row.locked_until is None


# Authentication


def test_no_token_is_rejected(client, database, owner):
    assert_access_rejected(client.post(URL, json={"password": PASSWORD}))


def test_an_invalid_token_is_rejected(client, database, owner):
    response = client.post(
        URL, json={"password": PASSWORD}, headers={"Authorization": "Bearer garbage"}
    )
    assert_access_rejected(response)


def test_a_revoked_session_is_rejected(client, database, signed_in, read_session):
    client.post("/auth/logout", headers=signed_in.headers)
    assert_access_rejected(reauthenticate(client, signed_in.headers))
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_a_rejected_token_counts_no_failure(client, database, owner):
    for _ in range(6):
        response = client.post(
            URL, json={"password": WRONG}, headers={"Authorization": "Bearer garbage"}
        )
        assert_access_rejected(response)
    assert read_failure(database) is None


def test_an_unverified_account_gets_email_not_verified(
    client, database, make_user, sign_in, read_session
):
    from app.services.passwords import hash_password

    user = make_user(
        email="new@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified=False,
    )
    session = sign_in(user)
    response = reauthenticate(client, session.headers)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "EMAIL_NOT_VERIFIED"
    assert body["field"] is None
    assert read_session(session.session_id).reauthenticated_at is None
    assert read_failure(database, "new@example.com") is None


def test_an_unverified_account_with_a_wrong_password_counts_no_failure(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        email="new@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified=False,
    )
    session = sign_in(user)
    response = reauthenticate(client, session.headers, WRONG)
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"
    assert read_failure(database, "new@example.com") is None


# Google re-authentication is not part of this endpoint


def test_google_re_authentication_is_still_not_implemented(client, database, signed_in):
    response = client.post(
        GOOGLE_URL, json={"idToken": "token"}, headers=signed_in.headers
    )
    assert response.status_code == 501
