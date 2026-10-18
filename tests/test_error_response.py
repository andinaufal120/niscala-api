"""Every error response uses the `{code, field, message}` shape."""

import pytest
from conftest import PROPERTY_ID
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

KEYS = {"code", "field", "message"}


def build_client(*, raise_server_exceptions: bool = True) -> TestClient:
    from app.errors import ApiError, register_error_handlers

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/taken")
    def taken():
        raise ApiError(409, "PROPERTY_NAME_TAKEN", field="name")

    @private.get("/no-field")
    def no_field():
        raise ApiError(403, "FORBIDDEN_ACTION")

    @private.get("/custom")
    def custom():
        raise ApiError(400, "CUSTOM_CODE", message="Custom text.", field="x")

    @private.get("/teapot")
    def teapot():
        raise HTTPException(418)

    @private.get("/retry")
    def retry():
        raise HTTPException(429, headers={"Retry-After": "30"})

    @private.get("/boom")
    def boom():
        raise RuntimeError("boom")

    return TestClient(private, raise_server_exceptions=raise_server_exceptions)


def assert_shape(body: dict) -> None:
    assert set(body) == KEYS
    assert isinstance(body["code"], str)
    assert body["field"] is None or isinstance(body["field"], str)
    assert isinstance(body["message"], str)
    assert body["message"]


def test_api_error_with_field_returns_code_field_and_message():
    response = build_client().get("/taken")
    assert response.status_code == 409
    body = response.json()
    assert_shape(body)
    assert body["code"] == "PROPERTY_NAME_TAKEN"
    assert body["field"] == "name"


def test_api_error_without_field_returns_null_field():
    response = build_client().get("/no-field")
    assert response.status_code == 403
    body = response.json()
    assert_shape(body)
    assert body["code"] == "FORBIDDEN_ACTION"
    assert body["field"] is None


def test_api_error_custom_message_is_returned_verbatim():
    response = build_client().get("/custom")
    assert response.status_code == 400
    assert response.json() == {
        "code": "CUSTOM_CODE",
        "field": "x",
        "message": "Custom text.",
    }


def test_http_exception_code_is_upper_snake_cased_status_phrase():
    response = build_client().get("/teapot")
    assert response.status_code == 418
    body = response.json()
    assert_shape(body)
    assert body["code"] == "IM_A_TEAPOT"
    assert body["field"] is None


def test_http_exception_headers_are_preserved():
    response = build_client().get("/retry")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert_shape(response.json())
    assert response.json()["code"] == "TOO_MANY_REQUESTS"


def test_unexpected_exception_returns_internal_error_without_leaking_details():
    response = build_client(raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert_shape(body)
    assert body["code"] == "INTERNAL_ERROR"
    assert body["field"] is None
    assert "boom" not in body["message"]


@pytest.fixture
def owner_headers(database, make_user, sign_in) -> dict[str, str]:
    return sign_in(make_user()).headers


def test_missing_body_field_reports_first_missing_field_only(client, owner_headers):
    response = client.post("/properties", json={}, headers=owner_headers)
    assert response.status_code == 422
    body = response.json()
    assert_shape(body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "name"
    assert "detail" not in body


def test_nested_field_path_is_camel_case_and_dotted(client, owner_headers):
    response = client.post(
        "/properties",
        json={
            "name": "Kos",
            "address": "Jl. A",
            "bankAccount": {"bankName": "BCA"},
        },
        headers=owner_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert_shape(body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "bankAccount.accountNumber"


def test_list_index_appears_as_number_segment_in_field_path(client):
    response = client.post(
        f"/properties/{PROPERTY_ID}/rooms",
        json={"number": "1", "baseRate": 100000, "facilities": [1]},
    )
    assert response.status_code == 422
    body = response.json()
    assert_shape(body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "facilities.0"


def test_invalid_path_parameter_reports_parameter_name(client, owner_headers):
    response = client.get("/properties/not-a-uuid", headers=owner_headers)
    assert response.status_code == 422
    body = response.json()
    assert_shape(body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "propertyId"


def test_malformed_json_body_returns_validation_failed_with_null_field(client):
    response = client.post(
        "/properties",
        content="{bad",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()
    assert_shape(body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] is None


def test_unimplemented_endpoint_returns_not_implemented(client, owner_headers):
    response = client.get(f"/properties/{PROPERTY_ID}/rooms", headers=owner_headers)
    assert response.status_code == 501
    body = response.json()
    assert_shape(body)
    assert body["code"] == "NOT_IMPLEMENTED"
    assert body["field"] is None


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/no-such-path", 404, "NOT_FOUND"),
        ("DELETE", "/properties", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_routing_errors_use_status_phrase_code(client, method, path, status, code):
    response = client.request(method, path)
    assert response.status_code == status
    body = response.json()
    assert_shape(body)
    assert body["code"] == code
    assert body["field"] is None
