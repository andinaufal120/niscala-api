"""Notifications created when a Tenant or a Manager activates an account."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from manager_invitation_support import edit_invitation, install_hook, stored_record
from notification_support import (
    ACCEPTANCES,
    ACTIVATION,
    assert_item,
    items,
    list_all,
    only,
    property_ref,
    register_token,
    role,
    room_ref,
    stored_for,
    stored_rows,
    tenant_ref,
    types,
)
from sqlalchemy.orm import Session

DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"
EMAIL = "new.person@example.com"
STORED_CONTACTS = [
    ("Siti", "Ibu", "081234567890"),
    ("Agus", "Kakak", "08571234567"),
]


def activate(client, token: str, name: str, **overrides):
    body = {
        "token": token,
        "name": name,
        "email": EMAIL,
        "password": PASSWORD,
        "device": DEVICE,
    }
    return client.post(ACTIVATION, json={**body, **overrides})


@pytest.fixture
def world(make_user, make_property, make_room, assign_manager, sign_in):
    """An owner with a property, a room and an assigned manager."""
    owner = make_user(name="Rina Owner")
    manager = make_user(name="Mira Manager", role=role("manager"))
    prop = make_property(owner, name="Kos Melati")
    assign_manager(manager, prop)
    return SimpleNamespace(
        owner=owner,
        manager=manager,
        prop=prop,
        room=make_room(prop, number="A1"),
        owner_in=sign_in(owner),
        manager_in=sign_in(manager),
    )


@pytest.fixture
def tenant(world, make_tenant):
    return make_tenant(world.room, name="Budi Tenant", contacts=STORED_CONTACTS)


@pytest.fixture
def invited(world, make_manager):
    """A Manager the owner invited and who has not activated yet."""
    return make_manager(
        world.owner, [world.prop], name="Dewi Manager", phone="081298765432"
    )


# A Tenant activates


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_a_tenant_activation_notifies_the_owner_and_the_assigned_manager(
    client, database, world, tenant, sent_emails, who
):
    assert activate(client, tenant.token, "Budi Tenant").status_code == 201
    recipient = getattr(world, who)
    item = only(client, recipient, "tenantActivated")
    assert_item(
        item,
        "tenantActivated",
        tenant=tenant_ref(tenant.user, "Budi Tenant"),
        room=room_ref(world.room),
        property=property_ref(world.prop),
    )
    assert types(client, recipient) == ["tenantActivated"]


def test_a_tenant_activation_does_not_notify_the_tenant(
    client, database, world, tenant, sent_emails
):
    activate(client, tenant.token, "Budi Tenant")
    assert stored_for(database, tenant.user) == []


def test_a_tenant_activation_notifies_nobody_else(
    client, database, world, tenant, sent_emails, make_user, make_site, sign_in
):
    outsider = make_user(name="Outside Manager", role=role("manager"))
    make_site(world.owner, name="Kos Kedua", number="B1", managers=[outsider])
    stranger = make_user(name="Other Owner")
    activate(client, tenant.token, "Budi Tenant")
    assert items(client, sign_in(outsider)) == []
    assert items(client, sign_in(stranger)) == []
    assert len(stored_rows(database)) == 2


def test_every_assigned_manager_is_told_about_the_tenant(
    client, database, world, tenant, sent_emails, make_user, assign_manager, sign_in
):
    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(colleague, world.prop)
    activate(client, tenant.token, "Budi Tenant")
    assert types(client, sign_in(colleague)) == ["tenantActivated"]
    assert len(stored_rows(database)) == 3


def test_a_tenant_notification_is_tied_to_the_property(
    client, database, world, tenant, sent_emails
):
    activate(client, tenant.token, "Budi Tenant")
    (row,) = stored_for(database, world.owner)
    assert str(row["type"]) == "tenantActivated"
    assert row["property_id"] == world.prop.id


@pytest.mark.parametrize(
    "case",
    ["unknown_token", "used_link", "expired_link", "weak_password", "taken_email"],
)
def test_a_refused_tenant_activation_creates_no_notification(
    client, database, world, tenant, sent_emails, make_user, case
):
    token = tenant.token
    overrides: dict = {}
    if case == "unknown_token":
        token = "unknown-token"
    elif case == "used_link":
        edit_invitation(database, token, used_at=datetime.now(UTC))
    elif case == "expired_link":
        edit_invitation(
            database, token, expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    elif case == "weak_password":
        overrides = {"password": "password123"}
    else:
        make_user(email=EMAIL)
    response = activate(client, token, "Budi Tenant", **overrides)
    assert response.status_code >= 400
    assert stored_rows(database) == []


def test_replaying_a_tenant_activation_creates_no_second_notification(
    client, database, world, tenant, sent_emails
):
    activate(client, tenant.token, "Budi Tenant")
    assert activate(client, tenant.token, "Budi Tenant").status_code == 409
    assert len(stored_for(database, world.owner)) == 1


class TenantHook:
    """Stands in for the hook that announces an activated Tenant."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bool, object]] = []
        self.error = error

    def __call__(self, db, tenant_user_id) -> None:
        self.calls.append((isinstance(db, Session), tenant_user_id))
        if self.error is not None:
            raise self.error


