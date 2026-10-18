"""Contract tests for the caller's session-management and change-password endpoints."""

from typing import Any

import pytest
from conftest import NOT_A_UUID, SESSION_ID, OpenApiDoc

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

SESSION_PATHS = {
    "/me/sessions": {"get", "delete"},
    "/me/sessions/{sessionId}": {"delete"},
    "/me/password-changes": {"post"},
}

# (method, path, operationId, tag, success status)
SESSION_OPERATIONS = [
    ("get", "/me/sessions", "list_my_sessions", "sessions", 200),
    ("delete", "/me/sessions/{sessionId}", "end_my_session", "sessions", 204),
    ("delete", "/me/sessions", "end_my_other_sessions", "sessions", 204),
    ("post", "/me/password-changes", "change_my_password", "account", 200),
]

# Operations that succeed without a response body.
NO_RESPONSE_BODY_OPERATIONS = [
    ("delete", "/me/sessions/{sessionId}", 204),
    ("delete", "/me/sessions", 204),
]

NO_REQUEST_BODY_OPERATIONS = [
    ("get", "/me/sessions"),
    ("delete", "/me/sessions/{sessionId}"),
    ("delete", "/me/sessions"),
]

# Component name -> (all properties, required properties).
SESSION_FIELDS = {
    "id",
    "deviceName",
    "platform",
    "loginMethod",
    "lastActiveAt",
    "isCurrent",
}
COMPONENT_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "Session": (SESSION_FIELDS, SESSION_FIELDS),
    "SessionList": ({"items"}, {"items"}),
    "PasswordChangeInput": (
        {"currentPassword", "newPassword"},
        {"currentPassword", "newPassword"},
    ),
    "PasswordChangeResult": ({"hasOtherSessions"}, {"hasOtherSessions"}),
}

LOGIN_METHODS = ["google", "password"]

VALID_PASSWORD_CHANGE_INPUT = {
    "currentPassword": "correct horse battery",
    "newPassword": "a brand new passphrase",
}

SESSIONS_URL = "/me/sessions"
SESSION_URL = f"/me/sessions/{SESSION_ID}"
PASSWORD_CHANGES_URL = "/me/password-changes"


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


def _field(openapi: OpenApiDoc, component: str, field: str) -> dict[str, Any]:
    return openapi.component(component)["properties"][field]


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), SESSION_PATHS.items())
def test_session_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), SESSION_OPERATIONS
)
def test_session_operation_has_operation_id(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), SESSION_OPERATIONS
)
def test_session_operation_has_its_tag(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path)["tags"] == [tag]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), SESSION_OPERATIONS
)
def test_session_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), SESSION_OPERATIONS
)
def test_session_operation_requires_bearer_auth(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


def test_end_my_session_path_parameter_is_required_uuid(openapi: OpenApiDoc) -> None:
    parameters = openapi.operation("delete", "/me/sessions/{sessionId}")["parameters"]
    assert [p["name"] for p in parameters] == ["sessionId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("get", "/me/sessions", id="list_my_sessions"),
        pytest.param("delete", "/me/sessions", id="end_my_other_sessions"),
        pytest.param("post", "/me/password-changes", id="change_my_password"),
    ],
)
def test_session_operation_without_path_parameter_declares_no_parameters(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path).get("parameters", []) == []


# Request and response schema references


def test_change_my_password_request_body_schema(openapi: OpenApiDoc) -> None:
    assert (
        openapi.request_schema_ref("post", "/me/password-changes")
        == "PasswordChangeInput"
    )


@pytest.mark.parametrize(("method", "path"), NO_REQUEST_BODY_OPERATIONS)
def test_session_read_and_end_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    [
        ("get", "/me/sessions", 200, "SessionList"),
        ("post", "/me/password-changes", 200, "PasswordChangeResult"),
    ],
    ids=["list_my_sessions", "change_my_password"],
)
def test_session_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


