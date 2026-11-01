"""Contract tests for the Admin user-account endpoints."""

from typing import Any

import pytest
from conftest import (
    NOT_A_UUID,
    USER_ACCOUNT_ID,
    OpenApiDoc,
    nullable_inner,
)
from user_account_support import account_url

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

USER_ACCOUNT_PATHS = {
    "/user-accounts": {"get"},
    "/user-accounts/{userAccountId}": {"get", "put", "delete"},
}

# (method, path, operationId, success status)
USER_ACCOUNT_OPERATIONS = [
    ("get", "/user-accounts", "list_user_accounts", 200),
    ("get", "/user-accounts/{userAccountId}", "get_user_account", 200),
    ("put", "/user-accounts/{userAccountId}", "update_user_account", 200),
    ("delete", "/user-accounts/{userAccountId}", "delete_user_account", 204),
]

USER_ACCOUNT_ID_OPERATIONS = [
    pytest.param("get", "/user-accounts/{userAccountId}", id="get_user_account"),
    pytest.param("put", "/user-accounts/{userAccountId}", id="update_user_account"),
    pytest.param("delete", "/user-accounts/{userAccountId}", id="delete_user_account"),
]

NEW_COMPONENTS = [
    "UserAccountStatus",
    "EditableAccountStatus",
    "UserAccountInput",
    "UserAccountSummary",
    "UserAccountList",
    "AccountPropertyRef",
    "AccountTenancy",
    "UserAccount",
]

VALID_USER_ACCOUNT_INPUT = {
    "name": "Budi Santoso",
    "email": "budi@example.com",
    "status": "active",
}

USER_ACCOUNTS_URL = "/user-accounts"


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _query_parameter(
    openapi: OpenApiDoc, name: str, path: str = "/user-accounts"
) -> dict[str, Any]:
    parameters = openapi.operation("get", path)["parameters"]
    (parameter,) = [p for p in parameters if p["name"] == name]
    return parameter


# Paths, operations, tags, security and status codes


@pytest.mark.parametrize(("path", "methods"), USER_ACCOUNT_PATHS.items())
def test_user_account_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), USER_ACCOUNT_OPERATIONS
)
def test_user_account_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), USER_ACCOUNT_OPERATIONS
)
def test_user_account_operation_is_tagged_user_accounts(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["user-accounts"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), USER_ACCOUNT_OPERATIONS
)
def test_user_account_operation_requires_bearer_authentication(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), USER_ACCOUNT_OPERATIONS
)
def test_user_account_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_delete_user_account_success_response_has_no_body(
    openapi: OpenApiDoc,
) -> None:
    response = openapi.operation("delete", "/user-accounts/{userAccountId}")[
        "responses"
    ]["204"]
    assert "content" not in response


