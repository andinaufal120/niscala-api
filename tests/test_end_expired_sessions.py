"""Ending every session that has been idle or open for too long."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session


def days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@pytest.fixture
def add_session(db_session, make_user):
    """Commit a session row with chosen timestamps and used refresh tokens."""
    from app.models import UsedRefreshToken, UserSession
    from app.schemas.sessions import LoginMethod

    def add(
        user=None,
        *,
        idle_days: float = 0,
        age_days: float = 0,
        revoked_at: datetime | None = None,
        used_tokens: int = 0,
    ) -> UserSession:
        owner = user or make_user()
        row = UserSession(
            user_id=owner.id,
            refresh_token_hash=uuid4().hex,
            device_name="Pixel 8",
            platform="Android 14",
            login_method=LoginMethod.PASSWORD,
            created_at=days_ago(max(age_days, idle_days)),
            last_active_at=days_ago(idle_days),
            revoked_at=revoked_at,
        )
        db_session.add(row)
        db_session.flush()
        for _ in range(used_tokens):
            db_session.add(
                UsedRefreshToken(
                    token_hash=uuid4().hex,
                    session_id=row.id,
                    rotated_at=datetime.now(UTC),
                )
            )
        db_session.commit()
        return row

    return add


def reload(db_session, row):
    db_session.expire_all()
    from app.models import UserSession

    return db_session.get(UserSession, row.id)


def used_hashes(db_session, session_id) -> set[str]:
    from app.models import UsedRefreshToken

    return set(
        db_session.scalars(
            select(UsedRefreshToken.token_hash).where(
                UsedRefreshToken.session_id == session_id
            )
        )
    )


def test_a_session_idle_for_more_than_ninety_days_is_ended(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=90.1)
    assert end_expired_sessions(db_session) == 1
    assert reload(db_session, row).revoked_at is not None


def test_a_session_idle_for_less_than_ninety_days_is_kept(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=89.9)
    assert end_expired_sessions(db_session) == 0
    assert reload(db_session, row).revoked_at is None


def test_a_session_older_than_a_year_is_ended_even_when_recently_active(
    db_session, add_session
):
    from app.services.sessions import end_expired_sessions

    row = add_session(age_days=365.1, idle_days=0)
    assert end_expired_sessions(db_session) == 1
    assert reload(db_session, row).revoked_at is not None


def test_a_session_younger_than_a_year_is_kept(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(age_days=364.9, idle_days=10)
    assert end_expired_sessions(db_session) == 0
    assert reload(db_session, row).revoked_at is None


def test_a_session_failing_both_limits_is_ended_once(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(age_days=400, idle_days=200)
    assert end_expired_sessions(db_session) == 1
    assert reload(db_session, row).revoked_at is not None


def test_a_fresh_session_is_kept(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session()
    assert end_expired_sessions(db_session) == 0
    assert reload(db_session, row).revoked_at is None


def test_the_ended_session_is_revoked_at_about_now(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=120)
    before = datetime.now(UTC)
    end_expired_sessions(db_session)
    revoked = reload(db_session, row).revoked_at
    assert before - timedelta(seconds=5) <= revoked <= datetime.now(UTC)


def test_the_count_covers_every_ended_session(db_session, add_session, make_user):
    from app.services.sessions import end_expired_sessions

    first, second = make_user(), make_user()
    add_session(first, idle_days=91)
    add_session(first, age_days=366)
    add_session(second, idle_days=500, age_days=500)
    add_session(second, idle_days=1)
    assert end_expired_sessions(db_session) == 3


def test_returns_zero_when_there_are_no_sessions(db_session):
    from app.services.sessions import end_expired_sessions

    assert end_expired_sessions(db_session) == 0


def test_a_second_call_ends_nothing(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    add_session(idle_days=120)
    add_session(age_days=400)
    assert end_expired_sessions(db_session) == 2
    assert end_expired_sessions(db_session) == 0


def test_an_already_revoked_session_is_not_touched_or_counted(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    revoked_at = days_ago(200)
    row = add_session(idle_days=300, age_days=400, revoked_at=revoked_at)
    assert end_expired_sessions(db_session) == 0
    assert reload(db_session, row).revoked_at == revoked_at


def test_only_the_expired_sessions_of_a_user_are_ended(
    db_session, add_session, make_user
):
    from app.services.sessions import end_expired_sessions

    user = make_user()
    expired = add_session(user, idle_days=100)
    live = add_session(user, idle_days=1)
    other_live = add_session(user, idle_days=89)
    assert end_expired_sessions(db_session) == 1
    assert reload(db_session, expired).revoked_at is not None
    assert reload(db_session, live).revoked_at is None
    assert reload(db_session, other_live).revoked_at is None


def test_sessions_of_other_users_are_ended_independently(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    expired = add_session(idle_days=100)
    live = add_session(idle_days=2)
    end_expired_sessions(db_session)
    assert reload(db_session, expired).revoked_at is not None
    assert reload(db_session, live).revoked_at is None


def test_used_refresh_tokens_of_ended_sessions_are_deleted(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=100, used_tokens=3)
    assert len(used_hashes(db_session, row.id)) == 3
    end_expired_sessions(db_session)
    assert used_hashes(db_session, row.id) == set()


def test_used_refresh_tokens_of_live_sessions_stay(db_session, add_session):
    from app.services.sessions import end_expired_sessions

    expired = add_session(idle_days=100, used_tokens=2)
    live = add_session(idle_days=1, used_tokens=2)
    before = used_hashes(db_session, live.id)
    end_expired_sessions(db_session)
    assert used_hashes(db_session, expired.id) == set()
    assert used_hashes(db_session, live.id) == before
    assert len(before) == 2


def test_used_refresh_tokens_of_a_revoked_session_are_left_alone(
    db_session, add_session
):
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=100, revoked_at=days_ago(50), used_tokens=2)
    before = used_hashes(db_session, row.id)
    end_expired_sessions(db_session)
    assert used_hashes(db_session, row.id) == before


def test_changes_are_flushed_but_not_committed(database, db_session, add_session):
    from app.models import UserSession
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=100, used_tokens=1)
    end_expired_sessions(db_session)
    with Session(database) as other:
        assert other.get(UserSession, row.id).revoked_at is None
    assert db_session.get(UserSession, row.id).revoked_at is not None
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(UserSession, row.id).revoked_at is None
    assert len(used_hashes(db_session, row.id)) == 1


def test_changes_persist_once_the_caller_commits(database, db_session, add_session):
    from app.models import UserSession
    from app.services.sessions import end_expired_sessions

    row = add_session(idle_days=100)
    end_expired_sessions(db_session)
    db_session.commit()
    with Session(database) as other:
        assert other.get(UserSession, row.id).revoked_at is not None
