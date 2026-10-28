"""Contract tests for the notification, notification-settings and push-token endpoints."""

from typing import Any

import pytest
from conftest import NOT_A_UUID, NOTIFICATION_ID, OpenApiDoc, nullable_inner
from notification_support import assert_error, settings_items, upload_receipt

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

NOTIFICATION_PATHS = {
    "/notifications": {"get"},
    "/notifications/{notificationId}/read": {"post"},
    "/notifications/read-all": {"post"},
    "/me/notification-settings": {"get", "put"},
    "/me/push-token": {"put"},
}

# (method, path, operationId, success status)
NOTIFICATION_OPERATIONS = [
    ("get", "/notifications", "list_notifications", 200),
    (
        "post",
        "/notifications/{notificationId}/read",
        "mark_notification_read",
        200,
    ),
    ("post", "/notifications/read-all", "mark_all_notifications_read", 204),
    ("get", "/me/notification-settings", "get_notification_settings", 200),
    ("put", "/me/notification-settings", "update_notification_settings", 200),
    ("put", "/me/push-token", "register_push_token", 204),
]

NO_PARAMETER_OPERATIONS = [
    pytest.param("get", "/notifications", id="list_notifications"),
    pytest.param("post", "/notifications/read-all", id="mark_all_notifications_read"),
    pytest.param("get", "/me/notification-settings", id="get_notification_settings"),
    pytest.param("put", "/me/notification-settings", id="update_notification_settings"),
    pytest.param("put", "/me/push-token", id="register_push_token"),
]

NO_REQUEST_BODY_OPERATIONS = [
    pytest.param("get", "/notifications", id="list_notifications"),
    pytest.param(
        "post", "/notifications/{notificationId}/read", id="mark_notification_read"
    ),
    pytest.param("post", "/notifications/read-all", id="mark_all_notifications_read"),
    pytest.param("get", "/me/notification-settings", id="get_notification_settings"),
]

NO_RESPONSE_BODY_OPERATIONS = [
    pytest.param("post", "/notifications/read-all", 204, id="read_all"),
    pytest.param("put", "/me/push-token", 204, id="push_token"),
]

NOTIFICATION_TYPES = [
    "billIssued",
    "dueDateReminder",
    "billOverdue",
    "paymentStatusChanged",
    "complaintStatusChanged",
    "complaintSubmitted",
    "receiptUploaded",
    "cashPaymentRecorded",
    "tenantActivated",
    "managerActivated",
]
NOTIFICATION_CATEGORIES = [
    "billing",
    "paymentStatus",
    "complaintProgress",
    "newComplaint",
    "receiptUpload",
    "overdueBill",
    "accountActivity",
]
URGENCY_SCOPES = ["allUrgencies", "highOnly"]

# Component name -> (all properties, required properties).
NOTIFICATION_FIELDS = {
    "id",
    "type",
    "createdAt",
    "read",
    "rentBill",
    "complaint",
    "tenant",
    "room",
    "property",
    "actorName",
}
RENT_BILL_FIELDS = {
    "rentBillId",
    "periodStart",
    "periodEnd",
    "dueDate",
    "amount",
    "paymentStatus",
    "paymentMethod",
    "reason",
    "daysOverdue",
}
COMPLAINT_FIELDS = {
    "complaintId",
    "description",
    "status",
    "category",
    "urgency",
    "handlingNote",
}
COMPONENT_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "Notification": (NOTIFICATION_FIELDS, NOTIFICATION_FIELDS),
    "NotificationRentBill": (RENT_BILL_FIELDS, RENT_BILL_FIELDS),
    "NotificationComplaint": (COMPLAINT_FIELDS, COMPLAINT_FIELDS),
    "NotificationList": ({"items", "unreadCount"}, {"items", "unreadCount"}),
    "NotificationSettings": ({"items"}, {"items"}),
    "NotificationSettingsInput": ({"items"}, {"items"}),
    "PushTokenInput": ({"token"}, {"token"}),
}
ENUM_COMPONENTS = {
    "NotificationType": NOTIFICATION_TYPES,
    "NotificationCategory": NOTIFICATION_CATEGORIES,
    "NotificationUrgencyScope": URGENCY_SCOPES,
}