@pytest.mark.parametrize(("method", "path"), USER_ACCOUNT_ID_OPERATIONS)
def test_user_account_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == ["userAccountId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


def test_list_user_accounts_declares_exactly_its_query_parameters(
    openapi: OpenApiDoc,
) -> None:
    parameters = openapi.operation("get", "/user-accounts")["parameters"]
    assert {p["name"] for p in parameters} == {"email", "role", "includeDeleted"}
    assert all(p["in"] == "query" for p in parameters)


@pytest.mark.parametrize("name", ["email", "role", "includeDeleted"])
def test_list_user_accounts_query_parameter_is_optional(
    openapi: OpenApiDoc, name: str
) -> None:
    assert _query_parameter(openapi, name).get("required", False) is False


def test_list_user_accounts_email_query_is_non_empty_string(
    openapi: OpenApiDoc,
) -> None:
    schema = nullable_inner(_query_parameter(openapi, "email")["schema"])
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_list_user_accounts_role_query_is_user_role_enum(openapi: OpenApiDoc) -> None:
    schema = nullable_inner(_query_parameter(openapi, "role")["schema"])
    assert openapi.ref_name(schema) == "UserRole"


def test_list_user_accounts_include_deleted_query_is_boolean_defaulting_to_false(
    openapi: OpenApiDoc,
) -> None:
    schema = _query_parameter(openapi, "includeDeleted")["schema"]
    assert schema["type"] == "boolean"
    assert schema["default"] is False


# Request and response schema references


def test_update_user_account_request_body_is_user_account_input(
    openapi: OpenApiDoc,
) -> None:
    assert (
        openapi.request_schema_ref("put", "/user-accounts/{userAccountId}")
        == "UserAccountInput"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/user-accounts"),
        ("get", "/user-accounts/{userAccountId}"),
        ("delete", "/user-accounts/{userAccountId}"),
    ],
    ids=["list_user_accounts", "get_user_account", "delete_user_account"],
)
def test_user_account_read_and_delete_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/user-accounts/{userAccountId}"),
        ("put", "/user-accounts/{userAccountId}"),
    ],
    ids=["get_user_account", "update_user_account"],
)
def test_single_user_account_operations_respond_with_user_account(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.response_schema_ref(method, path, 200) == "UserAccount"


def test_list_user_accounts_responds_with_user_account_list(
    openapi: OpenApiDoc,
) -> None:
    assert (
        openapi.response_schema_ref("get", "/user-accounts", 200) == "UserAccountList"
    )


@pytest.mark.parametrize("name", NEW_COMPONENTS)
def test_user_account_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", NEW_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_user_account_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", NEW_COMPONENTS)
def test_user_account_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


