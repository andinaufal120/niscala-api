"""The `subscriptions` table and its model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

ENDS_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)

SUBSCRIPTION_INSERT = text(
    "INSERT INTO subscriptions (owner_id, plan, ends_at) "
    "VALUES (:owner_id, :plan, :ends_at)"
)


def new_subscription(owner, **overrides):
    from app.models import Subscription

    return Subscription(
        **{"owner_id": owner.id, "plan": "basic", "ends_at": ENDS_AT, **overrides}
    )


def test_model_is_registered_on_the_metadata():
    from app.models import Base, Subscription

    assert Subscription.__tablename__ == "subscriptions"
    assert "subscriptions" in Base.metadata.tables


def test_migrations_create_the_table(database):
    assert inspect(database).has_table("subscriptions")


def test_subscription_round_trips_its_fields(db_session, make_user):
    from app.models import Subscription

    owner = make_user()
    db_session.add(new_subscription(owner, plan="pro"))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(Subscription, owner.id)
    assert stored.plan == "pro"
    assert stored.ends_at == ENDS_AT
    assert stored.ends_at.utcoffset() == timedelta(0)


def test_created_at_defaults_to_now(db_session, make_user):
    owner = make_user()
    row = new_subscription(owner)
    before = datetime.now(UTC)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_owner_id_is_the_primary_key(db_session, make_user):
    from app.models import Subscription

    owner = make_user()
    db_session.add(new_subscription(owner))
    db_session.flush()
    assert db_session.get(Subscription, owner.id).owner_id == owner.id


def test_an_owner_has_at_most_one_subscription(db_session, make_user):
    owner = make_user()
    db_session.add(new_subscription(owner))
    db_session.flush()
    db_session.add(new_subscription(owner, plan="pro"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_several_owners_can_each_have_a_subscription(db_session, make_user):
    db_session.add_all([new_subscription(make_user()), new_subscription(make_user())])
    db_session.flush()


@pytest.mark.parametrize("column", ["owner_id", "plan", "ends_at"])
def test_required_columns_reject_null(db_session, make_user, column):
    row = new_subscription(make_user(), **{column: None})
    db_session.add(row)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_owner_must_exist(db_session):
    with pytest.raises(IntegrityError):
        db_session.execute(
            SUBSCRIPTION_INSERT,
            {"owner_id": uuid4(), "plan": "basic", "ends_at": ENDS_AT},
        )


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_database_accepts_paid_plans(db_session, make_user, plan):
    db_session.execute(
        SUBSCRIPTION_INSERT,
        {"owner_id": make_user().id, "plan": plan, "ends_at": ENDS_AT},
    )


@pytest.mark.parametrize("plan", ["free", "gold", ""])
def test_database_rejects_other_plans(db_session, make_user, plan):
    with pytest.raises(IntegrityError):
        db_session.execute(
            SUBSCRIPTION_INSERT,
            {"owner_id": make_user().id, "plan": plan, "ends_at": ENDS_AT},
        )
