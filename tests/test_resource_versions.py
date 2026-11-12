"""The version of properties, rooms, tenants, managers and user accounts."""

import pytest
from resource_version_support import assert_error
from sqlalchemy.orm import Session
from user_account_support import PASSWORD, account_url, login, read_user, set_password

NEW_PROPERTY = {"name": "Kos Melati", "address": "Jl. Melati 5"}
NEW_ROOM = {"number": "A1", "baseRate": 1000000}
NEW_MANAGER_FIELDS = {"name": "Mira Manager", "phone": "081234567890"}


def stored_version(database, model, key) -> int:
    with Session(database, expire_on_commit=False) as db:
        return db.get(model, key).version


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


# Creation


def test_a_new_property_has_version_one(client, database, owner_in):
    from app.models import Property

    response = client.post("/properties", json=NEW_PROPERTY, headers=owner_in.headers)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["version"] == 1
    url = f"/properties/{created['id']}"
    assert client.get(url, headers=owner_in.headers).json()["version"] == 1
    listed = client.get("/properties", headers=owner_in.headers).json()["items"]
    assert [i["version"] for i in listed if i["id"] == created["id"]] == [1]
    assert stored_version(database, Property, created["id"]) == 1


def test_a_new_room_has_version_one(client, database, owner_in, prop):
    from app.models import Room

    url = f"/properties/{prop.id}/rooms"
    response = client.post(url, json=NEW_ROOM, headers=owner_in.headers)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["version"] == 1
    detail = client.get(f"/rooms/{created['id']}", headers=owner_in.headers)
    assert detail.json()["version"] == 1
    listed = client.get(url, headers=owner_in.headers).json()["items"]
    assert [i["version"] for i in listed if i["id"] == created["id"]] == [1]
    assert stored_version(database, Room, created["id"]) == 1


def test_a_new_tenant_has_version_one(client, database, owner_in, prop, make_room):
    from app.models import Tenant

    room = make_room(prop, number="A1")
    url = f"/properties/{prop.id}/tenants"
    body = {"name": "Budi", "phone": "081234567890", "roomId": str(room.id)}
    response = client.post(url, json=body, headers=owner_in.headers)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["version"] == 1
    detail = client.get(f"/tenants/{created['id']}", headers=owner_in.headers)
    assert detail.json()["version"] == 1
    listed = client.get(url, headers=owner_in.headers).json()["items"]
    assert [i["version"] for i in listed if i["id"] == created["id"]] == [1]
    assert stored_version(database, Tenant, created["id"]) == 1


def test_a_new_manager_has_version_one(client, database, owner_in, prop):
    from app.models import Manager

    body = {**NEW_MANAGER_FIELDS, "propertyIds": [str(prop.id)]}
    response = client.post("/managers", json=body, headers=owner_in.headers)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["version"] == 1
    detail = client.get(f"/managers/{created['id']}", headers=owner_in.headers)
    assert detail.json()["version"] == 1
    listed = client.get("/managers", headers=owner_in.headers).json()["items"]
    assert [i["version"] for i in listed if i["id"] == created["id"]] == [1]
    assert stored_version(database, Manager, created["id"]) == 1


def test_a_new_user_account_has_version_one(client, database, admin_in, make_user):
    from app.models import UserAccount

    user = make_user(name="Budi Santoso", email="budi@example.com")
    detail = client.get(account_url(user.id), headers=admin_in.headers)
    assert detail.json()["version"] == 1
    listed = client.get("/user-accounts", headers=admin_in.headers).json()["items"]
    assert [i["version"] for i in listed if i["id"] == str(user.id)] == [1]
    assert stored_version(database, UserAccount, user.id) == 1


def test_a_signed_up_owner_has_version_one(client, database, admin_in, register_owner):
    from app.models import UserAccount

    response = register_owner()
    assert response.status_code == 201, response.text
    user_id = response.json()["account"]["id"]
    detail = client.get(account_url(user_id), headers=admin_in.headers)
    assert detail.json()["version"] == 1
    assert stored_version(database, UserAccount, user_id) == 1


# Edits raise the version


