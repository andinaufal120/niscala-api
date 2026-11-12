"""Steps shared by the sign-up, login and invitation scenarios.

Everything goes through the public HTTP API except the two places where it has
no way in: making an invitation expire and ending a login lock.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from e2e.e2e_people import DEVICE, ROLES, Person, check_status

OTHER_PASSWORD = "violet harbor lantern"
LOCK_THRESHOLD = 5


def assert_error(response, status: int, code: str) -> dict:
    """Require an error answer with the status and code, and return its body."""
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code, body
    assert body["message"]
    return body


def raw_login(world, email: str, password: str, device: dict | None = None):
    """Send a login request and return the raw answer."""
    return world.client.post(
        "/auth/login",
        json={"email": email, "password": password, "device": device or DEVICE},
    )


def person_from(world, response, *, password: str | None = None) -> Person:
    """Build the person of a session-starting answer (201 or 200)."""
    assert response.status_code in (200, 201), response.text
    session = response.json()
    return ROLES[session["account"]["role"]](world, session, password)


def token_in(url: str) -> str:
    """The token of a link emailed to a user, in its query or its last segment."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "token" in query:
        return query["token"][0]
    return parsed.path.rsplit("/", 1)[-1]


def expire_invitation(database, token: str) -> None:
    """Move the expiry of an invitation link into the past."""
    from app.models import Invitation

    digest = hashlib.sha256(str(token).encode()).hexdigest()
    with Session(database) as db:
        from sqlalchemy import select

        row = db.scalars(
            select(Invitation).where(Invitation.token_hash == digest)
        ).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()


def end_login_lock(database, email: str) -> None:
    """Let the lock on an email run out, as time passing would."""
    from app.models import LoginFailure

    with Session(database) as db:
        row = db.get(LoginFailure, email.strip().lower())
        assert row is not None and row.locked_until is not None, "no lock to end"
        row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def preview(world, token: str):
    """Preview an invitation link and return the raw answer."""
    return world.client.post("/invitations/previews", json={"token": str(token)})


def activation_body(token: str, *, name: str, email: str, password: str, **extra):
    return {
        "token": str(token),
        "name": name,
        "email": email,
        "password": password,
        "device": DEVICE,
        **extra,
    }


def read_ok(response, step: str) -> dict:
    """Require 200 and return the JSON body."""
    return check_status(response, 200, step).json()
