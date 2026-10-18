"""Shared fixtures for API contract tests."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")

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
    from app.config import get_settings
    from app.db import get_engine
    from app.models import Base

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


@pytest.fixture
def db_session(database):
    """A SQLAlchemy session on the test database, closed after the test."""
    from sqlalchemy.orm import Session

    with Session(database) as session:
        yield session


@dataclass(frozen=True)
class SignedIn:
    """The result of signing a user in through `sign_in`."""

    tokens: Any
    headers: dict[str, str]
    session_id: UUID


_user_numbers = count(1)


@pytest.fixture
def make_user(database) -> Callable[..., Any]:
    """Create and commit a `UserAccount`."""
    from sqlalchemy.orm import Session

    from app.models import UserAccount
    from app.schemas.auth import UserRole

    def factory(
        *,
        name: str = "Rina Owner",
        email: str | None = None,
        password_hash: str | None = None,
        role: UserRole = UserRole.OWNER,
        email_verified: bool = True,
    ) -> UserAccount:
        if email is None:
            email = f"user{next(_user_numbers)}@example.com"
        with Session(database, expire_on_commit=False) as session:
            user = UserAccount(
                name=name,
                email=email,
                password_hash=password_hash,
                role=role,
                email_verified=email_verified,
            )
            session.add(user)
            session.commit()
            return user

    return factory


@pytest.fixture
def make_property(database) -> Callable[..., Any]:
    """Create and commit a `Property` owned by the given user."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.models import Property

    def factory(
        owner,
        name: str = "Kos Melati",
        address: str = "Jl. Melati 5",
        view_only: bool = False,
        deleted: bool = False,
    ) -> Property:
        with Session(database, expire_on_commit=False) as session:
            row = Property(
                owner_id=owner.id,
                name=name,
                address=address,
                view_only=view_only,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            session.add(row)
            session.commit()
            return row

    return factory


@pytest.fixture
def assign_manager(database) -> Callable[..., None]:
    """Commit a `ManagerAssignment` of a manager to a property."""
    from sqlalchemy.orm import Session

    from app.models import ManagerAssignment

    def assign(manager, property) -> None:
        with Session(database) as session:
            session.add(
                ManagerAssignment(manager_id=manager.id, property_id=property.id)
            )
            session.commit()

    return assign


@pytest.fixture
def sign_in(database) -> Callable[..., SignedIn]:
    """Start and commit a session for a user and return its tokens."""
    from sqlalchemy.orm import Session

    from app.schemas.auth import DeviceInfo
    from app.schemas.sessions import LoginMethod

    def factory(
        user,
        device_name: str = "Pixel 8",
        platform: str = "Android 14",
        login_method=LoginMethod.PASSWORD,
    ) -> SignedIn:
        device = DeviceInfo(name=device_name, platform=platform)
        from app.services.sessions import start_session

        with Session(database) as session:
            tokens = start_session(session, user, device, login_method)
            session.commit()
        claims = jwt.decode(tokens.access_token, options={"verify_signature": False})
        session_id = UUID(claims["sid"])
        return SignedIn(
            tokens=tokens,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
            session_id=session_id,
        )

    return factory


@pytest.fixture
def read_session(database) -> Callable[[UUID], Any]:
    """Read a `UserSession` row fresh from the database."""
    from sqlalchemy.orm import Session

    from app.models import UserSession

    def read(session_id: UUID):
        with Session(database, expire_on_commit=False) as session:
            return session.get(UserSession, session_id)

    return read


@pytest.fixture
def sent_emails(app) -> list[tuple[str, str]]:
    """Replace the email sender with one that records `(to, code)` tuples."""
    from app.email import get_email_sender

    sent: list[tuple[str, str]] = []

    class RecordingSender:
        def send_verification_code(self, to: str, code: str) -> None:
            sent.append((to, code))

    sender = RecordingSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sent
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture
def read_verification_code(database) -> Callable[[UUID | str], Any]:
    """Read the `EmailVerificationCode` row of a user fresh from the database."""
    from sqlalchemy.orm import Session

    from app.models import EmailVerificationCode

    def read(user_id: UUID | str):
        with Session(database, expire_on_commit=False) as session:
            return session.get(EmailVerificationCode, UUID(str(user_id)))

    return read


@pytest.fixture
def edit_verification_code(database) -> Callable[..., None]:
    """Overwrite columns of the `EmailVerificationCode` row of a user."""
    from sqlalchemy.orm import Session

    from app.models import EmailVerificationCode

    def edit(user_id: UUID | str, **columns: Any) -> None:
        with Session(database) as session:
            row = session.get(EmailVerificationCode, UUID(str(user_id)))
            for name, value in columns.items():
                setattr(row, name, value)
            session.commit()

    return edit


@pytest.fixture
def register_owner(client, database, sent_emails) -> Callable[..., Any]:
    """Register an owner through the API; keyword arguments override the body."""

    def register(**overrides: Any):
        body = {
            "name": "Rina Owner",
            "email": "rina@example.com",
            "password": "correct horse battery",
            "device": {"name": "Pixel 8", "platform": "Android 14"},
        }
        return client.post("/auth/register", json={**body, **overrides})

    return register


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
