"""Shared fixtures for API contract tests."""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

REF_PREFIX = "#/components/schemas/"

PROPERTY_ID = "3f1c2a4e-8b7d-4c6a-9e5f-1a2b3c4d5e6f"
ROOM_ID = "7a8b9c0d-1e2f-4a3b-8c5d-6e7f8a9b0c1d"
TENANT_ID = "c2d3e4f5-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
MANAGER_ID = "4a5b6c7d-8e9f-4a0b-9c1d-2e3f4a5b6c7d"
COMPLAINT_ID = "e5f6a7b8-9c0d-4e1f-8a2b-3c4d5e6f7a8b"
RENT_BILL_ID = "1b2c3d4e-5f60-4a71-8b92-a3b4c5d6e7f8"
SESSION_ID = "9d8c7b6a-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
NOTIFICATION_ID = "6c5d4e3f-2a1b-4c0d-9e8f-7a6b5c4d3e2f"
USER_ACCOUNT_ID = "2f3e4d5c-6b7a-4980-8a1b-0c9d8e7f6a5b"
ORDER_ID = "8e7d6c5b-4a39-4281-9f0e-d1c2b3a49586"
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


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRATCH_PREFIX = "scratch_"
_migrated_urls: set[str] = set()


def alembic_config(url: str | None = None) -> Config:
    """Build an Alembic config for the repository, optionally overriding the URL."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def postgres_url():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17", driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def db_engine(postgres_url):
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def database(postgres_url, db_engine, monkeypatch):
    """Point the application at a migrated Postgres container and clean up after."""
    from app.db import get_engine
    from app.models import Base

    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    if postgres_url not in _migrated_urls:
        command.upgrade(alembic_config(postgres_url), "head")
        _migrated_urls.add(postgres_url)
    engine = get_engine()
    yield engine
    engine.dispose()
    with db_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(
                text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE')
            )
        for name in inspect(connection).get_table_names():
            if name.startswith(SCRATCH_PREFIX):
                connection.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    get_settings.cache_clear()
    get_engine.cache_clear()


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
