"""The Google identity columns of `user_accounts`."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from conftest import alembic_config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def new_user(**overrides):
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    fields = {
        "name": "Rina Owner",
        "email": f"{uuid4().hex}@example.com",
        "password_hash": None,
        "role": UserRole.OWNER,
    }
    return UserAccount(**{**fields, **overrides})


def columns(database) -> dict:
    return {c["name"]: c for c in inspect(database).get_columns("user_accounts")}


@pytest.mark.parametrize("name", ["google_subject", "google_email"])
def test_the_column_exists_and_may_be_empty(database, name):
    found = columns(database)
    assert name in found
    assert found[name]["nullable"] is True


@pytest.mark.parametrize("name", ["google_subject", "google_email"])
def test_the_column_holds_text(database, name):
    assert columns(database)[name]["type"].python_type is str


@pytest.mark.parametrize("name", ["google_subject", "google_email"])
def test_the_model_attribute_is_empty_by_default(db_session, name):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    assert getattr(user, name) is None


def test_the_columns_round_trip(db_session):
    user = new_user(google_subject="1234567890", google_email="rina@gmail.example")
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(user), user.id)
    assert stored.google_subject == "1234567890"
    assert stored.google_email == "rina@gmail.example"


def test_the_subject_may_be_set_without_a_google_email(db_session):
    user = new_user(google_subject="1234567890")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.google_email is None


def test_the_subject_is_unique(db_session):
    db_session.add(new_user(google_subject="same-subject"))
    db_session.flush()
    db_session.add(new_user(google_subject="same-subject"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_subject_is_unique_even_for_a_deleted_account(db_session):
    from datetime import UTC, datetime

    db_session.add(
        new_user(google_subject="same-subject", deleted_at=datetime.now(UTC))
    )
    db_session.flush()
    db_session.add(new_user(google_subject="same-subject"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_different_subjects_may_coexist(db_session):
    db_session.add_all(
        [new_user(google_subject="first"), new_user(google_subject="second")]
    )
    db_session.flush()


def test_many_accounts_may_have_no_subject(db_session):
    db_session.add_all([new_user(), new_user(), new_user(google_subject=None)])
    db_session.flush()


def test_the_database_enforces_the_unique_subject(database):
    insert = text(
        "INSERT INTO user_accounts (id, name, email, role, email_verified, "
        "created_at, google_subject) "
        "VALUES (:id, 'Name', :email, 'owner', true, now(), 'dup')"
    )
    with database.connect() as connection:
        connection.execute(insert, {"id": uuid4(), "email": "a@example.com"})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {"id": uuid4(), "email": "b@example.com"})
        connection.rollback()


def test_the_migration_follows_the_previous_revision(postgres_url):
    script = ScriptDirectory.from_config(alembic_config(postgres_url))
    revision = script.get_revision("0020")
    assert revision is not None
    assert revision.down_revision == "0019"


def test_downgrading_the_migration_drops_the_columns_and_upgrading_restores_them(
    database, postgres_url
):
    config = alembic_config(postgres_url)
    try:
        command.downgrade(config, "0019")
        found = {c["name"] for c in inspect(database).get_columns("user_accounts")}
        assert "google_subject" not in found
        assert "google_email" not in found
    finally:
        command.upgrade(config, "head")
    found = {c["name"] for c in inspect(database).get_columns("user_accounts")}
    assert {"google_subject", "google_email"} <= found