def test_user_role_component_is_shared_enum_of_four_roles(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("UserRole")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["admin", "manager", "owner", "tenant"]


def test_login_method_component_is_shared_enum_of_google_and_password(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("LoginMethod")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["google", "password"]


# Status enums


def test_user_account_status_is_string_enum_of_active_inactive_and_deleted(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("UserAccountStatus")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["active", "deleted", "inactive"]
    assert len(schema["enum"]) == 3


def test_editable_account_status_is_string_enum_of_active_and_inactive(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("EditableAccountStatus")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["active", "inactive"]
    assert len(schema["enum"]) == 2


# UserAccountInput

USER_ACCOUNT_INPUT_FIELDS = {"name", "email", "status"}


@pytest.fixture
def input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("UserAccountInput")


def test_user_account_input_has_exactly_its_fields(
    input_schema: dict[str, Any],
) -> None:
    assert _property_names(input_schema) == USER_ACCOUNT_INPUT_FIELDS


def test_user_account_input_requires_every_field(input_schema: dict[str, Any]) -> None:
    assert set(input_schema["required"]) == USER_ACCOUNT_INPUT_FIELDS


def test_user_account_input_name_is_string_of_one_to_one_hundred_characters(
    input_schema: dict[str, Any],
) -> None:
    schema = input_schema["properties"]["name"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 100


def test_user_account_input_email_is_email_formatted_string(
    input_schema: dict[str, Any],
) -> None:
    schema = input_schema["properties"]["email"]
    assert schema["type"] == "string"
    assert schema["format"] == "email"


def test_user_account_input_status_is_editable_account_status_enum(
    openapi: OpenApiDoc, input_schema: dict[str, Any]
) -> None:
    schema = input_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "EditableAccountStatus"


# UserAccountSummary

SUMMARY_FIELDS = {"id", "name", "email", "role", "status"}


@pytest.fixture
def summary_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("UserAccountSummary")


def test_user_account_summary_has_exactly_its_fields(
    summary_schema: dict[str, Any],
) -> None:
    assert _property_names(summary_schema) == SUMMARY_FIELDS


def test_user_account_summary_requires_every_field(
    summary_schema: dict[str, Any],
) -> None:
    assert set(summary_schema["required"]) == SUMMARY_FIELDS


def test_user_account_summary_id_is_uuid_string(summary_schema: dict[str, Any]) -> None:
    _assert_uuid_string(summary_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "email"])
def test_user_account_summary_text_field_is_string(
    summary_schema: dict[str, Any], field: str
) -> None:
    assert summary_schema["properties"][field]["type"] == "string"


def test_user_account_summary_role_is_user_role_enum(
    openapi: OpenApiDoc, summary_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(summary_schema["properties"]["role"]) == "UserRole"


def test_user_account_summary_status_is_user_account_status_enum(
    openapi: OpenApiDoc, summary_schema: dict[str, Any]
) -> None:
    schema = summary_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "UserAccountStatus"


# UserAccountList


def test_user_account_list_items_is_required_array_of_user_account_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("UserAccountList")
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "UserAccountSummary"


# AccountPropertyRef

PROPERTY_REF_FIELDS = {"id", "name"}


@pytest.fixture
def property_ref_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("AccountPropertyRef")


def test_account_property_ref_has_exactly_its_fields(
    property_ref_schema: dict[str, Any],
) -> None:
    assert _property_names(property_ref_schema) == PROPERTY_REF_FIELDS


def test_account_property_ref_requires_every_field(
    property_ref_schema: dict[str, Any],
) -> None:
    assert set(property_ref_schema["required"]) == PROPERTY_REF_FIELDS


def test_account_property_ref_id_is_uuid_string(
    property_ref_schema: dict[str, Any],
) -> None:
    _assert_uuid_string(property_ref_schema["properties"]["id"])


def test_account_property_ref_name_is_string(
    property_ref_schema: dict[str, Any],
) -> None:
    assert property_ref_schema["properties"]["name"]["type"] == "string"


# AccountTenancy

TENANCY_FIELDS = {"propertyName", "roomNumber", "leaseEndDate"}


@pytest.fixture
def tenancy_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("AccountTenancy")


def test_account_tenancy_has_exactly_its_fields(
    tenancy_schema: dict[str, Any],
) -> None:
    assert _property_names(tenancy_schema) == TENANCY_FIELDS


def test_account_tenancy_requires_every_field(tenancy_schema: dict[str, Any]) -> None:
    assert set(tenancy_schema["required"]) == TENANCY_FIELDS


@pytest.mark.parametrize("field", ["propertyName", "roomNumber"])
def test_account_tenancy_text_field_is_string(
    tenancy_schema: dict[str, Any], field: str
) -> None:
    assert tenancy_schema["properties"][field]["type"] == "string"


def test_account_tenancy_lease_end_date_is_nullable_date_string(
    tenancy_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(tenancy_schema["properties"]["leaseEndDate"])
    assert inner["type"] == "string"
    assert inner["format"] == "date"


# UserAccount

USER_ACCOUNT_FIELDS = {
    "id",
    "name",
    "email",
    "pendingEmail",
    "pendingEmailExpiresAt",
    "role",
    "status",
    "registeredAt",
    "lastLoginAt",
    "loginMethods",
    "properties",
    "activeLeaseCount",
    "tenancy",
}


@pytest.fixture
def account_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(
        openapi.response_schema_ref("get", "/user-accounts/{userAccountId}", 200)
    )


def test_user_account_has_exactly_its_fields(account_schema: dict[str, Any]) -> None:
    assert _property_names(account_schema) == USER_ACCOUNT_FIELDS


def test_user_account_requires_every_field_including_nullable_ones(
    account_schema: dict[str, Any],
) -> None:
    assert set(account_schema["required"]) == USER_ACCOUNT_FIELDS


def test_user_account_id_is_uuid_string(account_schema: dict[str, Any]) -> None:
    _assert_uuid_string(account_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "email"])
def test_user_account_text_field_is_string(
    account_schema: dict[str, Any], field: str
) -> None:
    assert account_schema["properties"][field]["type"] == "string"


def test_user_account_pending_email_is_nullable_string(
    account_schema: dict[str, Any],
) -> None:
    schema = account_schema["properties"]["pendingEmail"]
    assert nullable_inner(schema)["type"] == "string"


def test_user_account_pending_email_expires_at_is_nullable_date_time_string(
    account_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(account_schema["properties"]["pendingEmailExpiresAt"])
    assert inner["type"] == "string"
    assert inner["format"] == "date-time"


def test_user_account_role_is_user_role_enum(
    openapi: OpenApiDoc, account_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(account_schema["properties"]["role"]) == "UserRole"


def test_user_account_status_is_user_account_status_enum(
    openapi: OpenApiDoc, account_schema: dict[str, Any]
) -> None:
    schema = account_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "UserAccountStatus"


def test_user_account_registered_at_is_date_time_string(
    account_schema: dict[str, Any],
) -> None:
    schema = account_schema["properties"]["registeredAt"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_user_account_last_login_at_is_nullable_date_time_string(
    account_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(account_schema["properties"]["lastLoginAt"])
    assert inner["type"] == "string"
    assert inner["format"] == "date-time"


def test_user_account_login_methods_is_array_of_login_method(
    openapi: OpenApiDoc, account_schema: dict[str, Any]
) -> None:
    schema = account_schema["properties"]["loginMethods"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "LoginMethod"


def test_user_account_properties_is_array_of_account_property_ref(
    openapi: OpenApiDoc, account_schema: dict[str, Any]
) -> None:
    schema = account_schema["properties"]["properties"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "AccountPropertyRef"


def test_user_account_active_lease_count_is_non_negative_integer(
    account_schema: dict[str, Any],
) -> None:
    schema = account_schema["properties"]["activeLeaseCount"]
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0


def test_user_account_tenancy_is_nullable_account_tenancy(
    openapi: OpenApiDoc, account_schema: dict[str, Any]
) -> None:
    schema = account_schema["properties"]["tenancy"]
    assert openapi.ref_name(nullable_inner(schema)) == "AccountTenancy"


# Runtime: valid requests reach the implemented operations


@pytest.fixture
def target(make_user):
    """An existing account the Admin reads, edits and deletes."""
    return make_user(name="Budi Santoso", email="budi@example.com")


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("", id="no_filters"),
        pytest.param("email=budi", id="email"),
        pytest.param("role=owner", id="role"),
        pytest.param("includeDeleted=true", id="including_deleted"),
        pytest.param("includeDeleted=false", id="excluding_deleted"),
        pytest.param("email=budi&role=tenant&includeDeleted=true", id="all_filters"),
    ],
)
def test_list_user_accounts_accepts_valid_filters(client, admin_in, query: str) -> None:
    response = client.get(f"{USER_ACCOUNTS_URL}?{query}", headers=admin_in.headers)
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)


@pytest.mark.parametrize("role", ["tenant", "owner", "manager", "admin"])
def test_list_user_accounts_accepts_every_role_filter(
    client, admin_in, role: str
) -> None:
    response = client.get(f"{USER_ACCOUNTS_URL}?role={role}", headers=admin_in.headers)
    assert response.status_code == 200


def test_get_user_account_is_not_a_stub(client, admin_in, target) -> None:
    response = client.get(account_url(target.id), headers=admin_in.headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(target.id)


def test_update_user_account_is_not_a_stub(client, admin_in, target) -> None:
    response = client.put(
        account_url(target.id), headers=admin_in.headers, json=VALID_USER_ACCOUNT_INPUT
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(target.id)


def test_delete_user_account_is_not_a_stub(client, admin_in, target) -> None:
    response = client.delete(account_url(target.id), headers=admin_in.headers)
    assert response.status_code == 204


@pytest.mark.parametrize(
    ("method", "body"),
    [
        pytest.param("get", None, id="get_user_account"),
        pytest.param("put", VALID_USER_ACCOUNT_INPUT, id="update_user_account"),
        pytest.param("delete", None, id="delete_user_account"),
    ],
)
def test_unknown_user_account_answers_not_found(
    client, admin_in, method: str, body: dict[str, Any] | None
) -> None:
    response = client.request(
        method, account_url(USER_ACCOUNT_ID), headers=admin_in.headers, json=body
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"status": "inactive"}, id="inactive_status"),
        pytest.param({"name": "B"}, id="single_character_name"),
        pytest.param({"name": "B" * 100}, id="name_at_maximum_length"),
        pytest.param({"name": "  Budi  "}, id="name_with_surrounding_spaces"),
        pytest.param({"email": "Budi@Example.COM"}, id="mixed_case_email"),
        pytest.param({"email": "budi+kost@sub.example.co.id"}, id="plus_tagged_email"),
    ],
)
def test_user_account_input_edge_body_is_accepted(
    client, admin_in, mailbox, target, extra: dict[str, Any]
) -> None:
    response = client.put(
        account_url(target.id),
        headers=admin_in.headers,
        json={**VALID_USER_ACCOUNT_INPUT, **extra},
    )
    assert response.status_code == 200


# Runtime: invalid requests are rejected with a validation error


def _assert_validation_failed(response) -> None:
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda b: _without(b, "name"), id="missing_name"),
        pytest.param(lambda b: {**b, "name": ""}, id="empty_name"),
        pytest.param(lambda b: {**b, "name": "   "}, id="blank_name"),
        pytest.param(lambda b: {**b, "name": None}, id="null_name"),
        pytest.param(lambda b: {**b, "name": "B" * 101}, id="name_too_long"),
        pytest.param(lambda b: {**b, "name": 123}, id="numeric_name"),
        pytest.param(lambda b: _without(b, "email"), id="missing_email"),
        pytest.param(lambda b: {**b, "email": ""}, id="empty_email"),
        pytest.param(lambda b: {**b, "email": None}, id="null_email"),
        pytest.param(lambda b: {**b, "email": "not-an-email"}, id="email_without_at"),
        pytest.param(lambda b: {**b, "email": "budi@"}, id="email_without_domain"),
        pytest.param(lambda b: {**b, "email": "@example.com"}, id="email_without_user"),
        pytest.param(lambda b: {**b, "email": "bu di@example.com"}, id="email_space"),
        pytest.param(lambda b: _without(b, "status"), id="missing_status"),
        pytest.param(lambda b: {**b, "status": None}, id="null_status"),
        pytest.param(lambda b: {**b, "status": ""}, id="empty_status"),
        pytest.param(lambda b: {**b, "status": "deleted"}, id="deleted_status"),
        pytest.param(lambda b: {**b, "status": "suspended"}, id="unknown_status"),
        pytest.param(lambda b: {**b, "status": "Active"}, id="wrong_case_status"),
        pytest.param(lambda b: {}, id="empty_object"),
    ],
)
def test_invalid_user_account_input_is_rejected_with_validation_error(
    client, admin_in, target, change
) -> None:
    response = client.put(
        account_url(target.id),
        headers=admin_in.headers,
        json=change(VALID_USER_ACCOUNT_INPUT),
    )
    _assert_validation_failed(response)


def test_user_account_write_without_body_is_rejected_with_validation_error(
    client, admin_in, target
) -> None:
    response = client.put(account_url(target.id), headers=admin_in.headers)
    _assert_validation_failed(response)


def test_invalid_body_for_unknown_user_account_answers_not_found(
    client, admin_in
) -> None:
    response = client.put(
        account_url(USER_ACCOUNT_ID), headers=admin_in.headers, json={}
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "body"),
    [
        pytest.param("get", None, id="get_user_account"),
        pytest.param("put", VALID_USER_ACCOUNT_INPUT, id="update_user_account"),
        pytest.param("delete", None, id="delete_user_account"),
    ],
)
def test_non_uuid_user_account_path_id_is_rejected_with_validation_error(
    client, admin_in, method: str, body: dict[str, Any] | None
) -> None:
    response = client.request(
        method, account_url(NOT_A_UUID), headers=admin_in.headers, json=body
    )
    _assert_validation_failed(response)


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("role=superuser", id="unknown_role"),
        pytest.param("role=Owner", id="wrong_case_role"),
        pytest.param("role=", id="empty_role"),
        pytest.param("includeDeleted=maybe", id="non_boolean_include_deleted"),
        pytest.param("includeDeleted=", id="empty_include_deleted"),
        pytest.param("email=", id="empty_email"),
    ],
)
def test_invalid_list_user_accounts_query_is_rejected_with_validation_error(
    client, admin_in, query: str
) -> None:
    response = client.get(f"{USER_ACCOUNTS_URL}?{query}", headers=admin_in.headers)
    _assert_validation_failed(response)