def test_an_edit_raises_the_version_by_one(client, target):
    assert target.version() == 1
    response = target.put(client, target.changed_body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert target.version() == 2


def test_the_edit_response_the_detail_and_the_list_agree_on_the_version(client, target):
    response = target.put(client, target.changed_body)
    assert response.status_code == 200, response.text
    assert target.read(client)["version"] == response.json()["version"] == 2
    assert target.listed(client)["version"] == 2


def test_an_edit_applies_the_submitted_values(client, target):
    before = target.stored_values()
    response = target.put(client, target.changed_body)
    assert response.status_code == 200, response.text
    assert target.stored_values() != before


def test_every_edit_raises_the_version_by_one(client, target):
    bodies = [target.changed_body, target.body, target.changed_body, target.body]
    for expected, body in enumerate(bodies, start=2):
        response = target.put(client, body)
        assert response.status_code == 200, response.text
        assert response.json()["version"] == expected
        assert target.version() == expected
    assert target.read(client)["version"] == 5


def test_an_edit_with_the_current_values_still_raises_the_version(client, target):
    before = target.stored_values()
    response = target.put(client, target.body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert target.version() == 2
    assert target.stored_values() == before


def test_two_edits_with_the_current_values_raise_the_version_twice(client, target):
    assert target.put(client, target.body).json()["version"] == 2
    assert target.put(client, target.body).json()["version"] == 3


def test_a_rejected_edit_does_not_raise_the_version(client, target):
    response = client.put(target.url, json={}, headers=target.headers)
    assert response.status_code == 422
    assert target.version() == 1


def test_an_edit_by_a_forbidden_role_does_not_raise_the_version(client, target):
    response = target.put(client, target.changed_body, headers=target.forbidden_headers)
    assert_error(response, 403, "FORBIDDEN")
    assert target.version() == 1


def test_reads_do_not_change_the_version(client, target):
    for _ in range(3):
        target.read(client)
        target.listed(client)
    assert target.version() == 1
    assert target.read(client)["version"] == 1


# Changes that are not edits leave the version alone


def test_adding_a_room_leaves_the_version_of_the_property(
    client, database, owner_in, prop
):
    from app.models import Property

    response = client.post(
        f"/properties/{prop.id}/rooms", json=NEW_ROOM, headers=owner_in.headers
    )
    assert response.status_code == 201, response.text
    assert stored_version(database, Property, prop.id) == 1
    detail = client.get(f"/properties/{prop.id}", headers=owner_in.headers)
    assert detail.json()["version"] == 1


def test_editing_a_room_leaves_the_version_of_the_property(
    client, database, owner_in, prop, make_room
):
    from app.models import Property

    room = make_room(prop, number="A1", base_rate=1000000)
    response = client.put(
        f"/rooms/{room.id}",
        json={"number": "A2", "baseRate": 1100000},
        headers=owner_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert stored_version(database, Property, prop.id) == 1


def test_editing_a_property_leaves_the_version_of_its_rooms(
    client, database, owner_in, prop, make_room
):
    from app.models import Room

    room = make_room(prop, number="A1")
    response = client.put(
        f"/properties/{prop.id}",
        json={"name": "Kos Mawar", "address": "Jl. Mawar 7"},
        headers=owner_in.headers,
    )
    assert response.status_code == 200, response.text
    assert stored_version(database, Room, room.id) == 1


def test_adding_a_tenant_leaves_the_versions_of_the_room_and_the_property(
    client, database, owner_in, prop, make_room
):
    from app.models import Property, Room

    room = make_room(prop, number="A1")
    response = client.post(
        f"/properties/{prop.id}/tenants",
        json={"name": "Budi", "phone": "081234567890", "roomId": str(room.id)},
        headers=owner_in.headers,
    )
    assert response.status_code == 201, response.text
    assert stored_version(database, Room, room.id) == 1
    assert stored_version(database, Property, prop.id) == 1
    detail = client.get(f"/rooms/{room.id}", headers=owner_in.headers)
    assert detail.json()["version"] == 1


def test_editing_a_tenant_leaves_the_version_of_the_room(
    client, database, owner_in, prop, make_room, make_tenant
):
    from app.models import Room

    room = make_room(prop, number="A1")
    stored = make_tenant(room, name="Budi Tenant", phone="081234567890")
    response = client.put(
        f"/tenants/{stored.id}",
        json={"name": "Budi Tenant", "phone": "081234567891"},
        headers=owner_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert stored_version(database, Room, room.id) == 1


def test_editing_a_manager_leaves_the_version_of_the_property(
    client, database, owner, owner_in, prop, make_manager
):
    from app.models import Property

    stored = make_manager(owner, [prop], name="Mira Manager", phone="081234567890")
    response = client.put(
        f"/managers/{stored.id}",
        json={
            "name": "Mira Manager",
            "phone": "081234567891",
            "propertyIds": [str(prop.id)],
        },
        headers=owner_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert stored_version(database, Property, prop.id) == 1


def test_account_activity_leaves_the_version_of_the_account(
    client, database, admin_in, make_user, sign_in
):
    user = make_user(email="rina@example.com")
    set_password(database, user)
    assert login(client, "rina@example.com").status_code == 200
    session = sign_in(user)
    push = client.put("/me/push-token", json={"token": "abc"}, headers=session.headers)
    assert push.status_code == 204, push.text
    assert client.get("/me", headers=session.headers).status_code == 200
    assert client.get("/me/sessions", headers=session.headers).status_code == 200
    detail = client.get(account_url(user.id), headers=admin_in.headers)
    assert detail.json()["version"] == 1
    assert read_user(database, user.id).version == 1


def test_changing_the_password_leaves_the_version_of_the_account(
    client, database, admin_in, make_user, sign_in
):
    user = make_user(email="rina@example.com")
    set_password(database, user)
    session = sign_in(user)
    response = client.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": "Zq8!new-horse-staple"},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    assert read_user(database, user.id).version == 1
    detail = client.get(account_url(user.id), headers=admin_in.headers)
    assert detail.json()["version"] == 1


def test_logging_out_leaves_the_version_of_the_account(
    client, database, make_user, sign_in
):
    user = make_user(email="rina@example.com")
    session = sign_in(user)
    response = client.post("/auth/logout", headers=session.headers)
    assert response.status_code == 204, response.text
    assert read_user(database, user.id).version == 1


def test_editing_one_account_leaves_the_version_of_another(
    client, database, admin_in, make_user
):
    first = make_user(name="Budi Santoso", email="budi@example.com")
    second = make_user(name="Sari Dewi", email="sari@example.com")
    response = client.put(
        account_url(first.id),
        json={"name": "Budi Baru", "email": "budi@example.com", "status": "active"},
        headers=admin_in.headers,
    )
    assert response.status_code == 200, response.text
    assert read_user(database, first.id).version == 2
    assert read_user(database, second.id).version == 1
