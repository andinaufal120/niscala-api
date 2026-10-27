"""Shared fixtures for API contract tests."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("INVITATION_ENCRYPTION_KEY", Fernet.generate_key().decode())

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
def make_room(database) -> Callable[..., Any]:
    """Create and commit a `Room` in a property."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.models import Room

    def factory(
        property_,
        number: str = "A1",
        base_rate: int = 1000000,
        facilities: list[str] | None = None,
        length_m=None,
        width_m=None,
        view_only: bool = False,
        deleted: bool = False,
    ) -> Room:
        with Session(database, expire_on_commit=False) as db:
            row = Room(
                property_id=property_.id,
                number=number,
                base_rate=base_rate,
                facilities=facilities or [],
                length_m=length_m,
                width_m=width_m,
                view_only=view_only,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            db.add(row)
            db.commit()
            return row

    return factory


@dataclass(frozen=True)
class StoredTenant:
    """Rows committed by `make_tenant`."""

    user: Any
    tenant: Any
    lease: Any
    invitation: Any
    token: str | None

    @property
    def id(self) -> UUID:
        return self.user.id


@pytest.fixture
def make_tenant(database) -> Callable[..., StoredTenant]:
    """Commit a tenant account with an active lease, contacts and an invitation."""
    from datetime import UTC, date, datetime, timedelta

    from sqlalchemy.orm import Session

    from app.models import EmergencyContact, Lease, Tenant, UserAccount
    from app.schemas.auth import UserRole
    from app.services.invitations import create_invitation

    def factory(
        room,
        *,
        name: str = "Budi Tenant",
        phone: str = "081234567890",
        occupation: str | None = None,
        email: str | None = None,
        activated: bool = False,
        deleted: bool = False,
        contacts: list[tuple[str, str, str]] | None = None,
        start_date: date | None = date(2099, 1, 10),
        end_date: date | None = None,
        billing_cycle: str = "monthly",
        rent: int = 1000000,
        grace_period_days: int = 0,
        lease_ended: bool = False,
        invitation: bool = True,
        expired: bool = False,
    ) -> StoredTenant:
        with Session(database, expire_on_commit=False) as db:
            user = UserAccount(
                name=name, email=email, password_hash=None, role=UserRole.TENANT
            )
            db.add(user)
            db.flush()
            now = datetime.now(UTC)
            tenant = Tenant(
                user_id=user.id,
                phone=phone,
                occupation=occupation,
                activated_at=now if activated else None,
                deleted_at=now if deleted else None,
            )
            db.add(tenant)
            db.flush()
            for position, (c_name, relationship, c_phone) in enumerate(contacts or []):
                db.add(
                    EmergencyContact(
                        tenant_id=user.id,
                        name=c_name,
                        relationship=relationship,
                        phone=c_phone,
                        position=position,
                    )
                )
            lease = Lease(
                tenant_id=user.id,
                room_id=room.id,
                start_date=start_date,
                end_date=end_date,
                billing_cycle=billing_cycle,
                rent=rent,
                grace_period_days=grace_period_days,
                ended_at=now if lease_ended else None,
            )
            db.add(lease)
            db.flush()
            row, token = None, None
            if invitation:
                row, token = create_invitation(db, user.id)
                if expired:
                    row.expires_at = now - timedelta(days=1)
            db.commit()
            return StoredTenant(user, tenant, lease, row, token)

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


@dataclass(frozen=True)
class StoredManager:
    """Rows committed by `make_manager`."""

    user: Any
    record: Any
    invitation: Any
    token: str | None

    @property
    def id(self) -> UUID:
        """The id of the Owner-Manager record, which is the `managerId` of the API."""
        return self.record.id

    @property
    def user_id(self) -> UUID:
        return self.user.id


_manager_numbers = count(1)


@pytest.fixture
def make_manager(database) -> Callable[..., StoredManager]:
    """Commit a Manager record of an Owner with its assignments and an invitation.

    Without `user` a new manager account is created; pass an existing account to
    give one person records with several Owners. `activated` fills the activation
    time (and an email when none is given). `expired`, `used` and `invalidated`
    shape the invitation; `invitation=False` stores none.
    """
    import hashlib
    import secrets
    from datetime import UTC, datetime, timedelta

    from cryptography.fernet import Fernet
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models import Invitation, Manager, ManagerAssignment, UserAccount
    from app.schemas.auth import UserRole
    from app.services.passwords import hash_password

    def factory(
        owner,
        properties=(),
        *,
        name: str = "Mira Manager",
        nickname: str | None = None,
        phone: str = "081234567890",
        email: str | None = None,
        password: str | None = None,
        activated: bool = False,
        deleted: bool = False,
        user=None,
        invitation: bool = True,
        expired: bool = False,
        used: bool = False,
        invalidated: bool = False,
    ) -> StoredManager:
        now = datetime.now(UTC)
        with Session(database, expire_on_commit=False) as db:
            if user is None:
                if activated and email is None:
                    email = f"manager{next(_manager_numbers)}@example.com"
                user = UserAccount(
                    name=name,
                    email=email,
                    password_hash=hash_password(password) if password else None,
                    role=UserRole.MANAGER,
                    email_verified=True,
                )
                db.add(user)
                db.flush()
            record = Manager(
                owner_id=owner.id,
                user_id=user.id,
                nickname=nickname,
                phone=phone,
                activated_at=now if activated else None,
                deleted_at=now if deleted else None,
            )
            db.add(record)
            db.flush()
            for property_ in properties:
                if db.get(ManagerAssignment, (user.id, property_.id)) is None:
                    db.add(
                        ManagerAssignment(manager_id=user.id, property_id=property_.id)
                    )
            row, token = None, None
            if invitation:
                token = secrets.token_urlsafe(32)
                fernet = Fernet(get_settings().invitation_encryption_key.encode())
                row = Invitation(
                    manager_id=record.id,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    token_encrypted=fernet.encrypt(token.encode()).decode(),
                    created_at=now - timedelta(days=8 if expired else 0),
                    expires_at=now + timedelta(days=-1 if expired else 7),
                    used_at=now if used else None,
                    invalidated_at=now if invalidated else None,
                )
                db.add(row)
            db.commit()
            return StoredManager(user, record, row, token)

    return factory


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


_tenant_numbers = count(1)


@pytest.fixture
def make_verified_tenant(database, make_tenant) -> Callable[..., StoredTenant]:
    """Commit an activated tenant with a verified email who can sign in."""
    from sqlalchemy.orm import Session

    from app.models import UserAccount

    def factory(room, **options: Any) -> StoredTenant:
        options.setdefault("email", f"tenant{next(_tenant_numbers)}@example.com")
        options.setdefault("invitation", False)
        stored = make_tenant(room, activated=True, **options)
        with Session(database) as db:
            db.get(UserAccount, stored.id).email_verified = True
            db.commit()
        return stored

    return factory


@pytest.fixture
def subscribe_owner(database) -> Callable[..., None]:
    """Give an owner a running paid plan."""
    from sqlalchemy.orm import Session

    from app.schemas.subscriptions import PaidPlanCode
    from app.services.subscriptions import grant_subscription

    def subscribe(owner, plan: str = "basic", days: int = 30) -> None:
        with Session(database) as db:
            grant_subscription(db, owner, PaidPlanCode(plan), days)
            db.commit()

    return subscribe


@pytest.fixture
def expire_subscription(database) -> Callable[..., None]:
    """End the paid period of an owner who has a subscription row."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import Session

    from app.models import Subscription

    def expire(owner) -> None:
        with Session(database) as db:
            db.get(Subscription, owner.id).ends_at = datetime.now(UTC) - timedelta(
                days=1
            )
            db.commit()

    return expire


@pytest.fixture
def make_complaint(database) -> Callable[..., Any]:
    """Commit a `Complaint` with its status history.

    `ai` is an optional `(category, urgency, suggested_action)` tuple. `changes`
    is a list of `(status, handling_note, changed_at)`; by default one `new`
    entry at the creation time.
    """
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.models import Complaint, ComplaintStatusChange

    def factory(
        tenant,
        room,
        *,
        description: str = "The tap in the bathroom leaks badly.",
        status: str = "new",
        classification_state: str | None = None,
        ai: tuple[str, str, str] | None = None,
        created_at: datetime | None = None,
        changes: list[tuple[str, str | None, datetime]] | None = None,
    ) -> Complaint:
        created = created_at or datetime.now(UTC)
        category, urgency, action = ai or (None, None, None)
        with Session(database, expire_on_commit=False) as db:
            row = Complaint(
                tenant_id=tenant.id,
                room_id=room.id,
                description=description,
                status=status,
                classification_state=classification_state,
                ai_category=category,
                ai_urgency=urgency,
                ai_suggested_action=action,
                created_at=created,
            )
            db.add(row)
            db.flush()
            for change_status, note, changed_at in changes or [("new", None, created)]:
                db.add(
                    ComplaintStatusChange(
                        complaint_id=row.id,
                        status=change_status,
                        handling_note=note,
                        changed_at=changed_at,
                    )
                )
            db.commit()
            return row

    return factory


BANK_ACCOUNT = {
    "bankName": "Bank Mandiri",
    "accountNumber": "1234567890",
    "accountHolderName": "Rina Owner",
}


@dataclass(frozen=True)
class RentScene:
    """A property with a bank account, one room, its tenant and the staff around it.

    The manager is assigned to the property. Every account is signed in.
    """

    owner: Any
    manager: Any
    prop: Any
    room: Any
    tenant: StoredTenant
    owner_in: SignedIn
    manager_in: SignedIn
    tenant_in: SignedIn


@pytest.fixture
def frozen_today(monkeypatch) -> date:
    """Fix the date the rent bill rules treat as today in Jakarta."""
    from rent_bill_support import TODAY

    monkeypatch.setattr("app.services.rent_bills.today_jakarta", lambda: TODAY)
    return TODAY


@pytest.fixture
def scene(
    frozen_today,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    assign_manager,
    sign_in,
) -> RentScene:
    """An owner, an assigned manager and a tenant with an active lease."""
    from sqlalchemy.orm import Session

    from app.models import Property
    from app.schemas.auth import UserRole

    owner = make_user(name="Rina Owner")
    manager = make_user(name="Mira Manager", role=UserRole.MANAGER)
    prop = make_property(owner, name="Kos Melati")
    with Session(database) as db:
        row = db.get(Property, prop.id)
        row.bank_name = BANK_ACCOUNT["bankName"]
        row.bank_account_number = BANK_ACCOUNT["accountNumber"]
        row.bank_account_holder_name = BANK_ACCOUNT["accountHolderName"]
        db.commit()
    assign_manager(manager, prop)
    room = make_room(prop, number="A1")
    tenant = make_verified_tenant(room, name="Budi Tenant")
    return RentScene(
        owner=owner,
        manager=manager,
        prop=prop,
        room=room,
        tenant=tenant,
        owner_in=sign_in(owner),
        manager_in=sign_in(manager),
        tenant_in=sign_in(tenant.user),
    )


@pytest.fixture
def make_rent_bill(database) -> Callable[..., Any]:
    """Commit a `RentBill` for a lease with its status history and optional receipt.

    The default bill covers today, is unpaid and is not yet due. `changes` is a
    list of `(status, method, reason, manual, actor_id, changed_at)`; by default
    one unpaid entry made by the system at the creation time. `receipt` is an
    optional `(content, content_type, uploaded_at)`.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import Session

    from app.models import RentBill, RentBillReceipt, RentBillStatusChange

    def factory(
        lease,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
        due_date: date | None = None,
        amount: int = 1000000,
        status: str = "unpaid",
        method: str | None = None,
        paid_on: date | None = None,
        rejection_reason: str | None = None,
        receipt: tuple[bytes, str, datetime] | None = None,
        changes: list[tuple] | None = None,
        created_at: datetime | None = None,
    ) -> RentBill:
        from rent_bill_support import TODAY as today

        start = period_start or today - timedelta(days=5)
        created = created_at or datetime.now(UTC)
        with Session(database, expire_on_commit=False) as db:
            row = RentBill(
                lease_id=lease.id,
                period_start=start,
                period_end=period_end or start + timedelta(days=29),
                due_date=due_date or today + timedelta(days=10),
                amount=amount,
                payment_status=status,
                payment_method=method,
                paid_on=paid_on,
                rejection_reason=rejection_reason,
                created_at=created,
            )
            db.add(row)
            db.flush()
            for c_status, c_method, reason, manual, actor_id, changed_at in changes or [
                ("unpaid", None, None, False, None, created)
            ]:
                db.add(
                    RentBillStatusChange(
                        rent_bill_id=row.id,
                        status=c_status,
                        method=c_method,
                        reason=reason,
                        manual=manual,
                        actor_id=actor_id,
                        changed_at=changed_at,
                    )
                )
            if receipt is not None:
                content, content_type, uploaded_at = receipt
                db.add(
                    RentBillReceipt(
                        rent_bill_id=row.id,
                        content=content,
                        content_type=content_type,
                        uploaded_at=uploaded_at,
                    )
                )
            db.commit()
            return row

    return factory


class FakeClassifier:
    """A complaint classifier that records calls and can return, raise or stall."""

    def __init__(self) -> None:
        from app.schemas.complaints import AiComplaintClassification, ComplaintUrgency

        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.result: Any = AiComplaintClassification(
            category="Listrik",
            urgency=ComplaintUrgency.HIGH,
            suggested_action="Send an electrician today.",
        )
        self.error: BaseException | None = None
        self.delay: float = 0.0

    def classify(self, description: str, categories) -> Any:
        import time

        self.calls.append((description, tuple(categories)))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def fake_classifier(app) -> FakeClassifier:
    """Install a `FakeClassifier` as the complaint classifier for one test."""
    from app.ai.classifier import get_complaint_classifier

    fake = FakeClassifier()
    app.dependency_overrides[get_complaint_classifier] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_complaint_classifier, None)


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
