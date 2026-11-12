"""Scenarios of choosing, buying and keeping a subscription."""

from uuid import uuid4

import pytest
from google_play_support import (
    GOOD_BEARER,
    envelope,
    push,
    subscription_message,
)

from e2e.e2e_rent import assert_field_error
from e2e.e2e_subscription import (
    DOWNGRADE,
    ORDERS,
    OWNER_ONLY_REQUESTS,
    days_from_now,
    last_token,
    notify_play,
    order_of,
    place_order,
    play_end_date,
    send_token,
)

PRICES = {
    ("basic", "monthly"): 49_000,
    ("basic", "yearly"): 490_000,
    ("pro", "monthly"): 129_000,
    ("pro", "yearly"): 1_290_000,
}
FREE_SUBSCRIPTION = {
    "planCode": "free",
    "status": "free",
    "billingPeriod": None,
    "endDate": None,
    "autoRenew": False,
    "propertyCount": 0,
    "openOrder": None,
    "scheduledDowngrade": None,
}


def error(response, status: int, code: str, field: str | None = None) -> dict:
    return assert_field_error(response, status, code, field)


def new_property_body(name: str) -> dict:
    return {"name": name, "address": "Jl. Melati 5"}


# Choosing a plan


def test_plans_show_limits_ai_and_prices_and_a_new_owner_starts_on_the_free_plan(
    world,
):
    owner = world.owner_signs_up()

    plans = owner.read("/subscription-plans")["items"]

    assert [plan["code"] for plan in plans] == ["free", "basic", "pro"]
    free, basic, pro = plans
    assert (free["maxProperties"], free["maxRoomsPerProperty"]) == (1, 15)
    assert (basic["maxProperties"], basic["maxRoomsPerProperty"]) == (3, None)
    assert (pro["maxProperties"], pro["maxRoomsPerProperty"]) == (None, None)
    assert [plan["aiEnabled"] for plan in plans] == [False, True, True]
    assert free["prices"] == []
    prices = {
        (plan["code"], price["billingPeriod"]): price
        for plan in (basic, pro)
        for price in plan["prices"]
    }
    assert {key: price["amount"] for key, price in prices.items()} == PRICES
    products = {key: price["googlePlayProductId"] for key, price in prices.items()}
    assert products[("basic", "monthly")] == products[("basic", "yearly")]
    assert products[("pro", "monthly")] == products[("pro", "yearly")]
    assert products[("basic", "monthly")] != products[("pro", "monthly")]
    base_plans = {key: price["googlePlayBasePlanId"] for key, price in prices.items()}
    assert base_plans[("basic", "monthly")] == base_plans[("pro", "monthly")]
    assert base_plans[("basic", "monthly")] != base_plans[("basic", "yearly")]
    assert owner.subscription() == FREE_SUBSCRIPTION


def test_only_owners_can_see_or_change_a_subscription(seeded_world, world):
    admin = world.admin()
    people = {
        "manager": seeded_world.manager,
        "tenant": seeded_world.budi,
        "admin": admin,
    }

    for role, person in people.items():
        for method, path, body in OWNER_ONLY_REQUESTS:
            response = person.request(method, path, json=body)
            assert response.status_code == 403, (role, method, path, response.text)
            assert response.json()["code"] == "FORBIDDEN"

    anonymous = world.client.get("/subscription")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "ACCESS_TOKEN_INVALID"
    assert seeded_world.owner.subscription()["planCode"] == "basic"
    assert seeded_world.owner.subscription()["openOrder"] is None


def test_a_new_order_replaces_the_open_one_and_only_a_higher_plan_can_be_ordered(
    world,
):
    owner = world.owner_signs_up()

    first = place_order(owner, "basic", "monthly")
    assert first["status"] == "awaitingPayment"
    assert (first["planCode"], first["billingPeriod"]) == ("basic", "monthly")
    assert first["obfuscatedAccountId"]
    assert owner.subscription()["openOrder"]["id"] == first["id"]
    assert order_of(owner, first) == first

    second = place_order(owner, "pro", "yearly")

    assert second["id"] != first["id"]
    assert second["obfuscatedAccountId"] == first["obfuscatedAccountId"]
    assert order_of(owner, first)["status"] == "expired"
    assert order_of(owner, second)["status"] == "awaitingPayment"
    assert owner.subscription()["openOrder"]["id"] == second["id"]
    stale_token = world.stubs.play_purchase(owner, first)
    error(send_token(owner, first, stale_token), 409, "SUBSCRIPTION_ORDER_CLOSED")
    assert owner.subscription()["planCode"] == "free"

    token = world.stubs.play_purchase(owner, second)
    paid = send_token(owner, second, token)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "succeeded"

    subscription = owner.subscription()
    assert (subscription["planCode"], subscription["billingPeriod"]) == (
        "pro",
        "yearly",
    )
    assert subscription["openOrder"] is None
    for plan, period in [("basic", "monthly"), ("pro", "monthly"), ("pro", "yearly")]:
        refused = owner.post(ORDERS, json={"planCode": plan, "billingPeriod": period})
        error(refused, 409, "SUBSCRIPTION_NOT_AN_UPGRADE")
    assert owner.subscription() == subscription


