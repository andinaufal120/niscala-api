"""The session records when it last re-authenticated."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session


def test_a_new_session_has_not_re_authenticated(
    database, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_the_column_round_trips_a_timezone_aware_value(
    database, make_user, sign_in, read_session
):
    from app.models import UserSession

    signed_in = sign_in(make_user())
    moment = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    with Session(database) as db:
        db.get(UserSession, signed_in.session_id).reauthenticated_at = moment
        db.commit()
    stored = read_session(signed_in.session_id).reauthenticated_at
    assert stored == moment
    assert stored.utcoffset() == timedelta(0)


def test_the_column_can_be_cleared_again(database, make_user, sign_in, read_session):
    from app.models import UserSession

    signed_in = sign_in(make_user())
    with Session(database) as db:
        db.get(UserSession, signed_in.session_id).reauthenticated_at = datetime.now(UTC)
        db.commit()
    with Session(database) as db:
        db.get(UserSession, signed_in.session_id).reauthenticated_at = None
        db.commit()
    assert read_session(signed_in.session_id).reauthenticated_at is None
