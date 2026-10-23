"""Every request commits its changes before the response starts.

A client may send its next request the moment the response head arrives, so the
effect of a request has to be visible to other connections by then. The tests
wrap the real application in an ASGI layer that, right before the response head
is passed on, runs an observer on a separate database connection.
"""

import hashlib
from collections.abc import Callable
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, object_session

OWNER_EMAIL = "rina@example.com"
OWNER_PASSWORD = "correct horse battery"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PHONE = "081234567890"
CONTACTS = [
    {"name": "Siti", "relationship": "Mother", "phone": "081200000001"},
    {"name": "Joko", "relationship": "Father", "phone": "081200000002"},
]


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ResponseStartProbe:
    """ASGI wrapper that runs `observe(status_code)` before the response head is sent."""

    def __init__(self, app, observe: Callable[[int], Any]) -> None:
        self.app = app
        self.observe = observe
        self.observed: list[Any] = []

    async def __call__(self, scope, receive, send) -> None:
        async def probing_send(message) -> None:
            if message["type"] == "http.response.start":
                self.observed.append(self.observe(message["status"]))
            await send(message)

        await self.app(scope, receive, probing_send)


def peek(engine, read: Callable[[Session], Any]) -> Any:
    """Run `read` on a fresh session, which is never the request's own."""
    with Session(engine) as session:
        return read(session)


