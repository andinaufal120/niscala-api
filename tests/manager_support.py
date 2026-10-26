"""Helpers shared by the manager endpoint tests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

MANAGERS = "/managers"
PROPERTIES = "/properties"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
ME_URL = "/me"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"

MANAGER_FIELDS = {
    "id",
    "name",
    "nickname",
    "phone",
    "email",
    "accountStatus",
    "properties",
    "invitation",
}
SUMMARY_FIELDS = MANAGER_FIELDS - {"invitation"}
INVITATION_FIELDS = {"url", "createdAt", "expiresAt", "expired"}
PROPERTY_FIELDS = {"id", "name", "address"}


def manager_url(manager_id) -> str:
    return f"{MANAGERS}/{manager_id}"


def invitation_url(manager_id) -> str:
    return f"{MANAGERS}/{manager_id}/invitation"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def without(body: dict, *keys: str) -> dict:
    return {k: v for k, v in body.items() if k not in keys}


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def assert_error_code(response, status: int, code: str) -> None:
    """Check the status and code of an error without looking at its field."""
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["message"]


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def assert_just_now(value) -> None:
    assert value is not None
    now = datetime.now(UTC)
    assert now - timedelta(minutes=1) <= value <= now + timedelta(minutes=1)


def invitation_base() -> str:
    from app.config import get_settings

    return get_settings().invitation_base_url.rstrip("/")


def link_for(token: str) -> str:
    return f"{invitation_base()}/invitations/{token}"


def token_of(url: str) -> str:
    prefix = f"{invitation_base()}/invitations/"
    assert url.startswith(prefix)
    return url.removeprefix(prefix)


def new_body(*properties, **overrides) -> dict:
    """A valid manager body assigning the given properties."""
    return {
        "name": "Budi Santoso",
        "phone": "081234567890",
        "propertyIds": [str(p.id) for p in properties],
        **overrides,
    }


def fetch_all(database, model) -> list:
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(model)))


def get_row(database, model, key):
    with Session(database, expire_on_commit=False) as db:
        return db.get(model, key)


def manager_users(database) -> list:
    from app.models import UserAccount

    return [u for u in fetch_all(database, UserAccount) if u.role == role("manager")]


def assigned_property_ids(database, user_id) -> set:
    from app.models import ManagerAssignment

    return {
        a.property_id
        for a in fetch_all(database, ManagerAssignment)
        if a.manager_id == user_id
    }


def invitation_rows(database, manager_id) -> list:
    """The invitations of a manager record, oldest first."""
    from app.models import Invitation

    rows = [i for i in fetch_all(database, Invitation) if i.manager_id == manager_id]
    return sorted(rows, key=lambda row: (row.created_at, str(row.id)))


def session_rows(database, user_id) -> list:
    from app.models import UserSession

    rows = [s for s in fetch_all(database, UserSession) if s.user_id == user_id]
    return sorted(rows, key=lambda row: (row.created_at, str(row.id)))


def state(database) -> dict:
    """Everything the manager endpoints may change, for before and after checks."""
    from app.models import (
        Invitation,
        Manager,
        ManagerAssignment,
        UserAccount,
        UserSession,
    )

    def ordered(rows, *columns):
        return sorted(
            (tuple(getattr(row, c) for c in columns) for row in rows),
            key=lambda item: tuple(str(v) for v in item),
        )

    return {
        "users": ordered(
            fetch_all(database, UserAccount),
            "id",
            "name",
            "email",
            "password_hash",
            "role",
            "email_verified",
        ),
        "managers": ordered(
            fetch_all(database, Manager),
            "id",
            "owner_id",
            "user_id",
            "nickname",
            "phone",
            "activated_at",
            "deleted_at",
        ),
        "assignments": ordered(
            fetch_all(database, ManagerAssignment), "manager_id", "property_id"
        ),
        "invitations": ordered(
            fetch_all(database, Invitation),
            "id",
            "tenant_id",
            "manager_id",
            "token_hash",
            "expires_at",
            "used_at",
            "invalidated_at",
        ),
        "sessions": ordered(fetch_all(database, UserSession), "id", "revoked_at"),
    }


def create_manager(client, headers, *properties, **overrides):
    return client.post(
        MANAGERS, json=new_body(*properties, **overrides), headers=headers
    )


def get_manager(client, headers, manager_id):
    return client.get(manager_url(manager_id), headers=headers)


def edit_manager(client, headers, manager_id, *properties, **overrides):
    return client.put(
        manager_url(manager_id),
        json=new_body(*properties, **overrides),
        headers=headers,
    )


def remove_manager(client, headers, manager_id):
    return client.delete(manager_url(manager_id), headers=headers)


def regenerate(client, headers, manager_id):
    return client.post(invitation_url(manager_id), headers=headers)


def list_managers(client, headers, **params):
    return client.get(MANAGERS, params=params, headers=headers)
