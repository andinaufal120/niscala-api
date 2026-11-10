"""Verifying a Google Play purchase token against a subscription order."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from google_play_support import (
    ENDED_STATES,
    RUNNING_STATES,
    edit_order,
    everything,
    now,
    subscription_state,
    verification_url,
    verify,
)
from subscription_support import (
    assert_error,
    insert_order,
    is_property_view_only,
    is_room_view_only,
    jakarta_date,
    schedule_row,
    set_subscription,
    store_schedule,
    stored_order,
    stored_subscription,
)

TOKEN = "play-token-1"


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def order(database, owner):
    return insert_order(database, owner, plan="basic", billing_period="monthly")


def get_subscription(client, headers) -> dict:
    response = client.get("/subscription", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def expiry_in(days: float) -> datetime:
    return now() + timedelta(days=days)


# Success: the purchase is paid


@pytest.mark.parametrize("state", RUNNING_STATES)
def test_a_running_purchase_succeeds_the_order(
    client, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state)
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(order.id)
    assert body["status"] == "succeeded"
    assert body["planCode"] == "basic"
    assert body["billingPeriod"] == "monthly"
    assert body["googlePlayProductId"] == "niscala_basic"
    assert body["googlePlayBasePlanId"] == "monthly"
    assert body["obfuscatedAccountId"] == str(owner.id)


def test_a_canceled_purchase_with_time_left_succeeds_the_order(
    client, play, owner, owner_in, order
):
    play.add(
        TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=expiry_in(10),
    )
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"


@pytest.mark.parametrize("state", RUNNING_STATES)
def test_the_stored_order_is_succeeded_and_keeps_the_token(
    client, database, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state)
    verify(client, owner_in.headers, order.id)
    stored = stored_order(database, order.id)
    assert stored.status == "succeeded"
    assert stored.purchase_token == TOKEN


def test_the_subscription_is_set_from_the_purchase(
    client, database, play, owner, owner_in, order
):
    expiry = expiry_in(31)
    play.add(TOKEN, owner=owner, expiry_time=expiry, auto_renewing=True)
    verify(client, owner_in.headers, order.id)
    stored = stored_subscription(database, owner)
    assert stored.plan == "basic"
    assert stored.billing_period == "monthly"
    assert stored.ends_at == expiry
    assert stored.auto_renew is True
    assert stored.purchase_token == TOKEN


def test_the_current_subscription_reflects_the_purchase(
    client, play, owner, owner_in, order
):
    expiry = expiry_in(31)
    play.add(TOKEN, owner=owner, expiry_time=expiry)
    verify(client, owner_in.headers, order.id)
    current = get_subscription(client, owner_in.headers)
    assert current["planCode"] == "basic"
    assert current["status"] == "active"
    assert current["billingPeriod"] == "monthly"
    assert current["endDate"] == jakarta_date(expiry).isoformat()
    assert current["autoRenew"] is True
    assert current["openOrder"] is None


def test_a_canceled_purchase_does_not_renew_but_stays_active(
    client, play, owner, owner_in, order
):
    play.add(
        TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=expiry_in(10),
    )
    verify(client, owner_in.headers, order.id)
    current = get_subscription(client, owner_in.headers)
    assert current["status"] == "active"
    assert current["autoRenew"] is False


@pytest.mark.parametrize(
    ("plan", "period", "product"),
    [
        ("basic", "monthly", "niscala_basic"),
        ("basic", "yearly", "niscala_basic"),
        ("pro", "monthly", "niscala_pro"),
        ("pro", "yearly", "niscala_pro"),
    ],
)
def test_the_plan_and_period_come_from_the_product_and_base_plan(
    client, database, play, owner, owner_in, plan, period, product
):
    bought = insert_order(database, owner, plan=plan, billing_period=period)
    play.add(TOKEN, owner=owner, product_id=product, base_plan_id=period)
    response = verify(client, owner_in.headers, bought.id)
    assert response.json()["status"] == "succeeded"
    stored = stored_subscription(database, owner)
    assert (stored.plan, stored.billing_period) == (plan, period)


def test_an_upgrade_replaces_the_running_subscription(
    client, database, play, owner, owner_in
):
    set_subscription(
        database,
        owner,
        plan="basic",
        billing_period="monthly",
        ends_at=expiry_in(5),
        auto_renew=True,
    )
    bought = insert_order(database, owner, plan="pro", billing_period="yearly")
    expiry = expiry_in(365)
    play.add(
        TOKEN,
        owner=owner,
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
        auto_renewing=False,
    )
    verify(client, owner_in.headers, bought.id)
    assert subscription_state(database, owner) == (
        "pro",
        "yearly",
        expiry,
        False,
        TOKEN,
    )


def test_an_unacknowledged_purchase_is_acknowledged_once(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, acknowledged=False)
    verify(client, owner_in.headers, order.id)
    assert play.acknowledged == [("niscala_basic", TOKEN)]


def test_the_acknowledgement_names_the_product_of_the_purchase(
    client, database, play, owner, owner_in
):
    bought = insert_order(database, owner, plan="pro", billing_period="monthly")
    play.add(TOKEN, owner=owner, product_id="niscala_pro", base_plan_id="monthly")
    verify(client, owner_in.headers, bought.id)
    assert play.acknowledged == [("niscala_pro", TOKEN)]


def test_an_acknowledged_purchase_is_not_acknowledged_again(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, acknowledged=True)
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "succeeded"
    assert play.acknowledge_attempts == []


@pytest.mark.parametrize("state", ["IN_GRACE_PERIOD", "CANCELED"])
def test_those_running_states_are_acknowledged_too(
    client, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state, acknowledged=False)
    verify(client, owner_in.headers, order.id)
    assert play.acknowledged == [("niscala_basic", TOKEN)]


def test_the_token_is_looked_up_at_google_play(client, play, owner, owner_in, order):
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    assert play.fetched == [TOKEN]


# Success: editability is restored


def test_view_only_properties_and_rooms_become_editable(
    client, database, play, owner, owner_in, order, make_property, make_room
):
    first = make_property(owner, name="Kos Satu", view_only=True)
    second = make_property(owner, name="Kos Dua", view_only=True)
    room = make_room(first, number="A1", view_only=True)
    other_room = make_room(second, number="B1", view_only=True)
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    assert not is_property_view_only(database, first)
    assert not is_property_view_only(database, second)
    assert not is_room_view_only(database, room)
    assert not is_room_view_only(database, other_room)


def test_the_scheduled_downgrade_is_removed(
    client, database, play, owner, owner_in, make_property
):
    prop = make_property(owner)
    set_subscription(database, owner, plan="pro", ends_at=expiry_in(5))
    store_schedule(database, owner, "free", property_ids=[prop.id])
    bought = insert_order(database, owner, plan="pro", billing_period="yearly")
    play.add(TOKEN, owner=owner, product_id="niscala_pro", base_plan_id="yearly")
    verify(client, owner_in.headers, bought.id)
    assert schedule_row(database, owner) is None


def test_another_owners_properties_stay_view_only(
    client, database, play, owner, owner_in, order, make_user, make_property
):
    stranger = make_user(name="Other Owner")
    theirs = make_property(stranger, view_only=True)
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    assert is_property_view_only(database, theirs)


@pytest.mark.parametrize("state", ENDED_STATES)
def test_a_failed_verification_leaves_view_only_properties_alone(
    client, database, play, owner, owner_in, order, make_property, state
):
    prop = make_property(owner, view_only=True)
    play.add(TOKEN, owner=owner, state=state, expiry_time=expiry_in(-1))
    verify(client, owner_in.headers, order.id)
    assert is_property_view_only(database, prop)


# Idempotence


def test_repeating_a_verified_order_with_the_same_token_changes_nothing(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    first = verify(client, owner_in.headers, order.id)
    before = everything(database)
    state = subscription_state(database, owner)
    second = verify(client, owner_in.headers, order.id)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert everything(database) == before
    assert subscription_state(database, owner) == state


def test_repeating_a_verified_order_does_not_ask_google_play_again(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    verify(client, owner_in.headers, order.id)
    assert play.fetched == [TOKEN]
    assert len(play.acknowledged) == 1


def test_a_verified_order_stays_succeeded_when_google_play_is_unreachable_later(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    play.unreachable = True
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


def test_a_verified_order_stays_succeeded_when_the_purchase_ended_later(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    verify(client, owner_in.headers, order.id)
    play.change(TOKEN, state="EXPIRED")
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert stored_order(database, order.id).status == "succeeded"


def test_an_owner_may_verify_a_new_order_with_the_token_of_their_own_subscription(
    client, database, play, owner, owner_in
):
    set_subscription(database, owner, plan="basic", ends_at=expiry_in(5))
    from google_play_support import set_token

    set_token(database, owner, TOKEN)
    bought = insert_order(database, owner, plan="basic", billing_period="monthly")
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, bought.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"


# Pending purchases


def test_a_pending_purchase_keeps_the_order_awaiting_payment(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="PENDING")
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaitingPayment"
    stored = stored_order(database, order.id)
    assert stored.status == "awaitingPayment"
    assert stored.purchase_token == TOKEN


def test_a_pending_purchase_changes_no_subscription_and_is_not_acknowledged(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="PENDING")
    verify(client, owner_in.headers, order.id)
    assert subscription_state(database, owner) is None
    assert play.acknowledge_attempts == []


def test_a_pending_purchase_leaves_a_running_subscription_alone(
    client, database, play, owner, owner_in
):
    set_subscription(database, owner, plan="basic", ends_at=expiry_in(5))
    before = subscription_state(database, owner)
    bought = insert_order(database, owner, plan="pro", billing_period="monthly")
    play.add(TOKEN, owner=owner, state="PENDING", product_id="niscala_pro")
    verify(client, owner_in.headers, bought.id)
    assert subscription_state(database, owner) == before


def test_a_pending_order_is_still_the_open_order(client, play, owner, owner_in, order):
    play.add(TOKEN, owner=owner, state="PENDING")
    verify(client, owner_in.headers, order.id)
    current = get_subscription(client, owner_in.headers)
    assert current["openOrder"]["id"] == str(order.id)
    assert current["planCode"] == "free"


def test_a_pending_order_does_not_expire_by_time(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="PENDING")
    verify(client, owner_in.headers, order.id)
    edit_order(database, order.id, expires_at=now() - timedelta(days=10))
    read = client.get(f"/subscription/orders/{order.id}", headers=owner_in.headers)
    assert read.json()["status"] == "awaitingPayment"
    current = get_subscription(client, owner_in.headers)
    assert current["openOrder"]["id"] == str(order.id)
    assert stored_order(database, order.id).status == "awaitingPayment"


def test_sending_the_same_pending_token_again_checks_google_play_again(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="PENDING")
    first = verify(client, owner_in.headers, order.id)
    second = verify(client, owner_in.headers, order.id)
    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "awaitingPayment"
    assert play.fetched == [TOKEN, TOKEN]


def test_a_pending_purchase_that_was_paid_succeeds_when_sent_again(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="PENDING")
    verify(client, owner_in.headers, order.id)
    play.change(TOKEN, state="ACTIVE")
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "succeeded"
    assert subscription_state(database, owner)[0] == "basic"
    assert play.acknowledged == [("niscala_basic", TOKEN)]


@pytest.mark.parametrize("state", ["PENDING_PURCHASE_CANCELED", "EXPIRED"])
def test_a_pending_purchase_that_was_canceled_fails_when_sent_again(
    client, database, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state="PENDING")
    verify(client, owner_in.headers, order.id)
    play.change(TOKEN, state=state, expiry_time=expiry_in(-1))
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "failed"
    assert subscription_state(database, owner) is None


# Purchases that did not succeed


@pytest.mark.parametrize("state", ENDED_STATES)
def test_an_ended_purchase_fails_the_order(
    client, database, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state, expiry_time=expiry_in(-1))
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert stored_order(database, order.id).status == "failed"


def test_a_canceled_purchase_past_its_expiry_fails_the_order(
    client, database, play, owner, owner_in, order
):
    play.add(
        TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=expiry_in(-1),
    )
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "failed"


def test_a_state_unknown_to_the_application_fails_the_order(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner, state="SOMETHING_NEW")
    response = verify(client, owner_in.headers, order.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert subscription_state(database, owner) is None


@pytest.mark.parametrize("state", ENDED_STATES)
def test_a_failed_purchase_creates_no_subscription_and_is_not_acknowledged(
    client, database, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state, expiry_time=expiry_in(-1))
    verify(client, owner_in.headers, order.id)
    assert subscription_state(database, owner) is None
    assert play.acknowledge_attempts == []
    assert get_subscription(client, owner_in.headers)["planCode"] == "free"


def test_a_failed_purchase_leaves_a_running_subscription_alone(
    client, database, play, owner, owner_in
):
    set_subscription(database, owner, plan="basic", ends_at=expiry_in(5))
    before = subscription_state(database, owner)
    bought = insert_order(database, owner, plan="pro", billing_period="monthly")
    play.add(
        TOKEN,
        owner=owner,
        state="EXPIRED",
        product_id="niscala_pro",
        expiry_time=expiry_in(-1),
    )
    verify(client, owner_in.headers, bought.id)
    assert subscription_state(database, owner) == before


def test_a_failed_order_cannot_be_verified_again(client, play, owner, owner_in, order):
    play.add(TOKEN, owner=owner, state="EXPIRED", expiry_time=expiry_in(-1))
    verify(client, owner_in.headers, order.id)
    again = verify(client, owner_in.headers, order.id)
    assert_error(again, 409, "SUBSCRIPTION_ORDER_CLOSED")


# Closed orders


@pytest.mark.parametrize("status", ["failed", "expired"])
def test_a_closed_order_is_refused_without_asking_google_play(
    client, database, play, owner, owner_in, status
):
    closed = insert_order(database, owner, status=status)
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, closed.id)
    assert_error(response, 409, "SUBSCRIPTION_ORDER_CLOSED")
    assert play.fetched == []
    assert stored_order(database, closed.id).status == status
    assert subscription_state(database, owner) is None


@pytest.mark.parametrize("status", ["failed", "expired"])
def test_an_order_closed_with_its_token_is_refused_with_that_token_too(
    client, database, play, owner, owner_in, status
):
    closed = insert_order(database, owner, status=status, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, closed.id)
    assert_error(response, 409, "SUBSCRIPTION_ORDER_CLOSED")


def test_a_replaced_order_is_closed(client, play, owner, owner_in, order):
    created = client.post(
        "/subscription/orders",
        json={"planCode": "pro", "billingPeriod": "monthly"},
        headers=owner_in.headers,
    )
    assert created.status_code == 201
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 409, "SUBSCRIPTION_ORDER_CLOSED")


# Who may verify


def test_an_unknown_order_is_not_found(client, play, owner_in):
    response = verify(client, owner_in.headers, uuid4())
    assert_error(response, 404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    assert play.fetched == []


def test_another_owners_order_is_not_found(client, database, play, owner_in, make_user):
    stranger = make_user(name="Other Owner")
    theirs = insert_order(database, stranger)
    play.add(TOKEN, owner=stranger)
    response = verify(client, owner_in.headers, theirs.id)
    assert_error(response, 404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    assert play.fetched == []
    assert stored_order(database, theirs.id).status == "awaitingPayment"
    assert subscription_state(database, stranger) is None


def test_another_owners_closed_order_is_not_found_rather_than_closed(
    client, database, play, owner_in, make_user
):
    stranger = make_user(name="Other Owner")
    theirs = insert_order(database, stranger, status="failed")
    response = verify(client, owner_in.headers, theirs.id)
    assert_error(response, 404, "SUBSCRIPTION_ORDER_NOT_FOUND")


@pytest.mark.parametrize("role", ["manager", "tenant", "admin"])
def test_only_an_owner_may_verify(
    client, database, play, order, make_user, sign_in, role
):
    from app.schemas.auth import UserRole

    user = make_user(name="Not Owner", role=UserRole(role))
    response = verify(client, sign_in(user).headers, order.id)
    assert_error(response, 403, "FORBIDDEN")
    assert play.fetched == []


def test_an_unauthenticated_request_is_refused(client, play, order):
    response = client.post(verification_url(order.id), json={"purchaseToken": TOKEN})
    assert response.status_code == 401
    assert play.fetched == []


def test_the_role_is_checked_before_the_order_is_looked_up(
    client, play, make_user, sign_in
):
    from app.schemas.auth import UserRole

    manager = make_user(name="Mira Manager", role=UserRole.MANAGER)
    response = verify(client, sign_in(manager).headers, uuid4())
    assert_error(response, 403, "FORBIDDEN")


# Token held by another owner


def test_a_token_on_another_owners_subscription_is_in_use(
    client, database, play, owner, owner_in, order, make_user
):
    from google_play_support import set_token

    stranger = make_user(name="Other Owner")
    set_subscription(database, stranger, plan="basic")
    set_token(database, stranger, TOKEN)
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 409, "PURCHASE_TOKEN_IN_USE")
    assert play.fetched == []
    assert stored_order(database, order.id).status == "awaitingPayment"
    assert subscription_state(database, owner) is None


@pytest.mark.parametrize(
    "status", ["awaitingPayment", "succeeded", "failed", "expired"]
)
def test_a_token_on_another_owners_order_is_in_use(
    client, database, play, owner, owner_in, order, make_user, status
):
    stranger = make_user(name="Other Owner")
    insert_order(database, stranger, status=status, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 409, "PURCHASE_TOKEN_IN_USE")
    assert play.fetched == []
    assert stored_order(database, order.id).purchase_token is None


def test_a_token_in_use_is_reported_before_google_play_is_asked(
    client, database, play, owner, owner_in, order, make_user
):
    stranger = make_user(name="Other Owner")
    insert_order(database, stranger, purchase_token=TOKEN)
    play.unreachable = True
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 409, "PURCHASE_TOKEN_IN_USE")


def test_a_closed_order_is_reported_before_a_token_in_use(
    client, database, play, owner, owner_in, make_user
):
    stranger = make_user(name="Other Owner")
    insert_order(database, stranger, purchase_token=TOKEN)
    closed = insert_order(database, owner, status="failed")
    response = verify(client, owner_in.headers, closed.id)
    assert_error(response, 409, "SUBSCRIPTION_ORDER_CLOSED")


# Google Play cannot be reached or disagrees


def test_an_unreachable_google_play_answers_503_and_changes_nothing(
    client, database, play, owner, owner_in, order
):
    play.unreachable = True
    before = everything(database)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 503, "GOOGLE_PLAY_UNREACHABLE")
    assert everything(database) == before
    stored = stored_order(database, order.id)
    assert stored.status == "awaitingPayment"
    assert stored.purchase_token is None
    assert subscription_state(database, owner) is None


def test_the_order_can_be_verified_once_google_play_is_back(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    play.unreachable = True
    verify(client, owner_in.headers, order.id)
    play.unreachable = False
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "succeeded"


def test_without_google_play_configured_the_answer_is_503(
    client, database, owner, owner_in, order
):
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 503, "GOOGLE_PLAY_UNREACHABLE")


def test_an_acknowledge_failure_answers_503_and_saves_nothing(
    client, database, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    play.acknowledge_fails = True
    before = everything(database)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 503, "GOOGLE_PLAY_UNREACHABLE")
    assert play.acknowledge_attempts == [("niscala_basic", TOKEN)]
    assert everything(database) == before
    stored = stored_order(database, order.id)
    assert stored.status == "awaitingPayment"
    assert stored.purchase_token is None
    assert subscription_state(database, owner) is None


def test_an_acknowledge_failure_leaves_view_only_properties_alone(
    client, database, play, owner, owner_in, order, make_property
):
    prop = make_property(owner, view_only=True)
    play.add(TOKEN, owner=owner)
    play.acknowledge_fails = True
    verify(client, owner_in.headers, order.id)
    assert is_property_view_only(database, prop)


def test_the_order_succeeds_when_the_acknowledgement_is_retried(
    client, play, owner, owner_in, order
):
    play.add(TOKEN, owner=owner)
    play.acknowledge_fails = True
    verify(client, owner_in.headers, order.id)
    play.acknowledge_fails = False
    response = verify(client, owner_in.headers, order.id)
    assert response.json()["status"] == "succeeded"
    assert play.acknowledged == [("niscala_basic", TOKEN)]


def test_an_unknown_token_is_invalid(client, database, play, owner_in, order):
    response = verify(client, owner_in.headers, order.id, token="never-issued")
    assert_error(response, 422, "PURCHASE_TOKEN_INVALID", "purchaseToken")
    stored = stored_order(database, order.id)
    assert stored.status == "awaitingPayment"
    assert stored.purchase_token is None


@pytest.mark.parametrize(
    "account_id",
    [None, "not-a-uuid", "00000000-0000-4000-8000-000000000000"],
    ids=["missing", "garbage", "another-account"],
)
def test_a_purchase_made_for_another_account_is_invalid(
    client, database, play, owner, owner_in, order, account_id
):
    play.add(TOKEN, obfuscated_account_id=account_id)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 422, "PURCHASE_TOKEN_INVALID", "purchaseToken")
    assert subscription_state(database, owner) is None
    assert stored_order(database, order.id).status == "awaitingPayment"
    assert play.acknowledge_attempts == []


def test_a_purchase_made_for_another_owner_is_invalid(
    client, database, play, owner, owner_in, order, make_user
):
    stranger = make_user(name="Other Owner")
    play.add(TOKEN, owner=stranger)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 422, "PURCHASE_TOKEN_INVALID", "purchaseToken")
    assert subscription_state(database, stranger) is None
    assert subscription_state(database, owner) is None


@pytest.mark.parametrize(
    ("product", "base_plan"),
    [
        ("niscala_pro", "monthly"),
        ("niscala_basic", "yearly"),
        ("niscala_pro", "yearly"),
        ("niscala_other", "monthly"),
        ("niscala_basic", "weekly"),
    ],
)
def test_a_purchase_of_another_product_or_base_plan_is_a_mismatch(
    client, database, play, owner, owner_in, order, product, base_plan
):
    play.add(TOKEN, owner=owner, product_id=product, base_plan_id=base_plan)
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 422, "PURCHASE_PRODUCT_MISMATCH", "purchaseToken")
    stored = stored_order(database, order.id)
    assert stored.status == "awaitingPayment"
    assert subscription_state(database, owner) is None
    assert play.acknowledge_attempts == []


@pytest.mark.parametrize("state", ["EXPIRED", "PENDING", "ACTIVE"])
def test_a_mismatch_is_reported_whatever_the_state(
    client, play, owner, owner_in, order, state
):
    play.add(TOKEN, owner=owner, state=state, product_id="niscala_pro")
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 422, "PURCHASE_PRODUCT_MISMATCH", "purchaseToken")


def test_an_invalid_account_is_reported_before_a_mismatch(
    client, play, owner_in, order
):
    play.add(TOKEN, product_id="niscala_pro", obfuscated_account_id=str(uuid4()))
    response = verify(client, owner_in.headers, order.id)
    assert_error(response, 422, "PURCHASE_TOKEN_INVALID", "purchaseToken")


# Request validation


@pytest.mark.parametrize("body", [{}, {"purchaseToken": ""}, {"purchaseToken": None}])
def test_a_missing_or_empty_token_fails_validation(client, play, owner_in, order, body):
    response = client.post(
        verification_url(order.id), json=body, headers=owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "purchaseToken")
    assert play.fetched == []


# Nothing is logged for the normal outcomes


def test_a_successful_verification_is_silent(
    client, play, owner, owner_in, order, caplog
):
    play.add(TOKEN, owner=owner)
    with caplog.at_level(logging.WARNING):
        verify(client, owner_in.headers, order.id)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_time_zone_of_the_expiry_does_not_matter(
    client, database, play, owner, owner_in, order
):
    expiry = datetime.now(UTC).astimezone(timezone_plus_seven()) + timedelta(days=30)
    play.add(TOKEN, owner=owner, expiry_time=expiry)
    verify(client, owner_in.headers, order.id)
    assert stored_subscription(database, owner).ends_at == expiry


def timezone_plus_seven():
    from datetime import timezone

    return timezone(timedelta(hours=7))
