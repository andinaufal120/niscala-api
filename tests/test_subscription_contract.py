"""Contract tests for the subscription endpoints."""

from typing import Any

import pytest
from conftest import (
    NOT_A_UUID,
    ORDER_ID,
    PROPERTY_ID,
    ROOM_ID,
    OpenApiDoc,
    nullable_inner,
)

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

SUBSCRIPTION_PATHS = {
    "/subscription-plans": {"get"},
    "/subscription": {"get"},
    "/subscription/orders": {"post"},
    "/subscription/orders/{orderId}": {"get"},
    "/subscription/orders/{orderId}/purchase-verification": {"post"},
    "/subscription/scheduled-downgrade": {"put", "delete"},
}

# (method, path, operationId, success status)
SUBSCRIPTION_OPERATIONS = [
    ("get", "/subscription-plans", "list_subscription_plans", 200),
    ("get", "/subscription", "get_subscription", 200),
    ("post", "/subscription/orders", "create_subscription_order", 201),
    ("get", "/subscription/orders/{orderId}", "get_subscription_order", 200),
    (
        "post",
        "/subscription/orders/{orderId}/purchase-verification",
        "verify_subscription_purchase",
        200,
    ),
    (
        "put",
        "/subscription/scheduled-downgrade",
        "schedule_subscription_downgrade",
        200,
    ),
    (
        "delete",
        "/subscription/scheduled-downgrade",
        "cancel_subscription_downgrade",
        204,
    ),
]

ORDER_ID_OPERATIONS = [
    pytest.param("get", "/subscription/orders/{orderId}", id="get_order"),
    pytest.param(
        "post",
        "/subscription/orders/{orderId}/purchase-verification",
        id="verify_purchase",
    ),
]

NEW_COMPONENTS = [
    "PlanCode",
    "PaidPlanCode",
    "SubscriptionPeriod",
    "SubscriptionStatus",
    "OrderStatus",
    "SubscriptionPlanPrice",
    "SubscriptionPlan",
    "SubscriptionPlanList",
    "ScheduledDowngrade",
    "ScheduledDowngradeInput",
    "SubscriptionOrderInput",
    "SubscriptionOrder",
    "PurchaseVerificationInput",
    "Subscription",
]

VALID_ORDER_INPUT = {"planCode": "basic", "billingPeriod": "monthly"}
VALID_VERIFICATION_INPUT = {"purchaseToken": "token-abc-123"}
VALID_DOWNGRADE_INPUT = {
    "planCode": "free",
    "keptPropertyIds": [PROPERTY_ID],
    "keptRoomIds": [ROOM_ID],
}

ORDERS_URL = "/subscription/orders"
ORDER_URL = f"/subscription/orders/{ORDER_ID}"
VERIFICATION_URL = f"/subscription/orders/{ORDER_ID}/purchase-verification"
DOWNGRADE_URL = "/subscription/scheduled-downgrade"


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_string_enum(schema: dict[str, Any], values: list[str]) -> None:
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(values)
    assert len(schema["enum"]) == len(values)


def _assert_date_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "date"


# Paths, operations, tags, security and status codes


@pytest.mark.parametrize(("path", "methods"), SUBSCRIPTION_PATHS.items())
def test_subscription_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), SUBSCRIPTION_OPERATIONS
)
def test_subscription_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), SUBSCRIPTION_OPERATIONS
)
def test_subscription_operation_is_tagged_subscriptions(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["subscriptions"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), SUBSCRIPTION_OPERATIONS
)
def test_subscription_operation_requires_bearer_authentication(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), SUBSCRIPTION_OPERATIONS
)
def test_subscription_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_cancel_subscription_downgrade_success_response_has_no_body(
    openapi: OpenApiDoc,
) -> None:
    response = openapi.operation("delete", DOWNGRADE_URL)["responses"]["204"]
    assert "content" not in response


