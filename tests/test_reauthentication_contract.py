"""Contract tests for the caller's re-authentication endpoints."""

from typing import Any

import pytest
from conftest import OpenApiDoc

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

PASSWORD_URL = "/me/reauthentication/password"
GOOGLE_URL = "/me/reauthentication/google"

REAUTHENTICATION_PATHS = [PASSWORD_URL, GOOGLE_URL]

# (path, operationId, input schema, input field)
REAUTHENTICATION_OPERATIONS = [
    (
        PASSWORD_URL,
        "reauthenticate_with_password",
        "ReauthenticationPasswordInput",
        "password",
    ),
    (
        GOOGLE_URL,
        "reauthenticate_with_google",
        "ReauthenticationGoogleInput",
        "idToken",
    ),
]

# Component name -> (all properties, required properties).
COMPONENT_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "ReauthenticationPasswordInput": ({"password"}, {"password"}),
    "ReauthenticationGoogleInput": ({"idToken"}, {"idToken"}),
    "Reauthentication": ({"reauthenticatedUntil"}, {"reauthenticatedUntil"}),
}

VALID_BODIES = {
    PASSWORD_URL: {"password": "correct horse battery"},
    GOOGLE_URL: {"idToken": "eyJhbGciOiJSUzI1NiJ9.payload.signature"},
}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


# Paths, operations, tags and status codes


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_path_declares_exactly_post(
    openapi: OpenApiDoc, path: str
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == {"post"}


@pytest.mark.parametrize(
    ("path", "operation_id", "schema", "field"), REAUTHENTICATION_OPERATIONS
)
def test_reauthentication_operation_has_operation_id(
    openapi: OpenApiDoc, path: str, operation_id: str, schema: str, field: str
) -> None:
    assert openapi.operation("post", path)["operationId"] == operation_id


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_operation_has_account_tag(
    openapi: OpenApiDoc, path: str
) -> None:
    assert openapi.operation("post", path)["tags"] == ["account"]


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_operation_declares_only_200_besides_validation_error(
    openapi: OpenApiDoc, path: str
) -> None:
    responses = set(openapi.operation("post", path)["responses"])
    assert responses - {"422"} == {"200"}


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_operation_requires_bearer_auth(
    openapi: OpenApiDoc, path: str
) -> None:
    assert openapi.operation("post", path)["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_operation_declares_no_parameters(
    openapi: OpenApiDoc, path: str
) -> None:
    assert openapi.operation("post", path).get("parameters", []) == []


# Request and response schema references


@pytest.mark.parametrize(
    ("path", "operation_id", "schema", "field"), REAUTHENTICATION_OPERATIONS
)
def test_reauthentication_request_body_schema(
    openapi: OpenApiDoc, path: str, operation_id: str, schema: str, field: str
) -> None:
    assert openapi.request_schema_ref("post", path) == schema


@pytest.mark.parametrize("path", REAUTHENTICATION_PATHS)
def test_reauthentication_response_schema(openapi: OpenApiDoc, path: str) -> None:
    assert openapi.response_schema_ref("post", path, 200) == "Reauthentication"


# Component schemas


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
def test_reauthentication_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_reauthentication_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
def test_reauthentication_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_reauthentication_component_has_exactly_its_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert _property_names(openapi.component(name)) == fields[0]


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_reauthentication_component_requires_exactly_its_required_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert set(openapi.component(name).get("required", [])) == fields[1]


@pytest.mark.parametrize(
    ("path", "operation_id", "schema", "field"), REAUTHENTICATION_OPERATIONS
)
def test_reauthentication_input_field_is_non_empty_string(
    openapi: OpenApiDoc, path: str, operation_id: str, schema: str, field: str
) -> None:
    field_schema = openapi.component(schema)["properties"][field]
    assert field_schema["type"] == "string"
    assert field_schema["minLength"] == 1
    assert "maxLength" not in field_schema


def test_reauthenticated_until_is_date_time_string(openapi: OpenApiDoc) -> None:
    schema = openapi.component("Reauthentication")["properties"]["reauthenticatedUntil"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


# Existing property edit contract is unchanged


def test_property_edit_still_takes_property_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("put", "/properties/{propertyId}") == (
        "PropertyInput"
    )


def test_property_input_has_no_reauthentication_field(openapi: OpenApiDoc) -> None:
    properties = _property_names(openapi.component("PropertyInput"))
    assert not {p for p in properties if "reauth" in p.lower()}


# Runtime: valid requests reach the not-implemented stub


def test_valid_google_reauthentication_request_responds_not_implemented(
    client,
) -> None:
    assert client.post(GOOGLE_URL, json=VALID_BODIES[GOOGLE_URL]).status_code == 501


@pytest.fixture
def auth_headers(make_user, sign_in) -> dict[str, str]:
    """Headers of a signed-in caller, so validation runs behind authentication."""
    return sign_in(make_user()).headers


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize("url", REAUTHENTICATION_PATHS)
def test_reauthentication_without_body_is_rejected_with_validation_error(
    client, auth_headers, url: str
) -> None:
    assert client.post(url, headers=auth_headers).status_code == 422


@pytest.mark.parametrize("url", REAUTHENTICATION_PATHS)
def test_reauthentication_with_empty_object_is_rejected_with_validation_error(
    client, auth_headers, url: str
) -> None:
    assert client.post(url, json={}, headers=auth_headers).status_code == 422


@pytest.mark.parametrize(
    ("url", "value"),
    [
        pytest.param(url, value, id=f"{field}_{label}")
        for url, _, _, field in REAUTHENTICATION_OPERATIONS
        for label, value in [("empty", ""), ("null", None), ("number", 12345)]
    ],
)
def test_reauthentication_with_invalid_credential_value_is_rejected(
    client, auth_headers, url: str, value: Any
) -> None:
    field = next(f for u, _, _, f in REAUTHENTICATION_OPERATIONS if u == url)
    response = client.post(url, json={field: value}, headers=auth_headers)
    assert response.status_code == 422


def test_password_reauthentication_with_snake_case_or_wrong_field_is_rejected(
    client, auth_headers
) -> None:
    wrong = {"Password": "secret"}
    assert (
        client.post(PASSWORD_URL, json=wrong, headers=auth_headers).status_code == 422
    )
    wrong = {"idToken": "secret"}
    assert (
        client.post(PASSWORD_URL, json=wrong, headers=auth_headers).status_code == 422
    )


def test_google_reauthentication_with_snake_case_field_name_is_rejected(
    client,
) -> None:
    assert client.post(GOOGLE_URL, json={"id_token": "token"}).status_code == 422
