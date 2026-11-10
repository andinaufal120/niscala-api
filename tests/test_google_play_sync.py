"""Bringing an owner's subscription and orders in line with a Google Play purchase."""

from datetime import timedelta
from uuid import uuid4

import pytest
from google_play_support import (
    ENDED_STATES,
    RUNNING_STATES,
    all_orders,
    current_plan_of,
    everything,
    now,
    set_token,
    subscription_state,
    sync,
)
from subscription_support import (
    insert_order,
    is_property_view_only,
    is_room_view_only,
    schedule_row,
    set_subscription,
    store_schedule,
    stored_order,
)

TOKEN = "play-token-1"
OLD_TOKEN = "play-token-0"


def in_days(days: float):
    return now() + timedelta(days=days)


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def running(database, owner):
    """The owner holds a running basic subscription bought with OLD_TOKEN."""
    set_subscription(
        database,
        owner,
        plan="basic",
        billing_period="monthly",
        ends_at=in_days(5),
        auto_renew=True,
    )
    set_token(database, owner, OLD_TOKEN)


# Owners without a running subscription adopt the purchase


@pytest.mark.parametrize("state", RUNNING_STATES)
def test_an_owner_without_a_subscription_gets_the_purchase(
    database, play, owner, state
):
    expiry = in_days(30)
    play.add(
        TOKEN,
        owner=owner,
        state=state,
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
        auto_renewing=False,
    )
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == (
        "pro",
        "yearly",
        expiry,
        False,
        TOKEN,
    )
    assert current_plan_of(database, owner) == "pro"


def test_a_canceled_purchase_with_time_left_keeps_the_plan_running(
    database, play, owner
):
    play.add(
        TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=in_days(10),
    )
    sync(database, play, TOKEN)
    assert current_plan_of(database, owner) == "basic"
    assert subscription_state(database, owner)[3] is False


def test_an_owner_whose_subscription_ended_adopts_an_unrelated_purchase(
    database, play, owner
):
    set_subscription(database, owner, plan="pro", ends_at=in_days(-3))
    set_token(database, owner, OLD_TOKEN)
    expiry = in_days(30)
    play.add(TOKEN, owner=owner, expiry_time=expiry)
    sync(database, play, TOKEN)
    plan, _, ends_at, _, token = subscription_state(database, owner)
    assert (plan, ends_at, token) == ("basic", expiry, TOKEN)


def test_an_owner_whose_ended_subscription_had_no_token_adopts_the_purchase(
    database, play, owner
):
    set_subscription(database, owner, plan="pro", ends_at=in_days(-3))
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert subscription_state(database, owner)[4] == TOKEN
    assert current_plan_of(database, owner) == "basic"


# Owners with a running subscription


def test_a_renewal_of_the_current_token_extends_the_period(
    database, play, owner, running
):
    expiry = in_days(35)
    play.add(OLD_TOKEN, owner=owner, expiry_time=expiry, auto_renewing=True)
    sync(database, play, OLD_TOKEN)
    state = subscription_state(database, owner)
    assert state[2] == expiry
    assert state[4] == OLD_TOKEN


def test_switching_off_renewal_updates_auto_renew(database, play, owner, running):
    expiry = in_days(5)
    play.add(
        OLD_TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=expiry,
    )
    sync(database, play, OLD_TOKEN)
    state = subscription_state(database, owner)
    assert state[3] is False
    assert state[2] == expiry
    assert current_plan_of(database, owner) == "basic"


def test_switching_renewal_back_on_updates_auto_renew(database, play, owner):
    set_subscription(
        database, owner, plan="basic", ends_at=in_days(5), auto_renew=False
    )
    set_token(database, owner, OLD_TOKEN)
    play.add(OLD_TOKEN, owner=owner, auto_renewing=True, expiry_time=in_days(5))
    sync(database, play, OLD_TOKEN)
    assert subscription_state(database, owner)[3] is True


def test_an_upgrade_linked_to_the_current_token_replaces_the_subscription(
    database, play, owner, running
):
    expiry = in_days(365)
    play.add(
        TOKEN,
        owner=owner,
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
        linked_purchase_token=OLD_TOKEN,
    )
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == (
        "pro",
        "yearly",
        expiry,
        True,
        TOKEN,
    )


def test_a_purchase_linked_to_another_token_is_left_alone(
    database, play, owner, running
):
    before = subscription_state(database, owner)
    play.add(TOKEN, owner=owner, product_id="niscala_pro", linked_purchase_token="x")
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == before


def test_an_unrelated_token_does_not_replace_a_running_subscription(
    database, play, owner, running
):
    before = subscription_state(database, owner)
    play.add(TOKEN, owner=owner, product_id="niscala_pro", base_plan_id="yearly")
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == before
    assert current_plan_of(database, owner) == "basic"


