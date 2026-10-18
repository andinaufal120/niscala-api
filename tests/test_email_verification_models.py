"""The `email_verification_codes` table and its model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

CODE_INSERT = text(
    "INSERT INTO email_verification_codes "
    "(user_id, code_hash, created_at, expires_at, failed_attempts) "
    "VALUES (:user_id, 'h', now(), now() + interval '10 minutes', :attempts)"
)


def new_user(db_session):
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    user = UserAccount(
        name="Rina Owner",
        email=f"{uuid4().hex}@example.com",
        password_hash=None,
        role=UserRole.OWNER,
    )
    db_session.add(user)
    db_session.flush()
    return user


def new_code(user_id, **overrides):
    from app.models import EmailVerificationCode

    now = datetime.now(UTC)
    fields = {
        "user_id": user_id,
        "code_hash": "a" * 64,
        "created_at": now,
        "expires_at": now + timedelta(minutes=10),
    }
    return EmailVerificationCode(**{**fields, **overrides})


def test_model_is_registered_on_the_metadata():
    from app.models import Base, EmailVerificationCode

    assert EmailVerificationCode.__tablename__ == "email_verification_codes"
    assert "email_verification_codes" in Base.metadata.tables


def test_migrations_create_the_table(database):
    assert inspect(database).has_table("email_verification_codes")


def test_code_round_trips_its_fields(db_session):
    from app.models import EmailVerificationCode

    user = new_user(db_session)
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    expires = created + timedelta(minutes=10)
    db_session.add(
        new_code(
            user.id,
            code_hash="b" * 64,
            created_at=created,
            expires_at=expires,
            failed_attempts=3,
        )
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(EmailVerificationCode, user.id)
    assert stored.code_hash == "b" * 64
    assert stored.created_at == created
    assert stored.created_at.utcoffset() == timedelta(0)
    assert stored.expires_at == expires
    assert stored.expires_at.utcoffset() == timedelta(0)
    assert stored.failed_attempts == 3


def test_failed_attempts_default_to_zero(db_session):
    user = new_user(db_session)
    row = new_code(user.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.failed_attempts == 0


def test_user_id_is_the_primary_key(db_session):
    from app.models import EmailVerificationCode

    user = new_user(db_session)
    db_session.add(new_code(user.id))
    db_session.flush()
    assert db_session.get(EmailVerificationCode, user.id).user_id == user.id


def test_user_has_at_most_one_code(db_session):
    user = new_user(db_session)
    db_session.add(new_code(user.id))
    db_session.flush()
    db_session.add(new_code(user.id, code_hash="c" * 64))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_several_users_can_each_have_a_code(db_session):
    first, second = new_user(db_session), new_user(db_session)
    db_session.add_all([new_code(first.id), new_code(second.id)])
    db_session.flush()


def test_code_requires_an_existing_user(db_session):
    db_session.add(new_code(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["user_id", "code_hash", "expires_at"])
def test_code_requires_its_mandatory_columns(db_session, field):
    user = new_user(db_session)
    db_session.add(new_code(**{"user_id": user.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_failed_attempts_cannot_be_negative(db_session):
    user = new_user(db_session)
    db_session.add(new_code(user.id, failed_attempts=-1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_negative_failed_attempts(db_session):
    user = new_user(db_session)
    with pytest.raises(IntegrityError):
        db_session.execute(CODE_INSERT, {"user_id": user.id, "attempts": -1})


@pytest.mark.parametrize("attempts", [0, 1, 5, 6])
def test_database_accepts_non_negative_failed_attempts(db_session, attempts):
    user = new_user(db_session)
    db_session.execute(CODE_INSERT, {"user_id": user.id, "attempts": attempts})
