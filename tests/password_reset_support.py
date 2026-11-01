"""Helpers shared by the password-reset endpoint tests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from user_account_support import (
    DEVICE,
    PASSWORD,
    assert_close,
    assert_error,
    assert_error_code,
    login,
    refresh,
    rows_of,
    set_columns,
    token_in,
)

__all__ = [
    "DEVICE",
    "NEW_PASSWORD",
    "PASSWORD",
    "PREVIEWS",
    "REQUESTS",
    "RESETS",
    "assert_close",
    "assert_error",
    "assert_error_code",
    "complete_reset",
    "expire_token",
    "last_reset_token",
    "login",
    "preview_reset",
    "refresh",
    "request_reset",
    "reset_rows",
    "set_columns",
    "snapshot",
    "start_reset",
]

REQUESTS = "/auth/password-reset-requests"
PREVIEWS = "/auth/password-reset-previews"
RESETS = "/auth/password-resets"
NEW_PASSWORD = "mUk3!xqz-Plover"
LIFETIME = timedelta(minutes=30)


def request_reset(client, email: str, headers: dict[str, str] | None = None):
    return client.post(REQUESTS, json={"email": email}, headers=headers)


def preview_reset(client, token: str):
    return client.post(PREVIEWS, json={"token": token})


def complete_reset(client, token: str, new_password: str = NEW_PASSWORD):
    return client.post(RESETS, json={"token": token, "newPassword": new_password})


def last_reset_token(mailbox) -> str:
    assert mailbox.reset_links, "no password reset link was sent"
    return token_in(mailbox.reset_links[-1][1])


def start_reset(client, mailbox, email: str) -> str:
    """Ask for a reset and return the token of the emailed link."""
    response = request_reset(client, email)
    assert response.status_code == 202, response.text
    return last_reset_token(mailbox)


def reset_rows(database, user_id) -> list:
    from app.models import PasswordResetToken

    rows = rows_of(database, PasswordResetToken, PasswordResetToken.user_id == user_id)
    return sorted(rows, key=lambda row: (row.created_at, str(row.id)))


def all_reset_rows(database) -> list:
    from app.models import PasswordResetToken

    return rows_of(database, PasswordResetToken)


def expire_token(database, row_id, minutes_ago: float = 1) -> None:
    from app.models import PasswordResetToken

    set_columns(
        database,
        PasswordResetToken,
        row_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def snapshot(response) -> tuple:
    """What a caller can observe of a response, apart from per-request headers."""
    headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in {"date", "x-request-id"}
    }
    return response.status_code, response.content, headers


def stored_hash(database, user_id) -> str | None:
    from app.models import UserAccount

    with Session(database) as db:
        return db.get(UserAccount, user_id).password_hash