def test_an_unrelated_ended_purchase_does_not_end_a_running_subscription(
    database, play, owner, running
):
    before = subscription_state(database, owner)
    play.add(TOKEN, owner=owner, state="EXPIRED", expiry_time=in_days(-2))
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == before


def test_a_running_subscription_without_a_token_is_not_matched_by_a_purchase_without_a_link(
    database, play, owner
):
    set_subscription(database, owner, plan="pro", ends_at=in_days(20))
    before = subscription_state(database, owner)
    assert before[4] is None
    play.add(TOKEN, owner=owner, linked_purchase_token=None)
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) == before
    assert current_plan_of(database, owner) == "pro"


# Purchases that end the plan


@pytest.mark.parametrize("state", ENDED_STATES)
def test_an_ended_purchase_of_the_current_token_ends_the_plan(
    database, play, owner, running, state
):
    expiry = in_days(-1)
    play.add(OLD_TOKEN, owner=owner, state=state, expiry_time=expiry)
    sync(database, play, OLD_TOKEN)
    assert subscription_state(database, owner)[2] == expiry
    assert current_plan_of(database, owner) == "free"


def test_a_canceled_purchase_past_its_expiry_ends_the_plan(
    database, play, owner, running
):
    expiry = in_days(-1)
    play.add(
        OLD_TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=expiry,
    )
    sync(database, play, OLD_TOKEN)
    assert subscription_state(database, owner)[2] == expiry
    assert current_plan_of(database, owner) == "free"


def test_a_refund_ends_the_plan_at_once(database, play, owner, running):
    refunded_at = now() - timedelta(minutes=5)
    play.add(OLD_TOKEN, owner=owner, state="EXPIRED", expiry_time=refunded_at)
    sync(database, play, OLD_TOKEN)
    assert subscription_state(database, owner)[2] == refunded_at
    assert current_plan_of(database, owner) == "free"


def test_an_ended_upgrade_linked_to_the_current_token_ends_the_plan(
    database, play, owner, running
):
    expiry = in_days(-1)
    play.add(
        TOKEN,
        owner=owner,
        state="EXPIRED",
        product_id="niscala_pro",
        expiry_time=expiry,
        linked_purchase_token=OLD_TOKEN,
    )
    sync(database, play, TOKEN)
    assert subscription_state(database, owner)[2] == expiry
    assert current_plan_of(database, owner) == "free"


def test_a_pending_purchase_of_the_current_token_changes_nothing_for_the_owner(
    database, play, owner
):
    set_subscription(database, owner, plan="basic", ends_at=in_days(3))
    set_token(database, owner, OLD_TOKEN)
    before = subscription_state(database, owner)
    play.add(OLD_TOKEN, owner=owner, state="PENDING")
    sync(database, play, OLD_TOKEN)
    assert subscription_state(database, owner) == before


def test_a_pending_purchase_creates_no_subscription(database, play, owner):
    play.add(TOKEN, owner=owner, state="PENDING")
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) is None


# Purchases that cannot be tied to an owner


@pytest.mark.parametrize(
    "account_id",
    [None, "", "not-a-uuid", str(uuid4())],
    ids=["missing", "empty", "garbage", "unknown-owner"],
)
def test_a_purchase_of_no_known_owner_changes_nothing(
    database, play, owner, account_id
):
    insert_order(database, owner)
    before = everything(database)
    play.add(TOKEN, obfuscated_account_id=account_id)
    sync(database, play, TOKEN)
    assert everything(database) == before


def test_a_purchase_is_adopted_by_its_own_owner_only(database, play, owner, make_user):
    stranger = make_user(name="Other Owner")
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert subscription_state(database, owner) is not None
    assert subscription_state(database, stranger) is None


def test_an_unreachable_google_play_is_reported_and_changes_nothing(
    database, play, owner, running
):
    from app.google_play import GooglePlayUnreachable

    before = everything(database)
    play.unreachable = True
    with pytest.raises(GooglePlayUnreachable):
        sync(database, play, OLD_TOKEN)
    assert everything(database) == before


def test_the_token_is_fetched_from_google_play(database, play, owner):
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert play.fetched == [TOKEN]


# Idempotence


@pytest.mark.parametrize("state", ["ACTIVE", "CANCELED", "EXPIRED", "PENDING"])
def test_syncing_twice_changes_nothing_more(database, play, owner, state):
    expiry = in_days(-1) if state == "EXPIRED" else in_days(10)
    play.add(TOKEN, owner=owner, state=state, expiry_time=expiry)
    insert_order(database, owner, plan="basic", billing_period="monthly")
    sync(database, play, TOKEN)
    once = everything(database)
    state_once = subscription_state(database, owner)
    sync(database, play, TOKEN)
    assert everything(database) == once
    assert subscription_state(database, owner) == state_once


