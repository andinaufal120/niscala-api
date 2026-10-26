"""Editing and deleting managers, including accounts shared between owners."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from manager_support import (
    DEVICE,
    INVITATION_FIELDS,
    LOGIN_URL,
    MANAGER_FIELDS,
    ME_URL,
    PASSWORD,
    PROPERTIES,
    REFRESH_URL,
    assert_error,
    assert_just_now,
    assigned_property_ids,
    create_manager,
    edit_manager,
    fetch_all,
    get_manager,
    get_row,
    invitation_rows,
    link_for,
    list_managers,
    manager_url,
    new_body,
    remove_manager,
    session_rows,
    state,
    without,
)


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def melati(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def anggrek(owner, make_property):
    return make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")


@pytest.fixture
def other_owner(make_user):
    return make_user(name="Dewi Owner")


@pytest.fixture
def theirs(other_owner, make_property):
    return make_property(other_owner, name="Kos Mawar", address="Jl. Mawar 9")


@pytest.fixture
def current(owner, melati, make_manager):
    """A manager who has not activated yet."""
    return make_manager(
        owner,
        [melati],
        name="Old Name",
        nickname="Old Nick",
        phone="081111111111",
    )


@pytest.fixture
def active(owner, melati, make_manager):
    """A manager who has activated with a password."""
    return make_manager(
        owner,
        [melati],
        name="Active Name",
        nickname="Old Nick",
        phone="081111111111",
        email="active@example.com",
        password=PASSWORD,
        activated=True,
        used=True,
    )


def login(client, email: str, password: str = PASSWORD):
    body = {"email": email, "password": password, "device": DEVICE}
    return client.post(LOGIN_URL, json=body)


def refresh_with(client, token: str):
    return client.post(REFRESH_URL, json={"refreshToken": token})


def record_of(database, manager_id):
    from app.models import Manager

    return get_row(database, Manager, manager_id)


def user_of(database, user_id):
    from app.models import UserAccount

    return get_row(database, UserAccount, user_id)


# PUT: success


def test_editing_answers_with_the_updated_manager(
    client, database, melati, anggrek, signed_in, current
):
    response = edit_manager(
        client,
        signed_in.headers,
        current.id,
        anggrek,
        name="New Name",
        nickname="New Nick",
        phone="082222222222",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == MANAGER_FIELDS
    assert body["id"] == str(current.id)
    assert body["name"] == "New Name"
    assert body["nickname"] == "New Nick"
    assert body["phone"] == "082222222222"
    assert body["email"] is None
    assert body["accountStatus"] == "notActivated"
    assert [p["id"] for p in body["properties"]] == [str(anggrek.id)]


def test_the_edited_manager_can_be_read_back_unchanged(
    client, database, melati, anggrek, signed_in, current
):
    edited = edit_manager(
        client, signed_in.headers, current.id, melati, anggrek, name="New Name"
    ).json()
    response = get_manager(client, signed_in.headers, current.id)
    assert response.json() == edited


def test_the_record_and_the_account_are_updated(
    client, database, melati, signed_in, current
):
    edit_manager(
        client,
        signed_in.headers,
        current.id,
        melati,
        name="  New Name ",
        nickname="New Nick",
        phone="0822-2222-2222",
    )
    record = record_of(database, current.id)
    assert record.nickname == "New Nick"
    assert record.phone == "082222222222"
    assert record.deleted_at is None
    assert record.activated_at is None
    assert user_of(database, current.user_id).name == "New Name"


def test_the_name_is_trimmed_on_edit(client, database, melati, signed_in, current):
    body = edit_manager(
        client, signed_in.headers, current.id, melati, name="  New Name \n"
    ).json()
    assert body["name"] == "New Name"


def test_the_list_shows_the_new_name(client, database, melati, signed_in, current):
    edit_manager(client, signed_in.headers, current.id, melati, name="Zed New")
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert item["name"] == "Zed New"


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("  Pak Budi ", "Pak Budi"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_the_nickname_is_trimmed_and_blank_clears_it_on_edit(
    client, database, melati, signed_in, current, submitted, expected
):
    response = edit_manager(
        client, signed_in.headers, current.id, melati, nickname=submitted
    )
    assert response.status_code == 200, response.text
    assert response.json()["nickname"] == expected
    assert record_of(database, current.id).nickname == expected


def test_an_omitted_nickname_clears_it_on_edit(
    client, database, melati, signed_in, current
):
    body = without(new_body(melati), "nickname")
    response = client.put(manager_url(current.id), json=body, headers=signed_in.headers)
    assert response.status_code == 200, response.text
    assert response.json()["nickname"] is None
    assert record_of(database, current.id).nickname is None


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("08123456789", "08123456789"),
        ("628123456789", "08123456789"),
        ("0812-3456-789", "08123456789"),
        ("62 812-3456 789", "08123456789"),
        ("08" + "1" * 11, "08" + "1" * 11),
    ],
)
def test_a_phone_is_normalized_on_edit(
    client, database, melati, signed_in, current, submitted, expected
):
    response = edit_manager(
        client, signed_in.headers, current.id, melati, phone=submitted
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == expected
    assert record_of(database, current.id).phone == expected


def test_editing_leaves_the_invitation_and_the_email_alone(
    client, database, melati, anggrek, signed_in, current
):
    before = state(database)["invitations"]
    body = edit_manager(
        client, signed_in.headers, current.id, melati, anggrek, name="New Name"
    ).json()
    assert state(database)["invitations"] == before
    assert set(body["invitation"]) == INVITATION_FIELDS
    assert body["invitation"]["url"] == link_for(current.token)
    assert body["email"] is None
    assert user_of(database, current.user_id).email is None


def test_editing_leaves_other_managers_untouched(
    client, database, owner, melati, signed_in, current, make_manager
):
    other = make_manager(owner, [melati], name="Other", nickname="Oth", phone="083")
    before = {
        "record": record_of(database, other.id).phone,
        "name": user_of(database, other.user_id).name,
        "assigned": assigned_property_ids(database, other.user_id),
    }
    edit_manager(
        client, signed_in.headers, current.id, melati, name="New", phone="082222222222"
    )
    assert record_of(database, other.id).phone == before["record"]
    assert user_of(database, other.user_id).name == before["name"]
    assert assigned_property_ids(database, other.user_id) == before["assigned"]


# PUT: assignments


def test_the_assignments_are_replaced(
    client, database, melati, anggrek, signed_in, current
):
    edit_manager(client, signed_in.headers, current.id, anggrek)
    assert assigned_property_ids(database, current.user_id) == {anggrek.id}


def test_properties_can_be_added_while_keeping_the_others(
    client, database, melati, anggrek, signed_in, current
):
    response = edit_manager(client, signed_in.headers, current.id, melati, anggrek)
    assert response.status_code == 200, response.text
    assert assigned_property_ids(database, current.user_id) == {melati.id, anggrek.id}
    assert [p["name"] for p in response.json()["properties"]] == [
        "Kos Anggrek",
        "Kos Melati",
    ]


def test_a_view_only_property_may_be_assigned_on_edit(
    client, database, owner, melati, make_property, signed_in, current
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    response = edit_manager(client, signed_in.headers, current.id, melati, frozen)
    assert response.status_code == 200, response.text
    assert assigned_property_ids(database, current.user_id) == {melati.id, frozen.id}


def test_a_removed_property_is_lost_at_once_and_an_added_one_is_gained(
    client, database, melati, anggrek, signed_in, current, sign_in
):
    manager_in = sign_in(current.user)
    listed = client.get(PROPERTIES, headers=manager_in.headers).json()["items"]
    assert [p["id"] for p in listed] == [str(melati.id)]
    assert (
        client.get(f"{PROPERTIES}/{melati.id}", headers=manager_in.headers).status_code
        == 200
    )
    assert_error(
        client.get(f"{PROPERTIES}/{anggrek.id}", headers=manager_in.headers),
        404,
        "PROPERTY_NOT_FOUND",
    )

    edit_manager(client, signed_in.headers, current.id, anggrek)

    listed = client.get(PROPERTIES, headers=manager_in.headers).json()["items"]
    assert [p["id"] for p in listed] == [str(anggrek.id)]
    assert_error(
        client.get(f"{PROPERTIES}/{melati.id}", headers=manager_in.headers),
        404,
        "PROPERTY_NOT_FOUND",
    )
    assert (
        client.get(f"{PROPERTIES}/{anggrek.id}", headers=manager_in.headers).status_code
        == 200
    )


def test_assignments_to_the_properties_of_other_owners_are_untouched(
    client, database, owner, melati, anggrek, theirs, other_owner, make_manager, sign_in
):
    shared = make_manager(
        owner, [melati], name="Shared", activated=True, email="shared@example.com"
    )
    make_manager(other_owner, [theirs], user=shared.user)
    manager_in = sign_in(shared.user)
    edit = edit_manager(
        client, sign_in(owner).headers, shared.id, anggrek, name="Shared"
    )
    assert edit.status_code == 200, edit.text
    assert assigned_property_ids(database, shared.user_id) == {anggrek.id, theirs.id}
    listed = client.get(PROPERTIES, headers=manager_in.headers).json()["items"]
    assert {p["id"] for p in listed} == {str(anggrek.id), str(theirs.id)}
    assert (
        client.get(f"{PROPERTIES}/{theirs.id}", headers=manager_in.headers).status_code
        == 200
    )


def test_editing_the_response_shows_only_the_properties_of_this_owner(
    client, database, owner, melati, theirs, other_owner, make_manager, signed_in
):
    shared = make_manager(owner, [melati], name="Shared", activated=True)
    make_manager(other_owner, [theirs], user=shared.user)
    body = edit_manager(
        client, signed_in.headers, shared.id, melati, name="Shared"
    ).json()
    assert [p["id"] for p in body["properties"]] == [str(melati.id)]


def test_an_unknown_property_is_not_found_on_edit(
    client, database, melati, signed_in, current
):
    before = state(database)
    body = {**new_body(melati), "propertyIds": [str(melati.id), str(uuid4())]}
    response = client.put(manager_url(current.id), json=body, headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.1")
    assert state(database) == before


def test_another_owners_property_is_not_found_on_edit(
    client, database, theirs, signed_in, current
):
    before = state(database)
    response = edit_manager(client, signed_in.headers, current.id, theirs)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert state(database) == before


def test_a_deleted_property_is_not_found_on_edit(
    client, database, owner, make_property, signed_in, current
):
    gone = make_property(owner, name="Gone", deleted=True)
    before = state(database)
    response = edit_manager(client, signed_in.headers, current.id, gone)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert state(database) == before


# PUT: field rules and atomicity


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": "  "}, "name"),
        ({"name": ""}, "name"),
        ({"phone": "nope"}, "phone"),
        ({"phone": "+628123456789"}, "phone"),
        ({"phone": "081234567"}, "phone"),
        ({"phone": ""}, "phone"),
        ({"propertyIds": []}, "propertyIds"),
    ],
    ids=[
        "blank_name",
        "empty_name",
        "bad_phone",
        "plus_phone",
        "short_phone",
        "empty_phone",
        "no_properties",
    ],
)
def test_a_failed_field_rule_saves_nothing_on_edit(
    client, database, melati, signed_in, current, change, field
):
    before = state(database)
    body = {**new_body(melati, name="Changed", nickname="Changed"), **change}
    response = client.put(manager_url(current.id), json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", field)
    assert state(database) == before


def test_a_duplicate_property_id_is_a_validation_failure_on_edit(
    client, database, melati, signed_in, current
):
    before = state(database)
    response = edit_manager(client, signed_in.headers, current.id, melati, melati)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyIds")
    assert state(database) == before


@pytest.mark.parametrize("key", ["name", "phone", "propertyIds"])
def test_a_missing_required_field_is_a_validation_failure_on_edit(
    client, database, melati, signed_in, current, key
):
    body = without(new_body(melati), key)
    response = client.put(manager_url(current.id), json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", key)


def test_any_other_failure_saves_nothing_on_edit(
    app, database, owner, melati, anggrek, current, sign_in, monkeypatch
):
    from sqlalchemy.orm import Session as OrmSession

    from app.models import ManagerAssignment

    headers = sign_in(owner).headers
    original = OrmSession.flush

    def failing_flush(self, *args, **kwargs):
        if any(isinstance(obj, ManagerAssignment) for obj in self.new):
            raise RuntimeError("storage failure")
        return original(self, *args, **kwargs)

    before = state(database)
    monkeypatch.setattr(OrmSession, "flush", failing_flush)
    client = TestClient(app, raise_server_exceptions=False)
    response = edit_manager(
        client,
        headers,
        current.id,
        melati,
        anggrek,
        name="Changed",
        phone="082222222222",
    )
    monkeypatch.setattr(OrmSession, "flush", original)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert state(database) == before


# PUT: active managers


def test_an_active_manager_keeps_the_account_name_when_it_is_resubmitted(
    client, database, melati, anggrek, signed_in, active
):
    response = edit_manager(
        client,
        signed_in.headers,
        active.id,
        anggrek,
        name="Active Name",
        nickname="New Nick",
        phone="082222222222",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Active Name"
    assert body["nickname"] == "New Nick"
    assert body["phone"] == "082222222222"
    assert body["accountStatus"] == "active"
    assert body["email"] == "active@example.com"
    assert body["invitation"] is None
    assert [p["id"] for p in body["properties"]] == [str(anggrek.id)]
    assert user_of(database, active.user_id).name == "Active Name"
    assert user_of(database, active.user_id).email == "active@example.com"


def test_a_different_name_for_an_active_manager_is_refused_and_nothing_is_saved(
    client, database, melati, anggrek, signed_in, active
):
    before = state(database)
    response = edit_manager(
        client,
        signed_in.headers,
        active.id,
        anggrek,
        name="Another Name",
        nickname="New Nick",
        phone="082222222222",
    )
    assert_error(response, 422, "MANAGER_NAME_NOT_EDITABLE", "name")
    assert state(database) == before
    assert user_of(database, active.user_id).name == "Active Name"


def test_a_manager_who_has_not_activated_can_be_renamed(
    client, database, melati, signed_in, current
):
    response = edit_manager(
        client, signed_in.headers, current.id, melati, name="New Name"
    )
    assert response.status_code == 200, response.text
    assert user_of(database, current.user_id).name == "New Name"


# PUT: manager access

EDIT_NOT_FOUND = [
    "unknown",
    "account_id",
    "deleted",
    "other_owner",
]


def not_found_id(kind, owner, melati, other_owner, theirs, make_manager):
    if kind == "unknown":
        return uuid4()
    stored = make_manager(owner, [melati], deleted=kind == "deleted")
    if kind == "account_id":
        return stored.user_id
    if kind == "other_owner":
        return make_manager(other_owner, [theirs]).id
    return stored.id


@pytest.mark.parametrize("kind", EDIT_NOT_FOUND)
def test_a_manager_that_is_not_the_owners_is_not_found_on_edit(
    client, database, owner, melati, other_owner, theirs, make_manager, signed_in, kind
):
    target = not_found_id(kind, owner, melati, other_owner, theirs, make_manager)
    before = state(database)
    response = edit_manager(client, signed_in.headers, target, melati, name="Changed")
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == before


def test_a_malformed_manager_id_is_a_validation_failure_on_edit(
    client, database, melati, signed_in
):
    response = edit_manager(client, signed_in.headers, "not-a-uuid", melati)
    assert_error(response, 422, "VALIDATION_FAILED", "managerId")


# Per-owner data


def test_two_owners_keep_their_own_nickname_and_phone_for_one_account(
    client, database, owner, melati, other_owner, theirs, make_manager, sign_in
):
    mine = make_manager(
        owner,
        [melati],
        name="Shared",
        nickname="Mine",
        phone="081111111111",
        activated=True,
        email="shared@example.com",
    )
    others = make_manager(
        other_owner,
        [theirs],
        nickname="Theirs",
        phone="082222222222",
        activated=True,
        user=mine.user,
    )
    my_headers = sign_in(owner).headers
    their_headers = sign_in(other_owner).headers
    response = edit_manager(
        client,
        my_headers,
        mine.id,
        melati,
        name="Shared",
        nickname="Changed",
        phone="083333333333",
    )
    assert response.status_code == 200, response.text
    mine_body = get_manager(client, my_headers, mine.id).json()
    assert (mine_body["nickname"], mine_body["phone"]) == ("Changed", "083333333333")
    theirs_body = get_manager(client, their_headers, others.id).json()
    assert (theirs_body["nickname"], theirs_body["phone"]) == (
        "Theirs",
        "082222222222",
    )
    assert theirs_body["id"] != mine_body["id"]
    assert theirs_body["email"] == mine_body["email"] == "shared@example.com"


def test_each_owner_lists_only_their_own_records_of_one_account(
    client, database, owner, melati, other_owner, theirs, make_manager, sign_in
):
    mine = make_manager(owner, [melati], name="Shared", nickname="Mine", activated=True)
    others = make_manager(
        other_owner, [theirs], nickname="Theirs", activated=True, user=mine.user
    )
    (my_item,) = list_managers(client, sign_in(owner).headers).json()["items"]
    (their_item,) = list_managers(client, sign_in(other_owner).headers).json()["items"]
    assert (my_item["id"], my_item["nickname"]) == (str(mine.id), "Mine")
    assert (their_item["id"], their_item["nickname"]) == (str(others.id), "Theirs")
    assert [p["id"] for p in my_item["properties"]] == [str(melati.id)]
    assert [p["id"] for p in their_item["properties"]] == [str(theirs.id)]


def test_one_owner_cannot_read_edit_or_delete_the_record_of_another(
    client, database, owner, melati, other_owner, theirs, make_manager, sign_in
):
    mine = make_manager(owner, [melati], name="Shared", activated=True)
    others = make_manager(other_owner, [theirs], activated=True, user=mine.user)
    headers = sign_in(owner).headers
    assert_error(get_manager(client, headers, others.id), 404, "MANAGER_NOT_FOUND")
    assert_error(
        edit_manager(client, headers, others.id, melati, name="Shared"),
        404,
        "MANAGER_NOT_FOUND",
    )
    assert_error(remove_manager(client, headers, others.id), 404, "MANAGER_NOT_FOUND")
    assert record_of(database, others.id).deleted_at is None


# DELETE: success


def test_removing_a_manager_answers_no_content(client, database, signed_in, current):
    response = remove_manager(client, signed_in.headers, current.id)
    assert response.status_code == 204, response.text
    assert response.content == b""


def test_the_record_is_soft_deleted_and_kept(client, database, signed_in, current):
    assert remove_manager(client, signed_in.headers, current.id).status_code == 204
    record = record_of(database, current.id)
    assert record is not None
    assert_just_now(record.deleted_at)
    assert record.phone == "081111111111"
    assert record.nickname == "Old Nick"
    assert record.user_id == current.user_id


def test_the_user_account_row_is_kept_after_removal(
    client, database, signed_in, current
):
    remove_manager(client, signed_in.headers, current.id)
    account = user_of(database, current.user_id)
    assert account.name == "Old Name"
    assert account.role == "manager"


def test_the_assignments_of_the_owners_properties_are_removed(
    client, database, owner, melati, anggrek, make_property, make_manager, signed_in
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    stored = make_manager(owner, [melati, anggrek, frozen])
    remove_manager(client, signed_in.headers, stored.id)
    assert assigned_property_ids(database, stored.user_id) == set()


def test_the_removed_manager_leaves_the_list_and_cannot_be_read(
    client, database, melati, signed_in, current
):
    assert list_managers(client, signed_in.headers).json()["items"]
    remove_manager(client, signed_in.headers, current.id)
    assert list_managers(client, signed_in.headers).json() == {"items": []}
    filtered = list_managers(client, signed_in.headers, propertyId=str(melati.id))
    assert filtered.json() == {"items": []}
    assert_error(
        get_manager(client, signed_in.headers, current.id), 404, "MANAGER_NOT_FOUND"
    )


def test_removing_twice_answers_not_found_the_second_time(
    client, database, signed_in, current
):
    assert remove_manager(client, signed_in.headers, current.id).status_code == 204
    after_first = state(database)
    response = remove_manager(client, signed_in.headers, current.id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == after_first


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"activated": True, "email": "budi@example.com"},
        {"expired": True},
        {"invitation": False},
    ],
    ids=["unused_link", "activated", "expired_link", "no_link"],
)
def test_a_manager_in_any_account_state_can_be_removed(
    client, database, owner, melati, make_manager, signed_in, options
):
    stored = make_manager(owner, [melati], **options)
    assert remove_manager(client, signed_in.headers, stored.id).status_code == 204
    assert_just_now(record_of(database, stored.id).deleted_at)
    assert assigned_property_ids(database, stored.user_id) == set()


@pytest.mark.parametrize("kind", EDIT_NOT_FOUND)
def test_a_manager_that_is_not_the_owners_is_not_found_on_removal(
    client, database, owner, melati, other_owner, theirs, make_manager, signed_in, kind
):
    target = not_found_id(kind, owner, melati, other_owner, theirs, make_manager)
    before = state(database)
    response = remove_manager(client, signed_in.headers, target)
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == before


def test_a_malformed_manager_id_is_a_validation_failure_on_removal(
    client, database, signed_in
):
    response = remove_manager(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "managerId")


def test_other_managers_are_untouched_by_a_removal(
    client, database, owner, melati, current, make_manager, signed_in
):
    other = make_manager(owner, [melati], name="Other")
    before = {
        "record": record_of(database, other.id),
        "assigned": assigned_property_ids(database, other.user_id),
        "invitations": [
            (i.id, i.invalidated_at) for i in invitation_rows(database, other.id)
        ],
    }
    remove_manager(client, signed_in.headers, current.id)
    assert record_of(database, other.id).deleted_at is None
    assert assigned_property_ids(database, other.user_id) == before["assigned"]
    assert [
        (i.id, i.invalidated_at) for i in invitation_rows(database, other.id)
    ] == before["invitations"]
    items = list_managers(client, signed_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(other.id)]


def test_a_removed_manager_can_no_longer_reach_the_properties(
    client, database, melati, signed_in, current, sign_in
):
    manager_in = sign_in(current.user)
    assert client.get(PROPERTIES, headers=manager_in.headers).json()["items"]
    remove_manager(client, signed_in.headers, current.id)
    response = client.get(PROPERTIES, headers=manager_in.headers)
    assert response.status_code == 401


# DELETE: invitation


def test_the_unused_invitation_is_invalidated(client, database, signed_in, current):
    remove_manager(client, signed_in.headers, current.id)
    (row,) = invitation_rows(database, current.id)
    assert_just_now(row.invalidated_at)
    assert row.used_at is None


def test_the_expired_invitation_is_invalidated(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], expired=True)
    remove_manager(client, signed_in.headers, stored.id)
    (row,) = invitation_rows(database, stored.id)
    assert_just_now(row.invalidated_at)


def test_a_used_invitation_is_left_as_it_was_on_removal(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], used=True)
    remove_manager(client, signed_in.headers, stored.id)
    (row,) = invitation_rows(database, stored.id)
    assert row.used_at is not None
    assert row.invalidated_at is None


def test_an_invitation_replaced_earlier_keeps_its_invalidation_time(
    client, database, signed_in, current
):
    from app.models import Invitation

    first_link = client.post(
        f"/managers/{current.id}/invitation", headers=signed_in.headers
    )
    assert first_link.status_code == 201
    old, _ = invitation_rows(database, current.id)
    replaced_at = old.invalidated_at
    remove_manager(client, signed_in.headers, current.id)
    rows = invitation_rows(database, current.id)
    assert rows[0].invalidated_at == replaced_at
    assert_just_now(rows[1].invalidated_at)
    assert len(fetch_all(database, Invitation)) == 2


def test_the_invitations_of_other_managers_stay_valid(
    client, database, owner, melati, current, make_manager, signed_in
):
    other = make_manager(owner, [melati], name="Other")
    remove_manager(client, signed_in.headers, current.id)
    (row,) = invitation_rows(database, other.id)
    assert row.invalidated_at is None
    detail = get_manager(client, signed_in.headers, other.id).json()["invitation"]
    assert detail["url"] == link_for(other.token)


# DELETE: the account loses access when no other owner keeps it


def test_removing_the_only_record_ends_every_session_of_the_account(
    client, database, signed_in, active, sign_in
):
    sessions = [sign_in(active.user, name) for name in ("Phone", "Tablet", "Laptop")]
    for session in sessions:
        assert client.get(ME_URL, headers=session.headers).status_code == 200
    assert remove_manager(client, signed_in.headers, active.id).status_code == 204
    rows = session_rows(database, active.user_id)
    assert len(rows) == 3
    for row in rows:
        assert_just_now(row.revoked_at)


def test_the_access_tokens_stop_working_at_once(
    client, database, signed_in, active, sign_in
):
    sessions = [sign_in(active.user, name) for name in ("Phone", "Tablet")]
    remove_manager(client, signed_in.headers, active.id)
    for session in sessions:
        assert_error(
            client.get(ME_URL, headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
        )
        assert_error(
            client.get(PROPERTIES, headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
        )


def test_the_refresh_tokens_stop_working(client, database, signed_in, active, sign_in):
    sessions = [sign_in(active.user, name) for name in ("Phone", "Tablet")]
    remove_manager(client, signed_in.headers, active.id)
    for session in sessions:
        response = refresh_with(client, session.tokens.refresh_token)
        assert_error(response, 401, "REFRESH_TOKEN_INVALID")


def test_the_account_can_no_longer_log_in(client, database, signed_in, active):
    assert login(client, "active@example.com").status_code == 200
    remove_manager(client, signed_in.headers, active.id)
    assert_error(login(client, "active@example.com"), 401, "INVALID_CREDENTIALS")


def test_the_login_failure_matches_an_unknown_email(
    client, database, signed_in, active
):
    remove_manager(client, signed_in.headers, active.id)
    removed = login(client, "active@example.com")
    unknown = login(client, "nobody@example.com")
    assert removed.status_code == unknown.status_code == 401
    assert removed.json() == unknown.json()


def test_a_session_ended_earlier_keeps_its_revocation_time(
    client, database, signed_in, active, sign_in, read_session
):
    ended = sign_in(active.user, "Old phone")
    live = sign_in(active.user, "Tablet")
    assert client.post("/auth/logout", headers=ended.headers).status_code == 204
    first_revoked_at = read_session(ended.session_id).revoked_at
    remove_manager(client, signed_in.headers, active.id)
    assert read_session(ended.session_id).revoked_at == first_revoked_at
    assert_just_now(read_session(live.session_id).revoked_at)


def test_the_sessions_of_other_users_are_untouched(
    client,
    database,
    owner,
    melati,
    signed_in,
    active,
    sign_in,
    make_manager,
    read_session,
):
    sign_in(active.user)
    bystander = make_manager(
        owner, [melati], name="Bystander", activated=True, email="by@example.com"
    )
    bystander_in = sign_in(bystander.user)
    remove_manager(client, signed_in.headers, active.id)
    for session in (signed_in, bystander_in):
        assert read_session(session.session_id).revoked_at is None
        assert client.get(ME_URL, headers=session.headers).status_code == 200
    assert refresh_with(client, bystander_in.tokens.refresh_token).status_code == 200


def test_a_deleted_record_of_another_owner_does_not_keep_the_account_alive(
    client, database, other_owner, theirs, signed_in, active, sign_in, make_manager
):
    make_manager(other_owner, [], user=active.user, deleted=True)
    session = sign_in(active.user)
    remove_manager(client, signed_in.headers, active.id)
    assert_error(
        client.get(ME_URL, headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    assert_error(login(client, "active@example.com"), 401, "INVALID_CREDENTIALS")


# DELETE: the account is shared with another owner


@pytest.fixture
def shared(owner, melati, other_owner, theirs, make_manager):
    """One active account working for two owners; returns (this owner's, other's)."""
    mine = make_manager(
        owner,
        [melati],
        name="Shared Name",
        email="shared@example.com",
        password=PASSWORD,
        activated=True,
        used=True,
    )
    others = make_manager(
        other_owner, [theirs], nickname="Theirs", activated=True, user=mine.user
    )
    return mine, others


def test_the_account_of_a_shared_manager_keeps_logging_in(
    client, database, signed_in, shared, sign_in
):
    mine, _ = shared
    session = sign_in(mine.user)
    assert remove_manager(client, signed_in.headers, mine.id).status_code == 204
    assert login(client, "shared@example.com").status_code == 200
    assert client.get(ME_URL, headers=session.headers).status_code == 200
    for row in session_rows(database, mine.user_id):
        assert row.revoked_at is None


def test_the_other_owners_assignments_and_record_survive(
    client, database, other_owner, theirs, melati, signed_in, shared, sign_in
):
    mine, others = shared
    manager_in = sign_in(mine.user)
    remove_manager(client, signed_in.headers, mine.id)
    assert assigned_property_ids(database, mine.user_id) == {theirs.id}
    assert record_of(database, mine.id).deleted_at is not None
    assert record_of(database, others.id).deleted_at is None
    listed = client.get(PROPERTIES, headers=manager_in.headers).json()["items"]
    assert [p["id"] for p in listed] == [str(theirs.id)]
    assert (
        client.get(f"{PROPERTIES}/{theirs.id}", headers=manager_in.headers).status_code
        == 200
    )
    assert_error(
        client.get(f"{PROPERTIES}/{melati.id}", headers=manager_in.headers),
        404,
        "PROPERTY_NOT_FOUND",
    )


def test_the_other_owner_still_manages_the_shared_account(
    client, database, other_owner, signed_in, shared, sign_in
):
    mine, others = shared
    remove_manager(client, signed_in.headers, mine.id)
    their_headers = sign_in(other_owner).headers
    body = get_manager(client, their_headers, others.id).json()
    assert body["accountStatus"] == "active"
    assert body["nickname"] == "Theirs"
    assert [i["id"] for i in list_managers(client, their_headers).json()["items"]] == [
        str(others.id)
    ]


def test_the_other_owner_can_remove_the_last_record_afterwards(
    client, database, other_owner, signed_in, shared, sign_in
):
    mine, others = shared
    their_headers = sign_in(other_owner).headers
    session = sign_in(mine.user)
    remove_manager(client, signed_in.headers, mine.id)
    assert client.get(ME_URL, headers=session.headers).status_code == 200
    assert remove_manager(client, their_headers, others.id).status_code == 204
    assert_error(
        client.get(ME_URL, headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    assert_error(login(client, "shared@example.com"), 401, "INVALID_CREDENTIALS")


# DELETE: history is kept


def test_the_payment_history_with_the_manager_as_actor_is_kept(
    client,
    database,
    owner,
    melati,
    signed_in,
    make_room,
    make_tenant,
    make_rent_bill,
    active,
):
    from rent_bill_support import days_ago

    from app.models import RentBill, RentBillStatusChange

    tenant = make_tenant(make_room(melati, number="A1"))
    make_rent_bill(
        tenant.lease,
        period_start=days_ago(40),
        status="paid",
        method="cash",
        paid_on=days_ago(35),
        changes=[
            ("unpaid", None, None, False, None, datetime.now(UTC)),
            ("paid", "cash", "Paid in person", True, active.user_id, datetime.now(UTC)),
        ],
    )
    sizes = [len(fetch_all(database, m)) for m in (RentBill, RentBillStatusChange)]
    assert remove_manager(client, signed_in.headers, active.id).status_code == 204
    after = [len(fetch_all(database, m)) for m in (RentBill, RentBillStatusChange)]
    assert after == sizes == [1, 2]
    actors = {c.actor_id for c in fetch_all(database, RentBillStatusChange)}
    assert actors == {None, active.user_id}


# DELETE: failures save nothing


def test_a_failure_while_ending_sessions_saves_nothing(
    app, database, owner, active, sign_in, monkeypatch
):
    from app.services import sessions

    sign_in(active.user, "Phone")
    sign_in(active.user, "Tablet")
    headers = sign_in(owner).headers
    before = state(database)
    original = sessions.end_session
    calls = []

    def fail_on_the_second_call(db, session):
        calls.append(session.id)
        if len(calls) == 2:
            raise RuntimeError("storage failure")
        return original(db, session)

    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr(sessions, "end_session", fail_on_the_second_call)
        response = remove_manager(client, headers, active.id)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert len(calls) == 2
    assert state(database) == before
    assert get_manager(client, headers, active.id).status_code == 200


def test_a_manager_can_be_removed_after_a_failed_attempt(
    app, database, owner, active, sign_in, monkeypatch
):
    from app.services import sessions

    sign_in(active.user)
    headers = sign_in(owner).headers

    def fail(db, session):
        raise RuntimeError("storage failure")

    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr(sessions, "end_session", fail)
        assert remove_manager(client, headers, active.id).status_code == 500
    assert remove_manager(client, headers, active.id).status_code == 204


def test_a_manager_added_and_then_removed_can_be_added_again(
    client, database, melati, signed_in
):
    first = create_manager(client, signed_in.headers, melati).json()
    assert remove_manager(client, signed_in.headers, first["id"]).status_code == 204
    second = create_manager(client, signed_in.headers, melati)
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first["id"]
