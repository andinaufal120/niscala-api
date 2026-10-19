"""The migration that moves previous refresh token hashes into their own table."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import inspect, text

BEFORE = "0010"
AFTER = "0011"

USER_INSERT = text(
    "INSERT INTO user_accounts (id, name, email, role, email_verified, created_at) "
    "VALUES (:id, 'Name', :email, 'owner', false, now())"
)
OLD_SESSION_INSERT = text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, "
    "previous_refresh_token_hash, device_name, platform, login_method, "
    "created_at, last_active_at) "
    "VALUES (:id, :user_id, :hash, :previous, 'Pixel 8', 'Android 14', "
    "'password', now(), now())"
)
NEW_SESSION_INSERT = text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, device_name, platform, "
    "login_method, created_at, last_active_at) "
    "VALUES (:id, :user_id, :hash, 'Pixel 8', 'Android 14', 'password', now(), now())"
)
USED_INSERT = text(
    "INSERT INTO used_refresh_tokens (token_hash, session_id, rotated_at) "
    "VALUES (:hash, :session_id, :rotated_at)"
)


@pytest.fixture
def migrated(database, postgres_url, db_engine):
    """Yield helpers to move the schema; always restore head afterwards."""
    config = alembic_config(postgres_url)
    yield config
    command.upgrade(config, "head")


def add_user(connection) -> object:
    user_id = uuid4()
    connection.execute(USER_INSERT, {"id": user_id, "email": f"{uuid4().hex}@x.com"})
    return user_id


def table_names(db_engine) -> set[str]:
    return set(inspect(db_engine).get_table_names())


def session_columns(db_engine) -> set[str]:
    return {column["name"] for column in inspect(db_engine).get_columns("sessions")}


def test_upgrade_creates_the_used_refresh_tokens_table(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    assert "used_refresh_tokens" not in table_names(db_engine)
    command.upgrade(migrated, AFTER)
    assert "used_refresh_tokens" in table_names(db_engine)


def test_upgrade_creates_the_expected_columns_keys_and_index(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("used_refresh_tokens")}
    assert set(columns) == {"token_hash", "session_id", "rotated_at"}
    assert columns["session_id"]["nullable"] is False
    assert columns["rotated_at"]["type"].timezone is True
    assert inspector.get_pk_constraint("used_refresh_tokens")[
        "constrained_columns"
    ] == ["token_hash"]
    (foreign_key,) = inspector.get_foreign_keys("used_refresh_tokens")
    assert foreign_key["constrained_columns"] == ["session_id"]
    assert foreign_key["referred_table"] == "sessions"
    assert foreign_key["options"].get("ondelete", "").upper() == "CASCADE"
    indexed = [i["column_names"] for i in inspector.get_indexes("used_refresh_tokens")]
    assert ["session_id"] in indexed


def test_upgrade_drops_the_previous_hash_column(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    assert "previous_refresh_token_hash" in session_columns(db_engine)
    command.upgrade(migrated, AFTER)
    assert "previous_refresh_token_hash" not in session_columns(db_engine)


def test_upgrade_copies_non_null_previous_hashes_and_skips_null_ones(
    migrated, db_engine
):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        user_id = add_user(connection)
        with_previous, without_previous = uuid4(), uuid4()
        connection.execute(
            OLD_SESSION_INSERT,
            {
                "id": with_previous,
                "user_id": user_id,
                "hash": "current-a",
                "previous": "previous-a",
            },
        )
        connection.execute(
            OLD_SESSION_INSERT,
            {
                "id": without_previous,
                "user_id": user_id,
                "hash": "current-b",
                "previous": None,
            },
        )
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT token_hash, session_id, rotated_at FROM used_refresh_tokens")
        ).all()
        current = connection.execute(
            text("SELECT refresh_token_hash FROM sessions ORDER BY 1")
        ).scalars()
        assert list(current) == ["current-a", "current-b"]
    assert len(rows) == 1
    token_hash, session_id, rotated_at = rows[0]
    assert token_hash == "previous-a"
    assert session_id == with_previous
    assert rotated_at.tzinfo is not None


def test_upgrade_with_no_sessions_succeeds_and_leaves_the_table_empty(
    migrated, db_engine
):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM used_refresh_tokens")
        ).scalar_one()
    assert count == 0


def test_downgrade_restores_the_column_and_drops_the_table(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    assert "used_refresh_tokens" not in table_names(db_engine)
    assert "previous_refresh_token_hash" in session_columns(db_engine)


def test_downgrade_keeps_the_newest_used_token_of_each_session(migrated, db_engine):
    now = datetime.now(UTC)
    newest_session, single_session, empty_session = uuid4(), uuid4(), uuid4()
    with db_engine.begin() as connection:
        user_id = add_user(connection)
        for session_id, current in (
            (newest_session, "current-a"),
            (single_session, "current-b"),
            (empty_session, "current-c"),
        ):
            connection.execute(
                NEW_SESSION_INSERT,
                {"id": session_id, "user_id": user_id, "hash": current},
            )
        for token, session_id, age in (
            ("oldest", newest_session, 30),
            ("newest", newest_session, 10),
            ("middle", newest_session, 20),
            ("only", single_session, 5),
        ):
            connection.execute(
                USED_INSERT,
                {
                    "hash": token,
                    "session_id": session_id,
                    "rotated_at": now - timedelta(minutes=age),
                },
            )
    command.downgrade(migrated, BEFORE)
    with db_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text("SELECT id, previous_refresh_token_hash FROM sessions")
            ).all()
        )
    assert rows == {
        newest_session: "newest",
        single_session: "only",
        empty_session: None,
    }


def test_downgrade_keeps_current_hashes_untouched(migrated, db_engine):
    session_id = uuid4()
    with db_engine.begin() as connection:
        user_id = add_user(connection)
        connection.execute(
            NEW_SESSION_INSERT,
            {"id": session_id, "user_id": user_id, "hash": "current"},
        )
        connection.execute(
            USED_INSERT,
            {"hash": "old", "session_id": session_id, "rotated_at": datetime.now(UTC)},
        )
    command.downgrade(migrated, BEFORE)
    with db_engine.connect() as connection:
        current = connection.execute(
            text("SELECT refresh_token_hash FROM sessions")
        ).scalar_one()
    assert current == "current"


def test_upgrade_after_downgrade_round_trips_the_newest_used_token(migrated, db_engine):
    session_id = uuid4()
    now = datetime.now(UTC)
    with db_engine.begin() as connection:
        user_id = add_user(connection)
        connection.execute(
            NEW_SESSION_INSERT, {"id": session_id, "user_id": user_id, "hash": "now"}
        )
        for token, age in (("older", 20), ("newer", 10)):
            connection.execute(
                USED_INSERT,
                {
                    "hash": token,
                    "session_id": session_id,
                    "rotated_at": now - timedelta(minutes=age),
                },
            )
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        hashes = connection.execute(
            text("SELECT token_hash FROM used_refresh_tokens")
        ).scalars()
        assert list(hashes) == ["newer"]