@pytest.mark.parametrize(("method", "path"), ORDER_ID_OPERATIONS)
def test_order_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == ["orderId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/subscription-plans"),
        ("get", "/subscription"),
        ("post", "/subscription/orders"),
        ("put", "/subscription/scheduled-downgrade"),
        ("delete", "/subscription/scheduled-downgrade"),
    ],
    ids=[
        "list_subscription_plans",
        "get_subscription",
        "create_subscription_order",
        "schedule_subscription_downgrade",
        "cancel_subscription_downgrade",
    ],
)
def test_operation_without_path_id_takes_no_parameters(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path).get("parameters", []) == []


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path", "schema"),
    [
        ("post", "/subscription/orders", "SubscriptionOrderInput"),
        (
            "post",
            "/subscription/orders/{orderId}/purchase-verification",
            "PurchaseVerificationInput",
        ),
        ("put", "/subscription/scheduled-downgrade", "ScheduledDowngradeInput"),
    ],
    ids=["create_order", "verify_purchase", "schedule_downgrade"],
)
def test_subscription_write_request_body_schema(
    openapi: OpenApiDoc, method: str, path: str, schema: str
) -> None:
    assert openapi.request_schema_ref(method, path) == schema


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/subscription-plans"),
        ("get", "/subscription"),
        ("get", "/subscription/orders/{orderId}"),
        ("delete", "/subscription/scheduled-downgrade"),
    ],
    ids=[
        "list_subscription_plans",
        "get_subscription",
        "get_subscription_order",
        "cancel_subscription_downgrade",
    ],
)
def test_subscription_read_and_delete_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    [
        ("get", "/subscription-plans", 200, "SubscriptionPlanList"),
        ("get", "/subscription", 200, "Subscription"),
        ("post", "/subscription/orders", 201, "SubscriptionOrder"),
        ("get", "/subscription/orders/{orderId}", 200, "SubscriptionOrder"),
        (
            "post",
            "/subscription/orders/{orderId}/purchase-verification",
            200,
            "SubscriptionOrder",
        ),
        ("put", "/subscription/scheduled-downgrade", 200, "ScheduledDowngrade"),
    ],
    ids=[
        "list_subscription_plans",
        "get_subscription",
        "create_subscription_order",
        "get_subscription_order",
        "verify_subscription_purchase",
        "schedule_subscription_downgrade",
    ],
)
def test_subscription_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


@pytest.mark.parametrize("name", NEW_COMPONENTS)
def test_subscription_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


# Enums


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("PlanCode", ["free", "basic", "pro"]),
        ("PaidPlanCode", ["basic", "pro"]),
        ("SubscriptionPeriod", ["monthly", "yearly"]),
        ("SubscriptionStatus", ["free", "active"]),
        ("OrderStatus", ["awaitingPayment", "succeeded", "failed", "expired"]),
    ],
)
def test_subscription_enum_has_exactly_its_values(
    openapi: OpenApiDoc, name: str, values: list[str]
) -> None:
    _assert_string_enum(openapi.component(name), values)


# SubscriptionPlanPrice


@pytest.fixture
def plan_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("SubscriptionPlan")


@pytest.fixture
def plan_price_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("SubscriptionPlanPrice")


PLAN_PRICE_FIELDS = {
    "billingPeriod",
    "amount",
    "googlePlayProductId",
    "googlePlayBasePlanId",
}


def test_plan_price_has_exactly_its_fields(plan_price_schema: dict[str, Any]) -> None:
    assert _property_names(plan_price_schema) == PLAN_PRICE_FIELDS


def test_plan_price_requires_every_field(plan_price_schema: dict[str, Any]) -> None:
    assert set(plan_price_schema["required"]) == PLAN_PRICE_FIELDS


def test_plan_price_billing_period_is_subscription_period(
    openapi: OpenApiDoc, plan_price_schema: dict[str, Any]
) -> None:
    schema = plan_price_schema["properties"]["billingPeriod"]
    assert openapi.ref_name(schema) == "SubscriptionPeriod"


