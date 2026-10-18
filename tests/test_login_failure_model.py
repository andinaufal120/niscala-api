"""The `login_failures` table and its model."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

FAILURE_INSERT = text(
    "INSERT INTO login_failures (email, failed_attempts) VALUES (:email, :attempts)"
)


def new_failure(**overrides):
    from app.models import LoginFailure

    return LoginFailure(**{"email": "rina@example.com", **overrides})


def test_model_is_registered_on_the_metadata():
    from app.models import Base, LoginFailure

    assert LoginFailure.__tablename__ == "login_failures"
    assert "login_failures" in Base.metadata.tables


def test_migrations_create_the_table(database):
    assert inspect(database).has_table("login_failures")


def test_failure_round_trips_its_fields(db_session):
    from app.models import LoginFailure

    locked = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    db_session.add(new_failure(failed_attempts=5, locked_until=locked))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(LoginFailure, "rina@example.com")
    assert stored.failed_attempts == 5
    assert stored.locked_until == locked
    assert stored.locked_until.utcoffset() == timedelta(0)


def test_failed_attempts_default_to_zero(db_session):
    row = new_failure()
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.failed_attempts == 0


def test_locked_until_is_empty_by_default(db_session):
    row = new_failure()
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.locked_until is None


def test_email_is_the_primary_key(db_session):
    from app.models import LoginFailure

    db_session.add(new_failure())
    db_session.flush()
    assert db_session.get(LoginFailure, "rina@example.com").email == "rina@example.com"


def test_an_email_has_at_most_one_row(db_session):
    db_session.add(new_failure())
    db_session.flush()
    db_session.add(new_failure(failed_attempts=2))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_several_emails_can_each_have_a_row(db_session):
    db_session.add_all(
        [new_failure(email="a@example.com"), new_failure(email="b@example.com")]
    )
    db_session.flush()


def test_email_is_required(db_session):
    db_session.add(new_failure(email=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_failed_attempts_cannot_be_negative(db_session):
    db_session.add(new_failure(failed_attempts=-1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_negative_failed_attempts(db_session):
    with pytest.raises(IntegrityError):
        db_session.execute(FAILURE_INSERT, {"email": "x@example.com", "attempts": -1})


@pytest.mark.parametrize("attempts", [0, 1, 5, 6])
def test_database_accepts_non_negative_failed_attempts(db_session, attempts):
    db_session.execute(FAILURE_INSERT, {"email": "x@example.com", "attempts": attempts})
