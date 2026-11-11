"""The subscription columns for billing, and the order and scheduled downgrade tables."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

ENDS_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
CREATED_AT = datetime(2029, 12, 1, 8, 0, 0, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(days=3)


def new_order(owner, **overrides):
    from app.models import SubscriptionOrder

    return SubscriptionOrder(
        **{
            "owner_id": owner.id,
            "plan": "basic",
            "billing_period": "monthly",
            "status": "awaitingPayment",
            "created_at": CREATED_AT,
            "expires_at": EXPIRES_AT,
            **overrides,
        }
    )


def new_schedule(owner, **overrides):
    from app.models import ScheduledDowngrade

    return ScheduledDowngrade(
        **{
            "owner_id": owner.id,
            "plan": "free",
            "kept_property_ids": [],
            "kept_room_ids": [],
            **overrides,
        }
    )


# Subscription columns


def test_a_subscription_row_made_without_billing_details_is_monthly_and_not_renewing(
    db_session, make_user
):
    from app.models import Subscription

    owner = make_user()
    db_session.execute(
        text(
            "INSERT INTO subscriptions (owner_id, plan, ends_at) "
            "VALUES (:owner_id, 'basic', :ends_at)"
        ),
        {"owner_id": owner.id, "ends_at": ENDS_AT},
    )
    row = db_session.get(Subscription, owner.id)
    assert row.billing_period == "monthly"
    assert row.auto_renew is False
    assert row.purchase_token is None


def test_a_subscription_defaults_when_added_through_the_model(db_session, make_user):
    from app.models import Subscription

    owner = make_user()
    row = Subscription(owner_id=owner.id, plan="pro", ends_at=ENDS_AT)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.billing_period == "monthly"
    assert row.auto_renew is False
    assert row.purchase_token is None


def test_a_subscription_round_trips_its_billing_columns(db_session, make_user):
    from app.models import Subscription

    owner = make_user()
    db_session.add(
        Subscription(
            owner_id=owner.id,
            plan="pro",
            ends_at=ENDS_AT,
            billing_period="yearly",
            auto_renew=True,
            purchase_token="token-1",
        )
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(Subscription, owner.id)
    assert row.billing_period == "yearly"
    assert row.auto_renew is True
    assert row.purchase_token == "token-1"


def test_a_purchase_token_belongs_to_one_subscription(db_session, make_user):
    from app.models import Subscription

    db_session.add(
        Subscription(
            owner_id=make_user().id, plan="basic", ends_at=ENDS_AT, purchase_token="t"
        )
    )
    db_session.flush()
    db_session.add(
        Subscription(
            owner_id=make_user().id, plan="pro", ends_at=ENDS_AT, purchase_token="t"
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_subscriptions_without_a_purchase_token_do_not_clash(db_session, make_user):
    from app.models import Subscription

    db_session.add_all(
        [
            Subscription(owner_id=make_user().id, plan="basic", ends_at=ENDS_AT),
            Subscription(owner_id=make_user().id, plan="pro", ends_at=ENDS_AT),
        ]
    )
    db_session.flush()


# Orders


def test_the_order_model_is_registered_on_the_metadata():
    from app.models import Base, SubscriptionOrder

    assert SubscriptionOrder.__tablename__ == "subscription_orders"
    assert "subscription_orders" in Base.metadata.tables


def test_migrations_create_the_order_table(database):
    assert inspect(database).has_table("subscription_orders")


def test_an_order_round_trips_its_fields(db_session, make_user):
    from app.models import SubscriptionOrder

    owner = make_user()
    order = new_order(
        owner, plan="pro", billing_period="yearly", purchase_token="token-9"
    )
    db_session.add(order)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(SubscriptionOrder, order.id)
    assert stored.owner_id == owner.id
    assert stored.plan == "pro"
    assert stored.billing_period == "yearly"
    assert stored.status == "awaitingPayment"
    assert stored.purchase_token == "token-9"
    assert stored.created_at == CREATED_AT
    assert stored.expires_at == EXPIRES_AT
    assert stored.created_at.utcoffset() == timedelta(0)


def test_an_order_gets_an_id_when_added(db_session, make_user):
    order = new_order(make_user())
    db_session.add(order)
    db_session.flush()
    assert order.id is not None


def test_an_owner_can_have_many_orders(db_session, make_user):
    owner = make_user()
    db_session.add_all([new_order(owner), new_order(owner), new_order(owner)])
    db_session.flush()


def test_the_purchase_token_of_an_order_is_optional(db_session, make_user):
    order = new_order(make_user())
    db_session.add(order)
    db_session.flush()
    db_session.refresh(order)
    assert order.purchase_token is None


def test_a_purchase_token_belongs_to_one_order(db_session, make_user):
    db_session.add(new_order(make_user(), purchase_token="same"))
    db_session.flush()
    db_session.add(new_order(make_user(), purchase_token="same"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_orders_without_a_purchase_token_do_not_clash(db_session, make_user):
    db_session.add_all([new_order(make_user()), new_order(make_user())])
    db_session.flush()


@pytest.mark.parametrize(
    "column", ["owner_id", "plan", "billing_period", "status", "expires_at"]
)
def test_required_order_columns_reject_null(db_session, make_user, column):
    db_session.add(new_order(make_user(), **{column: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_creation_time_of_an_order_defaults_to_now(db_session, make_user):
    from app.models import SubscriptionOrder

    order = SubscriptionOrder(
        owner_id=make_user().id,
        plan="basic",
        billing_period="monthly",
        status="awaitingPayment",
        expires_at=EXPIRES_AT,
    )
    before = datetime.now(UTC)
    db_session.add(order)
    db_session.flush()
    db_session.refresh(order)
    assert before - timedelta(minutes=1) <= order.created_at <= datetime.now(UTC)


def test_the_owner_of_an_order_must_exist(db_session):
    db_session.add(new_order(SimpleNamespace(id=uuid4())))
    with pytest.raises(IntegrityError):
        db_session.flush()


# Scheduled downgrades


def test_the_scheduled_downgrade_model_is_registered_on_the_metadata():
    from app.models import Base, ScheduledDowngrade

    assert ScheduledDowngrade.__tablename__ == "scheduled_downgrades"
    assert "scheduled_downgrades" in Base.metadata.tables


def test_migrations_create_the_scheduled_downgrade_table(database):
    assert inspect(database).has_table("scheduled_downgrades")


def test_a_scheduled_downgrade_round_trips_its_fields(db_session, make_user):
    from app.models import ScheduledDowngrade

    owner = make_user()
    properties = [uuid4(), uuid4()]
    rooms = [uuid4(), uuid4(), uuid4()]
    db_session.add(
        new_schedule(owner, kept_property_ids=properties, kept_room_ids=rooms)
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ScheduledDowngrade, owner.id)
    assert stored.plan == "free"
    assert stored.kept_property_ids == properties
    assert stored.kept_room_ids == rooms


def test_an_empty_list_of_ids_is_stored_as_empty(db_session, make_user):
    from app.models import ScheduledDowngrade

    owner = make_user()
    db_session.add(new_schedule(owner))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ScheduledDowngrade, owner.id)
    assert stored.kept_property_ids == []
    assert stored.kept_room_ids == []


def test_the_owner_is_the_primary_key_of_a_scheduled_downgrade(db_session, make_user):
    from app.models import ScheduledDowngrade

    owner = make_user()
    db_session.add(new_schedule(owner))
    db_session.flush()
    assert db_session.get(ScheduledDowngrade, owner.id).owner_id == owner.id


def test_an_owner_has_at_most_one_scheduled_downgrade(db_session, make_user):
    owner = make_user()
    db_session.add(new_schedule(owner))
    db_session.flush()
    db_session.add(new_schedule(owner, plan="basic"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "column", ["owner_id", "plan", "kept_property_ids", "kept_room_ids"]
)
def test_required_scheduled_downgrade_columns_reject_null(
    db_session, make_user, column
):
    db_session.add(new_schedule(make_user(), **{column: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_owner_of_a_scheduled_downgrade_must_exist(db_session):
    db_session.add(new_schedule(SimpleNamespace(id=uuid4())))
    with pytest.raises(IntegrityError):
        db_session.flush()