# Paying


def test_owner_buys_basic_and_the_limits_and_period_follow_the_purchase(world):
    owner = world.owner_signs_up()
    melati = owner.add_property("Kos Melati")
    error(
        owner.post("/properties", json=new_property_body("Kos Anggrek")),
        403,
        "PROPERTY_LIMIT_REACHED",
    )
    for number in range(1, 16):
        owner.add_room(melati, f"R{number:02d}")
    error(
        owner.post(
            f"/properties/{melati['id']}/rooms",
            json={"number": "R16", "baseRate": 1_000_000, "facilities": []},
        ),
        403,
        "ROOM_LIMIT_REACHED",
    )
    prices = owner.read("/subscription-plans")["items"][1]["prices"]
    monthly = next(price for price in prices if price["billingPeriod"] == "monthly")

    order = place_order(owner, "basic", "monthly")

    assert order["googlePlayProductId"] == monthly["googlePlayProductId"]
    assert order["googlePlayBasePlanId"] == monthly["googlePlayBasePlanId"]
    assert owner.subscription()["planCode"] == "free"
    token = world.stubs.play_purchase(owner, order)

    response = send_token(owner, order, token)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == order["id"]
    assert response.json()["status"] == "succeeded"
    world.stubs.assert_play_acknowledged(token)
    subscription = owner.subscription()
    assert subscription["planCode"] == "basic"
    assert subscription["status"] == "active"
    assert subscription["billingPeriod"] == "monthly"
    assert subscription["endDate"] == play_end_date(world, token)
    assert subscription["autoRenew"] is True
    assert subscription["openOrder"] is None
    assert subscription["propertyCount"] == 1
    assert order_of(owner, order)["status"] == "succeeded"
    owner.add_room(melati, "R16")
    owner.add_property("Kos Anggrek")
    owner.add_property("Kos Bakung")
    error(
        owner.post("/properties", json=new_property_body("Kos Cempaka")),
        403,
        "PROPERTY_LIMIT_REACHED",
    )
    assert owner.subscription()["propertyCount"] == 3