NOTIFICATIONS_URL = "/notifications"
NOTIFICATION_URL = f"/notifications/{NOTIFICATION_ID}"
MARK_READ_URL = f"{NOTIFICATION_URL}/read"
READ_ALL_URL = "/notifications/read-all"
SETTINGS_URL = "/me/notification-settings"
PUSH_TOKEN_URL = "/me/push-token"

VALID_SETTINGS_INPUT = {"items": settings_items("owner", off=("receiptUpload",))}
VALID_PUSH_TOKEN_INPUT = {"token": "fcm-device-token-123"}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_string_enum(schema: dict[str, Any], values: list[str]) -> None:
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(values)
    assert len(schema["enum"]) == len(values)


def _field(openapi: OpenApiDoc, component: str, field: str) -> dict[str, Any]:
    return openapi.component(component)["properties"][field]


# Paths, operations, tags, security and status codes


@pytest.mark.parametrize(("path", "methods"), NOTIFICATION_PATHS.items())
def test_notification_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), NOTIFICATION_OPERATIONS
)
def test_notification_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), NOTIFICATION_OPERATIONS
)
def test_notification_operation_is_tagged_notifications(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["notifications"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), NOTIFICATION_OPERATIONS
)
def test_notification_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), NOTIFICATION_OPERATIONS
)
def test_notification_operation_requires_bearer_auth(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


def test_mark_notification_read_path_parameter_is_required_uuid(
    openapi: OpenApiDoc,
) -> None:
    operation = openapi.operation("post", "/notifications/{notificationId}/read")
    parameters = operation["parameters"]
    assert [p["name"] for p in parameters] == ["notificationId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


@pytest.mark.parametrize(("method", "path"), NO_PARAMETER_OPERATIONS)
def test_notification_operation_without_path_parameter_declares_no_parameters(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path).get("parameters", []) == []


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path", "schema"),
    [
        ("put", "/me/notification-settings", "NotificationSettingsInput"),
        ("put", "/me/push-token", "PushTokenInput"),
    ],
    ids=["update_notification_settings", "register_push_token"],
)
def test_notification_write_operation_request_body_schema(
    openapi: OpenApiDoc, method: str, path: str, schema: str
) -> None:
    assert openapi.request_schema_ref(method, path) == schema


@pytest.mark.parametrize(("method", "path"), NO_REQUEST_BODY_OPERATIONS)
def test_notification_operation_takes_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    [
        ("get", "/notifications", 200, "NotificationList"),
        ("post", "/notifications/{notificationId}/read", 200, "Notification"),
        ("get", "/me/notification-settings", 200, "NotificationSettings"),
        ("put", "/me/notification-settings", 200, "NotificationSettings"),
    ],
    ids=[
        "list_notifications",
        "mark_notification_read",
        "get_notification_settings",
        "update_notification_settings",
    ],
)
def test_notification_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


@pytest.mark.parametrize(("method", "path", "status"), NO_RESPONSE_BODY_OPERATIONS)
def test_notification_operation_succeeds_without_a_response_body(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    response = openapi.operation(method, path)["responses"][str(status)]
    assert "content" not in response


# Component schemas

ALL_COMPONENTS = [*COMPONENT_FIELDS, "NotificationSettingItem", *ENUM_COMPONENTS]


@pytest.mark.parametrize("name", ALL_COMPONENTS)
def test_notification_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", ALL_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_notification_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", [*COMPONENT_FIELDS, "NotificationSettingItem"])
def test_notification_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_component_has_exactly_its_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert _property_names(openapi.component(name)) == fields[0]


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_component_requires_exactly_its_required_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert set(openapi.component(name).get("required", [])) == fields[1]


# Enums


@pytest.mark.parametrize(("name", "values"), ENUM_COMPONENTS.items())
def test_notification_enum_is_string_enum_of_its_values(
    openapi: OpenApiDoc, name: str, values: list[str]
) -> None:
    _assert_string_enum(openapi.component(name), values)


# Notification