def test_plan_price_amount_is_positive_integer(
    plan_price_schema: dict[str, Any],
) -> None:
    schema = plan_price_schema["properties"]["amount"]
    assert schema["type"] == "integer"
    assert schema["exclusiveMinimum"] == 0


@pytest.mark.parametrize("field", ["googlePlayProductId", "googlePlayBasePlanId"])
def test_plan_price_google_play_id_is_string(
    plan_price_schema: dict[str, Any], field: str
) -> None:
    assert plan_price_schema["properties"][field]["type"] == "string"


# SubscriptionPlan

PLAN_FIELDS = {"code", "maxProperties", "maxRoomsPerProperty", "aiEnabled", "prices"}


def test_plan_has_exactly_its_fields(plan_schema: dict[str, Any]) -> None:
    assert _property_names(plan_schema) == PLAN_FIELDS


def test_plan_requires_every_field(plan_schema: dict[str, Any]) -> None:
    assert set(plan_schema["required"]) == PLAN_FIELDS


def test_plan_code_is_plan_code(
    openapi: OpenApiDoc, plan_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(plan_schema["properties"]["code"]) == "PlanCode"


@pytest.mark.parametrize("field", ["maxProperties", "maxRoomsPerProperty"])
def test_plan_limit_is_nullable_integer_meaning_unlimited(
    plan_schema: dict[str, Any], field: str
) -> None:
    assert nullable_inner(plan_schema["properties"][field])["type"] == "integer"


def test_plan_ai_enabled_is_boolean(plan_schema: dict[str, Any]) -> None:
    assert plan_schema["properties"]["aiEnabled"]["type"] == "boolean"


def test_plan_prices_is_array_of_plan_price(
    openapi: OpenApiDoc, plan_schema: dict[str, Any]
) -> None:
    schema = plan_schema["properties"]["prices"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "SubscriptionPlanPrice"


# SubscriptionPlanList


def test_plan_list_has_required_items_array_of_plan(openapi: OpenApiDoc) -> None:
    schema = openapi.component("SubscriptionPlanList")
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "SubscriptionPlan"


# SubscriptionOrderInput


@pytest.fixture
def order_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("SubscriptionOrderInput")


def test_order_input_has_exactly_its_required_fields(
    order_input_schema: dict[str, Any],
) -> None:
    assert _property_names(order_input_schema) == {"planCode", "billingPeriod"}
    assert set(order_input_schema["required"]) == {"planCode", "billingPeriod"}


def test_order_input_plan_code_is_paid_plan_code(
    openapi: OpenApiDoc, order_input_schema: dict[str, Any]
) -> None:
    schema = order_input_schema["properties"]["planCode"]
    assert openapi.ref_name(schema) == "PaidPlanCode"


def test_order_input_billing_period_is_subscription_period(
    openapi: OpenApiDoc, order_input_schema: dict[str, Any]
) -> None:
    schema = order_input_schema["properties"]["billingPeriod"]
    assert openapi.ref_name(schema) == "SubscriptionPeriod"


# SubscriptionOrder

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


@pytest.fixture
def order_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("SubscriptionOrder")


def test_order_has_exactly_its_fields(order_schema: dict[str, Any]) -> None:
    assert _property_names(order_schema) == ORDER_FIELDS


def test_order_requires_every_field(order_schema: dict[str, Any]) -> None:
    assert set(order_schema["required"]) == ORDER_FIELDS


def test_order_id_is_uuid_string(order_schema: dict[str, Any]) -> None:
    _assert_uuid_string(order_schema["properties"]["id"])


def test_order_plan_code_is_paid_plan_code(
    openapi: OpenApiDoc, order_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(order_schema["properties"]["planCode"]) == "PaidPlanCode"


def test_order_billing_period_is_subscription_period(
    openapi: OpenApiDoc, order_schema: dict[str, Any]
) -> None:
    schema = order_schema["properties"]["billingPeriod"]
    assert openapi.ref_name(schema) == "SubscriptionPeriod"


def test_order_status_is_order_status(
    openapi: OpenApiDoc, order_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(order_schema["properties"]["status"]) == "OrderStatus"


@pytest.mark.parametrize(
    "field", ["googlePlayProductId", "googlePlayBasePlanId", "obfuscatedAccountId"]
)
def test_order_text_field_is_string(order_schema: dict[str, Any], field: str) -> None:
    assert order_schema["properties"][field]["type"] == "string"


def test_order_created_at_is_date_time_string(order_schema: dict[str, Any]) -> None:
    schema = order_schema["properties"]["createdAt"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


# PurchaseVerificationInput


@pytest.fixture
def verification_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PurchaseVerificationInput")


def test_purchase_verification_input_has_only_required_purchase_token(
    verification_input_schema: dict[str, Any],
) -> None:
    assert _property_names(verification_input_schema) == {"purchaseToken"}
    assert set(verification_input_schema["required"]) == {"purchaseToken"}


def test_purchase_token_is_non_empty_string(
    verification_input_schema: dict[str, Any],
) -> None:
    schema = verification_input_schema["properties"]["purchaseToken"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


# ScheduledDowngradeInput


@pytest.fixture
def downgrade_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ScheduledDowngradeInput")


def test_downgrade_input_has_exactly_its_fields(
    downgrade_input_schema: dict[str, Any],
) -> None:
    assert _property_names(downgrade_input_schema) == {
        "planCode",
        "keptPropertyIds",
        "keptRoomIds",
    }


def test_downgrade_input_requires_plan_code_and_kept_property_ids_only(
    downgrade_input_schema: dict[str, Any],
) -> None:
    assert set(downgrade_input_schema["required"]) == {"planCode", "keptPropertyIds"}


def test_downgrade_input_plan_code_is_plan_code(
    openapi: OpenApiDoc, downgrade_input_schema: dict[str, Any]
) -> None:
    schema = downgrade_input_schema["properties"]["planCode"]
    assert openapi.ref_name(schema) == "PlanCode"


@pytest.mark.parametrize("field", ["keptPropertyIds", "keptRoomIds"])
def test_downgrade_input_kept_ids_is_array_of_uuid_strings(
    downgrade_input_schema: dict[str, Any], field: str
) -> None:
    schema = downgrade_input_schema["properties"][field]
    assert schema["type"] == "array"
    _assert_uuid_string(schema["items"])


def test_downgrade_input_kept_room_ids_defaults_to_empty(
    downgrade_input_schema: dict[str, Any],
) -> None:
    assert downgrade_input_schema["properties"]["keptRoomIds"]["default"] == []


# ScheduledDowngrade

DOWNGRADE_FIELDS = {"planCode", "effectiveDate", "keptPropertyIds", "keptRoomIds"}


@pytest.fixture
def downgrade_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ScheduledDowngrade")


def test_downgrade_has_exactly_its_fields(downgrade_schema: dict[str, Any]) -> None:
    assert _property_names(downgrade_schema) == DOWNGRADE_FIELDS


def test_downgrade_requires_every_field(downgrade_schema: dict[str, Any]) -> None:
    assert set(downgrade_schema["required"]) == DOWNGRADE_FIELDS


def test_downgrade_plan_code_is_plan_code(
    openapi: OpenApiDoc, downgrade_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(downgrade_schema["properties"]["planCode"]) == "PlanCode"


def test_downgrade_effective_date_is_date_string(
    downgrade_schema: dict[str, Any],
) -> None:
    _assert_date_string(downgrade_schema["properties"]["effectiveDate"])


@pytest.mark.parametrize("field", ["keptPropertyIds", "keptRoomIds"])
def test_downgrade_kept_ids_is_array_of_uuid_strings(
    downgrade_schema: dict[str, Any], field: str
) -> None:
    schema = downgrade_schema["properties"][field]
    assert schema["type"] == "array"
    _assert_uuid_string(schema["items"])


# Subscription

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


@pytest.fixture
def subscription_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("Subscription")


def test_subscription_has_exactly_its_fields(
    subscription_schema: dict[str, Any],
) -> None:
    assert _property_names(subscription_schema) == SUBSCRIPTION_FIELDS


def test_subscription_requires_every_field(subscription_schema: dict[str, Any]) -> None:
    assert set(subscription_schema["required"]) == SUBSCRIPTION_FIELDS


def test_subscription_plan_code_is_plan_code(
    openapi: OpenApiDoc, subscription_schema: dict[str, Any]
) -> None:
    schema = subscription_schema["properties"]["planCode"]
    assert openapi.ref_name(schema) == "PlanCode"


def test_subscription_status_is_subscription_status(
    openapi: OpenApiDoc, subscription_schema: dict[str, Any]
) -> None:
    schema = subscription_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "SubscriptionStatus"


def test_subscription_billing_period_is_nullable_subscription_period(
    openapi: OpenApiDoc, subscription_schema: dict[str, Any]
) -> None:
    schema = subscription_schema["properties"]["billingPeriod"]
    assert openapi.ref_name(nullable_inner(schema)) == "SubscriptionPeriod"


def test_subscription_end_date_is_nullable_date_string(
    subscription_schema: dict[str, Any],
) -> None:
    _assert_date_string(nullable_inner(subscription_schema["properties"]["endDate"]))


def test_subscription_auto_renew_is_boolean(
    subscription_schema: dict[str, Any],
) -> None:
    assert subscription_schema["properties"]["autoRenew"]["type"] == "boolean"


def test_subscription_property_count_is_integer(
    subscription_schema: dict[str, Any],
) -> None:
    assert subscription_schema["properties"]["propertyCount"]["type"] == "integer"


def test_subscription_open_order_is_nullable_subscription_order(
    openapi: OpenApiDoc, subscription_schema: dict[str, Any]
) -> None:
    schema = subscription_schema["properties"]["openOrder"]
    assert openapi.ref_name(nullable_inner(schema)) == "SubscriptionOrder"


def test_subscription_scheduled_downgrade_is_nullable_scheduled_downgrade(
    openapi: OpenApiDoc, subscription_schema: dict[str, Any]
) -> None:
    schema = subscription_schema["properties"]["scheduledDowngrade"]
    assert openapi.ref_name(nullable_inner(schema)) == "ScheduledDowngrade"


# Runtime: valid requests reach the not-implemented stub


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param("get", "/subscription-plans", None, id="list_plans"),
        pytest.param("get", "/subscription", None, id="get_subscription"),
        pytest.param("post", ORDERS_URL, VALID_ORDER_INPUT, id="create_order"),
        pytest.param("get", ORDER_URL, None, id="get_order"),
        pytest.param(
            "post", VERIFICATION_URL, VALID_VERIFICATION_INPUT, id="verify_purchase"
        ),
        pytest.param("put", DOWNGRADE_URL, VALID_DOWNGRADE_INPUT, id="schedule"),
        pytest.param("delete", DOWNGRADE_URL, None, id="cancel_downgrade"),
    ],
)
def test_valid_subscription_request_responds_not_implemented(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"planCode": "basic", "billingPeriod": "yearly"}, id="basic_year"),
        pytest.param({"planCode": "pro", "billingPeriod": "monthly"}, id="pro_month"),
        pytest.param({"planCode": "pro", "billingPeriod": "yearly"}, id="pro_year"),
    ],
)
def test_order_input_every_paid_plan_and_period_is_accepted(
    client, body: dict[str, Any]
) -> None:
    response = client.post(ORDERS_URL, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {"planCode": "free", "keptPropertyIds": [PROPERTY_ID]},
            id="kept_rooms_omitted",
        ),
        pytest.param(
            {"planCode": "free", "keptPropertyIds": [PROPERTY_ID], "keptRoomIds": []},
            id="kept_rooms_empty",
        ),
        pytest.param(
            {"planCode": "basic", "keptPropertyIds": [PROPERTY_ID, PROPERTY_ID]},
            id="basic_with_property_list",
        ),
    ],
)
def test_downgrade_input_edge_body_is_accepted(client, body: dict[str, Any]) -> None:
    response = client.put(DOWNGRADE_URL, json=body)
    assert response.status_code == 501