# Orders


def test_an_order_holding_the_token_succeeds_when_it_is_paid(
    database, play, owner, make_property
):
    prop = make_property(owner, view_only=True)
    bought = insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner, state="ACTIVE")
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "succeeded"
    assert not is_property_view_only(database, prop)


def test_a_paid_order_restores_editability_and_drops_the_scheduled_downgrade(
    database, play, owner, make_property, make_room
):
    prop = make_property(owner, view_only=True)
    room = make_room(prop, view_only=True)
    store_schedule(database, owner, "free", property_ids=[prop.id])
    insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert not is_property_view_only(database, prop)
    assert not is_room_view_only(database, room)
    assert schedule_row(database, owner) is None


@pytest.mark.parametrize("state", ["IN_GRACE_PERIOD", "CANCELED"])
def test_those_running_states_succeed_a_pending_order_too(database, play, owner, state):
    bought = insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner, state=state, expiry_time=in_days(10))
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "succeeded"


def test_a_pending_purchase_keeps_its_order_awaiting_payment(
    database, play, owner, make_property
):
    prop = make_property(owner, view_only=True)
    bought = insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner, state="PENDING")
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "awaitingPayment"
    assert is_property_view_only(database, prop)


@pytest.mark.parametrize("state", ["PENDING_PURCHASE_CANCELED", "EXPIRED"])
def test_a_canceled_purchase_fails_its_order(database, play, owner, state):
    bought = insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner, state=state, expiry_time=in_days(-1))
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "failed"


def test_an_order_that_already_succeeded_stays_succeeded(database, play, owner):
    bought = insert_order(database, owner, status="succeeded", purchase_token=TOKEN)
    play.add(TOKEN, owner=owner, state="EXPIRED", expiry_time=in_days(-1))
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "succeeded"


@pytest.mark.parametrize("status", ["failed", "expired"])
def test_a_closed_order_is_not_reopened(database, play, owner, status):
    closed = insert_order(database, owner, status=status, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert stored_order(database, closed.id).status == status


def test_the_newest_awaiting_order_for_the_product_succeeds_without_a_token(
    database, play, owner
):
    older = insert_order(
        database, owner, created_at=now() - timedelta(days=2), plan="basic"
    )
    newer = insert_order(
        database, owner, created_at=now() - timedelta(days=1), plan="basic"
    )
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert stored_order(database, newer.id).status == "succeeded"
    assert stored_order(database, older.id).status != "succeeded"


def test_an_order_for_another_product_or_period_is_not_succeeded(database, play, owner):
    other_plan = insert_order(database, owner, plan="pro", billing_period="monthly")
    other_period = insert_order(database, owner, plan="basic", billing_period="yearly")
    play.add(TOKEN, owner=owner, product_id="niscala_basic", base_plan_id="monthly")
    sync(database, play, TOKEN)
    assert stored_order(database, other_plan.id).status == "awaitingPayment"
    assert stored_order(database, other_period.id).status == "awaitingPayment"


def test_the_order_holding_the_token_is_preferred_to_a_newer_one(database, play, owner):
    holding = insert_order(
        database,
        owner,
        purchase_token=TOKEN,
        created_at=now() - timedelta(days=2),
    )
    newer = insert_order(database, owner, created_at=now() - timedelta(days=1))
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert stored_order(database, holding.id).status == "succeeded"
    assert stored_order(database, newer.id).status != "succeeded"


def test_another_owners_order_is_not_touched(database, play, owner, make_user):
    stranger = make_user(name="Other Owner")
    theirs = insert_order(database, stranger, plan="basic")
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert stored_order(database, theirs.id).status == "awaitingPayment"


def test_a_purchase_without_an_awaiting_order_still_updates_the_subscription(
    database, play, owner
):
    play.add(TOKEN, owner=owner)
    sync(database, play, TOKEN)
    assert subscription_state(database, owner)[4] == TOKEN
    assert all_orders(database) == []


def test_the_order_and_the_subscription_are_updated_together(database, play, owner):
    bought = insert_order(database, owner, plan="pro", billing_period="yearly")
    expiry = in_days(365)
    play.add(
        TOKEN,
        owner=owner,
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
    )
    sync(database, play, TOKEN)
    assert stored_order(database, bought.id).status == "succeeded"
    assert subscription_state(database, owner)[:3] == ("pro", "yearly", expiry)