def test_the_tenant_hook_is_called_once_with_the_session_and_the_tenant_id(
    client, database, world, tenant, sent_emails, monkeypatch
):
    hook = TenantHook()
    monkeypatch.setattr("app.services.activation.notify_tenant_activated", hook)
    assert activate(client, tenant.token, "Budi Tenant").status_code == 201
    assert hook.calls == [(True, tenant.id)]


def test_the_tenant_hook_is_not_called_for_a_refused_activation(
    client, database, world, tenant, sent_emails, monkeypatch
):
    hook = TenantHook()
    monkeypatch.setattr("app.services.activation.notify_tenant_activated", hook)
    activate(client, "unknown-token", "Budi Tenant")
    activate(client, tenant.token, "Budi Tenant", password="password123")
    assert hook.calls == []


def test_a_failing_tenant_hook_does_not_undo_the_activation(
    client, database, world, tenant, sent_emails, monkeypatch
):
    hook = TenantHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.activation.notify_tenant_activated", hook)
    response = activate(client, tenant.token, "Budi Tenant")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == EMAIL
    assert len(hook.calls) == 1
    preview = client.post("/invitations/previews", json={"token": tenant.token})
    assert preview.json()["status"] == "used"


class BrokenSender:
    def send_verification_code(self, to: str, code: str) -> None:
        raise RuntimeError("mail server down")


def test_nothing_is_notified_when_the_activation_fails_after_the_account_is_built(
    app, client, database, world, tenant, sent_emails, pushes, monkeypatch
):
    from app.email import get_email_sender

    register_token(client, world.owner_in, "owner-device")
    monkeypatch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
    failing = TestClient(app, raise_server_exceptions=False)
    response = failing.post(
        ACTIVATION,
        json={
            "token": tenant.token,
            "name": "Budi Tenant",
            "email": EMAIL,
            "password": PASSWORD,
            "device": DEVICE,
        },
    )
    assert response.status_code == 500
    assert stored_rows(database) == []
    assert pushes.attempts == []


# A Manager activates with a password


def test_a_manager_activation_notifies_the_inviting_owner(
    client, database, world, invited, sent_emails
):
    assert activate(client, invited.token, "Dewi Manager").status_code == 201
    item = only(client, world.owner_in, "managerActivated")
    assert_item(item, "managerActivated", actorName="Dewi Manager")
    assert types(client, world.owner_in) == ["managerActivated"]


def test_a_manager_activation_notification_has_no_property_room_or_tenant(
    client, database, world, invited, sent_emails
):
    activate(client, invited.token, "Dewi Manager")
    item = only(client, world.owner_in, "managerActivated")
    for field in ("rentBill", "complaint", "tenant", "room", "property"):
        assert item[field] is None
    (row,) = stored_for(database, world.owner)
    assert row["property_id"] is None


def test_a_notification_without_a_property_stays_visible_to_the_owner(
    client, database, world, invited, sent_emails, make_site
):
    activate(client, invited.token, "Dewi Manager")
    make_site(world.owner, name="Kos Kedua", number="B1")
    body = list_all(client, world.owner_in)
    assert len(body["items"]) == 1
    assert body["unreadCount"] == 1


def test_a_manager_activation_does_not_notify_managers(
    client, database, world, invited, sent_emails
):
    activate(client, invited.token, "Dewi Manager")
    assert stored_for(database, world.manager) == []
    assert stored_for(database, invited.user) == []
    assert len(stored_rows(database)) == 1


def test_a_manager_activation_does_not_notify_other_owners(
    client, database, world, invited, sent_emails, make_user, sign_in
):
    stranger = sign_in(make_user(name="Other Owner"))
    activate(client, invited.token, "Dewi Manager")
    assert items(client, stranger) == []