def test_notification_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(_field(openapi, "Notification", "id"))


def test_notification_type_is_notification_type(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Notification", "type")
    assert openapi.ref_name(schema) == "NotificationType"


def test_notification_created_at_is_date_time_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Notification", "createdAt")
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_notification_read_is_boolean(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "Notification", "read")["type"] == "boolean"


@pytest.mark.parametrize(
    ("field", "component"),
    [
        ("rentBill", "NotificationRentBill"),
        ("complaint", "NotificationComplaint"),
        ("tenant", "TenantRef"),
        ("room", "RoomRef"),
        ("property", "PropertyRef"),
    ],
)
def test_notification_optional_object_is_nullable_reference(
    openapi: OpenApiDoc, field: str, component: str
) -> None:
    schema = _field(openapi, "Notification", field)
    assert openapi.ref_name(nullable_inner(schema)) == component


def test_notification_actor_name_is_nullable_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Notification", "actorName")
    assert nullable_inner(schema)["type"] == "string"


# NotificationRentBill


def test_notification_rent_bill_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(_field(openapi, "NotificationRentBill", "rentBillId"))


@pytest.mark.parametrize("field", ["periodStart", "periodEnd", "dueDate"])
def test_notification_rent_bill_date_field_is_date_string(
    openapi: OpenApiDoc, field: str
) -> None:
    schema = _field(openapi, "NotificationRentBill", field)
    assert schema["type"] == "string"
    assert schema["format"] == "date"


def test_notification_rent_bill_amount_is_integer(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "NotificationRentBill", "amount")["type"] == "integer"


def test_notification_rent_bill_payment_status_is_payment_status(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationRentBill", "paymentStatus")
    assert openapi.ref_name(schema) == "PaymentStatus"


def test_notification_rent_bill_payment_method_is_nullable_payment_method(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationRentBill", "paymentMethod")
    assert openapi.ref_name(nullable_inner(schema)) == "PaymentMethod"


def test_notification_rent_bill_reason_is_nullable_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "NotificationRentBill", "reason")
    assert nullable_inner(schema)["type"] == "string"


def test_notification_rent_bill_days_overdue_is_non_negative_integer(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationRentBill", "daysOverdue")
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0


# NotificationComplaint


def test_notification_complaint_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(_field(openapi, "NotificationComplaint", "complaintId"))


def test_notification_complaint_description_is_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "NotificationComplaint", "description")
    assert schema["type"] == "string"


def test_notification_complaint_status_is_complaint_status(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationComplaint", "status")
    assert openapi.ref_name(schema) == "ComplaintStatus"


def test_notification_complaint_category_is_nullable_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationComplaint", "category")
    assert nullable_inner(schema)["type"] == "string"


def test_notification_complaint_urgency_is_nullable_complaint_urgency(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationComplaint", "urgency")
    assert openapi.ref_name(nullable_inner(schema)) == "ComplaintUrgency"


def test_notification_complaint_handling_note_is_nullable_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationComplaint", "handlingNote")
    assert nullable_inner(schema)["type"] == "string"


# NotificationList


def test_notification_list_items_is_array_of_notification(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "NotificationList", "items")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "Notification"


def test_notification_list_unread_count_is_non_negative_integer(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationList", "unreadCount")
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0


# NotificationSettingItem, NotificationSettings and NotificationSettingsInput


def test_notification_setting_item_has_exactly_its_fields(openapi: OpenApiDoc) -> None:
    schema = openapi.component("NotificationSettingItem")
    assert _property_names(schema) == {"category", "pushEnabled", "urgencyScope"}


def test_notification_setting_item_requires_category_and_push_enabled(
    openapi: OpenApiDoc,
) -> None:
    required = set(openapi.component("NotificationSettingItem").get("required", []))
    assert {"category", "pushEnabled"} <= required


def test_notification_setting_item_category_is_notification_category(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationSettingItem", "category")
    assert openapi.ref_name(schema) == "NotificationCategory"


def test_notification_setting_item_push_enabled_is_boolean(openapi: OpenApiDoc) -> None:
    assert (
        _field(openapi, "NotificationSettingItem", "pushEnabled")["type"] == "boolean"
    )


def test_notification_setting_item_urgency_scope_is_nullable_urgency_scope(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "NotificationSettingItem", "urgencyScope")
    assert openapi.ref_name(nullable_inner(schema)) == "NotificationUrgencyScope"


@pytest.mark.parametrize("name", ["NotificationSettings", "NotificationSettingsInput"])
def test_notification_settings_items_is_array_of_setting_item(
    openapi: OpenApiDoc, name: str
) -> None:
    schema = _field(openapi, name, "items")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "NotificationSettingItem"


# PushTokenInput


def test_push_token_is_string_of_1_to_1024_characters(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "PushTokenInput", "token")
    assert schema["type"] == "string"
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 1024


# Runtime: valid requests reach the implemented operations


@pytest.fixture
def owner_notification_id(client, scene, make_rent_bill) -> str:
    """The id of a notification waiting in the owner's list."""
    bill = make_rent_bill(scene.tenant.lease)
    assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200
    response = client.get(NOTIFICATIONS_URL, headers=scene.owner_in.headers)
    return response.json()["items"][0]["id"]


@pytest.mark.parametrize(
    ("method", "url", "body", "status"),
    [
        pytest.param("get", NOTIFICATIONS_URL, None, 200, id="list"),
        pytest.param("post", READ_ALL_URL, None, 204, id="mark_all_read"),
        pytest.param("get", SETTINGS_URL, None, 200, id="get_settings"),
        pytest.param(
            "put", SETTINGS_URL, VALID_SETTINGS_INPUT, 200, id="update_settings"
        ),
        pytest.param(
            "put", PUSH_TOKEN_URL, VALID_PUSH_TOKEN_INPUT, 204, id="push_token"
        ),
    ],
)
def test_valid_notification_request_succeeds_for_a_signed_in_user(
    client, scene, method: str, url: str, body: dict[str, Any] | None, status: int
) -> None:
    response = client.request(method, url, json=body, headers=scene.owner_in.headers)
    assert response.status_code == status


def test_marking_an_existing_notification_read_succeeds(
    client, scene, owner_notification_id: str
) -> None:
    response = client.post(
        f"/notifications/{owner_notification_id}/read", headers=scene.owner_in.headers
    )
    assert response.status_code == 200
    assert response.json()["id"] == owner_notification_id


def test_marking_an_unknown_notification_read_is_not_found(client, scene) -> None:
    response = client.post(MARK_READ_URL, headers=scene.owner_in.headers)
    assert_error(response, 404, "NOTIFICATION_NOT_FOUND")


@pytest.mark.parametrize("scope", URGENCY_SCOPES)
def test_every_urgency_scope_is_accepted_in_settings(client, scene, scope: str) -> None:
    body = {"items": settings_items("owner", scope=scope)}
    response = client.put(SETTINGS_URL, json=body, headers=scene.owner_in.headers)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("a", id="single_character"),
        pytest.param("a" * 1024, id="max_length"),
        pytest.param("  abc  ", id="padded_with_whitespace"),
        pytest.param("a" * 1024 + "   ", id="max_length_before_trimming"),
        pytest.param("  " + "a" * 1024, id="max_length_with_leading_whitespace"),
        pytest.param("abc:def-ghi_jkl", id="punctuation"),
    ],
)
def test_push_token_of_1_to_1024_characters_after_trimming_is_accepted(
    client, scene, token: str
) -> None:
    response = client.put(
        PUSH_TOKEN_URL, json={"token": token}, headers=scene.owner_in.headers
    )
    assert response.status_code == 204


def assert_validation_failed(response) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_FAILED"


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(
    ("method", "url"),
    [
        pytest.param("post", f"/notifications/{NOT_A_UUID}/read", id="not_a_uuid"),
        pytest.param("post", "/notifications/123/read", id="number"),
        pytest.param("post", "/notifications/6c5d4e3f-2a1b/read", id="truncated_uuid"),
    ],
)
def test_mark_notification_read_with_malformed_id_is_rejected_with_validation_error(
    client, scene, method: str, url: str
) -> None:
    response = client.request(method, url, headers=scene.owner_in.headers)
    assert_validation_failed(response)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty_object"),
        pytest.param({"token": ""}, id="empty"),
        pytest.param({"token": "   "}, id="blank"),
        pytest.param({"token": "\n\t"}, id="only_control_whitespace"),
        pytest.param({"token": "a" * 1025}, id="too_long"),
        pytest.param({"token": " " + "a" * 1025 + " "}, id="too_long_after_trimming"),
        pytest.param({"token": None}, id="null"),
        pytest.param({"token": 12345}, id="number"),
        pytest.param({"token": ["abc"]}, id="array"),
        pytest.param({"Token": "abc"}, id="wrong_field_name"),
    ],
)
def test_invalid_push_token_input_is_rejected_with_validation_error(
    client, scene, body: dict[str, Any]
) -> None:
    response = client.put(PUSH_TOKEN_URL, json=body, headers=scene.owner_in.headers)
    assert_validation_failed(response)


def test_push_token_without_body_is_rejected_with_validation_error(
    client, scene
) -> None:
    response = client.put(PUSH_TOKEN_URL, headers=scene.owner_in.headers)
    assert_validation_failed(response)


def test_settings_update_without_body_is_rejected_with_validation_error(
    client, scene
) -> None:
    response = client.put(SETTINGS_URL, headers=scene.owner_in.headers)
    assert_validation_failed(response)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty_object"),
        pytest.param({"items": None}, id="null_items"),
        pytest.param({"items": "billing"}, id="string_items"),
        pytest.param({"items": {}}, id="object_items"),
        pytest.param({"items": [None]}, id="null_item"),
        pytest.param({"items": ["billing"]}, id="string_item"),
        pytest.param(
            {"items": [{"pushEnabled": True, "urgencyScope": None}]},
            id="item_without_category",
        ),
        pytest.param(
            {"items": [{"category": "billing", "urgencyScope": None}]},
            id="item_without_push_enabled",
        ),
        pytest.param(
            {"items": [{"category": None, "pushEnabled": True, "urgencyScope": None}]},
            id="null_category",
        ),
        pytest.param(
            {
                "items": [
                    {"category": "email", "pushEnabled": True, "urgencyScope": None}
                ]
            },
            id="unknown_category",
        ),
        pytest.param(
            {
                "items": [
                    {
                        "category": "new_complaint",
                        "pushEnabled": True,
                        "urgencyScope": None,
                    }
                ]
            },
            id="snake_case_category",
        ),
        pytest.param(
            {
                "items": [
                    {"category": "Billing", "pushEnabled": True, "urgencyScope": None}
                ]
            },
            id="wrong_case_category",
        ),
        pytest.param(
            {
                "items": [
                    {"category": "billing", "pushEnabled": None, "urgencyScope": None}
                ]
            },
            id="null_push_enabled",
        ),
        pytest.param(
            {
                "items": [
                    {
                        "category": "billing",
                        "pushEnabled": "maybe",
                        "urgencyScope": None,
                    }
                ]
            },
            id="non_boolean_push_enabled",
        ),
        pytest.param(
            {
                "items": [
                    {
                        "category": "newComplaint",
                        "pushEnabled": True,
                        "urgencyScope": "mediumOnly",
                    }
                ]
            },
            id="unknown_urgency_scope",
        ),
        pytest.param(
            {
                "items": [
                    {
                        "category": "newComplaint",
                        "pushEnabled": True,
                        "urgencyScope": "high_only",
                    }
                ]
            },
            id="snake_case_urgency_scope",
        ),
        pytest.param(
            {
                "items": [
                    {
                        "category": "newComplaint",
                        "pushEnabled": True,
                        "urgencyScope": "",
                    }
                ]
            },
            id="empty_urgency_scope",
        ),
    ],
)
def test_invalid_notification_settings_input_is_rejected_with_validation_error(
    client, scene, body: dict[str, Any]
) -> None:
    response = client.put(SETTINGS_URL, json=body, headers=scene.owner_in.headers)
    assert_validation_failed(response)
