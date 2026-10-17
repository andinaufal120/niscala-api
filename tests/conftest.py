"""Shared fixtures for API contract tests."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

REF_PREFIX = "#/components/schemas/"

PROPERTY_ID = "3f1c2a4e-8b7d-4c6a-9e5f-1a2b3c4d5e6f"
ROOM_ID = "7a8b9c0d-1e2f-4a3b-8c5d-6e7f8a9b0c1d"
TENANT_ID = "c2d3e4f5-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
NOT_A_UUID = "not-a-uuid"


class OpenApiDoc:
    """Read-only helpers for navigating a generated OpenAPI document."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    @property
    def components(self) -> dict[str, Any]:
        return self.document.get("components", {}).get("schemas", {})

    def operation(self, method: str, path: str) -> dict[str, Any]:
        paths = self.document.get("paths", {})
        assert path in paths, f"path {path} is not declared"
        assert method.lower() in paths[path], f"{method} {path} is not declared"
        return paths[path][method.lower()]

    def component(self, name: str) -> dict[str, Any]:
        assert name in self.components, f"component schema {name} is not declared"
        return self.components[name]

    def ref_name(self, schema: dict[str, Any]) -> str:
        """Return the component name a `$ref` schema points at."""
        assert "$ref" in schema, f"expected a $ref, got {schema}"
        ref = schema["$ref"]
        assert ref.startswith(REF_PREFIX), f"unexpected $ref {ref}"
        return ref.removeprefix(REF_PREFIX)

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in schema:
            return self.component(self.ref_name(schema))
        return schema

    def request_schema_ref(self, method: str, path: str) -> str:
        operation = self.operation(method, path)
        assert "requestBody" in operation, f"{method} {path} has no request body"
        body = operation["requestBody"]
        assert body.get("required") is True
        return self.ref_name(body["content"]["application/json"]["schema"])

    def response_schema_ref(self, method: str, path: str, status: int) -> str:
        responses = self.operation(method, path)["responses"]
        assert str(status) in responses, f"{method} {path} lacks a {status} response"
        content = responses[str(status)]["content"]
        return self.ref_name(content["application/json"]["schema"])


def nullable_inner(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the non-null part of a nullable schema, failing if it is not nullable.

    Accepts `anyOf: [X, {"type": "null"}]` and `type: [T, "null"]`. Keywords set
    beside `anyOf` (such as constraints) are merged into the returned schema.
    """
    if "anyOf" in schema:
        branches = schema["anyOf"]
        assert len(branches) == 2, f"expected exactly two branches, got {branches}"
        assert {"type": "null"} in branches, f"no null branch in {branches}"
        (inner,) = [b for b in branches if b != {"type": "null"}]
        outer = {
            k: v
            for k, v in schema.items()
            if k not in ("anyOf", "default", "title", "description")
        }
        return {**outer, **inner}
    types = schema.get("type")
    assert isinstance(types, list), f"schema is not nullable: {schema}"
    assert sorted(types) == sorted([*(t for t in types if t != "null"), "null"])
    (non_null,) = [t for t in types if t != "null"]
    return {**schema, "type": non_null}


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="session")
def openapi(app) -> OpenApiDoc:
    return OpenApiDoc(app.openapi())


@pytest.fixture(scope="session")
def client(app) -> TestClient:
    return TestClient(app)
