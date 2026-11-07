"""Tests for the public health check endpoint."""

import pytest
from sqlalchemy.exc import OperationalError

from app.db import get_session


class UnreachableSession:
    """A session whose database cannot be reached."""

    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def unreachable_database(app):
    app.dependency_overrides[get_session] = lambda: UnreachableSession()
    yield
    app.dependency_overrides.pop(get_session, None)


def test_health_reports_ok_when_database_is_reachable(client, database):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_authorization_header(client, database):
    response = client.get("/health")

    assert "Authorization" not in response.request.headers
    assert response.status_code == 200


def test_health_ignores_an_invalid_bearer_token(client, database):
    response = client.get("/health", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_when_database_is_unreachable(
    client, unreachable_database
):
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_health_unavailable_body_has_no_error_fields(client, unreachable_database):
    body = client.get("/health").json()

    assert set(body) == {"status"}


def test_health_unavailable_needs_no_authorization_header(client, unreachable_database):
    response = client.get("/health")

    assert response.status_code == 503


def test_health_recovers_after_database_becomes_reachable_again(app, client, database):
    app.dependency_overrides[get_session] = lambda: UnreachableSession()
    try:
        assert client.get("/health").status_code == 503
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert client.get("/health").status_code == 200


def test_health_is_declared_in_openapi_as_a_get_operation(openapi):
    openapi.operation("get", "/health")


def test_health_declares_no_security_requirement(openapi):
    operation = openapi.operation("get", "/health")

    assert not operation.get("security")


def test_health_ok_response_references_the_health_schema(openapi):
    assert openapi.response_schema_ref("get", "/health", 200) == "Health"


def test_health_unavailable_response_references_the_health_schema(openapi):
    assert openapi.response_schema_ref("get", "/health", 503) == "Health"


def test_health_schema_requires_a_string_status(openapi):
    schema = openapi.component("Health")

    assert schema["properties"]["status"]["type"] == "string"
    assert "status" in schema["required"]
