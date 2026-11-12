"""Builders for the tests of record versions and the `If-Match` header."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

KINDS = ["property", "room", "tenant", "manager", "user_account"]

# (HTTP method upper case, path template) of the five edit operations.
PUT_OPERATIONS = [
    ("PUT", "/properties/{propertyId}"),
    ("PUT", "/rooms/{roomId}"),
    ("PUT", "/tenants/{tenantId}"),
    ("PUT", "/managers/{managerId}"),
    ("PUT", "/user-accounts/{userAccountId}"),
]

# Schemas that describe one of the five resources, as a list item or in detail.
VERSIONED_SCHEMAS = [
    "Property",
    "PropertySummary",
    "Room",
    "RoomSummary",
    "Tenant",
    "TenantSummary",
    "Manager",
    "ManagerSummary",
    "UserAccount",
    "UserAccountSummary",
]

CONFLICT = "RESOURCE_VERSION_CONFLICT"
NOT_SENT = object()

PASSWORD = "T7#vq9-lorem-ipsum"


def etag(version: int) -> str:
    """The `If-Match` value for a version: the whole number in double quotes."""
    return f'"{version}"'


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def database_state(database, skip: tuple[str, ...] = ("sessions",)) -> dict:
    """Every row of every table but the skipped ones, to compare before and after."""
    from app.models import Base

    with database.connect() as connection:
        return {
            table.name: sorted(
                repr(tuple(row)) for row in connection.execute(select(table)).all()
            )
            for table in Base.metadata.sorted_tables
            if table.name not in skip
        }


@dataclass
class Target:
    """One editable record with the requests that read and edit it.

    `body` repeats the record's current values; `changed_body` changes some of
    them. `values` reads the stored values the edit may change.
    """

    kind: str
    id: Any
    url: str
    list_url: str
    headers: dict[str, str]
    forbidden_headers: dict[str, str]
    body: dict[str, Any]
    changed_body: dict[str, Any]
    model: type
    database: Any
    not_found_code: str
    values: Callable[[Any], tuple]

    @property
    def missing_url(self) -> str:
        return self.url.rsplit("/", 1)[0] + f"/{uuid4()}"

    def row(self):
        with Session(self.database, expire_on_commit=False) as db:
            return db.get(self.model, self.id)

    def version(self) -> int:
        return self.row().version

    def stored_values(self) -> tuple:
        return self.values(self.row())

    def put(self, client, body=None, if_match: Any = NOT_SENT, headers=None):
        sent = dict(self.headers if headers is None else headers)
        if if_match is not NOT_SENT:
            sent["If-Match"] = if_match
        return client.put(
            self.url, json=self.body if body is None else body, headers=sent
        )

    def read(self, client):
        response = client.get(self.url, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def listed(self, client) -> dict:
        response = client.get(self.list_url, headers=self.headers)
        assert response.status_code == 200, response.text
        (item,) = [i for i in response.json()["items"] if i["id"] == str(self.id)]
        return item


def build_target(
    kind: str,
    *,
    database,
    make_user,
    sign_in,
    make_property,
    make_room,
    make_tenant,
    make_manager,
) -> Target:
    """Create a record of the kind, its owner or admin, and a Target for it."""
    from app.models import Manager, Property, Room, Tenant, UserAccount
    from app.schemas.auth import UserRole

    outsider = sign_in(make_user(role=UserRole.TENANT)).headers
    common = {
        "kind": kind,
        "database": database,
        "forbidden_headers": outsider,
    }
    if kind == "user_account":
        admin = make_user(
            name="Ade Admin", role=UserRole.ADMIN, email="ade@example.com"
        )
        subject = make_user(name="Budi Santoso", email="budi@example.com")
        body = {"name": "Budi Santoso", "email": "budi@example.com", "status": "active"}
        return Target(
            id=subject.id,
            url=f"/user-accounts/{subject.id}",
            list_url="/user-accounts",
            headers=sign_in(admin).headers,
            body=body,
            changed_body={**body, "name": "Budi Baru"},
            model=UserAccount,
            not_found_code="USER_ACCOUNT_NOT_FOUND",
            values=lambda row: (row.name, row.email, str(row.status)),
            **common,
        )

    owner = make_user(name="Rina Owner")
    headers = sign_in(owner).headers
    prop = make_property(owner, name="Kos Melati", address="Jl. Melati 5")
    if kind == "property":
        body = {"name": "Kos Melati", "address": "Jl. Melati 5"}
        return Target(
            id=prop.id,
            url=f"/properties/{prop.id}",
            list_url="/properties",
            headers=headers,
            body=body,
            changed_body={"name": "Kos Mawar", "address": "Jl. Mawar 7"},
            model=Property,
            not_found_code="PROPERTY_NOT_FOUND",
            values=lambda row: (
                row.name,
                row.address,
                row.bank_name,
                row.bank_account_number,
                row.bank_account_holder_name,
            ),
            **common,
        )
    room = make_room(prop, number="A1", base_rate=1000000)
    if kind == "room":
        body = {"number": "A1", "baseRate": 1000000}
        return Target(
            id=room.id,
            url=f"/rooms/{room.id}",
            list_url=f"/properties/{prop.id}/rooms",
            headers=headers,
            body=body,
            changed_body={"number": "A2", "baseRate": 1200000, "facilities": ["wifi"]},
            model=Room,
            not_found_code="ROOM_NOT_FOUND",
            values=lambda row: (row.number, row.base_rate, list(row.facilities)),
            **common,
        )
    if kind == "tenant":
        stored = make_tenant(room, name="Budi Tenant", phone="081234567890")
        body = {"name": "Budi Tenant", "phone": "081234567890"}
        return Target(
            id=stored.id,
            url=f"/tenants/{stored.id}",
            list_url=f"/properties/{prop.id}/tenants",
            headers=headers,
            body=body,
            changed_body={**body, "phone": "081234567891", "occupation": "Mahasiswa"},
            model=Tenant,
            not_found_code="TENANT_NOT_FOUND",
            values=lambda row: (row.phone, row.occupation),
            **common,
        )
    assert kind == "manager"
    stored = make_manager(owner, [prop], name="Mira Manager", phone="081234567890")
    body = {
        "name": "Mira Manager",
        "phone": "081234567890",
        "propertyIds": [str(prop.id)],
    }
    return Target(
        id=stored.id,
        url=f"/managers/{stored.id}",
        list_url="/managers",
        headers=headers,
        body=body,
        changed_body={**body, "phone": "081234567891", "nickname": "Bu Mira"},
        model=Manager,
        not_found_code="MANAGER_NOT_FOUND",
        values=lambda row: (row.phone, row.nickname),
        **common,
    )
