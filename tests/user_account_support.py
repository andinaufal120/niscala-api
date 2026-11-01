"""Helpers shared by the user-account endpoint tests."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from manager_support import assert_error, assert_error_code, invitation_base
from sqlalchemy import select
from sqlalchemy.orm import Session

__all__ = [
    "assert_error",
    "assert_error_code",
    "invitation_base",
]

USER_ACCOUNTS = "/user-accounts"
EMAIL_CHANGES = "/auth/email-changes"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
ME_URL = "/me"
PASSWORD = "T7#vq9-lorem-ipsum"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
CHANGE_LIFETIME = timedelta(days=7)

SUMMARY_FIELDS = {"id", "name", "email", "role", "status"}
ACCOUNT_FIELDS = {
    "id",
    "name",
    "email",
    "pendingEmail",
    "pendingEmailExpiresAt",
    "role",
    "status",
    "registeredAt",
    "lastLoginAt",
    "loginMethods",
    "properties",
    "activeLeaseCount",
    "tenancy",
}
TENANCY_FIELDS = {"propertyName", "roomNumber", "leaseEndDate"}
PROPERTY_REF_FIELDS = {"id", "name"}


def account_url(user_id) -> str:
    return f"{USER_ACCOUNTS}/{user_id}"


def list_accounts(client, headers, **params):
    return client.get(USER_ACCOUNTS, headers=headers, params=params)


def get_account(client, headers, user_id):
    return client.get(account_url(user_id), headers=headers)


def edit_body(user, **overrides: Any) -> dict[str, Any]:
    """A body that repeats the account's current name and email, status active."""
    return {
        "name": user.name,
        "email": user.email,
        "status": "active",
        **overrides,
    }


def edit_account(client, headers, user, **overrides: Any):
    """PUT the account with its current values, changed by the overrides."""
    return client.put(
        account_url(user.id), headers=headers, json=edit_body(user, **overrides)
    )


def delete_account(client, headers, user_id):
    return client.delete(account_url(user_id), headers=headers)


def confirm_change(client, token: str):
    return client.post(EMAIL_CHANGES, json={"token": token})


def login(client, email: str, password: str = PASSWORD):
    return client.post(
        LOGIN_URL, json={"email": email, "password": password, "device": DEVICE}
    )


def refresh(client, token: str):
    return client.post(REFRESH_URL, json={"refreshToken": token})


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def assert_close(first: datetime, second: datetime, seconds: float = 5) -> None:
    assert abs(first - second) <= timedelta(seconds=seconds), (first, second)


def token_in(url: str) -> str:
    """Extract the opaque token from an emailed link.

    The link starts with the configured base URL. Nothing else about its shape
    is fixed, so the token is the single long run of URL-safe characters after
    the base.
    """
    base = invitation_base()
    assert url.startswith(base), url
    found = re.findall(r"[A-Za-z0-9_-]{32,}", url.removeprefix(base))
    assert len(found) == 1, f"expected exactly one token in {url}"
    return found[0]


def last_token(mailbox) -> str:
    assert mailbox.links, "no email change link was sent"
    return token_in(mailbox.links[-1][1])


def change_email(client, headers, user, new_email: str, **overrides: Any):
    """Ask for an email change through the edit endpoint."""
    return edit_account(client, headers, user, email=new_email, **overrides)


def read_user(database, user_id):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.get(UserAccount, user_id)


def change_requests(database, user_id) -> list:
    from app.models import EmailChangeRequest

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(EmailChangeRequest)
                .where(EmailChangeRequest.user_id == user_id)
                .order_by(EmailChangeRequest.created_at, EmailChangeRequest.id)
            )
        )


def all_change_requests(database) -> list:
    from app.models import EmailChangeRequest

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(EmailChangeRequest)))


def expire_change_request(database, request_id) -> None:
    from app.models import EmailChangeRequest

    with Session(database) as db:
        db.get(EmailChangeRequest, request_id).expires_at = datetime.now(
            UTC
        ) - timedelta(minutes=1)
        db.commit()


def sessions_of(database, user_id) -> list:
    from app.models import UserSession

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at, UserSession.id)
            )
        )


def set_columns(database, model, key, **columns: Any) -> None:
    with Session(database) as db:
        row = db.get(model, key)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def set_password(database, user, password: str = PASSWORD) -> None:
    from app.models import UserAccount
    from app.services.passwords import hash_password

    set_columns(database, UserAccount, user.id, password_hash=hash_password(password))


def set_status(database, user, status: str) -> None:
    from app.models import UserAccount

    set_columns(database, UserAccount, user.id, status=status)


def rows_of(database, model, *conditions) -> list:
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(model).where(*conditions)))


def get_row(database, model, key):
    with Session(database, expire_on_commit=False) as db:
        return db.get(model, key)


def count_rows(database, model) -> int:
    return len(rows_of(database, model))


def ids(response) -> list[str]:
    return [item["id"] for item in response.json()["items"]]


def listed_ids(client, headers, **params) -> list[str]:
    response = list_accounts(client, headers, **params)
    assert response.status_code == 200, response.text
    return ids(response)
