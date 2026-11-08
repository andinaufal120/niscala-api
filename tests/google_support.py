"""Helpers shared by the Google sign-in tests."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

REGISTER_URL = "/auth/register/google"
LOGIN_URL = "/auth/login/google"
PASSWORD_LOGIN_URL = "/auth/login"
ACTIVATION_URL = "/invitations/activations/google"
PREVIEW_URL = "/invitations/previews"
REAUTHENTICATION_URL = "/me/reauthentication/google"
ME_URL = "/me"
SESSIONS_URL = "/me/sessions"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
LOCK_SECONDS = 15 * 60
WINDOW = timedelta(minutes=5)


class AnyField:
    """Stands for a `field` value the contract leaves open."""

    def __repr__(self) -> str:
        return "<any field>"


ANY_FIELD = AnyField()


class FakeGoogleVerifier:
    """A Google verifier that knows a fixed set of tokens.

    `add` registers a token and the identity it stands for. Every token passed to
    `verify` is recorded in `verified`; an unknown token is rejected the way a bad
    signature, audience or expiry is.
    """

    def __init__(self) -> None:
        self.identities: dict[str, Any] = {}
        self.verified: list[str] = []

    def add(
        self,
        token: str,
        *,
        subject: str | None = None,
        email: str | None = None,
        email_verified: bool = True,
        name: str | None = "Google Person",
    ) -> Any:
        from app.google import GoogleIdentity

        identity = GoogleIdentity(
            subject=subject or f"sub-{token}",
            email=email or f"{token}@example.com",
            email_verified=email_verified,
            name=name,
        )
        self.identities[token] = identity
        return identity

    def verify(self, id_token: str) -> Any:
        from app.google import GoogleTokenInvalid

        self.verified.append(id_token)
        if id_token not in self.identities:
            raise GoogleTokenInvalid("unknown token")
        return self.identities[id_token]


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def assert_error(
    response, status: int, code: str, field: str | None | AnyField = None
) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    if not isinstance(field, AnyField):
        assert body["field"] == field
    assert body["message"]


def assert_locked(response) -> None:
    assert response.status_code == 429, response.text
    body = response.json()
    assert body["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert body["field"] is None
    assert body["message"]
    assert 1 <= int(response.headers["Retry-After"]) <= LOCK_SECONDS


# Requests


def register(client, id_token: str, **overrides):
    body = {"idToken": id_token, "device": DEVICE, **overrides}
    return client.post(REGISTER_URL, json=body)


def login(client, id_token: str, **overrides):
    body = {"idToken": id_token, "device": DEVICE, **overrides}
    return client.post(LOGIN_URL, json=body)


def password_login(client, email: str, password: str = "wrong password"):
    body = {"email": email, "password": password, "device": DEVICE}
    return client.post(PASSWORD_LOGIN_URL, json=body)


def reauthenticate(client, headers, id_token: str):
    return client.post(
        REAUTHENTICATION_URL, json={"idToken": id_token}, headers=headers
    )


def bearer(body: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['accessToken']}"}


# Stored rows


def make_google_user(
    database,
    *,
    subject: str,
    google_email: str | None = None,
    email: str | None = None,
    name: str = "Rina Owner",
    role=None,
    password_hash: str | None = None,
    email_verified: bool = True,
    status: str | None = None,
    deleted: bool = False,
):
    """Commit an account that is linked to a Google subject."""
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    extra: dict[str, Any] = {}
    if status is not None:
        extra["status"] = status
    if deleted:
        extra["deleted_at"] = datetime.now(UTC)
    with Session(database, expire_on_commit=False) as db:
        user = UserAccount(
            name=name,
            email=email or f"{subject}@example.com",
            password_hash=password_hash,
            role=role or UserRole.OWNER,
            email_verified=email_verified,
            google_subject=subject,
            google_email=google_email or f"{subject}@gmail.example",
            **extra,
        )
        db.add(user)
        db.commit()
        return user


def user_by_subject(database, subject: str):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.scalars(
            select(UserAccount).where(UserAccount.google_subject == subject)
        ).one_or_none()


def user_by_email(database, email: str):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.scalars(
            select(UserAccount).where(UserAccount.email == email)
        ).one_or_none()


def stored_user(database, user_id):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.get(UserAccount, user_id)


def count_rows(database, model) -> int:
    with Session(database) as db:
        return len(list(db.scalars(select(model))))


def snapshot(database) -> dict:
    """Everything a refused Google request must leave untouched."""
    from app.models import (
        EmailVerificationCode,
        Invitation,
        LoginFailure,
        UserAccount,
        UserSession,
    )

    with Session(database) as db:
        users = db.scalars(select(UserAccount).order_by(UserAccount.id))
        invitations = db.scalars(
            select(Invitation).order_by(Invitation.created_at, Invitation.token_hash)
        )
        return {
            "users": [
                (
                    u.id,
                    u.name,
                    u.email,
                    u.password_hash,
                    u.email_verified,
                    u.google_subject,
                    u.google_email,
                    u.status,
                )
                for u in users
            ],
            "invitations": [
                (i.token_hash, i.used_at, i.invalidated_at, i.expires_at)
                for i in invitations
            ],
            "sessions": count_rows(database, UserSession),
            "codes": count_rows(database, EmailVerificationCode),
            "failures": count_rows(database, LoginFailure),
        }


def read_failure(database, email: str):
    from app.models import LoginFailure

    with Session(database, expire_on_commit=False) as db:
        return db.get(LoginFailure, email)


def set_failure(database, email: str, **columns) -> None:
    from app.models import LoginFailure

    with Session(database) as db:
        row = db.get(LoginFailure, email)
        if row is None:
            db.add(LoginFailure(email=email, **columns))
        else:
            for name, value in columns.items():
                setattr(row, name, value)
        db.commit()


def recent_reauthentication_status(headers) -> int:
    """Status of a throwaway endpoint that needs a recent re-authentication."""
    from typing import Annotated

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app.access import require_recent_reauthentication
    from app.errors import register_error_handlers
    from app.security import CurrentUser

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/sensitive")
    def sensitive(
        current: Annotated[CurrentUser, Depends(require_recent_reauthentication)],
    ):
        return {}

    return TestClient(private).get("/sensitive", headers=headers).status_code