@pytest.mark.parametrize(
    "case",
    ["unknown_token", "used_link", "expired_link", "weak_password", "taken_email"],
)
def test_a_refused_manager_activation_creates_no_notification(
    client, database, world, invited, sent_emails, make_user, case
):
    token = invited.token
    overrides: dict = {}
    if case == "unknown_token":
        token = "unknown-token"
    elif case == "used_link":
        edit_invitation(database, token, used_at=datetime.now(UTC))
    elif case == "expired_link":
        edit_invitation(
            database, token, expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    elif case == "weak_password":
        overrides = {"password": "password123"}
    else:
        make_user(email=EMAIL)
    response = activate(client, token, "Dewi Manager", **overrides)
    assert response.status_code >= 400
    assert stored_rows(database) == []


def test_replaying_a_manager_activation_creates_no_second_notification(
    client, database, world, invited, sent_emails
):
    activate(client, invited.token, "Dewi Manager")
    assert activate(client, invited.token, "Dewi Manager").status_code == 409
    assert len(stored_for(database, world.owner)) == 1


def test_nothing_is_notified_when_the_manager_activation_fails_after_the_account_is_built(
    app, client, database, world, invited, sent_emails, pushes, monkeypatch
):
    from app.email import get_email_sender

    register_token(client, world.owner_in, "owner-device")
    monkeypatch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
    failing = TestClient(app, raise_server_exceptions=False)
    response = failing.post(
        ACTIVATION,
        json={
            "token": invited.token,
            "name": "Dewi Manager",
            "email": EMAIL,
            "password": PASSWORD,
            "device": DEVICE,
        },
    )
    assert response.status_code == 500
    assert stored_rows(database) == []
    assert pushes.attempts == []


def test_the_manager_hook_receives_the_session_and_the_record(
    client, database, world, invited, sent_emails, monkeypatch
):
    seen: list[tuple[bool, object]] = []

    def hook(db, record) -> None:
        seen.append((isinstance(db, Session), record.id))

    monkeypatch.setattr("app.services.activation.notify_manager_activated", hook)
    assert activate(client, invited.token, "Dewi Manager").status_code == 201
    assert seen == [(True, invited.id)]


def test_a_failing_manager_hook_does_not_undo_the_activation(
    client, database, world, invited, sent_emails, monkeypatch
):
    calls = install_hook(monkeypatch, error=RuntimeError("notification down"))
    response = activate(client, invited.token, "Dewi Manager")
    assert response.status_code == 201, response.text
    assert calls.record_ids == [invited.id]
    assert stored_record(database, invited.id).activated_at is not None
    assert stored_rows(database) == []


# A Manager accepts an invitation with an existing account


@pytest.fixture
def caller(make_user, sign_in):
    """A Manager account that works for another owner and is signed in."""
    other_owner = make_user(name="Dewi Owner")
    user = make_user(
        name="Citra Caller", role=role("manager"), email="citra.caller@example.com"
    )
    return SimpleNamespace(user=user, other_owner=other_owner, signed_in=sign_in(user))


def accept(client, token: str, headers: dict):
    return client.post(ACCEPTANCES, json={"token": token}, headers=headers)


def test_an_accepted_invitation_notifies_the_inviting_owner(
    client, database, world, invited, caller, sent_emails
):
    response = accept(client, invited.token, caller.signed_in.headers)
    assert response.status_code == 204, response.text
    item = only(client, world.owner_in, "managerActivated")
    assert_item(item, "managerActivated", actorName="Citra Caller")
    assert types(client, world.owner_in) == ["managerActivated"]


def test_an_accepted_invitation_notifies_nobody_else(
    client, database, world, invited, caller, sent_emails
):
    accept(client, invited.token, caller.signed_in.headers)
    assert stored_for(database, caller.user) == []
    assert stored_for(database, caller.other_owner) == []
    assert stored_for(database, world.manager) == []
    assert len(stored_rows(database)) == 1


def test_an_accepted_invitation_notification_has_no_property(
    client, database, world, invited, caller, sent_emails
):
    accept(client, invited.token, caller.signed_in.headers)
    (row,) = stored_for(database, world.owner)
    assert str(row["type"]) == "managerActivated"
    assert row["property_id"] is None


def test_accepting_twice_creates_no_second_notification(
    client, database, world, invited, caller, sent_emails
):
    accept(client, invited.token, caller.signed_in.headers)
    assert accept(client, invited.token, caller.signed_in.headers).status_code == 409
    assert len(stored_rows(database)) == 1


def test_a_manager_who_already_works_for_the_owner_creates_no_notification(
    client, database, world, invited, caller, make_manager, sent_emails
):
    make_manager(world.owner, [world.prop], user=caller.user, activated=True)
    response = accept(client, invited.token, caller.signed_in.headers)
    assert response.status_code == 409
    assert stored_rows(database) == []


@pytest.mark.parametrize("name", ["owner", "tenant", "admin"])
def test_an_account_of_another_role_creates_no_notification(
    client, database, world, invited, make_user, sign_in, sent_emails, name
):
    other = sign_in(make_user(role=role(name)))
    response = accept(client, invited.token, other.headers)
    assert response.status_code == 409
    assert stored_rows(database) == []


def test_an_expired_invitation_creates_no_notification(
    client, database, world, make_manager, caller, sent_emails
):
    stale = make_manager(world.owner, [world.prop], name="Late Manager", expired=True)
    assert accept(client, stale.token, caller.signed_in.headers).status_code == 409
    assert stored_rows(database) == []


def test_the_acceptance_calls_the_manager_hook_with_the_session_and_the_record(
    client, database, world, invited, caller, sent_emails, monkeypatch
):
    seen: list[tuple[bool, object]] = []

    def hook(db, record) -> None:
        seen.append((isinstance(db, Session), record.id))

    monkeypatch.setattr("app.services.activation.notify_manager_activated", hook)
    assert accept(client, invited.token, caller.signed_in.headers).status_code == 204
    assert seen == [(True, invited.id)]


def test_a_failing_manager_hook_does_not_undo_the_acceptance(
    client, database, world, invited, caller, sent_emails, monkeypatch
):
    calls = install_hook(monkeypatch, error=RuntimeError("notification down"))
    assert accept(client, invited.token, caller.signed_in.headers).status_code == 204
    assert calls.record_ids == [invited.id]
    assert stored_record(database, invited.id).user_id == caller.user.id
    assert stored_record(database, invited.id).activated_at is not None