def test_purchase_token_of_one_character_is_accepted(client) -> None:
    response = client.post(VERIFICATION_URL, json={"purchaseToken": "t"})
    assert response.status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_without(VALID_ORDER_INPUT, "planCode"), id="missing_plan_code"),
        pytest.param(
            _without(VALID_ORDER_INPUT, "billingPeriod"), id="missing_billing_period"
        ),
        pytest.param({**VALID_ORDER_INPUT, "planCode": "free"}, id="free_plan_code"),
        pytest.param({**VALID_ORDER_INPUT, "planCode": "gold"}, id="unknown_plan"),
        pytest.param({**VALID_ORDER_INPUT, "planCode": None}, id="null_plan_code"),
        pytest.param({**VALID_ORDER_INPUT, "planCode": "BASIC"}, id="plan_wrong_case"),
        pytest.param(
            {**VALID_ORDER_INPUT, "billingPeriod": "weekly"}, id="unknown_period"
        ),
        pytest.param(
            {**VALID_ORDER_INPUT, "billingPeriod": None}, id="null_billing_period"
        ),
        pytest.param({}, id="empty_object"),
    ],
)
def test_invalid_order_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    response = client.post(ORDERS_URL, json=body)
    assert response.status_code == 422


def test_create_order_without_body_is_rejected_with_validation_error(client) -> None:
    response = client.post(ORDERS_URL)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing_purchase_token"),
        pytest.param({"purchaseToken": ""}, id="empty_purchase_token"),
        pytest.param({"purchaseToken": None}, id="null_purchase_token"),
        pytest.param({"purchaseToken": 123}, id="numeric_purchase_token"),
    ],
)
def test_invalid_purchase_verification_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    response = client.post(VERIFICATION_URL, json=body)
    assert response.status_code == 422


