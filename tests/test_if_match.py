"""Conflicting edits: the `If-Match` header of the five edit operations."""

import threading
from typing import Any

import pytest
from conftest import OpenApiDoc, nullable_inner
from fastapi.testclient import TestClient
from resource_version_support import (
    CONFLICT,
    PUT_OPERATIONS,
    VERSIONED_SCHEMAS,
    assert_error,
    database_state,
    etag,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from user_account_support import account_url

BANK = {
    "bankName": "BCA",
    "accountNumber": "1234567890",
    "accountHolderName": "Budi Santoso",
}
CONTACTS = [
    {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
    {"name": "Agus", "relationship": "Kakak", "phone": "081234567891"},
]
# Values that are not a quoted whole number, with the current version being 1.
MALFORMED = [
    pytest.param("1", id="unquoted"),
    pytest.param("3", id="unquoted_other_number"),
    pytest.param('W/"1"', id="weak"),
    pytest.param('"abc"', id="word"),
    pytest.param('"-1"', id="negative"),
    pytest.param('""', id="empty_quotes"),
    pytest.param('"1.0"', id="decimal"),
    pytest.param('"3.0"', id="other_decimal"),
    pytest.param("*", id="star"),
    pytest.param('"1", "2"', id="two_values"),
    pytest.param('"1","1"', id="two_equal_values"),
]


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


def edit_property(client, headers, prop, if_match=None, **overrides):
    body = {"name": "Kos Melati", "address": "Jl. Melati 5", **overrides}
    if if_match is not None:
        headers = {**headers, "If-Match": if_match}
    return client.put(f"/properties/{prop.id}", json=body, headers=headers)


def edit_room(client, headers, room, if_match=None, **overrides):
    body = {"number": "A1", "baseRate": 1000000, **overrides}
    if if_match is not None:
        headers = {**headers, "If-Match": if_match}
    return client.put(f"/rooms/{room.id}", json=body, headers=headers)


# Declared in the OpenAPI document


def operation(openapi: OpenApiDoc, method: str, path: str) -> dict[str, Any]:
    return openapi.operation(method, path)


def if_match_parameters(op: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in op.get("parameters", []) if p["name"].lower() == "if-match"]


@pytest.mark.parametrize(("method", "path"), PUT_OPERATIONS)
def test_an_edit_operation_declares_if_match_as_an_optional_header(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    (parameter,) = if_match_parameters(operation(openapi, method, path))
    assert parameter["name"] == "If-Match"
    assert parameter["in"] == "header"
    assert parameter.get("required", False) is False
    schema = parameter["schema"]
    inner = nullable_inner(schema) if "anyOf" in schema else schema
    assert inner["type"] == "string"


def test_no_other_operation_declares_if_match(openapi: OpenApiDoc) -> None:
    edits = {(m.lower(), p) for m, p in PUT_OPERATIONS}
    others = [
        f"{method.upper()} {path}"
        for path, item in openapi.document["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict)
        and (method, path) not in edits
        and if_match_parameters(op)
    ]
    assert others == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("put", "/me/notification-settings"),
        ("put", "/me/push-token"),
        ("put", "/subscription/scheduled-downgrade"),
        ("put", "/complaints/{complaintId}/classification"),
        ("put", "/complaints/{complaintId}/photo"),
        ("put", "/rent-bills/{rentBillId}/receipt"),
    ],
)
def test_the_other_edit_operations_take_no_if_match(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert if_match_parameters(operation(openapi, method, path)) == []


@pytest.mark.parametrize(("method", "path"), PUT_OPERATIONS)
def test_an_edit_operation_lists_the_version_conflict_code(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    op = operation(openapi, method, path)
    assert CONFLICT in op["x-error-codes"]
    response = op["responses"]["409"]
    schema = response["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/ErrorBody"


def test_only_the_edit_operations_list_the_version_conflict_code(
    openapi: OpenApiDoc,
) -> None:
    edits = {(m.lower(), p) for m, p in PUT_OPERATIONS}
    listing = {
        (method, path)
        for path, item in openapi.document["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict) and CONFLICT in op.get("x-error-codes", [])
    }
    assert listing == edits


def test_the_catalog_has_the_version_conflict_for_the_edit_operations_only():
    from app.error_catalog import ERROR_STATUS, ROUTE_ERRORS

    assert ERROR_STATUS[CONFLICT] == 409
    assert {key for key, codes in ROUTE_ERRORS.items() if CONFLICT in codes} == set(
        PUT_OPERATIONS
    )


@pytest.mark.parametrize("name", VERSIONED_SCHEMAS)
def test_a_resource_schema_requires_an_integer_version(
    openapi: OpenApiDoc, name: str
) -> None:
    schema = openapi.component(name)
    assert schema["properties"]["version"]["type"] == "integer"
    assert "version" in schema["required"]


@pytest.mark.parametrize(
    "name",
    ["PropertyInput", "RoomInput", "TenantInput", "ManagerInput", "UserAccountInput"],
)
def test_an_edit_body_does_not_carry_the_version(
    openapi: OpenApiDoc, name: str
) -> None:
    assert "version" not in openapi.component(name)["properties"]


# Matching, stale and missing headers


def test_a_matching_header_applies_the_edit(client, database, target):
    response = target.put(client, target.changed_body, if_match=etag(1))
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert target.version() == 2


def test_a_matching_header_follows_each_new_version(client, database, target):
    for version in (1, 2, 3):
        response = target.put(client, target.changed_body, if_match=etag(version))
        assert response.status_code == 200, response.text
        assert response.json()["version"] == version + 1


def test_the_header_name_is_case_insensitive(client, database, target):
    headers = {**target.headers, "if-match": etag(7)}
    response = target.put(client, target.changed_body, headers=headers)
    assert_error(response, 409, CONFLICT)


def test_a_matching_header_applies_an_edit_with_the_current_values(
    client, database, target
):
    response = target.put(client, target.body, if_match=etag(1))
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2


@pytest.mark.parametrize("sent", [0, 2, 5, 1000])
def test_a_version_that_is_not_current_conflicts_and_saves_nothing(
    client, database, target, sent
):
    before = database_state(database)
    response = target.put(client, target.changed_body, if_match=etag(sent))
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before
    assert target.version() == 1


def test_a_stale_version_conflicts_after_another_edit(client, database, target):
    assert target.put(client, target.changed_body).status_code == 200
    before = database_state(database)
    stored = target.stored_values()
    response = target.put(client, target.body, if_match=etag(1))
    assert_error(response, 409, CONFLICT)
    assert target.version() == 2
    assert target.stored_values() == stored
    assert database_state(database) == before


def test_a_conflict_leaves_the_record_readable_with_its_version(
    client, database, target
):
    target.put(client, target.changed_body, if_match=etag(9))
    assert target.read(client)["version"] == 1
    assert target.listed(client)["version"] == 1


def test_a_request_without_the_header_is_applied_whatever_the_version(
    client, database, target
):
    assert target.put(client, target.changed_body).status_code == 200
    assert target.put(client, target.body).status_code == 200
    response = target.put(client, target.changed_body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 4


def test_the_version_in_a_response_can_be_sent_back_as_the_header(
    client, database, target
):
    first = target.put(client, target.changed_body)
    version = first.json()["version"]
    second = target.put(client, target.body, if_match=etag(version))
    assert second.status_code == 200, second.text
    assert second.json()["version"] == version + 1


def test_the_version_read_from_the_detail_can_be_sent_back_as_the_header(
    client, database, target
):
    version = target.read(client)["version"]
    response = target.put(client, target.changed_body, if_match=etag(version))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("value", MALFORMED)
def test_a_header_that_is_not_a_quoted_whole_number_is_a_validation_failure(
    client, database, target, value
):
    before = database_state(database)
    response = target.put(client, target.changed_body, if_match=value)
    assert_error(response, 422, "VALIDATION_FAILED", "ifMatch")
    assert database_state(database) == before
    assert target.version() == 1


def test_a_conflicting_email_change_saves_no_pending_change(
    client, database, admin_in, make_user, mailbox
):
    from app.models import EmailChangeRequest

    user = make_user(name="Budi Santoso", email="budi@example.com")
    body = {"name": "Budi Santoso", "email": "baru@example.com", "status": "active"}
    response = client.put(
        account_url(user.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(4)},
    )
    assert_error(response, 409, CONFLICT)
    with Session(database) as db:
        assert db.scalars(select(EmailChangeRequest)).all() == []
    assert mailbox.is_empty
    detail = client.get(account_url(user.id), headers=admin_in.headers).json()
    assert detail["pendingEmail"] is None
    assert detail["version"] == 1


def test_a_matching_email_change_is_requested_and_raises_the_version(
    client, database, admin_in, make_user, mailbox
):
    user = make_user(name="Budi Santoso", email="budi@example.com")
    body = {"name": "Budi Santoso", "email": "baru@example.com", "status": "active"}
    response = client.put(
        account_url(user.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(1)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == "baru@example.com"
    assert response.json()["version"] == 2
    assert not mailbox.is_empty


def test_a_conflicting_deactivation_keeps_the_sessions_of_the_account(
    client, database, admin_in, make_user, sign_in
):
    user = make_user(name="Budi Santoso", email="budi@example.com")
    session = sign_in(user)
    body = {"name": "Budi Santoso", "email": "budi@example.com", "status": "inactive"}
    response = client.put(
        account_url(user.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(3)},
    )
    assert_error(response, 409, CONFLICT)
    assert client.get("/me", headers=session.headers).status_code == 200
    detail = client.get(account_url(user.id), headers=admin_in.headers).json()
    assert detail["status"] == "active"


def test_a_conflicting_tenant_edit_keeps_the_invitation(client, database, target):
    if target.kind != "tenant":
        pytest.skip("only a tenant has an invitation")
    before = database_state(database)
    response = target.put(client, target.changed_body, if_match=etag(2))
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before
    assert target.read(client)["invitation"] is not None


def test_a_conflicting_manager_edit_keeps_the_assignments_and_invitation(
    client, database, target
):
    if target.kind != "manager":
        pytest.skip("only a manager has assignments and an invitation")
    before = database_state(database)
    response = target.put(client, target.changed_body, if_match=etag(2))
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before
    assert target.read(client)["invitation"] is not None


# Order of the checks


def test_a_wrong_role_is_forbidden_before_the_version_is_looked_at(
    client, database, target
):
    before = database_state(database)
    response = target.put(
        client,
        target.changed_body,
        if_match=etag(9),
        headers=target.forbidden_headers,
    )
    assert_error(response, 403, "FORBIDDEN")
    assert database_state(database) == before


def test_an_unknown_record_is_not_found_before_the_version_is_looked_at(
    client, database, target
):
    response = client.put(
        target.missing_url,
        json=target.changed_body,
        headers={**target.headers, "If-Match": etag(9)},
    )
    assert_error(response, 404, target.not_found_code)


def test_a_view_only_property_refuses_the_edit_before_the_version(
    client, database, owner, owner_in, make_property
):
    prop = make_property(owner, name="Kos Tua", view_only=True)
    response = edit_property(client, owner_in.headers, prop, etag(9))
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_a_room_of_a_view_only_property_refuses_the_edit_before_the_version(
    client, database, owner_in, owner, make_property, make_room
):
    prop = make_property(owner, name="Kos Tua", view_only=True)
    room = make_room(prop, number="A1")
    response = edit_room(client, owner_in.headers, room, etag(9))
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_a_view_only_room_refuses_the_edit_before_the_version(
    client, database, owner_in, prop, make_room
):
    room = make_room(prop, number="A1", view_only=True)
    response = edit_room(client, owner_in.headers, room, etag(9))
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_a_tenant_of_a_view_only_property_refuses_the_edit_before_the_version(
    client, database, owner, owner_in, make_property, make_room, make_tenant
):
    prop = make_property(owner, name="Kos Tua", view_only=True)
    stored = make_tenant(make_room(prop, number="A1"))
    response = client.put(
        f"/tenants/{stored.id}",
        json={"name": "Budi Tenant", "phone": "081234567890"},
        headers={**owner_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_a_tenant_of_a_view_only_room_refuses_the_edit_before_the_version(
    client, database, owner_in, prop, make_room, make_tenant
):
    stored = make_tenant(make_room(prop, number="A1", view_only=True))
    response = client.put(
        f"/tenants/{stored.id}",
        json={"name": "Budi Tenant", "phone": "081234567890"},
        headers={**owner_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_a_deleted_account_is_refused_before_the_version(
    client, database, admin_in, make_user
):
    deleted = make_user(
        name="Sari Dewi", email="sari@example.com", status="deleted", deleted=True
    )
    body = {"name": "Sari Dewi", "email": "sari@example.com", "status": "active"}
    response = client.put(
        account_url(deleted.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_stale_version_conflicts_before_a_taken_property_name(
    client, database, owner, owner_in, prop, make_property
):
    make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")
    before = database_state(database)
    response = edit_property(
        client, owner_in.headers, prop, etag(9), name="kos anggrek"
    )
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_the_taken_property_name_answer(
    client, database, owner, owner_in, prop, make_property
):
    make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")
    response = edit_property(
        client, owner_in.headers, prop, etag(1), name="kos anggrek"
    )
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")


def test_no_header_lets_the_taken_property_name_answer(
    client, database, owner, owner_in, prop, make_property
):
    make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")
    response = edit_property(client, owner_in.headers, prop, name="kos anggrek")
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")


def test_a_stale_version_conflicts_before_re_authentication_is_asked_for(
    client, database, owner_in, prop
):
    before = database_state(database)
    response = edit_property(client, owner_in.headers, prop, etag(9), bankAccount=BANK)
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_re_authentication_be_asked_for(
    client, database, owner_in, prop
):
    response = edit_property(client, owner_in.headers, prop, etag(1), bankAccount=BANK)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")


def test_a_stale_version_conflicts_before_a_taken_room_number(
    client, database, owner_in, prop, make_room
):
    make_room(prop, number="A1")
    second = make_room(prop, number="A2")
    before = database_state(database)
    response = edit_room(client, owner_in.headers, second, etag(9), number="a1")
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_the_taken_room_number_answer(
    client, database, owner_in, prop, make_room
):
    make_room(prop, number="A1")
    second = make_room(prop, number="A2")
    response = edit_room(client, owner_in.headers, second, etag(1), number="a1")
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")


def test_a_stale_version_conflicts_before_the_name_of_an_active_manager(
    client, database, owner, owner_in, prop, make_manager
):
    stored = make_manager(
        owner, [prop], name="Mira Manager", phone="081234567890", activated=True
    )
    body = {
        "name": "Mira Baru",
        "phone": "081234567890",
        "propertyIds": [str(prop.id)],
    }
    before = database_state(database)
    response = client.put(
        f"/managers/{stored.id}",
        json=body,
        headers={**owner_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_the_name_of_an_active_manager_answer(
    client, database, owner, owner_in, prop, make_manager
):
    stored = make_manager(
        owner, [prop], name="Mira Manager", phone="081234567890", activated=True
    )
    body = {
        "name": "Mira Baru",
        "phone": "081234567890",
        "propertyIds": [str(prop.id)],
    }
    response = client.put(
        f"/managers/{stored.id}",
        json=body,
        headers={**owner_in.headers, "If-Match": etag(1)},
    )
    assert_error(response, 422, "MANAGER_NAME_NOT_EDITABLE", "name")


def active_tenant(make_room, make_verified_tenant, prop):
    room = make_room(prop, number="A1")
    contacts = [(c["name"], c["relationship"], c["phone"]) for c in CONTACTS]
    return make_verified_tenant(room, name="Budi Tenant", contacts=contacts)


def test_a_stale_version_conflicts_before_the_name_of_an_active_tenant(
    client, database, owner_in, prop, make_room, make_verified_tenant
):
    stored = active_tenant(make_room, make_verified_tenant, prop)
    body = {"name": "Budi Baru", "phone": "081234567890", "emergencyContacts": CONTACTS}
    before = database_state(database)
    response = client.put(
        f"/tenants/{stored.id}",
        json=body,
        headers={**owner_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_the_name_of_an_active_tenant_answer(
    client, database, owner_in, prop, make_room, make_verified_tenant
):
    stored = active_tenant(make_room, make_verified_tenant, prop)
    body = {"name": "Budi Baru", "phone": "081234567890", "emergencyContacts": CONTACTS}
    response = client.put(
        f"/tenants/{stored.id}",
        json=body,
        headers={**owner_in.headers, "If-Match": etag(1)},
    )
    assert_error(response, 422, "TENANT_NAME_NOT_EDITABLE", "name")


def test_a_stale_version_conflicts_before_a_taken_email(
    client, database, admin_in, make_user
):
    user = make_user(name="Budi Santoso", email="budi@example.com")
    make_user(name="Sari Dewi", email="sari@example.com")
    body = {"name": "Budi Santoso", "email": "sari@example.com", "status": "active"}
    before = database_state(database)
    response = client.put(
        account_url(user.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_the_taken_email_answer(
    client, database, admin_in, make_user
):
    user = make_user(name="Budi Santoso", email="budi@example.com")
    make_user(name="Sari Dewi", email="sari@example.com")
    body = {"name": "Budi Santoso", "email": "sari@example.com", "status": "active"}
    response = client.put(
        account_url(user.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(1)},
    )
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_a_stale_version_conflicts_before_an_admin_deactivates_themselves(
    client, database, admin, admin_in
):
    body = {"name": admin.name, "email": admin.email, "status": "inactive"}
    before = database_state(database)
    response = client.put(
        account_url(admin.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(9)},
    )
    assert_error(response, 409, CONFLICT)
    assert database_state(database) == before


def test_a_matching_version_lets_an_admin_be_refused_deactivating_themselves(
    client, database, admin, admin_in
):
    body = {"name": admin.name, "email": admin.email, "status": "inactive"}
    response = client.put(
        account_url(admin.id),
        json=body,
        headers={**admin_in.headers, "If-Match": etag(1)},
    )
    assert_error(response, 409, "CANNOT_MODIFY_OWN_ACCOUNT")


# Two edits with the same version


def race(app, url: str, headers: dict, version: int, names: list[str]) -> list:
    """Send one edit per name at the same moment, all carrying the same version."""
    barrier = threading.Barrier(len(names))
    outcomes: list[tuple[str, Any]] = []

    def worker(name: str) -> None:
        client = TestClient(app)
        barrier.wait()
        response = client.put(
            url,
            json={"name": name, "address": "Jl. Melati 5"},
            headers={**headers, "If-Match": etag(version)},
        )
        outcomes.append((name, response))

    threads = [threading.Thread(target=worker, args=(n,)) for n in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_two_edits_carrying_the_same_version_never_both_succeed(
    app, database, owner, owner_in, prop
):
    from app.models import Property

    rounds = 6
    wins = 0
    for number in range(rounds):
        with Session(database) as db:
            version = db.get(Property, prop.id).version
        outcomes = race(
            app,
            f"/properties/{prop.id}",
            owner_in.headers,
            version,
            [f"Kos A{number}", f"Kos B{number}"],
        )
        assert len(outcomes) == 2
        winners = [(n, r) for n, r in outcomes if r.status_code == 200]
        losers = [(n, r) for n, r in outcomes if r.status_code != 200]
        assert len(winners) <= 1, [r.text for _, r in outcomes]
        for _, response in losers:
            assert_error(response, 409, CONFLICT)
        wins += len(winners)
        with Session(database) as db:
            row = db.get(Property, prop.id)
            assert row.version == version + len(winners)
            if winners:
                assert row.name == winners[0][0]
                assert winners[0][1].json()["version"] == version + 1
    assert wins >= 1
    with Session(database) as db:
        assert db.get(Property, prop.id).version == 1 + wins