def test_owner_upgrades_from_basic_to_pro_and_the_limit_rises_at_once(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    for name in ("Kos Melati", "Kos Anggrek", "Kos Bakung"):
        owner.add_property(name)
    error(
        owner.post("/properties", json=new_property_body("Kos Cempaka")),
        403,
        "PROPERTY_LIMIT_REACHED",
    )
    basic_end = owner.subscription()["endDate"]

    subscription = owner.subscribe("pro", "yearly")

    assert subscription["planCode"] == "pro"
    assert subscription["billingPeriod"] == "yearly"
    assert subscription["endDate"] == play_end_date(world, last_token(world))
    assert subscription["endDate"] > basic_end
    for name in ("Kos Cempaka", "Kos Dahlia", "Kos Edelweis"):
        owner.add_property(name)
    assert owner.subscription()["propertyCount"] == 6


def test_a_token_that_is_repeated_or_held_by_another_owner_is_handled_safely(world):
    rina = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    toni = world.owner_signs_up(email="toni@example.com", name="Toni Owner")
    order = place_order(rina)
    token = world.stubs.play_purchase(rina, order)
    paid = send_token(rina, order, token)
    assert paid.status_code == 200, paid.text
    rina_subscription = rina.subscription()
    acknowledgements = len(world.stubs.play.acknowledged)

    again = send_token(rina, order, token)

    assert again.status_code == 200, again.text
    assert again.json() == paid.json()
    assert rina.subscription() == rina_subscription
    assert len(world.stubs.play.acknowledged) == acknowledgements

    toni_order = place_order(toni)
    error(send_token(toni, toni_order, token), 409, "PURCHASE_TOKEN_IN_USE")
    assert order_of(toni, toni_order)["status"] == "awaitingPayment"
    assert toni.subscription()["planCode"] == "free"

    error(toni.get(f"{ORDERS}/{order['id']}"), 404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    error(send_token(toni, order, "anything"), 404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    error(toni.get(f"{ORDERS}/{uuid4()}"), 404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    assert rina.subscription() == rina_subscription

    bought_for_rina = world.stubs.play_purchase(
        toni, toni_order, obfuscated_account_id=order["obfuscatedAccountId"]
    )
    error(
        send_token(toni, toni_order, bought_for_rina),
        422,
        "PURCHASE_TOKEN_INVALID",
        "purchaseToken",
    )
    assert toni.subscription()["planCode"] == "free"


def test_a_purchase_google_does_not_know_or_that_does_not_match_the_order_is_refused(
    world,
):
    owner = world.owner_signs_up()
    order = place_order(owner, "basic", "monthly")

    error(
        send_token(owner, order, "never-bought"),
        422,
        "PURCHASE_TOKEN_INVALID",
        "purchaseToken",
    )
    other_product = world.stubs.play_purchase(owner, order, product_id="niscala_pro")
    error(
        send_token(owner, order, other_product),
        422,
        "PURCHASE_PRODUCT_MISMATCH",
        "purchaseToken",
    )
    other_period = world.stubs.play_purchase(owner, order, base_plan_id="yearly")
    error(
        send_token(owner, order, other_period),
        422,
        "PURCHASE_PRODUCT_MISMATCH",
        "purchaseToken",
    )

    assert owner.subscription()["planCode"] == "free"
    assert order_of(owner, order)["status"] == "awaitingPayment"
    good = world.stubs.play_purchase(owner, order)
    assert send_token(owner, order, good).json()["status"] == "succeeded"
    assert owner.subscription()["planCode"] == "basic"


def test_a_failed_purchase_closes_the_order_and_the_owner_pays_again_with_a_new_one(
    world,
):
    owner = world.owner_signs_up()
    order = place_order(owner)
    token = world.stubs.play_purchase(owner, order, state="PENDING_PURCHASE_CANCELED")

    response = send_token(owner, order, token)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert owner.subscription()["planCode"] == "free"
    assert owner.subscription()["openOrder"] is None
    error(send_token(owner, order, token), 409, "SUBSCRIPTION_ORDER_CLOSED")
    good = world.stubs.play_purchase(owner, order)
    error(send_token(owner, order, good), 409, "SUBSCRIPTION_ORDER_CLOSED")

    retry = place_order(owner)
    assert retry["id"] != order["id"]
    paid = send_token(owner, retry, good)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "succeeded"
    assert owner.subscription()["planCode"] == "basic"


def test_a_pending_purchase_keeps_the_order_open_until_google_completes_it(world):
    owner = world.owner_signs_up()
    order = place_order(owner)
    token = world.stubs.play_purchase(owner, order, state="PENDING")

    first = send_token(owner, order, token)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "awaitingPayment"
    assert owner.subscription()["planCode"] == "free"
    assert owner.subscription()["openOrder"]["id"] == order["id"]
    assert not world.stubs.play.acknowledged

    again = send_token(owner, order, token)
    assert again.json()["status"] == "awaitingPayment"

    world.stubs.play.change(token, state="ACTIVE")
    done = send_token(owner, order, token)

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "succeeded"
    subscription = owner.subscription()
    assert subscription["planCode"] == "basic"
    assert subscription["openOrder"] is None
    world.stubs.assert_play_acknowledged(token)


def test_nothing_is_saved_while_google_play_is_down_and_the_same_token_works_later(
    world,
):
    owner = world.owner_signs_up()
    order = place_order(owner)
    token = world.stubs.play_purchase(owner, order)
    world.stubs.play_unreachable()

    error(send_token(owner, order, token), 503, "GOOGLE_PLAY_UNREACHABLE")

    assert owner.subscription()["planCode"] == "free"
    assert order_of(owner, order)["status"] == "awaitingPayment"
    world.stubs.play_reachable()
    world.stubs.play_acknowledge_fails()

    error(send_token(owner, order, token), 503, "GOOGLE_PLAY_UNREACHABLE")

    assert owner.subscription()["planCode"] == "free"
    assert order_of(owner, order)["status"] == "awaitingPayment"
    assert not world.stubs.play.acknowledged
    world.stubs.play.acknowledge_fails = False

    done = send_token(owner, order, token)

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "succeeded"
    assert owner.subscription()["planCode"] == "basic"
    world.stubs.assert_play_acknowledged(token)


# Play notifications


def test_renewal_and_cancellation_notifications_move_the_end_date_and_stop_renewal(
    world, rtdn
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    token = last_token(world)
    first_end = owner.subscription()["endDate"]
    assert owner.subscription()["autoRenew"] is True

    world.stubs.play.change(token, expiry_time=days_from_now(60))
    renewed = notify_play(world, token)

    assert renewed.status_code == 204
    subscription = owner.subscription()
    assert subscription["planCode"] == "basic"
    assert subscription["endDate"] == play_end_date(world, token)
    assert subscription["endDate"] > first_end
    assert subscription["autoRenew"] is True

    world.stubs.play.change(token, state="CANCELED", auto_renewing=False)
    cancelled = notify_play(world, token)

    assert cancelled.status_code == 204
    after = owner.subscription()
    assert after["autoRenew"] is False
    assert after["planCode"] == "basic"
    assert after["status"] == "active"
    assert after["endDate"] == subscription["endDate"]
    assert rtdn.verified == [GOOD_BEARER, GOOD_BEARER]


@pytest.mark.parametrize("state", ["EXPIRED", "ON_HOLD", "PAUSED"])
def test_a_notification_about_an_ended_purchase_ends_the_paid_period_at_once(
    world, rtdn, state
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    owner.add_property("Kos Melati")
    token = last_token(world)
    assert owner.subscription()["planCode"] == "basic"

    world.stubs.play.change(
        token, state=state, expiry_time=days_from_now(-0.01), auto_renewing=False
    )
    response = notify_play(world, token)

    assert response.status_code == 204
    subscription = owner.subscription()
    assert subscription["planCode"] == "free"
    assert subscription["status"] == "free"
    assert subscription["endDate"] is None
    assert subscription["billingPeriod"] is None
    error(
        owner.post("/properties", json=new_property_body("Kos Anggrek")),
        403,
        "PROPERTY_LIMIT_REACHED",
    )


def test_notifications_that_are_not_authenticated_or_not_usable_change_nothing(
    world, rtdn
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    token = last_token(world)
    world.stubs.play.change(
        token, state="EXPIRED", expiry_time=days_from_now(-0.01), auto_renewing=False
    )
    before = owner.subscription()
    rtdn.add("other-account", email="stranger@iam.example.com")
    rtdn.add("unverified-mail", email_verified=False)

    refused = [
        notify_play(world, token, bearer=None),
        notify_play(world, token, bearer="not-a-pubsub-token"),
        notify_play(world, token, bearer="other-account"),
        notify_play(world, token, bearer="unverified-mail"),
    ]

    for response in refused:
        error(response, 401, "UNAUTHORIZED")
    assert owner.subscription() == before
    assert before["planCode"] == "basic"

    garbage = push(world.client, b"this is not json", GOOD_BEARER)
    assert garbage.status_code == 204
    empty = push(world.client, {"message": {"data": ""}}, GOOD_BEARER)
    assert empty.status_code == 204
    other_package = push(
        world.client,
        _message_for(token, package="com.someone.else"),
        GOOD_BEARER,
    )
    assert other_package.status_code == 204
    unknown_purchase = notify_play(world, "a-purchase-nobody-bought")
    assert unknown_purchase.status_code == 204
    assert owner.subscription() == before

    accepted = notify_play(world, token)
    assert accepted.status_code == 204
    assert owner.subscription()["planCode"] == "free"


def _message_for(token: str, package: str) -> dict:
    return envelope(subscription_message(token, package=package))


def test_a_notification_cannot_be_delivered_while_google_play_is_down(world, rtdn):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    token = last_token(world)
    world.stubs.play.change(
        token, state="EXPIRED", expiry_time=days_from_now(-0.01), auto_renewing=False
    )
    world.stubs.play_unreachable()

    error(notify_play(world, token), 503, "GOOGLE_PLAY_UNREACHABLE")
    assert owner.subscription()["planCode"] == "basic"

    world.stubs.play_reachable()
    assert notify_play(world, token).status_code == 204
    assert owner.subscription()["planCode"] == "free"


def test_the_notification_endpoint_is_off_until_it_is_configured(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")

    response = notify_play(world, last_token(world))

    error(response, 404, "NOT_FOUND")


# The daily re-check


def test_the_daily_job_recovers_a_renewal_whose_notification_never_arrived(
    world, expire_subscription
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    token = last_token(world)
    fetched = len(world.stubs.play.fetched)

    world.clock.run_daily_jobs()

    assert len(world.stubs.play.fetched) == fetched
    assert owner.subscription()["planCode"] == "basic"

    world.stubs.play.change(token, expiry_time=days_from_now(30))
    expire_subscription(owner.namespace)
    assert owner.subscription()["planCode"] == "free"

    world.stubs.play_unreachable()
    world.clock.run_daily_jobs()
    assert owner.subscription()["planCode"] == "free"

    world.stubs.play_reachable()
    world.clock.run_daily_jobs()

    subscription = owner.subscription()
    assert subscription["planCode"] == "basic"
    assert subscription["status"] == "active"
    assert subscription["endDate"] == play_end_date(world, token)
    assert token in world.stubs.play.fetched[fetched:]


def test_the_daily_job_confirms_an_ended_purchase_and_leaves_the_owner_on_free(
    world, expire_subscription
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    token = last_token(world)
    world.stubs.play.change(
        token, state="EXPIRED", expiry_time=days_from_now(-1), auto_renewing=False
    )
    expire_subscription(owner.namespace)

    world.clock.run_daily_jobs()

    subscription = owner.subscription()
    assert subscription["planCode"] == "free"
    assert subscription["endDate"] is None


# A subscription that is no longer active


def test_a_lapsed_subscription_withholds_ai_results_until_the_owner_subscribes_again(
    seeded_world, world, expire_subscription
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    melati = seeded_world.melati
    bill = next(b for b in owner.rent_bills() if b["tenant"]["name"] == "Budi Tenant")
    owner.post(
        f"/rent-bills/{bill['id']}/cash-payment",
        json={"receivedOn": world.clock.today.isoformat()},
        expect=200,
    )
    patterns = owner.read(f"/properties/{melati['id']}/payment-patterns")["items"]
    budi_pattern = next(p for p in patterns if p["tenant"]["name"] == "Budi Tenant")
    assert budi_pattern["summary"]
    assert budi_pattern["summaryWithheld"] is False
    classified = owner.complaints()[0]
    assert classified["classification"]["category"] == "Listrik"
    assert classified["classificationWithheld"] is False

    expire_subscription(owner.namespace)

    assert owner.subscription()["planCode"] == "free"
    for person in (owner, manager):
        withheld = person.complaints()[0]
        assert withheld["id"] == classified["id"]
        assert withheld["classification"] is None
        assert withheld["classificationState"] is None
        assert withheld["classificationWithheld"] is True
    for person in (owner, manager):
        patterns = person.read(f"/properties/{melati['id']}/payment-patterns")["items"]
        lapsed = next(p for p in patterns if p["tenant"]["name"] == "Budi Tenant")
        assert lapsed["summary"] is None
        assert lapsed["summaryWithheld"] is True
        assert lapsed["onTimeCount"] == budi_pattern["onTimeCount"]
        assert lapsed["countedBillCount"] == budi_pattern["countedBillCount"]
        assert lapsed["arrears"] == budi_pattern["arrears"]
        assert lapsed["atRisk"] == budi_pattern["atRisk"]
    error(
        owner.post("/properties", json=new_property_body("Kos Bakung")),
        403,
        "PROPERTY_LIMIT_REACHED",
    )

    second = budi.submit_complaint(
        seeded_world.rooms["A1"], "The window will not close."
    )
    assert second["classificationState"] == "notClassified"
    manual = manager.put(
        f"/complaints/{second['id']}/classification",
        json={"category": "Bangunan", "urgency": "low"},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["classification"]["category"] == "Bangunan"
    assert manual.json()["classification"]["urgency"] == "low"
    assert manual.json()["classificationWithheld"] is False
    assert owner.complaint(second)["classification"]["category"] == "Bangunan"
    assert owner.complaint(classified)["classificationWithheld"] is True

    resubscribed = owner.subscribe("basic")

    assert resubscribed["planCode"] == "basic"
    restored = owner.complaint(classified)
    assert restored["classification"]["category"] == "Listrik"
    assert restored["classificationWithheld"] is False
    assert owner.complaint(second)["classification"]["category"] == "Bangunan"
    patterns = owner.read(f"/properties/{melati['id']}/payment-patterns")["items"]
    back = next(p for p in patterns if p["tenant"]["name"] == "Budi Tenant")
    assert back["summary"] == budi_pattern["summary"]
    assert back["summaryWithheld"] is False
    fresh = budi.submit_complaint(
        seeded_world.rooms["A1"], "The lamp keeps flickering."
    )
    assert fresh["classificationState"] == "classifying"


def test_a_downgrade_cannot_be_scheduled_without_a_running_paid_period(world):
    owner = world.owner_signs_up()
    response = owner.put(
        DOWNGRADE,
        json={"planCode": "free", "keptPropertyIds": [], "keptRoomIds": []},
    )

    error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")
    assert owner.delete(DOWNGRADE).status_code == 204
    assert owner.subscription() == FREE_SUBSCRIPTION
