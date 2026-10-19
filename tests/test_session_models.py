"""The `user_accounts` and `sessions` tables and their models."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

USER_INSERT = text(
    "INSERT INTO user_accounts (id, name, email, role, email_verified, created_at) "
    "VALUES (:id, 'Name', :email, :role, false, now())"
)
SESSION_INSERT = text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, device_name, platform, "
    "login_method, created_at, last_active_at) "
    "VALUES (:id, :user_id, :hash, 'Pixel 8', 'Android 14', :method, now(), now())"
)


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


def new_session(user_id, **overrides):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod

    fields = {
        "user_id": user_id,
        "refresh_token_hash": uuid4().hex,
        "device_name": "Pixel 8",
        "platform": "Android 14",
        "login_method": LoginMethod.PASSWORD,
    }
    return UserSession(**{**fields, **overrides})


def test_models_are_registered_on_the_metadata():
    from app.models import Base

    assert {"user_accounts", "sessions"} <= set(Base.metadata.tables)


def test_models_use_the_expected_table_names():
    from app.models import UserAccount, UserSession

    assert UserAccount.__tablename__ == "user_accounts"
    assert UserSession.__tablename__ == "sessions"


def test_user_account_gets_defaults_on_insert(db_session):
    before = datetime.now(UTC)
    user = new_user()
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    assert isinstance(user.id, UUID)
    assert user.email_verified is False
    assert user.created_at.tzinfo is not None
    assert user.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= user.created_at <= datetime.now(UTC)


def test_user_account_ids_are_unique_per_row(db_session):
    first, second = new_user(), new_user()
    db_session.add_all([first, second])
    db_session.flush()
    assert first.id != second.id


def test_user_account_round_trips_its_fields(db_session):
    from app.schemas.auth import UserRole

    user = new_user(
        name="Budi", password_hash="hash", role=UserRole.MANAGER, email_verified=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(user), user.id)
    assert stored.name == "Budi"
    assert stored.password_hash == "hash"
    assert stored.role == UserRole.MANAGER
    assert stored.email_verified is True


def test_user_account_email_is_stored_trimmed_and_lower_case(db_session):
    user = new_user(email="  Rina.Owner@Example.COM \n")
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    assert user.email == "rina.owner@example.com"


def test_user_account_accepts_missing_email_and_password_hash(db_session):
    user = new_user(email=None, password_hash=None)
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    assert user.email is None
    assert user.password_hash is None


def test_user_accounts_without_email_can_coexist(db_session):
    db_session.add_all([new_user(email=None), new_user(email=None)])
    db_session.flush()


def test_user_account_email_must_be_unique(db_session):
    db_session.add(new_user(email="same@example.com"))
    db_session.flush()
    db_session.add(new_user(email="same@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_account_email_uniqueness_ignores_case(db_session):
    db_session.add(new_user(email="same@example.com"))
    db_session.flush()
    db_session.add(new_user(email="SAME@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_account_name_is_required(db_session):
    db_session.add(new_user(name=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_account_role_is_required(db_session):
    db_session.add(new_user(role=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("role", ["tenant", "owner", "manager", "admin"])
def test_database_accepts_each_known_role(db_session, role):
    db_session.execute(
        USER_INSERT, {"id": uuid4(), "email": "a@example.com", "role": role}
    )


def test_database_rejects_an_unknown_role(db_session):
    with pytest.raises(IntegrityError):
        db_session.execute(
            USER_INSERT,
            {"id": uuid4(), "email": "a@example.com", "role": "superuser"},
        )


def test_user_session_gets_defaults_on_insert(db_session):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    before = datetime.now(UTC)
    row = new_session(user.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.revoked_at is None
    for stamp in (row.created_at, row.last_active_at):
        assert stamp.tzinfo is not None
        assert stamp.utcoffset() == timedelta(0)
        assert before - timedelta(minutes=1) <= stamp <= datetime.now(UTC)


def test_user_session_round_trips_its_fields(db_session):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod

    user = new_user()
    db_session.add(user)
    db_session.flush()
    revoked = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = new_session(
        user.id,
        refresh_token_hash="abc",
        device_name="Galaxy",
        platform="Android 13",
        login_method=LoginMethod.GOOGLE,
        revoked_at=revoked,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(UserSession, row.id)
    assert stored.user_id == user.id
    assert stored.refresh_token_hash == "abc"
    assert stored.device_name == "Galaxy"
    assert stored.platform == "Android 13"
    assert stored.login_method == LoginMethod.GOOGLE
    assert stored.revoked_at == revoked


def test_user_session_refresh_token_hash_must_be_unique(db_session):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(new_session(user.id, refresh_token_hash="dup"))
    db_session.flush()
    db_session.add(new_session(user.id, refresh_token_hash="dup"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_session_requires_an_existing_user(db_session):
    db_session.add(new_session(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field",
    ["user_id", "refresh_token_hash", "device_name", "platform", "login_method"],
)
def test_user_session_requires_its_mandatory_columns(db_session, field):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(new_session(**{"user_id": user.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_session_revoked_at_accepts_none(db_session):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    row = new_session(user.id, revoked_at=None)
    db_session.add(row)
    db_session.flush()


def test_user_session_no_longer_stores_a_previous_refresh_token_hash():
    from app.models import UserSession

    assert "previous_refresh_token_hash" not in UserSession.__table__.columns


def test_database_sessions_table_has_no_previous_refresh_token_hash_column(database):
    from sqlalchemy import inspect

    columns = {c["name"] for c in inspect(database).get_columns("sessions")}
    assert "previous_refresh_token_hash" not in columns


def new_used_token(session_id, **overrides):
    from app.models import UsedRefreshToken

    fields = {
        "token_hash": uuid4().hex,
        "session_id": session_id,
        "rotated_at": datetime.now(UTC),
    }
    return UsedRefreshToken(**{**fields, **overrides})


def stored_session(db_session):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    row = new_session(user.id)
    db_session.add(row)
    db_session.flush()
    return row


def test_used_refresh_token_model_is_registered_and_exported():
    from app.models import Base, UsedRefreshToken

    assert UsedRefreshToken.__tablename__ == "used_refresh_tokens"
    assert "used_refresh_tokens" in Base.metadata.tables


def test_used_refresh_token_has_the_expected_columns():
    from app.models import UsedRefreshToken

    table = UsedRefreshToken.__table__
    assert set(table.columns.keys()) == {"token_hash", "session_id", "rotated_at"}
    assert [c.name for c in table.primary_key.columns] == ["token_hash"]


def test_used_refresh_token_round_trips_its_fields(db_session):
    from app.models import UsedRefreshToken

    session = stored_session(db_session)
    rotated = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    db_session.add(new_used_token(session.id, token_hash="old", rotated_at=rotated))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(UsedRefreshToken, "old")
    assert stored.session_id == session.id
    assert stored.rotated_at == rotated
    assert stored.rotated_at.utcoffset() == timedelta(0)


def test_used_refresh_token_hash_must_be_unique(db_session):
    session = stored_session(db_session)
    db_session.add(new_used_token(session.id, token_hash="dup"))
    db_session.flush()
    db_session.add(new_used_token(session.id, token_hash="dup"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_used_refresh_token_hash_is_unique_across_sessions(db_session):
    first, second = stored_session(db_session), stored_session(db_session)
    db_session.add(new_used_token(first.id, token_hash="dup"))
    db_session.flush()
    db_session.add(new_used_token(second.id, token_hash="dup"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_used_refresh_token_requires_an_existing_session(db_session):
    db_session.add(new_used_token(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["token_hash", "session_id"])
def test_used_refresh_token_requires_its_key_columns(db_session, field):
    session = stored_session(db_session)
    db_session.add(new_used_token(**{"session_id": session.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_session_can_have_many_used_refresh_tokens(db_session):
    session = stored_session(db_session)
    db_session.add_all([new_used_token(session.id) for _ in range(3)])
    db_session.flush()


def test_deleting_a_session_deletes_its_used_refresh_tokens(db_session):
    from sqlalchemy import delete, func, select

    from app.models import UsedRefreshToken, UserSession

    doomed, kept = stored_session(db_session), stored_session(db_session)
    db_session.add_all(
        [new_used_token(doomed.id), new_used_token(doomed.id), new_used_token(kept.id)]
    )
    db_session.flush()
    db_session.execute(delete(UserSession).where(UserSession.id == doomed.id))
    remaining = db_session.scalars(select(UsedRefreshToken.session_id)).all()
    assert remaining == [kept.id]
    assert db_session.scalar(select(func.count()).select_from(UsedRefreshToken)) == 1


def test_database_cascades_session_deletion_to_used_refresh_tokens(db_session):
    session = stored_session(db_session)
    db_session.add(new_used_token(session.id, token_hash="old"))
    db_session.flush()
    db_session.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session.id})
    count = db_session.execute(
        text("SELECT count(*) FROM used_refresh_tokens WHERE token_hash = 'old'")
    ).scalar_one()
    assert count == 0


def test_used_refresh_tokens_session_id_is_indexed(database):
    from sqlalchemy import inspect

    indexes = inspect(database).get_indexes("used_refresh_tokens")
    assert ["session_id"] in [index["column_names"] for index in indexes]


@pytest.mark.parametrize("method", ["google", "password"])
def test_database_accepts_each_known_login_method(db_session, method):
    user_id = uuid4()
    db_session.execute(
        USER_INSERT, {"id": user_id, "email": "a@example.com", "role": "owner"}
    )
    db_session.execute(
        SESSION_INSERT,
        {"id": uuid4(), "user_id": user_id, "hash": "h", "method": method},
    )


def test_database_rejects_an_unknown_login_method(db_session):
    user_id = uuid4()
    db_session.execute(
        USER_INSERT, {"id": user_id, "email": "a@example.com", "role": "owner"}
    )
    with pytest.raises(IntegrityError):
        db_session.execute(
            SESSION_INSERT,
            {"id": uuid4(), "user_id": user_id, "hash": "h", "method": "facebook"},
        )


def test_user_can_have_several_sessions(db_session):
    user = new_user()
    db_session.add(user)
    db_session.flush()
    db_session.add_all([new_session(user.id), new_session(user.id)])
    db_session.flush()