@pytest.fixture
def probe(database) -> Callable[..., tuple[Any, Any]]:
    """Send one request and return `(response, what the observer saw at response start)`."""
    from app.main import app

    def call(
        method: str,
        url: str,
        read: Callable[[Session], Any],
        *,
        application=None,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        wrapper = ResponseStartProbe(
            application or app, lambda _status: peek(database, read)
        )
        response = TestClient(wrapper).request(method, url, **kwargs)
        assert len(wrapper.observed) == 1
        return response, wrapper.observed[0]

    return call


def count(session: Session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


def register(client, email: str = OWNER_EMAIL):
    response = client.post(
        "/auth/register",
        json={
            "name": "Rina Owner",
            "email": email,
            "password": OWNER_PASSWORD,
            "device": DEVICE,
        },
    )
    assert response.status_code == 201
    return response.json()


def auth(body: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['accessToken']}"}


# auth


def test_register_is_committed_when_the_response_starts(probe, sent_emails):
    from app.models import EmailVerificationCode, UserAccount, UserSession

    def read(s):
        return (
            s.scalars(select(UserAccount.email)).all(),
            count(s, UserSession),
            count(s, EmailVerificationCode),
        )

    response, seen = probe(
        "POST",
        "/auth/register",
        read,
        json={
            "name": "Rina Owner",
            "email": OWNER_EMAIL,
            "password": OWNER_PASSWORD,
            "device": DEVICE,
        },
    )
    assert response.status_code == 201
    assert seen == ([OWNER_EMAIL], 1, 1)


def test_login_session_is_committed_when_the_response_starts(
    probe, client, sent_emails
):
    from app.models import UserSession

    register(client)
    response, seen = probe(
        "POST",
        "/auth/login",
        lambda s: count(s, UserSession),
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD, "device": DEVICE},
    )
    assert response.status_code == 200
    assert seen == 2


def test_refresh_rotation_is_committed_when_the_response_starts(
    probe, client, sent_emails
):
    from app.models import UsedRefreshToken, UserSession

    old_token = register(client)["refreshToken"]

    def read(s):
        current_hash = s.scalars(select(UserSession.refresh_token_hash)).one()
        used_hashes = set(s.scalars(select(UsedRefreshToken.token_hash)))
        return current_hash, used_hashes

    response, (current_hash, used_hashes) = probe(
        "POST", "/auth/refresh", read, json={"refreshToken": old_token}
    )
    assert response.status_code == 200
    assert used_hashes == {sha256(old_token)}
    assert current_hash != sha256(old_token)


def test_logout_revocation_is_committed_when_the_response_starts(
    probe, client, sent_emails
):
    from app.models import UserSession

    body = register(client)
    response, revoked_at = probe(
        "POST",
        "/auth/logout",
        lambda s: s.scalars(select(UserSession.revoked_at)).one(),
        headers=auth(body),
    )
    assert response.status_code == 204
    assert revoked_at is not None


def test_rejected_registration_leaves_nothing_committed_at_response_start(
    probe, make_user, sent_emails
):
    from app.models import EmailVerificationCode, UserAccount, UserSession

    make_user(email=OWNER_EMAIL)

    def read(s):
        return (
            count(s, UserAccount),
            count(s, UserSession),
            count(s, EmailVerificationCode),
        )

    response, seen = probe(
        "POST",
        "/auth/register",
        read,
        json={
            "name": "Rina Owner",
            "email": OWNER_EMAIL,
            "password": OWNER_PASSWORD,
            "device": DEVICE,
        },
    )
    assert response.status_code == 409
    assert seen == (1, 0, 0)


# properties and rooms


def test_property_creation_is_committed_when_the_response_starts(
    probe, make_user, sign_in
):
    from app.models import Property

    owner = make_user()
    response, names = probe(
        "POST",
        "/properties",
        lambda s: s.scalars(
            select(Property.name).where(Property.owner_id == owner.id)
        ).all(),
        headers=sign_in(owner).headers,
        json={"name": "Kos Melati", "address": "Jl. Melati 5"},
    )
    assert response.status_code == 201
    assert names == ["Kos Melati"]


def test_property_update_is_committed_when_the_response_starts(
    probe, make_user, make_property, sign_in
):
    from app.models import Property

    owner = make_user()
    prop = make_property(owner, name="Kos Melati")
    response, name = probe(
        "PUT",
        f"/properties/{prop.id}",
        lambda s: s.get(Property, prop.id).name,
        headers=sign_in(owner).headers,
        json={"name": "Kos Mawar", "address": "Jl. Mawar 1"},
    )
    assert response.status_code == 200
    assert name == "Kos Mawar"


def test_property_deletion_is_committed_when_the_response_starts(
    probe, make_user, make_property, sign_in
):
    from app.models import Property

    owner = make_user()
    prop = make_property(owner)
    response, deleted_at = probe(
        "DELETE",
        f"/properties/{prop.id}",
        lambda s: s.get(Property, prop.id).deleted_at,
        headers=sign_in(owner).headers,
    )
    assert response.status_code == 204
    assert deleted_at is not None


def test_rejected_duplicate_property_leaves_nothing_committed_at_response_start(
    probe, make_user, make_property, sign_in
):
    from app.models import Property

    owner = make_user()
    make_property(owner, name="Kos Melati")
    response, total = probe(
        "POST",
        "/properties",
        lambda s: count(s, Property),
        headers=sign_in(owner).headers,
        json={"name": "Kos Melati", "address": "Jl. Melati 5"},
    )
    assert response.status_code == 409
    assert total == 1


def test_room_creation_is_committed_when_the_response_starts(
    probe, make_user, make_property, sign_in
):
    from app.models import Room

    owner = make_user()
    prop = make_property(owner)
    response, numbers = probe(
        "POST",
        f"/properties/{prop.id}/rooms",
        lambda s: s.scalars(
            select(Room.number).where(Room.property_id == prop.id)
        ).all(),
        headers=sign_in(owner).headers,
        json={"number": "A1", "baseRate": 1000000},
    )
    assert response.status_code == 201
    assert numbers == ["A1"]


def test_room_deletion_is_committed_when_the_response_starts(
    probe, make_user, make_property, make_room, sign_in
):
    from app.models import Room

    owner = make_user()
    room = make_room(make_property(owner))
    response, deleted_at = probe(
        "DELETE",
        f"/rooms/{room.id}",
        lambda s: s.get(Room, room.id).deleted_at,
        headers=sign_in(owner).headers,
    )
    assert response.status_code == 204
    assert deleted_at is not None


# tenants, invitations, complaints


def test_tenant_creation_is_committed_when_the_response_starts(
    probe, make_user, make_property, make_room, sign_in, subscribe_owner
):
    from app.models import Invitation, Lease, Tenant

    owner = make_user()
    subscribe_owner(owner)
    prop = make_property(owner)
    room = make_room(prop)
    response, seen = probe(
        "POST",
        f"/properties/{prop.id}/tenants",
        lambda s: (count(s, Tenant), count(s, Lease), count(s, Invitation)),
        headers=sign_in(owner).headers,
        json={"name": "Budi Tenant", "phone": PHONE, "roomId": str(room.id)},
    )
    assert response.status_code == 201
    assert seen == (1, 1, 1)


def test_complaint_is_committed_when_the_response_starts(
    probe,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
    subscribe_owner,
    fake_classifier,
):
    from app.models import Complaint

    owner = make_user()
    subscribe_owner(owner)
    room = make_room(make_property(owner))
    tenant = make_verified_tenant(room)
    response, states = probe(
        "POST",
        "/complaints",
        lambda s: s.scalars(select(Complaint.classification_state)).all(),
        headers=sign_in(tenant.user).headers,
        json={"description": "The tap in the bathroom leaks badly."},
    )
    assert response.status_code == 201
    assert len(states) == 1


def test_password_activation_is_committed_when_the_response_starts(
    probe, make_user, make_property, make_room, make_tenant, sent_emails
):
    from app.models import Invitation, Tenant

    room = make_room(make_property(make_user()))
    stored = make_tenant(room)

    def read(s):
        return (
            s.get(Tenant, stored.id).activated_at,
            s.scalars(
                select(Invitation.used_at).where(Invitation.tenant_id == stored.id)
            ).one(),
        )

    response, (activated_at, used_at) = probe(
        "POST",
        "/invitations/activations/password",
        read,
        json={
            "token": stored.token,
            "name": "Budi Tenant",
            "email": "budi@example.com",
            "password": OWNER_PASSWORD,
            "emergencyContacts": CONTACTS,
            "device": DEVICE,
        },
    )
    assert response.status_code == 201
    assert activated_at is not None
    assert used_at is not None


# private application


def scratch_app(engine) -> FastAPI:
    from app.db import SessionDep
    from app.errors import ApiError, register_error_handlers

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE scratch_items (id int PRIMARY KEY)"))

    private = FastAPI()
    register_error_handlers(private)

    def insert(session: Session, item_id: int) -> None:
        session.execute(text("INSERT INTO scratch_items VALUES (:id)"), {"id": item_id})

    @private.get("/commit")
    def commit(session: SessionDep):
        insert(session, 1)
        return {"ok": True}

    @private.get("/api-error")
    def api_error(session: SessionDep):
        insert(session, 2)
        raise ApiError(409, "SCRATCH_CONFLICT")

    @private.get("/ping")
    def ping(session: SessionDep):
        return {"value": session.execute(text("SELECT 1")).scalar_one()}

    return private


def scratch_ids(session: Session) -> list[int]:
    return list(session.scalars(text("SELECT id FROM scratch_items ORDER BY id")))


def test_session_dependency_commits_before_the_response_starts(probe, database):
    response, ids = probe(
        "GET", "/commit", scratch_ids, application=scratch_app(database)
    )
    assert response.status_code == 200
    assert ids == [1]


def test_session_dependency_commits_nothing_when_the_handler_raises_api_error(
    probe, database
):
    response, ids = probe(
        "GET", "/api-error", scratch_ids, application=scratch_app(database)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SCRATCH_CONFLICT"
    assert ids == []
    assert peek(database, scratch_ids) == []


def test_read_only_request_works_and_releases_its_connection(
    database, make_user, make_property, sign_in
):
    owner = make_user()
    make_property(owner)
    from app.main import app

    response = TestClient(app).get("/properties", headers=sign_in(owner).headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert database.pool.checkedout() == 0


def test_session_is_released_after_a_scratch_request(database):
    response = TestClient(scratch_app(database)).get("/ping")
    assert response.json() == {"value": 1}
    assert database.pool.checkedout() == 0


def test_dependencies_and_handler_share_one_session_per_request(
    database, make_user, sign_in
):
    from app.db import SessionDep
    from app.errors import register_error_handlers
    from app.security import CurrentUser, get_current_user

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/who")
    def who(current: Annotated[CurrentUser, Depends(get_current_user)], db: SessionDep):
        return {
            "user": object_session(current.user) is db,
            "session": object_session(current.session) is db,
        }

    user = make_user()
    response = TestClient(private).get("/who", headers=sign_in(user).headers)
    assert response.status_code == 200
    assert response.json() == {"user": True, "session": True}