@pytest.mark.parametrize(("method", "path", "status"), NO_RESPONSE_BODY_OPERATIONS)
def test_end_session_operation_succeeds_without_a_response_body(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    response = openapi.operation(method, path)["responses"][str(status)]
    assert "content" not in response


# Component schemas


@pytest.mark.parametrize("name", [*COMPONENT_FIELDS, "LoginMethod"])
def test_session_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", [*COMPONENT_FIELDS, "LoginMethod"])
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_session_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
def test_session_component_property_names_contain_no_underscore(
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


# LoginMethod


def test_login_method_is_string_enum_of_google_and_password(
    openapi: OpenApiDoc,
) -> None:
    _assert_string_enum(openapi.component("LoginMethod"), LOGIN_METHODS)


# Session and SessionList


def test_session_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(_field(openapi, "Session", "id"))


def test_session_device_name_is_string(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "Session", "deviceName")["type"] == "string"


def test_session_platform_is_free_text(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Session", "platform")
    assert schema["type"] == "string"
    assert "enum" not in schema
    assert "$ref" not in schema


def test_session_login_method_is_login_method(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Session", "loginMethod")
    assert openapi.ref_name(schema) == "LoginMethod"


def test_session_last_active_at_is_date_time_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Session", "lastActiveAt")
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_session_is_current_is_boolean(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "Session", "isCurrent")["type"] == "boolean"


def test_session_list_items_is_array_of_session(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "SessionList", "items")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "Session"


# PasswordChangeInput and PasswordChangeResult


def test_password_change_current_password_is_non_empty_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "PasswordChangeInput", "currentPassword")
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_password_change_new_password_is_string_of_8_to_128_characters(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "PasswordChangeInput", "newPassword")
    assert schema["type"] == "string"
    assert schema["minLength"] == 8
    assert schema["maxLength"] == 128


def test_password_change_input_has_no_confirmation_field(openapi: OpenApiDoc) -> None:
    assert "confirmPassword" not in _property_names(
        openapi.component("PasswordChangeInput")
    )


def test_password_change_result_has_other_sessions_is_boolean(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "PasswordChangeResult", "hasOtherSessions")
    assert schema["type"] == "boolean"


# Runtime: valid requests reach the not-implemented stub


@pytest.mark.parametrize(
    ("method", "url"),
    [
        pytest.param("get", SESSIONS_URL, id="list_my_sessions"),
        pytest.param("delete", SESSION_URL, id="end_my_session"),
        pytest.param("delete", SESSIONS_URL, id="end_my_other_sessions"),
    ],
)
def test_valid_session_request_responds_not_implemented(
    client, method: str, url: str
) -> None:
    response = client.request(method, url)
    assert response.status_code == 501


def test_valid_password_change_request_responds_not_implemented(client) -> None:
    response = client.post(PASSWORD_CHANGES_URL, json=VALID_PASSWORD_CHANGE_INPUT)
    assert response.status_code == 501


@pytest.mark.parametrize(
    "new_password", ["12345678", "a" * 128, "pässwörd with spaces", " " * 8]
)
def test_new_password_of_8_to_128_characters_is_accepted(
    client, new_password: str
) -> None:
    body = {**VALID_PASSWORD_CHANGE_INPUT, "newPassword": new_password}
    assert client.post(PASSWORD_CHANGES_URL, json=body).status_code == 501


@pytest.mark.parametrize("current_password", ["x", " ", "a" * 200])
def test_any_non_empty_current_password_is_accepted(
    client, current_password: str
) -> None:
    body = {**VALID_PASSWORD_CHANGE_INPUT, "currentPassword": current_password}
    assert client.post(PASSWORD_CHANGES_URL, json=body).status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize("session_id", [NOT_A_UUID, "123", "9d8c7b6a-5e4f"])
def test_end_my_session_with_malformed_session_id_is_rejected(
    client, session_id: str
) -> None:
    assert client.delete(f"/me/sessions/{session_id}").status_code == 422


def test_password_change_without_body_is_rejected_with_validation_error(
    client,
) -> None:
    assert client.post(PASSWORD_CHANGES_URL).status_code == 422


def test_password_change_with_empty_object_is_rejected_with_validation_error(
    client,
) -> None:
    assert client.post(PASSWORD_CHANGES_URL, json={}).status_code == 422


@pytest.mark.parametrize("field", ["currentPassword", "newPassword"])
def test_password_change_with_a_required_field_missing_is_rejected(
    client, field: str
) -> None:
    body = _without(VALID_PASSWORD_CHANGE_INPUT, field)
    assert client.post(PASSWORD_CHANGES_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "newPassword": "1234567"}, id="7_chars"
        ),
        pytest.param({**VALID_PASSWORD_CHANGE_INPUT, "newPassword": ""}, id="empty"),
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "newPassword": "a" * 129}, id="129_chars"
        ),
        pytest.param({**VALID_PASSWORD_CHANGE_INPUT, "newPassword": None}, id="null"),
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "newPassword": 12345678}, id="number"
        ),
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "currentPassword": ""}, id="empty_current"
        ),
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "currentPassword": None}, id="null_current"
        ),
        pytest.param(
            {**VALID_PASSWORD_CHANGE_INPUT, "currentPassword": 12345},
            id="number_current",
        ),
        pytest.param(
            {
                "current_password": "correct horse battery",
                "new_password": "a brand new passphrase",
            },
            id="snake_case_field_names",
        ),
    ],
)
def test_invalid_password_change_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(PASSWORD_CHANGES_URL, json=body).status_code == 422