def test_verify_purchase_without_body_is_rejected_with_validation_error(client) -> None:
    response = client.post(VERIFICATION_URL)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_without(VALID_DOWNGRADE_INPUT, "planCode"), id="missing_plan"),
        pytest.param(
            _without(VALID_DOWNGRADE_INPUT, "keptPropertyIds"),
            id="missing_kept_property_ids",
        ),
        pytest.param({**VALID_DOWNGRADE_INPUT, "planCode": "gold"}, id="unknown_plan"),
        pytest.param({**VALID_DOWNGRADE_INPUT, "planCode": None}, id="null_plan"),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptPropertyIds": None},
            id="null_kept_property_ids",
        ),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptPropertyIds": PROPERTY_ID},
            id="kept_property_ids_not_array",
        ),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptPropertyIds": [NOT_A_UUID]},
            id="non_uuid_kept_property_id",
        ),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptRoomIds": [NOT_A_UUID]},
            id="non_uuid_kept_room_id",
        ),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptRoomIds": ROOM_ID},
            id="kept_room_ids_not_array",
        ),
        pytest.param(
            {**VALID_DOWNGRADE_INPUT, "keptRoomIds": None}, id="null_kept_room_ids"
        ),
        pytest.param({}, id="empty_object"),
    ],
)
def test_invalid_downgrade_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    response = client.put(DOWNGRADE_URL, json=body)
    assert response.status_code == 422


def test_schedule_downgrade_without_body_is_rejected_with_validation_error(
    client,
) -> None:
    response = client.put(DOWNGRADE_URL)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param("get", f"/subscription/orders/{NOT_A_UUID}", None, id="get_order"),
        pytest.param(
            "post",
            f"/subscription/orders/{NOT_A_UUID}/purchase-verification",
            VALID_VERIFICATION_INPUT,
            id="verify_purchase",
        ),
    ],
)
def test_non_uuid_order_id_is_rejected_with_validation_error(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 422
