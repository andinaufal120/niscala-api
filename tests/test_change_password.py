"""Changing the caller's own password."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

URL = "/me/password-changes"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
ME_URL = "/me"
EMAIL = "rina@example.com"
NAME = "Rina Owner"
PASSWORD = "correct horse battery"
NEW = "T7#vq9-lorem-ipsum"
WRONG = "wrong password"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
LOCK_SECONDS = 15 * 60


def change(client, headers, current: str = PASSWORD, new: str = NEW):
    body = {"currentPassword": current, "newPassword": new}
    return client.post(URL, json=body, headers=headers)


def login(client, password: str = PASSWORD, email: str = EMAIL):
    body = {"email": email, "password": password, "device": DEVICE}
    return client.post(LOGIN_URL, json=body)


def days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def set_session_columns(database, session_id, **columns) -> None:
    from app.models import UserSession

    with Session(database) as db:
        row = db.get(UserSession, session_id)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


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


def stored_hash(database, user) -> str | None:
    from app.models import UserAccount

    with Session(database) as db:
        return db.get(UserAccount, user.id).password_hash


def set_email(database, user, email: str) -> None:
    from app.models import UserAccount

    with Session(database) as db:
        db.get(UserAccount, user.id).email = email
        db.commit()


def refresh(client, token: str):
    return client.post(REFRESH_URL, json={"refreshToken": token})


def assert_still_signed_in(client, signed_in) -> None:
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    assert refresh(client, signed_in.tokens.refresh_token).status_code == 200


def assert_error(response, status: int, code: str, field: str | None) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def assert_locked(response) -> None:
    assert_error(response, 429, "TOO_MANY_ATTEMPTS", None)
    assert 1 <= int(response.headers["Retry-After"]) <= LOCK_SECONDS


def assert_login_locked(response) -> None:
    assert_error(response, 429, "TOO_MANY_LOGIN_ATTEMPTS", None)


def assert_current_incorrect(response) -> None:
    assert_error(response, 422, "CURRENT_PASSWORD_INCORRECT", "currentPassword")


def assert_unchanged_rejected(response) -> None:
    assert_error(response, 422, "PASSWORD_UNCHANGED", "newPassword")


def assert_too_common(response) -> None:
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "newPassword")


def assert_validation_failed(response, field: str) -> None:
    assert_error(response, 422, "VALIDATION_FAILED", field)


def assert_access_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


@pytest.fixture
def owner(make_user):
    from app.services.passwords import hash_password

    return make_user(name=NAME, email=EMAIL, password_hash=hash_password(PASSWORD))


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def original_hash(database, owner) -> str:
    return stored_hash(database, owner)


# Success


def test_a_valid_change_answers_with_has_other_sessions(client, signed_in):
    response = change(client, signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {"hasOtherSessions": False}


def test_the_stored_hash_is_replaced_by_an_argon2_hash_of_the_new_password(
    client, database, owner, signed_in, original_hash
):
    assert change(client, signed_in.headers).status_code == 200
    updated = stored_hash(database, owner)
    assert updated != original_hash
    assert updated.startswith("$argon2")
    assert NEW not in updated


def test_login_with_the_old_password_fails_after_the_change(
    client, database, signed_in
):
    assert change(client, signed_in.headers).status_code == 200
    response = login(client, PASSWORD)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_login_with_the_new_password_works_after_the_change(
    client, database, signed_in
):
    assert change(client, signed_in.headers).status_code == 200
    assert login(client, NEW).status_code == 200


def test_the_calling_session_stays_signed_in(client, database, signed_in, read_session):
    assert change(client, signed_in.headers).status_code == 200
    assert read_session(signed_in.session_id).revoked_at is None
    assert_still_signed_in(client, signed_in)


def test_all_other_sessions_of_the_user_stay_signed_in(
    client, database, owner, sign_in, read_session
):
    current = sign_in(owner)
    phone = sign_in(owner, device_name="Phone")
    tablet = sign_in(owner, device_name="Tablet")
    assert change(client, current.headers).status_code == 200
    for other in (phone, tablet):
        assert read_session(other.session_id).revoked_at is None
        assert_still_signed_in(client, other)
    assert_still_signed_in(client, current)


def test_a_session_started_with_google_stays_signed_in(
    client, database, owner, sign_in, read_session
):
    from app.schemas.sessions import LoginMethod

    google = sign_in(owner, device_name="Laptop", login_method=LoginMethod.GOOGLE)
    current = sign_in(owner)
    assert change(client, current.headers).status_code == 200
    assert read_session(google.session_id).revoked_at is None
    assert_still_signed_in(client, google)


def test_sessions_of_other_users_are_untouched(
    client, database, signed_in, make_user, sign_in, read_session
):
    stranger = sign_in(make_user(email="budi@example.com"))
    assert change(client, signed_in.headers).status_code == 200
    assert read_session(stranger.session_id).revoked_at is None
    assert_still_signed_in(client, stranger)


def test_the_password_of_other_users_is_untouched(
    client, database, signed_in, make_user
):
    from app.services.passwords import hash_password

    stranger = make_user(email="budi@example.com", password_hash=hash_password(WRONG))
    before = stored_hash(database, stranger)
    assert change(client, signed_in.headers).status_code == 200
    assert stored_hash(database, stranger) == before


def test_a_change_sends_no_email(client, database, signed_in, sent_emails):
    assert change(client, signed_in.headers).status_code == 200
    assert sent_emails == []


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_can_change_its_password(client, database, make_user, sign_in, role):
    from app.schemas.auth import UserRole
    from app.services.passwords import hash_password

    user = make_user(
        email="role@example.com",
        password_hash=hash_password(PASSWORD),
        role=UserRole(role),
    )
    session = sign_in(user)
    assert change(client, session.headers).status_code == 200
    assert login(client, NEW, "role@example.com").status_code == 200
    assert login(client, PASSWORD, "role@example.com").status_code == 401


def test_a_user_signed_in_by_google_who_has_a_password_can_change_it(
    client, database, owner, sign_in
):
    from app.schemas.sessions import LoginMethod

    session = sign_in(owner, login_method=LoginMethod.GOOGLE)
    assert change(client, session.headers).status_code == 200
    assert login(client, NEW).status_code == 200


@pytest.mark.parametrize(
    "new",
    ["pässwörd with spaces", "  padded passphrase  ", ("T7#vq9-lorem-" * 10)[:128]],
)
def test_the_new_password_is_stored_exactly_as_given(client, database, signed_in, new):
    assert change(client, signed_in.headers, new=new).status_code == 200
    assert login(client, new).status_code == 200
    assert login(client, new.strip() + "x").status_code == 401


def test_a_new_password_of_exactly_8_characters_is_accepted(
    client, database, signed_in
):
    assert change(client, signed_in.headers, new="T7#vq9-l").status_code == 200
    assert login(client, "T7#vq9-l").status_code == 200


def test_a_new_password_differing_only_in_case_is_a_change(client, database, signed_in):
    assert change(client, signed_in.headers, new=PASSWORD.upper()).status_code == 200
    assert login(client, PASSWORD.upper()).status_code == 200


def test_the_new_password_may_differ_from_the_current_one_by_a_space(
    client, database, signed_in
):
    assert change(client, signed_in.headers, new=PASSWORD + " x").status_code == 200


def test_the_password_can_be_changed_again_with_the_new_one(
    client, database, signed_in
):
    assert change(client, signed_in.headers).status_code == 200
    again = change(client, signed_in.headers, current=NEW, new="mUk3!xqz-Plover")
    assert again.status_code == 200
    assert login(client, "mUk3!xqz-Plover").status_code == 200
    assert login(client, NEW).status_code == 401


def test_the_old_password_cannot_be_used_as_current_after_a_change(
    client, database, signed_in
):
    assert change(client, signed_in.headers).status_code == 200
    assert_current_incorrect(
        change(client, signed_in.headers, current=PASSWORD, new="mUk3!xqz-Plover")
    )


def test_a_current_password_of_any_length_is_accepted_by_validation(
    client, database, signed_in
):
    assert_current_incorrect(change(client, signed_in.headers, current="a" * 200))
    assert_current_incorrect(change(client, signed_in.headers, current=" "))


def test_the_current_password_is_compared_untrimmed(client, database, signed_in):
    assert_current_incorrect(change(client, signed_in.headers, current=f" {PASSWORD}"))


# hasOtherSessions


def test_has_other_sessions_is_true_with_another_active_session(
    client, database, owner, signed_in, sign_in
):
    sign_in(owner, device_name="Tablet")
    response = change(client, signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {"hasOtherSessions": True}


def test_has_other_sessions_is_true_with_several_other_sessions(
    client, database, owner, signed_in, sign_in
):
    sign_in(owner, device_name="Tablet")
    sign_in(owner, device_name="Laptop")
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": True}


def test_has_other_sessions_ignores_a_revoked_session(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    set_session_columns(database, other.session_id, revoked_at=datetime.now(UTC))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


def test_has_other_sessions_ignores_a_session_ended_by_logout(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    assert client.post("/auth/logout", headers=other.headers).status_code == 204
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


def test_has_other_sessions_ignores_a_session_idle_for_more_than_90_days(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    set_session_columns(database, other.session_id, last_active_at=days_ago(91))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


def test_has_other_sessions_counts_a_session_idle_for_89_days(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    set_session_columns(database, other.session_id, last_active_at=days_ago(89))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": True}


def test_has_other_sessions_ignores_a_session_older_than_a_year(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    set_session_columns(
        database,
        other.session_id,
        created_at=days_ago(366),
        last_active_at=datetime.now(UTC),
    )
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


def test_has_other_sessions_counts_a_session_created_364_days_ago(
    client, database, owner, signed_in, sign_in
):
    other = sign_in(owner, device_name="Tablet")
    set_session_columns(database, other.session_id, created_at=days_ago(364))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": True}


def test_has_other_sessions_ignores_sessions_of_other_users(
    client, database, signed_in, make_user, sign_in
):
    sign_in(make_user(email="budi@example.com"))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


def test_has_other_sessions_is_true_when_one_other_session_is_active_among_dead_ones(
    client, database, owner, signed_in, sign_in
):
    revoked = sign_in(owner, device_name="Revoked")
    idle = sign_in(owner, device_name="Idle")
    sign_in(owner, device_name="Active")
    set_session_columns(database, revoked.session_id, revoked_at=datetime.now(UTC))
    set_session_columns(database, idle.session_id, last_active_at=days_ago(120))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": True}


def test_has_other_sessions_does_not_count_the_calling_session(
    client, database, owner, signed_in, sign_in
):
    set_session_columns(database, signed_in.session_id, last_active_at=days_ago(1))
    assert change(client, signed_in.headers).json() == {"hasOtherSessions": False}


# Account without a local password


def google_only_session(make_user, sign_in):
    from app.schemas.sessions import LoginMethod

    user = make_user(email="google@example.com", password_hash=None)
    return user, sign_in(user, login_method=LoginMethod.GOOGLE)


def test_an_account_without_a_password_gets_password_not_set(
    client, database, make_user, sign_in
):
    user, session = google_only_session(make_user, sign_in)
    assert_error(change(client, session.headers), 409, "PASSWORD_NOT_SET", None)
    assert stored_hash(database, user) is None
    assert_still_signed_in(client, session)


def test_an_account_without_a_password_is_not_counted_as_a_failure(
    client, database, make_user, sign_in
):
    _, session = google_only_session(make_user, sign_in)
    for _ in range(6):
        assert change(client, session.headers).status_code == 409
    assert read_failure(database, "google@example.com") is None


def test_an_account_without_a_password_is_answered_before_the_lock(
    client, database, make_user, sign_in
):
    _, session = google_only_session(make_user, sign_in)
    set_failure(
        database,
        "google@example.com",
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert_error(change(client, session.headers), 409, "PASSWORD_NOT_SET", None)


def test_an_account_without_a_password_is_answered_before_the_new_password_rules(
    client, database, make_user, sign_in
):
    _, session = google_only_session(make_user, sign_in)
    response = change(client, session.headers, new="password123")
    assert_error(response, 409, "PASSWORD_NOT_SET", None)


# Lock


def test_a_locked_email_cannot_change_the_password_even_with_the_right_one(
    client, database, owner, signed_in, original_hash
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100),
    )
    assert_locked(change(client, signed_in.headers))
    assert stored_hash(database, owner) == original_hash
    assert_still_signed_in(client, signed_in)


def test_the_lock_answer_reports_the_remaining_time_rounded_up(
    client, database, signed_in
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100.9),
    )
    response = change(client, signed_in.headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "101"


def test_an_existing_lock_answers_before_the_password_is_checked_and_changes_nothing(
    client, database, signed_in
):
    locked_until = datetime.now(UTC) + timedelta(seconds=100)
    set_failure(database, failed_attempts=5, locked_until=locked_until)
    assert_locked(change(client, signed_in.headers, current=WRONG))
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until == locked_until


def test_a_lock_is_answered_before_the_current_password_equals_new_check(
    client, database, signed_in
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100),
    )
    assert_locked(change(client, signed_in.headers, new=PASSWORD))
    assert_locked(change(client, signed_in.headers, new="password123"))


def test_a_lapsed_lock_lets_a_change_through(client, database, owner, signed_in):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert change(client, signed_in.headers).status_code == 200
    assert login(client, NEW).status_code == 200


def test_a_lapsed_lock_starts_the_count_again_on_a_wrong_current_password(
    client, database, signed_in
):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
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
    assert change(client, signed_in.headers).status_code == 200


def test_a_lock_set_by_failed_logins_blocks_the_change(client, database, signed_in):
    for _ in range(5):
        assert login(client, WRONG).status_code in (401, 429)
    assert_locked(change(client, signed_in.headers))


def test_the_lock_uses_the_trimmed_lower_cased_account_email(
    client, database, owner, signed_in
):
    set_email(database, owner, "  Rina@Example.COM ")
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    assert read_failure(database, EMAIL).failed_attempts == 1
    assert read_failure(database, "  Rina@Example.COM ") is None
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert_locked(change(client, signed_in.headers))


# Wrong current password


def test_a_wrong_current_password_is_rejected_on_its_field(
    client, database, owner, signed_in, original_hash
):
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    assert stored_hash(database, owner) == original_hash
    assert login(client, PASSWORD).status_code == 200


def test_a_wrong_current_password_leaves_every_session_signed_in(
    client, database, owner, signed_in, sign_in, read_session
):
    other = sign_in(owner, device_name="Tablet")
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    assert read_session(signed_in.session_id).revoked_at is None
    assert read_session(other.session_id).revoked_at is None
    assert_still_signed_in(client, signed_in)
    assert_still_signed_in(client, other)


@pytest.mark.parametrize("attempts", [1, 2, 3, 4])
def test_wrong_current_passwords_are_counted_and_persisted_without_locking(
    client, database, signed_in, attempts
):
    for _ in range(attempts):
        assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    row = read_failure(database)
    assert row.failed_attempts == attempts
    assert row.locked_until is None


def test_the_fifth_wrong_current_password_still_answers_incorrect_and_locks(
    client, database, signed_in
):
    for _ in range(4):
        assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    before = datetime.now(UTC)
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    after = datetime.now(UTC)
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert (
        before + timedelta(seconds=LOCK_SECONDS)
        <= row.locked_until
        <= after + timedelta(seconds=LOCK_SECONDS)
    )


def test_attempts_after_the_lock_answer_too_many_attempts(
    client, database, owner, signed_in, original_hash
):
    for _ in range(5):
        assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    assert_locked(change(client, signed_in.headers, current=WRONG))
    assert_locked(change(client, signed_in.headers))
    assert stored_hash(database, owner) == original_hash


def test_wrong_logins_and_a_wrong_current_password_share_one_counter_login_first(
    client, database, signed_in
):
    for _ in range(4):
        assert login(client, WRONG).status_code == 401
    assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_login_locked(login(client))
    assert_locked(change(client, signed_in.headers))


def test_wrong_logins_and_a_wrong_current_password_share_one_counter_change_first(
    client, database, signed_in
):
    for _ in range(3):
        assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    for _ in range(2):
        assert login(client, WRONG).status_code == 401
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_login_locked(login(client))
    assert_locked(change(client, signed_in.headers))


def test_a_wrong_current_password_with_a_blocked_new_password_reports_the_current_one(
    client, database, signed_in
):
    response = change(client, signed_in.headers, current=WRONG, new="password123")
    assert_current_incorrect(response)


def test_a_wrong_current_password_equal_to_the_new_one_reports_the_current_one(
    client, database, signed_in
):
    assert_current_incorrect(
        change(client, signed_in.headers, current=WRONG, new=WRONG)
    )


# Success resets the counter


@pytest.mark.parametrize("failures", [1, 3, 4])
def test_a_successful_change_clears_the_failed_login_count(
    client, database, signed_in, failures
):
    for _ in range(failures):
        assert login(client, WRONG).status_code == 401
    assert change(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None


def test_a_successful_change_restarts_the_count(client, database, signed_in):
    for _ in range(3):
        assert login(client, WRONG).status_code == 401
    assert change(client, signed_in.headers).status_code == 200
    for _ in range(4):
        assert login(client, WRONG).status_code == 401
    assert read_failure(database).locked_until is None
    assert login(client, NEW).status_code == 200


def test_a_successful_change_without_earlier_failures_leaves_no_failure_row(
    client, database, signed_in
):
    assert change(client, signed_in.headers).status_code == 200
    assert read_failure(database) is None


def test_a_successful_change_does_not_clear_the_count_of_other_emails(
    client, database, signed_in
):
    set_failure(database, "other@example.com", failed_attempts=2)
    assert change(client, signed_in.headers).status_code == 200
    assert read_failure(database, "other@example.com").failed_attempts == 2


# New password equals the current one


@pytest.mark.parametrize("session_count", [1, 2])
def test_a_new_password_equal_to_the_current_one_is_rejected(
    client, database, owner, sign_in, original_hash, session_count
):
    sessions = [sign_in(owner, device_name=f"Device {n}") for n in range(session_count)]
    response = change(client, sessions[0].headers, new=PASSWORD)
    assert_unchanged_rejected(response)
    assert stored_hash(database, owner) == original_hash
    for session in sessions:
        assert_still_signed_in(client, session)


def test_an_unchanged_password_is_reported_even_when_it_is_blocklisted(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        email="weak@example.com", password_hash=hash_password("password123")
    )
    session = sign_in(user)
    response = change(client, session.headers, current="password123", new="password123")
    assert_unchanged_rejected(response)


def test_an_unchanged_password_is_reported_before_the_blocklist_on_the_user_name(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    weak = "xx-niscala-xx"
    user = make_user(email="weak@example.com", password_hash=hash_password(weak))
    session = sign_in(user)
    assert_unchanged_rejected(change(client, session.headers, current=weak, new=weak))


# Blocklisted new password


@pytest.mark.parametrize(
    "new",
    [
        "password123",
        "qwertyuiop",
        "PASSWORD123",
        "aaaaaaaa",
        "AAAAAAAA",
        "11111111",
        "12345678",
        "abcdefgh",
        "87654321",
        "HGFEDCBA",
        "niscala!",
        "xx-NISCALA-xx",
        "T7#vq9-rina-ipsum",
        "T7#vq9-RINA-ipsum",
        "T7#vq9-rina owner-ipsum",
        "T7#vq9-RINA OWNER-ipsum",
    ],
)
def test_a_blocklisted_new_password_is_rejected_and_nothing_changes(
    client, database, owner, signed_in, sign_in, original_hash, new
):
    other = sign_in(owner, device_name="Tablet")
    assert_too_common(change(client, signed_in.headers, new=new))
    assert stored_hash(database, owner) == original_hash
    assert login(client, PASSWORD).status_code == 200
    assert_still_signed_in(client, signed_in)
    assert_still_signed_in(client, other)


def test_the_blocklist_checks_the_accounts_own_email_local_part(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        name="Someone Else",
        email="budi.s@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(user)
    assert_too_common(change(client, session.headers, new="T7#vq9-budi.s-x"))
    assert change(client, session.headers, new="T7#vq9-rina-ipsum").status_code == 200


def test_the_blocklist_checks_the_accounts_own_name(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        name="Budi Santoso",
        email="owner@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(user)
    assert_too_common(change(client, session.headers, new="T7#vq9-budi santoso-x"))


def test_a_short_email_local_part_or_name_is_not_blocked(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        name="Ann", email="abc@example.com", password_hash=hash_password(PASSWORD)
    )
    session = sign_in(user)
    assert change(client, session.headers, new="T7#vq9-abc-ann-x").status_code == 200


# Validation


@pytest.mark.parametrize("value", ["", None, 12345])
def test_an_unusable_current_password_is_a_validation_failure_and_not_counted(
    client, database, signed_in, value
):
    for _ in range(6):
        response = client.post(
            URL,
            json={"currentPassword": value, "newPassword": NEW},
            headers=signed_in.headers,
        )
        assert_validation_failed(response, "currentPassword")
    assert read_failure(database) is None
    assert change(client, signed_in.headers).status_code == 200


@pytest.mark.parametrize("value", ["", "1234567", "a" * 129, None, 12345678])
def test_an_unusable_new_password_is_a_validation_failure(
    client, database, owner, signed_in, original_hash, value
):
    response = client.post(
        URL,
        json={"currentPassword": PASSWORD, "newPassword": value},
        headers=signed_in.headers,
    )
    assert_validation_failed(response, "newPassword")
    assert stored_hash(database, owner) == original_hash


def test_a_missing_current_password_is_a_validation_failure(
    client, database, signed_in
):
    response = client.post(URL, json={"newPassword": NEW}, headers=signed_in.headers)
    assert_validation_failed(response, "currentPassword")


def test_a_missing_new_password_is_a_validation_failure(client, database, signed_in):
    response = client.post(
        URL, json={"currentPassword": PASSWORD}, headers=signed_in.headers
    )
    assert_validation_failed(response, "newPassword")


def test_a_missing_body_is_a_validation_failure(client, database, signed_in):
    response = client.post(URL, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert read_failure(database) is None


def test_an_empty_object_is_a_validation_failure(client, database, signed_in):
    response = client.post(URL, json={}, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_validation_failure_does_not_count_towards_the_limit(
    client, database, signed_in
):
    for _ in range(4):
        assert_current_incorrect(change(client, signed_in.headers, current=WRONG))
    client.post(
        URL,
        json={"currentPassword": WRONG, "newPassword": "short"},
        headers=signed_in.headers,
    )
    row = read_failure(database)
    assert row.failed_attempts == 4
    assert row.locked_until is None


def test_validation_is_reported_before_the_password_check(client, database, signed_in):
    response = client.post(
        URL,
        json={"currentPassword": WRONG, "newPassword": "short"},
        headers=signed_in.headers,
    )
    assert_validation_failed(response, "newPassword")
    assert read_failure(database) is None


def test_validation_is_reported_before_the_lock(client, database, signed_in):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    response = client.post(
        URL,
        json={"currentPassword": PASSWORD, "newPassword": "short"},
        headers=signed_in.headers,
    )
    assert_validation_failed(response, "newPassword")


def test_validation_is_reported_before_an_account_without_a_password(
    client, database, make_user, sign_in
):
    _, session = google_only_session(make_user, sign_in)
    response = client.post(
        URL,
        json={"currentPassword": PASSWORD, "newPassword": "short"},
        headers=session.headers,
    )
    assert_validation_failed(response, "newPassword")


# Authentication


def test_no_token_is_rejected(client, database, owner, original_hash):
    body = {"currentPassword": PASSWORD, "newPassword": NEW}
    assert_access_rejected(client.post(URL, json=body))
    assert stored_hash(database, owner) == original_hash


def test_an_invalid_token_is_rejected(client, database, owner):
    response = change(client, {"Authorization": "Bearer garbage"})
    assert_access_rejected(response)


def test_a_rejected_token_counts_no_failure(client, database, owner):
    for _ in range(6):
        response = change(client, {"Authorization": "Bearer garbage"}, current=WRONG)
        assert_access_rejected(response)
    assert read_failure(database) is None


def test_a_revoked_session_is_rejected(client, database, owner, signed_in):
    client.post("/auth/logout", headers=signed_in.headers)
    assert_access_rejected(change(client, signed_in.headers))
    assert login(client, PASSWORD).status_code == 200


def test_an_unverified_account_gets_email_not_verified(
    client, database, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        email="new@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified=False,
    )
    session = sign_in(user)
    before = stored_hash(database, user)
    response = change(client, session.headers, current=WRONG)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED", None)
    assert stored_hash(database, user) == before
    assert read_failure(database, "new@example.com") is None
