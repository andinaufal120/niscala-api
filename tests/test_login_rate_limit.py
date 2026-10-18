"""Repeated failed logins lock an email for a while."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

LOGIN_URL = "/auth/login"
EMAIL = "rina@example.com"
PASSWORD = "correct horse battery"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
LOCK_SECONDS = 15 * 60


def login(client, email: str = EMAIL, password: str = PASSWORD):
    body = {"email": email, "password": password, "device": DEVICE}
    return client.post(LOGIN_URL, json=body)


def fail(client, times: int, email: str = EMAIL) -> None:
    for _ in range(times):
        assert login(client, email=email, password="wrong password").status_code in (
            401,
            429,
        )


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


def count_sessions(database) -> int:
    from app.models import UserSession

    with Session(database) as db:
        return len(list(db.scalars(select(UserSession))))


def assert_invalid_credentials(response) -> None:
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def assert_locked(response) -> None:
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert body["field"] is None
    assert body["message"]
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= LOCK_SECONDS


@pytest.fixture
def owner(make_user):
    from app.services.passwords import hash_password

    return make_user(
        name="Rina Owner", email=EMAIL, password_hash=hash_password(PASSWORD)
    )


@pytest.mark.parametrize("attempts", [1, 2, 3, 4])
def test_failed_logins_are_counted_without_locking(client, database, owner, attempts):
    for _ in range(attempts):
        assert_invalid_credentials(login(client, password="wrong password"))
    row = read_failure(database)
    assert row.failed_attempts == attempts
    assert row.locked_until is None


def test_the_first_failure_creates_the_row(client, database, owner):
    assert read_failure(database) is None
    login(client, password="wrong password")
    assert read_failure(database) is not None


def test_the_fifth_failure_still_answers_invalid_credentials_and_locks(
    client, database, owner
):
    fail(client, 4)
    before = datetime.now(UTC)
    assert_invalid_credentials(login(client, password="wrong password"))
    after = datetime.now(UTC)
    row = read_failure(database)
    assert row.failed_attempts == 5
    assert row.locked_until.utcoffset() == timedelta(0)
    assert (
        before + timedelta(seconds=LOCK_SECONDS)
        <= row.locked_until
        <= after + timedelta(seconds=LOCK_SECONDS)
    )


def test_the_sixth_attempt_is_locked_out(client, database, owner):
    fail(client, 5)
    assert_locked(login(client, password="wrong password"))


def test_a_locked_email_cannot_log_in_even_with_the_right_password(
    client, database, owner
):
    fail(client, 5)
    assert_locked(login(client))
    assert count_sessions(database) == 0


def test_the_lock_answer_reports_the_remaining_time_rounded_up(client, database, owner):
    set_failure(
        database,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100.9),
    )
    response = login(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "101"


def test_the_lock_answer_right_after_locking_asks_for_about_fifteen_minutes(
    client, database, owner
):
    fail(client, 5)
    response = login(client)
    assert_locked(response)
    assert int(response.headers["Retry-After"]) >= LOCK_SECONDS - 30


def test_attempts_while_locked_change_nothing(client, database, owner):
    fail(client, 5)
    locked_until = read_failure(database).locked_until
    for password in ("wrong password", PASSWORD, "wrong password"):
        assert_locked(login(client, password=password))
    row = read_failure(database)
    assert row.locked_until == locked_until
    assert row.failed_attempts == 5
    assert count_sessions(database) == 0


def test_the_lock_applies_to_an_email_without_an_account(client, database):
    for _ in range(5):
        assert_invalid_credentials(login(client, email="ghost@example.com"))
    assert_locked(login(client, email="ghost@example.com"))
    assert read_failure(database, "ghost@example.com").failed_attempts == 5


def test_an_account_without_a_password_is_counted_and_locked(
    client, database, make_user
):
    make_user(email="google@example.com", password_hash=None)
    for _ in range(5):
        assert_invalid_credentials(login(client, email="google@example.com"))
    assert_locked(login(client, email="google@example.com"))


def test_a_lapsed_lock_lets_the_right_password_in(client, database, owner):
    fail(client, 5)
    set_failure(database, locked_until=datetime.now(UTC) - timedelta(seconds=1))
    response = login(client)
    assert response.status_code == 200
    row = read_failure(database)
    assert row is None or (row.failed_attempts == 0 and row.locked_until is None)


def test_a_lapsed_lock_starts_the_count_again_on_a_wrong_password(
    client, database, owner
):
    fail(client, 5)
    set_failure(database, locked_until=datetime.now(UTC) - timedelta(seconds=1))
    assert_invalid_credentials(login(client, password="wrong password"))
    row = read_failure(database)
    assert row.failed_attempts == 1
    assert row.locked_until is None


def test_a_lapsed_lock_needs_five_new_failures_to_lock_again(client, database, owner):
    fail(client, 5)
    set_failure(database, locked_until=datetime.now(UTC) - timedelta(seconds=1))
    for _ in range(4):
        assert_invalid_credentials(login(client, password="wrong password"))
    assert read_failure(database).locked_until is None
    assert_invalid_credentials(login(client, password="wrong password"))
    assert read_failure(database).locked_until is not None
    assert_locked(login(client))


@pytest.mark.parametrize("failures", [1, 2, 3, 4])
def test_a_successful_login_clears_the_count(client, database, owner, failures):
    fail(client, failures)
    assert login(client).status_code == 200
    assert read_failure(database) is None
    for _ in range(4):
        assert_invalid_credentials(login(client, password="wrong password"))
    row = read_failure(database)
    assert row.failed_attempts == 4
    assert row.locked_until is None
    assert login(client).status_code == 200


def test_a_successful_login_without_earlier_failures_leaves_no_row(
    client, database, owner
):
    assert login(client).status_code == 200
    assert read_failure(database) is None


def test_emails_differing_by_case_or_spaces_share_one_counter(client, database, owner):
    variants = [
        "rina@example.com",
        "RINA@EXAMPLE.COM",
        "  rina@example.com",
        "Rina@Example.com  ",
        " Rina@Example.COM ",
    ]
    for variant in variants:
        assert_invalid_credentials(
            login(client, email=variant, password="wrong password")
        )
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_locked(login(client, email="RINA@example.com"))
    assert_locked(login(client, email=" rina@example.com "))
    assert_locked(login(client))


def test_the_counter_is_stored_under_the_normalized_email(client, database, owner):
    login(client, email="  Rina@Example.COM ", password="wrong password")
    assert read_failure(database, EMAIL).failed_attempts == 1
    assert read_failure(database, "  Rina@Example.COM ") is None


def test_different_emails_count_independently(client, database, owner, make_user):
    from app.services.passwords import hash_password

    make_user(email="budi@example.com", password_hash=hash_password(PASSWORD))
    fail(client, 5)
    assert_locked(login(client))
    assert login(client, email="budi@example.com").status_code == 200
    assert read_failure(database, "budi@example.com") is None
    fail(client, 2, email="budi@example.com")
    assert read_failure(database, "budi@example.com").failed_attempts == 2
    assert read_failure(database, EMAIL).failed_attempts == 5


def test_an_empty_password_is_not_a_failure(client, database, owner):
    for _ in range(6):
        response = login(client, password="")
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert read_failure(database) is None
    assert login(client).status_code == 200


def test_an_invalid_email_is_not_a_failure(client, database):
    response = login(client, email="not-an-email", password="wrong password")
    assert response.status_code == 422
    assert read_failure(database, "not-an-email") is None


def test_a_validation_failure_does_not_count_towards_the_limit(client, database, owner):
    fail(client, 4)
    assert login(client, password="").status_code == 422
    assert read_failure(database).failed_attempts == 4
    assert read_failure(database).locked_until is None


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_the_lock_works_for_every_role(client, database, make_user, role):
    from app.schemas.auth import UserRole
    from app.services.passwords import hash_password

    make_user(
        email="role@example.com",
        password_hash=hash_password(PASSWORD),
        role=UserRole(role),
    )
    fail(client, 5, email="role@example.com")
    assert_locked(login(client, email="role@example.com"))
    assert count_sessions(database) == 0


def test_a_locked_email_does_not_block_registration_of_others(
    client, database, owner, register_owner
):
    fail(client, 5)
    assert (
        register_owner(
            email="other@example.com", password="T7#vq9-lorem-ipsum"
        ).status_code
        == 201
    )
