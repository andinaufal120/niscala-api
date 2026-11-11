"""Listing plans, reading the current subscription and creating and reading orders."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from subscription_support import (
    assert_error,
    insert_order,
    jakarta_date,
    set_subscription,
    store_schedule,
    stored_order,
    stored_orders,
)

PLANS_URL = "/subscription-plans"
SUBSCRIPTION_URL = "/subscription"
ORDERS_URL = "/subscription/orders"
DOWNGRADE_URL = "/subscription/scheduled-downgrade"

ORDER_BODY = {"planCode": "basic", "billingPeriod": "monthly"}
ORDER_FIELDS = {
    "id",
    "planCode",
    "billingPeriod",
    "status",
    "googlePlayProductId",
    "googlePlayBasePlanId",
    "obfuscatedAccountId",
    "createdAt",
}
SUBSCRIPTION_FIELDS = {
    "planCode",
    "status",
    "billingPeriod",
    "endDate",
    "autoRenew",
    "propertyCount",
    "openOrder",
    "scheduledDowngrade",
}

OWNER_ENDPOINTS = [
    pytest.param("get", PLANS_URL, None, id="list_plans"),
    pytest.param("get", SUBSCRIPTION_URL, None, id="get_subscription"),
    pytest.param("post", ORDERS_URL, ORDER_BODY, id="create_order"),
    pytest.param("get", f"{ORDERS_URL}/{uuid4()}", None, id="get_order"),
    pytest.param(
        "put",
        DOWNGRADE_URL,
        {"planCode": "free", "keptPropertyIds": []},
        id="schedule_downgrade",
    ),
    pytest.param("delete", DOWNGRADE_URL, None, id="cancel_downgrade"),
]


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


def read_plans(client, headers) -> dict:
    response = client.get(PLANS_URL, headers=headers)
    assert response.status_code == 200, response.text
    return {plan["code"]: plan for plan in response.json()["items"]}


def read_subscription(client, headers) -> dict:
    response = client.get(SUBSCRIPTION_URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def create_order(client, headers, plan="basic", period="monthly"):
    return client.post(
        ORDERS_URL, json={"planCode": plan, "billingPeriod": period}, headers=headers
    )


# Access


@pytest.mark.parametrize(("method", "url", "body"), OWNER_ENDPOINTS)
def test_a_request_without_a_session_is_unauthenticated(
    client, database, method, url, body
):
    response = client.request(method, url, json=body)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), OWNER_ENDPOINTS)
def test_an_invalid_token_is_unauthenticated(client, database, method, url, body):
    response = client.request(
        method, url, json=body, headers={"Authorization": "Bearer not-a-token"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("role", ["tenant", "manager", "admin"])
@pytest.mark.parametrize(("method", "url", "body"), OWNER_ENDPOINTS)
def test_only_an_owner_may_use_the_endpoints(
    client, make_user, sign_in, method, url, body, role
):
    from app.schemas.auth import UserRole

    headers = sign_in(make_user(role=UserRole(role))).headers
    response = client.request(method, url, json=body, headers=headers)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize(("method", "url", "body"), OWNER_ENDPOINTS)
def test_an_owner_with_an_unverified_email_is_refused(
    client, make_user, sign_in, method, url, body
):
    headers = sign_in(make_user(email_verified=False)).headers
    response = client.request(method, url, json=body, headers=headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("method", ["post", "put"])
def test_the_role_is_checked_before_the_body(client, make_user, sign_in, method):
    from app.schemas.auth import UserRole

    headers = sign_in(make_user(role=UserRole.TENANT)).headers
    url = ORDERS_URL if method == "post" else DOWNGRADE_URL
    response = client.request(method, url, json={"nonsense": True}, headers=headers)
    assert_error(response, 403, "FORBIDDEN")


# Plans


def test_the_plans_are_listed_free_basic_pro_in_that_order(client, owner_in):
    response = client.get(PLANS_URL, headers=owner_in.headers)
    assert response.status_code == 200
    assert [p["code"] for p in response.json()["items"]] == ["free", "basic", "pro"]


def test_a_plan_has_exactly_its_fields(client, owner_in):
    items = client.get(PLANS_URL, headers=owner_in.headers).json()["items"]
    for plan in items:
        assert set(plan) == {
            "code",
            "maxProperties",
            "maxRoomsPerProperty",
            "aiEnabled",
            "prices",
        }


@pytest.mark.parametrize(
    ("code", "max_properties", "max_rooms", "ai"),
    [
        ("free", 1, 15, False),
        ("basic", 3, None, True),
        ("pro", None, None, True),
    ],
)
def test_a_plan_carries_its_limits_and_ai_availability(
    client, owner_in, code, max_properties, max_rooms, ai
):
    plan = read_plans(client, owner_in.headers)[code]
    assert plan["maxProperties"] == max_properties
    assert plan["maxRoomsPerProperty"] == max_rooms
    assert plan["aiEnabled"] is ai


def test_the_free_plan_has_no_prices(client, owner_in):
    assert read_plans(client, owner_in.headers)["free"]["prices"] == []


@pytest.mark.parametrize(
    ("code", "monthly", "yearly"),
    [("basic", 49000, 490000), ("pro", 129000, 1290000)],
)
def test_a_paid_plan_has_a_monthly_and_a_yearly_price(
    client, owner_in, code, monthly, yearly
):
    prices = read_plans(client, owner_in.headers)[code]["prices"]
    by_period = {price["billingPeriod"]: price["amount"] for price in prices}
    assert len(prices) == 2
    assert by_period == {"monthly": monthly, "yearly": yearly}


@pytest.mark.parametrize("code", ["basic", "pro"])
def test_a_price_carries_its_google_play_ids(client, owner_in, code):
    prices = read_plans(client, owner_in.headers)[code]["prices"]
    for price in prices:
        assert set(price) == {
            "billingPeriod",
            "amount",
            "googlePlayProductId",
            "googlePlayBasePlanId",
        }
        assert price["googlePlayProductId"] == f"niscala_{code}"
        assert price["googlePlayBasePlanId"] == price["billingPeriod"]


def test_the_plans_do_not_depend_on_the_subscription(
    client, owner_in, owner, database, subscribe_owner
):
    before = client.get(PLANS_URL, headers=owner_in.headers).json()
    subscribe_owner(owner, "pro")
    assert client.get(PLANS_URL, headers=owner_in.headers).json() == before


# Current subscription


def test_an_owner_without_a_subscription_is_on_the_free_plan(client, owner_in):
    body = read_subscription(client, owner_in.headers)
    assert set(body) == SUBSCRIPTION_FIELDS
    assert body == {
        "planCode": "free",
        "status": "free",
        "billingPeriod": None,
        "endDate": None,
        "autoRenew": False,
        "propertyCount": 0,
        "openOrder": None,
        "scheduledDowngrade": None,
    }


@pytest.mark.parametrize("plan", ["basic", "pro"])
@pytest.mark.parametrize("period", ["monthly", "yearly"])
def test_a_running_paid_period_is_active(
    client, owner, owner_in, database, plan, period
):
    set_subscription(database, owner, plan=plan, billing_period=period)
    body = read_subscription(client, owner_in.headers)
    assert body["planCode"] == plan
    assert body["status"] == "active"
    assert body["billingPeriod"] == period


def test_a_subscription_made_by_the_grant_command_is_monthly_and_not_renewing(
    client, owner, owner_in, subscribe_owner
):
    subscribe_owner(owner, "basic", days=30)
    body = read_subscription(client, owner_in.headers)
    assert body["billingPeriod"] == "monthly"
    assert body["autoRenew"] is False


@pytest.mark.parametrize("auto_renew", [True, False])
def test_the_subscription_reports_whether_it_renews(
    client, owner, owner_in, database, auto_renew
):
    set_subscription(database, owner, plan="pro", auto_renew=auto_renew)
    assert read_subscription(client, owner_in.headers)["autoRenew"] is auto_renew


def test_the_end_date_is_the_jakarta_date_of_the_end_of_the_period(
    client, owner, owner_in, database
):
    ends_at = datetime(2099, 3, 10, 20, 0, tzinfo=UTC)
    set_subscription(database, owner, plan="basic", ends_at=ends_at)
    body = read_subscription(client, owner_in.headers)
    assert jakarta_date(ends_at).isoformat() == "2099-03-11"
    assert body["endDate"] == "2099-03-11"


def test_the_end_date_in_the_morning_of_the_same_utc_day(
    client, owner, owner_in, database
):
    ends_at = datetime(2099, 3, 10, 2, 0, tzinfo=UTC)
    set_subscription(database, owner, plan="basic", ends_at=ends_at)
    assert read_subscription(client, owner_in.headers)["endDate"] == "2099-03-10"


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_an_ended_period_is_free_again(
    client, owner, owner_in, database, expire_subscription, plan
):
    set_subscription(database, owner, plan=plan, billing_period="yearly")
    expire_subscription(owner)
    body = read_subscription(client, owner_in.headers)
    assert body["planCode"] == "free"
    assert body["status"] == "free"
    assert body["billingPeriod"] is None
    assert body["endDate"] is None


def test_a_period_ending_exactly_now_or_earlier_is_free(
    client, owner, owner_in, database
):
    set_subscription(
        database,
        owner,
        plan="pro",
        ends_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert read_subscription(client, owner_in.headers)["status"] == "free"


def test_a_period_ending_in_a_moment_is_still_active(client, owner, owner_in, database):
    set_subscription(
        database,
        owner,
        plan="pro",
        ends_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert read_subscription(client, owner_in.headers)["status"] == "active"


def test_the_property_count_includes_view_only_properties(
    client, owner, owner_in, make_property
):
    make_property(owner, name="Kos A")
    make_property(owner, name="Kos B", view_only=True)
    assert read_subscription(client, owner_in.headers)["propertyCount"] == 2


def test_the_property_count_excludes_deleted_properties(
    client, owner, owner_in, make_property
):
    make_property(owner, name="Kos A")
    make_property(owner, name="Kos B", deleted=True)
    assert read_subscription(client, owner_in.headers)["propertyCount"] == 1


def test_the_property_count_ignores_other_owners(
    client, owner, owner_in, make_user, make_property
):
    make_property(owner, name="Kos A")
    make_property(make_user(), name="Kos B")
    assert read_subscription(client, owner_in.headers)["propertyCount"] == 1


def test_the_subscription_of_another_owner_is_not_shown(
    client, owner_in, make_user, database
):
    other = make_user()
    set_subscription(database, other, plan="pro")
    insert_order(database, other)
    body = read_subscription(client, owner_in.headers)
    assert body["planCode"] == "free"
    assert body["openOrder"] is None


def test_no_open_order_is_none(client, owner_in):
    assert read_subscription(client, owner_in.headers)["openOrder"] is None


def test_the_open_order_is_the_order_awaiting_payment(
    client, owner, owner_in, database
):
    order = insert_order(database, owner, plan="pro", billing_period="yearly")
    open_order = read_subscription(client, owner_in.headers)["openOrder"]
    assert set(open_order) == ORDER_FIELDS
    assert open_order["id"] == str(order.id)
    assert open_order["planCode"] == "pro"
    assert open_order["billingPeriod"] == "yearly"
    assert open_order["status"] == "awaitingPayment"


@pytest.mark.parametrize("status", ["succeeded", "failed", "expired"])
def test_an_order_that_is_not_awaiting_payment_is_not_open(
    client, owner, owner_in, database, status
):
    insert_order(database, owner, status=status)
    assert read_subscription(client, owner_in.headers)["openOrder"] is None


def test_the_open_order_is_the_newest_one_awaiting_payment(
    client, owner, owner_in, database
):
    now = datetime.now(UTC)
    insert_order(database, owner, created_at=now - timedelta(hours=5))
    newest = insert_order(database, owner, created_at=now - timedelta(hours=1))
    insert_order(database, owner, created_at=now - timedelta(hours=3))
    insert_order(
        database,
        owner,
        status="succeeded",
        created_at=now - timedelta(minutes=1),
    )
    assert read_subscription(client, owner_in.headers)["openOrder"]["id"] == str(
        newest.id
    )


def test_an_order_past_its_expiry_is_not_open_and_is_saved_as_expired(
    client, owner, owner_in, database
):
    order = insert_order(
        database,
        owner,
        created_at=datetime.now(UTC) - timedelta(days=4),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert read_subscription(client, owner_in.headers)["openOrder"] is None
    assert stored_order(database, order.id).status == "expired"


def test_an_expired_order_does_not_hide_a_newer_open_one(
    client, owner, owner_in, database
):
    now = datetime.now(UTC)
    insert_order(
        database,
        owner,
        created_at=now - timedelta(days=5),
        expires_at=now - timedelta(days=2),
    )
    fresh = insert_order(database, owner, created_at=now - timedelta(hours=1))
    assert read_subscription(client, owner_in.headers)["openOrder"]["id"] == str(
        fresh.id
    )


def test_an_order_with_a_purchase_token_stays_open_past_its_expiry(
    client, owner, owner_in, database
):
    order = insert_order(
        database,
        owner,
        purchase_token="token-1",
        created_at=datetime.now(UTC) - timedelta(days=4),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    body = read_subscription(client, owner_in.headers)
    assert body["openOrder"]["id"] == str(order.id)
    assert stored_order(database, order.id).status == "awaitingPayment"


def test_no_scheduled_downgrade_is_none(client, owner_in):
    assert read_subscription(client, owner_in.headers)["scheduledDowngrade"] is None


def test_a_scheduled_downgrade_is_shown_with_the_day_after_the_period_ends(
    client, owner, owner_in, database, make_property
):
    ends_at = datetime(2099, 3, 10, 20, 0, tzinfo=UTC)
    set_subscription(database, owner, plan="pro", ends_at=ends_at)
    kept = make_property(owner, name="Kos A")
    store_schedule(database, owner, "free", [kept.id])
    downgrade = read_subscription(client, owner_in.headers)["scheduledDowngrade"]
    assert downgrade == {
        "planCode": "free",
        "effectiveDate": "2099-03-12",
        "keptPropertyIds": [str(kept.id)],
        "keptRoomIds": [],
    }


def test_a_stored_downgrade_is_hidden_when_no_paid_period_runs(
    client, owner, owner_in, database, make_property, expire_subscription
):
    set_subscription(database, owner, plan="pro")
    kept = make_property(owner, name="Kos A")
    store_schedule(database, owner, "free", [kept.id])
    expire_subscription(owner)
    assert read_subscription(client, owner_in.headers)["scheduledDowngrade"] is None


def test_the_downgrade_of_another_owner_is_not_shown(
    client, owner_in, make_user, database, make_property
):
    other = make_user()
    set_subscription(database, other, plan="pro")
    store_schedule(database, other, "free", [make_property(other).id])
    assert read_subscription(client, owner_in.headers)["scheduledDowngrade"] is None


# Creating an order


@pytest.mark.parametrize("plan", ["basic", "pro"])
@pytest.mark.parametrize("period", ["monthly", "yearly"])
def test_a_free_owner_can_order_any_paid_plan_and_period(
    client, owner_in, plan, period
):
    response = create_order(client, owner_in.headers, plan, period)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ORDER_FIELDS
    assert body["planCode"] == plan
    assert body["billingPeriod"] == period
    assert body["status"] == "awaitingPayment"
    assert body["googlePlayProductId"] == f"niscala_{plan}"
    assert body["googlePlayBasePlanId"] == period


def test_an_order_carries_the_owner_account_id(client, owner, owner_in):
    body = create_order(client, owner_in.headers).json()
    assert body["obfuscatedAccountId"] == str(owner.id)


def test_every_order_of_an_owner_carries_the_same_account_id(client, owner_in):
    first = create_order(client, owner_in.headers, "basic", "monthly").json()
    second = create_order(client, owner_in.headers, "pro", "yearly").json()
    assert first["obfuscatedAccountId"] == second["obfuscatedAccountId"]


def test_the_account_id_differs_between_owners(client, owner_in, make_user, sign_in):
    other_in = sign_in(make_user())
    mine = create_order(client, owner_in.headers).json()
    theirs = create_order(client, other_in.headers).json()
    assert mine["obfuscatedAccountId"] != theirs["obfuscatedAccountId"]


def test_an_order_is_created_at_the_current_time(client, owner_in):
    before = datetime.now(UTC)
    body = create_order(client, owner_in.headers).json()
    after = datetime.now(UTC)
    assert body["createdAt"].endswith("Z")
    created = datetime.fromisoformat(body["createdAt"])
    assert before - timedelta(seconds=1) <= created <= after + timedelta(seconds=1)


def test_an_order_is_stored_and_expires_three_days_after_creation(
    client, owner, owner_in, database
):
    body = create_order(client, owner_in.headers, "pro", "yearly").json()
    row = stored_order(database, body["id"])
    assert row.owner_id == owner.id
    assert row.plan == "pro"
    assert row.billing_period == "yearly"
    assert row.status == "awaitingPayment"
    assert row.purchase_token is None
    assert row.expires_at - row.created_at == timedelta(days=3)


def test_every_order_gets_its_own_id(client, owner_in):
    first = create_order(client, owner_in.headers).json()
    second = create_order(client, owner_in.headers).json()
    assert first["id"] != second["id"]


def test_the_new_order_becomes_the_open_order(client, owner_in):
    created = create_order(client, owner_in.headers, "pro", "monthly").json()
    open_order = read_subscription(client, owner_in.headers)["openOrder"]
    assert open_order == created


def test_a_new_order_expires_the_earlier_open_order(client, owner, owner_in, database):
    first = create_order(client, owner_in.headers, "basic", "monthly").json()
    second = create_order(client, owner_in.headers, "pro", "yearly").json()
    assert stored_order(database, first["id"]).status == "expired"
    assert stored_order(database, second["id"]).status == "awaitingPayment"
    reread = client.get(f"{ORDERS_URL}/{first['id']}", headers=owner_in.headers)
    assert reread.json()["status"] == "expired"
    assert (
        read_subscription(client, owner_in.headers)["openOrder"]["id"] == (second["id"])
    )


def test_a_new_order_expires_every_earlier_open_order(
    client, owner, owner_in, database
):
    older = insert_order(database, owner, created_at=datetime.now(UTC) - timedelta(1))
    newer = insert_order(database, owner, created_at=datetime.now(UTC) - timedelta(0.5))
    create_order(client, owner_in.headers)
    assert stored_order(database, older.id).status == "expired"
    assert stored_order(database, newer.id).status == "expired"


@pytest.mark.parametrize("status", ["succeeded", "failed", "expired"])
def test_a_new_order_leaves_finished_orders_alone(
    client, owner, owner_in, database, status
):
    finished = insert_order(database, owner, status=status)
    create_order(client, owner_in.headers)
    assert stored_order(database, finished.id).status == status


def test_a_new_order_leaves_the_orders_of_other_owners_alone(
    client, owner_in, make_user, database
):
    other_order = insert_order(database, make_user())
    create_order(client, owner_in.headers)
    assert stored_order(database, other_order.id).status == "awaitingPayment"


def test_a_new_order_saves_a_lapsed_order_as_expired(client, owner, owner_in, database):
    lapsed = insert_order(
        database,
        owner,
        created_at=datetime.now(UTC) - timedelta(days=4),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    create_order(client, owner_in.headers)
    assert stored_order(database, lapsed.id).status == "expired"


def test_creating_an_order_does_not_change_the_subscription(
    client, owner, owner_in, database
):
    create_order(client, owner_in.headers, "pro", "yearly")
    body = read_subscription(client, owner_in.headers)
    assert body["planCode"] == "free"
    assert body["status"] == "free"


@pytest.mark.parametrize(
    ("current", "ordered"),
    [("free", "basic"), ("free", "pro"), ("basic", "pro")],
)
def test_a_higher_plan_than_the_current_one_is_accepted(
    client, owner, owner_in, database, current, ordered
):
    if current != "free":
        set_subscription(database, owner, plan=current)
    assert create_order(client, owner_in.headers, ordered).status_code == 201


@pytest.mark.parametrize(
    ("current", "ordered"),
    [("basic", "basic"), ("pro", "pro"), ("pro", "basic")],
)
@pytest.mark.parametrize("period", ["monthly", "yearly"])
def test_the_same_or_a_lower_plan_is_not_an_upgrade(
    client, owner, owner_in, database, current, ordered, period
):
    set_subscription(database, owner, plan=current)
    response = create_order(client, owner_in.headers, ordered, period)
    assert_error(response, 409, "SUBSCRIPTION_NOT_AN_UPGRADE")


def test_a_rejected_order_is_not_stored_and_expires_nothing(
    client, owner, owner_in, database
):
    set_subscription(database, owner, plan="pro")
    open_order = insert_order(database, owner, plan="pro")
    create_order(client, owner_in.headers, "basic")
    rows = stored_orders(database, owner)
    assert [row.id for row in rows] == [open_order.id]
    assert rows[0].status == "awaitingPayment"


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_an_ended_period_counts_as_the_free_plan_for_ordering(
    client, owner, owner_in, database, expire_subscription, plan
):
    set_subscription(database, owner, plan=plan)
    expire_subscription(owner)
    assert create_order(client, owner_in.headers, "basic").status_code == 201


def test_plan_limits_are_not_checked_when_ordering(
    client, owner_in, owner, make_property
):
    for number in range(3):
        make_property(owner, name=f"Kos {number}")
    assert create_order(client, owner_in.headers, "basic").status_code == 201


@pytest.mark.parametrize(
    ("body", "field"),
    [
        pytest.param(
            {"planCode": "free", "billingPeriod": "monthly"}, "planCode", id="free"
        ),
        pytest.param(
            {"planCode": "gold", "billingPeriod": "monthly"},
            "planCode",
            id="unknown_plan",
        ),
        pytest.param(
            {"planCode": "basic", "billingPeriod": "weekly"},
            "billingPeriod",
            id="bad_period",
        ),
        pytest.param({"billingPeriod": "monthly"}, "planCode", id="missing_plan"),
        pytest.param({"planCode": "basic"}, "billingPeriod", id="missing_period"),
    ],
)
def test_an_invalid_order_body_is_a_validation_failure(
    client, owner, owner_in, database, body, field
):
    response = client.post(ORDERS_URL, json=body, headers=owner_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", field)
    assert stored_orders(database, owner) == []


# Reading an order


def test_an_order_can_be_read_by_its_owner(client, owner, owner_in, database):
    order = insert_order(database, owner, plan="pro", billing_period="yearly")
    response = client.get(f"{ORDERS_URL}/{order.id}", headers=owner_in.headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == ORDER_FIELDS
    assert body["id"] == str(order.id)
    assert body["planCode"] == "pro"
    assert body["billingPeriod"] == "yearly"
    assert body["status"] == "awaitingPayment"
    assert body["googlePlayProductId"] == "niscala_pro"
    assert body["googlePlayBasePlanId"] == "yearly"
    assert body["obfuscatedAccountId"] == str(owner.id)


def test_a_created_order_reads_back_the_same(client, owner_in):
    created = create_order(client, owner_in.headers).json()
    response = client.get(f"{ORDERS_URL}/{created['id']}", headers=owner_in.headers)
    assert response.json() == created


@pytest.mark.parametrize("status", ["succeeded", "failed", "expired"])
def test_a_finished_order_reports_its_status(client, owner, owner_in, database, status):
    order = insert_order(
        database,
        owner,
        status=status,
        created_at=datetime.now(UTC) - timedelta(days=10),
        expires_at=datetime.now(UTC) - timedelta(days=7),
    )
    response = client.get(f"{ORDERS_URL}/{order.id}", headers=owner_in.headers)
    assert response.json()["status"] == status
    assert stored_order(database, order.id).status == status


def test_an_unknown_order_is_not_found(client, owner_in):
    response = client.get(f"{ORDERS_URL}/{uuid4()}", headers=owner_in.headers)
    assert_error(response, 404, "SUBSCRIPTION_ORDER_NOT_FOUND")


def test_the_order_of_another_owner_is_not_found(client, owner_in, make_user, database):
    other_order = insert_order(database, make_user())
    response = client.get(f"{ORDERS_URL}/{other_order.id}", headers=owner_in.headers)
    assert_error(response, 404, "SUBSCRIPTION_ORDER_NOT_FOUND")


def test_a_lapsed_order_is_reported_and_saved_as_expired(
    client, owner, owner_in, database
):
    order = insert_order(
        database,
        owner,
        created_at=datetime.now(UTC) - timedelta(days=4),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    response = client.get(f"{ORDERS_URL}/{order.id}", headers=owner_in.headers)
    assert response.json()["status"] == "expired"
    assert stored_order(database, order.id).status == "expired"


def test_an_order_not_yet_lapsed_stays_awaiting_payment(
    client, owner, owner_in, database
):
    order = insert_order(
        database,
        owner,
        created_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    response = client.get(f"{ORDERS_URL}/{order.id}", headers=owner_in.headers)
    assert response.json()["status"] == "awaitingPayment"
    assert stored_order(database, order.id).status == "awaitingPayment"


def test_a_lapsed_order_with_a_purchase_token_stays_awaiting_payment(
    client, owner, owner_in, database
):
    order = insert_order(
        database,
        owner,
        purchase_token="token-2",
        created_at=datetime.now(UTC) - timedelta(days=4),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    response = client.get(f"{ORDERS_URL}/{order.id}", headers=owner_in.headers)
    assert response.json()["status"] == "awaitingPayment"
    assert stored_order(database, order.id).status == "awaitingPayment"
