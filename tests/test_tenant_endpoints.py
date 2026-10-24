"""Adding tenants, listing them by property and reading one tenant."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

PROPERTIES = "/properties"
LEASE = {
    "startDate": "2099-01-10",
    "endDate": "2099-12-31",
    "billingCycle": "monthly",
    "rent": 1200000,
    "gracePeriodDays": 3,
}
CONTACTS = [
    {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
    {"name": "Agus", "relationship": "Kakak", "phone": "628571234567"},
]
TENANT_FIELDS = {
    "id",
    "name",
    "phone",
    "email",
    "occupation",
    "accountStatus",
    "room",
    "lease",
    "emergencyContacts",
    "invitation",
}
LEASE_FIELDS = {
    "startDate",
    "endDate",
    "rent",
    "billingCycle",
    "gracePeriodDays",
    "nextBillDate",
}
INVITATION_FIELDS = {"url", "createdAt", "expiresAt", "expired"}
SUMMARY_FIELDS = {
    "id",
    "name",
    "room",
    "accountStatus",
    "billingCycle",
    "leaseEndDate",
    "invitationExpiresAt",
}


def tenants_url(property_id) -> str:
    return f"{PROPERTIES}/{property_id}/tenants"


def tenant_url(tenant_id) -> str:
    return f"/tenants/{tenant_id}"


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


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def new_body(room, **overrides) -> dict:
    return {
        "name": "Budi Santoso",
        "phone": "081234567890",
        "occupation": "Mahasiswa",
        "emergencyContacts": CONTACTS,
        "lease": LEASE,
        "roomId": str(room.id),
        **overrides,
    }


def lease_body(**overrides) -> dict:
    return {**LEASE, **overrides}


def fetch_all(database, model) -> list:
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(model)))


def stored_tenant_users(database) -> list:
    from app.models import UserAccount

    return [u for u in fetch_all(database, UserAccount) if u.role == role("tenant")]


def counts(database) -> dict[str, int]:
    from app.models import EmergencyContact, Invitation, Lease, Tenant

    result = {"users": len(stored_tenant_users(database))}
    for model in (Tenant, EmergencyContact, Lease, Invitation):
        result[model.__tablename__] = len(fetch_all(database, model))
    return result


def assert_nothing_saved(database) -> None:
    assert counts(database) == {
        "users": 0,
        "tenants": 0,
        "emergency_contacts": 0,
        "leases": 0,
        "invitations": 0,
    }


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


def invitation_base() -> str:
    from app.config import get_settings

    return get_settings().invitation_base_url.rstrip("/")


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def manager(make_user):
    return make_user(name="Mira Manager", role=role("manager"))


@pytest.fixture
def manager_in(manager, sign_in):
    return sign_in(manager)


@pytest.fixture
def existing(owner, make_property):
    return make_property(owner, name="Kos Melati")


@pytest.fixture
def room(existing, make_room):
    return make_room(existing, number="A1", base_rate=1750000)


def create(client, headers, property_id, room, **overrides):
    return client.post(
        tenants_url(property_id), json=new_body(room, **overrides), headers=headers
    )


# Authentication and roles

REQUESTS = [
    pytest.param(
        "post",
        tenants_url(uuid4()),
        {"name": "Budi", "phone": "081234567890", "roomId": str(uuid4())},
        id="create",
    ),
    pytest.param("get", tenants_url(uuid4()), None, id="list"),
    pytest.param("get", tenant_url(uuid4()), None, id="get"),
    pytest.param(
        "put",
        tenant_url(uuid4()),
        {"name": "Budi", "phone": "081234567890"},
        id="edit",
    ),
    pytest.param(
        "post", tenant_url(uuid4()) + "/invitation", None, id="regenerate_invitation"
    ),
    pytest.param("delete", tenant_url(uuid4()), None, id="delete"),
]


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_without_a_token_is_rejected(client, database, method, url, body):
    response = client.request(method, url, json=body)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_with_a_garbage_token_is_rejected(
    client, database, method, url, body
):
    response = client.request(
        method, url, json=body, headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_from_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, method, url, body
):
    session = sign_in(make_user(email_verified=False))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["tenant", "admin"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_tenants_and_admins_are_forbidden_everywhere(
    client, database, make_user, sign_in, name, method, url, body
):
    session = sign_in(make_user(role=role(name)))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_forbidden_account_adds_nothing(
    client, database, make_user, sign_in, existing, room
):
    headers = sign_in(make_user(role=role("tenant"))).headers
    before = counts(database)
    create(client, headers, existing.id, room)
    assert counts(database) == before


def test_a_forbidden_tenant_account_sees_no_tenant_details(
    client, database, make_user, sign_in, room, make_tenant
):
    stored = make_tenant(room)
    headers = sign_in(make_user(role=role("tenant"))).headers
    response = client.get(tenant_url(stored.id), headers=headers)
    assert_error(response, 403, "FORBIDDEN")


# POST: success


def test_adding_a_tenant_answers_with_the_stored_tenant(
    client, database, existing, signed_in, room
):
    response = create(client, signed_in.headers, existing.id, room)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == TENANT_FIELDS
    (user,) = stored_tenant_users(database)
    assert body["id"] == str(user.id)
    assert body["name"] == "Budi Santoso"
    assert body["phone"] == "081234567890"
    assert body["email"] is None
    assert body["occupation"] == "Mahasiswa"
    assert body["accountStatus"] == "notActivated"
    assert body["room"] == {"id": str(room.id), "number": "A1"}


def test_the_response_lease_carries_the_submitted_terms_and_next_bill_date(
    client, database, existing, signed_in, room
):
    body = create(client, signed_in.headers, existing.id, room).json()
    assert set(body["lease"]) == LEASE_FIELDS
    assert body["lease"] == {
        "startDate": "2099-01-10",
        "endDate": "2099-12-31",
        "rent": 1200000,
        "billingCycle": "monthly",
        "gracePeriodDays": 3,
        "nextBillDate": "2099-01-10",
    }


def test_the_response_emergency_contacts_are_in_submitted_order_with_normalized_phones(
    client, database, existing, signed_in, room
):
    body = create(client, signed_in.headers, existing.id, room).json()
    assert body["emergencyContacts"] == [
        {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
        {"name": "Agus", "relationship": "Kakak", "phone": "08571234567"},
    ]


def test_the_account_is_stored_as_an_unverified_tenant_without_email_or_password(
    client, database, existing, signed_in, room
):
    create(client, signed_in.headers, existing.id, room)
    (user,) = stored_tenant_users(database)
    assert user.name == "Budi Santoso"
    assert user.email is None
    assert user.password_hash is None
    assert user.role == role("tenant")
    assert user.email_verified is False


def test_the_tenant_row_is_stored_not_activated(
    client, database, existing, signed_in, room
):
    from app.models import Tenant

    before = datetime.now(UTC)
    create(client, signed_in.headers, existing.id, room)
    (user,) = stored_tenant_users(database)
    (row,) = fetch_all(database, Tenant)
    assert row.user_id == user.id
    assert row.phone == "081234567890"
    assert row.occupation == "Mahasiswa"
    assert row.activated_at is None
    assert row.deleted_at is None
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_the_emergency_contacts_are_stored_in_order_with_normalized_phones(
    client, database, existing, signed_in, room
):
    from app.models import EmergencyContact

    create(client, signed_in.headers, existing.id, room)
    (user,) = stored_tenant_users(database)
    rows = sorted(fetch_all(database, EmergencyContact), key=lambda r: r.position)
    assert [r.tenant_id for r in rows] == [user.id, user.id]
    assert [r.position for r in rows] == [0, 1]
    assert [(r.name, r.relationship, r.phone) for r in rows] == [
        ("Siti", "Ibu", "081234567890"),
        ("Agus", "Kakak", "08571234567"),
    ]


def test_an_active_lease_is_stored_for_the_room(
    client, database, existing, signed_in, room
):
    from app.models import Lease

    create(client, signed_in.headers, existing.id, room)
    (user,) = stored_tenant_users(database)
    (lease,) = fetch_all(database, Lease)
    assert lease.tenant_id == user.id
    assert lease.room_id == room.id
    assert lease.start_date == date(2099, 1, 10)
    assert lease.end_date == date(2099, 12, 31)
    assert lease.billing_cycle == "monthly"
    assert lease.rent == 1200000
    assert lease.grace_period_days == 3
    assert lease.ended_at is None


def test_an_invitation_valid_for_seven_days_is_stored(
    client, database, existing, signed_in, room
):
    from app.models import Invitation

    create(client, signed_in.headers, existing.id, room)
    (user,) = stored_tenant_users(database)
    (invitation,) = fetch_all(database, Invitation)
    assert invitation.tenant_id == user.id
    assert invitation.expires_at - invitation.created_at == timedelta(days=7)
    assert invitation.used_at is None
    assert invitation.invalidated_at is None


def test_the_response_invitation_is_a_fresh_link(
    client, database, existing, signed_in, room
):
    from app.models import Invitation

    body = create(client, signed_in.headers, existing.id, room).json()
    (stored,) = fetch_all(database, Invitation)
    invitation = body["invitation"]
    assert set(invitation) == INVITATION_FIELDS
    assert invitation["expired"] is False
    assert parse_time(invitation["createdAt"]) == stored.created_at
    assert parse_time(invitation["expiresAt"]) == stored.expires_at
    assert parse_time(invitation["expiresAt"]) - parse_time(
        invitation["createdAt"]
    ) == timedelta(days=7)


def test_the_invitation_link_carries_the_raw_token_that_hashes_to_the_stored_hash(
    client, database, existing, signed_in, room
):
    import hashlib

    from app.models import Invitation

    body = create(client, signed_in.headers, existing.id, room).json()
    (stored,) = fetch_all(database, Invitation)
    prefix = f"{invitation_base()}/invitations/"
    url = body["invitation"]["url"]
    assert url.startswith(prefix)
    token = url.removeprefix(prefix)
    assert token
    assert hashlib.sha256(token.encode()).hexdigest() == stored.token_hash
    assert token not in stored.token_encrypted


def test_the_invitation_link_uses_the_configured_base_url(
    client, database, existing, signed_in, room, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setenv("INVITATION_BASE_URL", "https://example.test/")
    get_settings.cache_clear()
    try:
        body = create(client, signed_in.headers, existing.id, room).json()
    finally:
        get_settings.cache_clear()
    assert body["invitation"]["url"].startswith("https://example.test/invitations/")
    assert "//invitations" not in body["invitation"]["url"]


def test_the_added_tenant_can_be_read_back_unchanged(
    client, database, existing, signed_in, room
):
    created = create(client, signed_in.headers, existing.id, room).json()
    response = client.get(tenant_url(created["id"]), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == created


def test_the_added_tenant_appears_in_the_property_list(
    client, database, existing, signed_in, room
):
    created = create(client, signed_in.headers, existing.id, room).json()
    items = client.get(tenants_url(existing.id), headers=signed_in.headers).json()
    assert [i["id"] for i in items["items"]] == [created["id"]]


def test_a_tenant_with_only_the_required_fields_gets_the_defaults(
    client, database, existing, signed_in, room
):
    response = client.post(
        tenants_url(existing.id),
        json={"name": "Budi", "phone": "081234567890", "roomId": str(room.id)},
        headers=signed_in.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["occupation"] is None
    assert body["emergencyContacts"] == []
    assert body["lease"] == {
        "startDate": None,
        "endDate": None,
        "rent": 1750000,
        "billingCycle": "monthly",
        "gracePeriodDays": 0,
        "nextBillDate": None,
    }
    assert body["invitation"]["url"]


def test_adding_a_tenant_leaves_other_rooms_untouched(
    client, database, existing, signed_in, room, make_room
):
    from app.models import Lease

    other = make_room(existing, number="A2")
    create(client, signed_in.headers, existing.id, room)
    (lease,) = fetch_all(database, Lease)
    assert lease.room_id == room.id
    assert lease.room_id != other.id


def test_two_tenants_can_be_added_to_different_rooms(
    client, database, existing, signed_in, room, make_room
):
    other = make_room(existing, number="A2")
    assert create(client, signed_in.headers, existing.id, room).status_code == 201
    response = create(client, signed_in.headers, existing.id, other, name="Dewi")
    assert response.status_code == 201
    assert counts(database)["users"] == 2
    assert counts(database)["leases"] == 2
    assert counts(database)["invitations"] == 2


def test_the_same_phone_may_be_used_for_two_tenants(
    client, database, existing, signed_in, room, make_room
):
    other = make_room(existing, number="A2")
    create(client, signed_in.headers, existing.id, room)
    assert create(client, signed_in.headers, existing.id, other).status_code == 201


# POST: property access


def test_an_unknown_property_is_not_found_and_nothing_is_saved(
    client, database, signed_in, room
):
    response = create(client, signed_in.headers, uuid4(), room)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert_nothing_saved(database)


def test_another_owners_property_is_not_found_and_nothing_is_saved(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_property(make_user(), name="Theirs")
    theirs_room = make_room(theirs)
    response = create(client, signed_in.headers, theirs.id, theirs_room)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property, make_room
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = create(client, signed_in.headers, gone.id, make_room(gone))
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_malformed_property_id_is_a_validation_failure(
    client, database, signed_in, room
):
    response = create(client, signed_in.headers, "not-a-uuid", room)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


def test_a_manager_adds_a_tenant_to_an_assigned_property(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    response = create(client, manager_in.headers, existing.id, room)
    assert response.status_code == 201, response.text
    assert counts(database)["leases"] == 1


def test_a_manager_cannot_add_a_tenant_to_an_unassigned_property(
    client, database, manager_in, existing, room
):
    response = create(client, manager_in.headers, existing.id, room)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_manager_loses_the_right_to_add_tenants_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, make_room, assign_manager
):
    assign_manager(manager, existing)
    assert create(client, manager_in.headers, existing.id, room).status_code == 201
    unassign(database, manager, existing)
    other = make_room(existing, number="A2")
    response = create(client, manager_in.headers, existing.id, other)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert counts(database)["leases"] == 1


# POST: view-only property and room


def test_a_view_only_property_refuses_new_tenants(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    response = create(client, signed_in.headers, frozen.id, make_room(frozen))
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert_nothing_saved(database)


def test_a_view_only_property_refuses_new_tenants_from_a_manager(
    client,
    database,
    owner,
    manager,
    manager_in,
    make_property,
    make_room,
    assign_manager,
):
    frozen = make_property(owner, view_only=True)
    assign_manager(manager, frozen)
    response = create(client, manager_in.headers, frozen.id, make_room(frozen))
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_not_found_is_reported_before_view_only(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_property(make_user(), view_only=True)
    response = create(client, signed_in.headers, theirs.id, make_room(theirs))
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_view_only_property_is_reported_before_an_unknown_room(
    client, database, owner, signed_in, make_property, room
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    response = create(client, signed_in.headers, frozen.id, room)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_property_is_reported_before_field_rules(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    response = create(
        client, signed_in.headers, frozen.id, make_room(frozen), name="   "
    )
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_an_unknown_room_is_not_found_and_nothing_is_saved(
    client, database, existing, signed_in, room
):
    response = client.post(
        tenants_url(existing.id),
        json={**new_body(room), "roomId": str(uuid4())},
        headers=signed_in.headers,
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_room_of_another_property_is_not_found(
    client, database, owner, existing, signed_in, make_property, make_room
):
    elsewhere = make_room(make_property(owner, name="Other"), number="Z1")
    response = create(client, signed_in.headers, existing.id, elsewhere)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_room_of_another_owners_property_is_not_found(
    client, database, existing, signed_in, make_user, make_property, make_room
):
    theirs = make_room(make_property(make_user(), name="Theirs"))
    response = create(client, signed_in.headers, existing.id, theirs)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_deleted_room_is_not_found(client, database, existing, signed_in, make_room):
    gone = make_room(existing, number="Gone", deleted=True)
    response = create(client, signed_in.headers, existing.id, gone)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert_nothing_saved(database)


def test_a_view_only_room_refuses_new_tenants(
    client, database, existing, signed_in, make_room
):
    frozen = make_room(existing, number="F1", view_only=True)
    response = create(client, signed_in.headers, existing.id, frozen)
    assert_error(response, 403, "ROOM_READ_ONLY")
    assert_nothing_saved(database)


def test_room_checks_are_reported_before_field_rules(
    client, database, existing, signed_in, make_room, room
):
    frozen = make_room(existing, number="F1", view_only=True)
    assert_error(
        create(client, signed_in.headers, existing.id, frozen, name=" "),
        403,
        "ROOM_READ_ONLY",
    )
    response = client.post(
        tenants_url(existing.id),
        json={**new_body(room, phone="bad"), "roomId": str(uuid4())},
        headers=signed_in.headers,
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_a_room_with_an_active_lease_is_not_vacant(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    before = counts(database)
    response = create(client, signed_in.headers, existing.id, room)
    assert_error(response, 409, "ROOM_NOT_VACANT", "roomId")
    assert counts(database) == before


def test_a_room_that_is_not_vacant_is_reported_before_field_rules(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    response = create(client, signed_in.headers, existing.id, room, phone="bad")
    assert_error(response, 409, "ROOM_NOT_VACANT", "roomId")


def test_a_room_whose_lease_has_ended_is_vacant_again(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    response = create(client, signed_in.headers, existing.id, room, name="Dewi")
    assert response.status_code == 201, response.text


def test_a_room_freed_by_a_deleted_tenant_with_an_ended_lease_can_be_reused(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, deleted=True, lease_ended=True)
    assert create(client, signed_in.headers, existing.id, room).status_code == 201


def test_a_second_tenant_cannot_take_a_room_just_filled(
    client, database, existing, signed_in, room
):
    assert create(client, signed_in.headers, existing.id, room).status_code == 201
    response = create(client, signed_in.headers, existing.id, room, name="Dewi")
    assert_error(response, 409, "ROOM_NOT_VACANT", "roomId")
    assert counts(database)["leases"] == 1


# POST: field rules


def test_the_name_is_trimmed(client, database, existing, signed_in, room):
    body = create(client, signed_in.headers, existing.id, room, name="  Budi \n").json()
    assert body["name"] == "Budi"
    (user,) = stored_tenant_users(database)
    assert user.name == "Budi"


@pytest.mark.parametrize("value", [" ", " \t\n "])
def test_a_blank_name_is_a_validation_failure(
    client, database, existing, signed_in, room, value
):
    response = create(client, signed_in.headers, existing.id, room, name=value)
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert_nothing_saved(database)


def test_a_missing_name_is_a_validation_failure(
    client, database, existing, signed_in, room
):
    response = client.post(
        tenants_url(existing.id),
        json=without(new_body(room), "name"),
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert_nothing_saved(database)


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("08123456789", "08123456789"),
        ("628123456789", "08123456789"),
        ("0812-3456-789", "08123456789"),
        ("0812 3456 789", "08123456789"),
        ("62 812-3456 789", "08123456789"),
        (" 08123456789 ", "08123456789"),
        ("0812345678", "0812345678"),
        ("08" + "1" * 11, "08" + "1" * 11),
        ("628" + "1" * 8, "08" + "1" * 8),
        ("628" + "1" * 11, "08" + "1" * 11),
    ],
)
def test_a_phone_is_normalized_to_digits_starting_with_08(
    client, database, existing, signed_in, room, submitted, expected
):
    from app.models import Tenant

    response = create(client, signed_in.headers, existing.id, room, phone=submitted)
    assert response.status_code == 201, response.text
    assert response.json()["phone"] == expected
    (row,) = fetch_all(database, Tenant)
    assert row.phone == expected


@pytest.mark.parametrize(
    "submitted",
    [
        "+628123456789",
        "+62 812 3456 789",
        "0812345678a",
        "abcdefghijk",
        "0712345678",
        "8123456789",
        "081234567",
        "08123456789012",
        "08" + "1" * 12,
        "628" + "1" * 7,
        "628" + "1" * 12,
        "0812.3456.789",
        "(0812)3456789",
        "08",
        "628",
        "   ",
    ],
)
def test_an_invalid_phone_is_a_validation_failure(
    client, database, existing, signed_in, room, submitted
):
    response = create(client, signed_in.headers, existing.id, room, phone=submitted)
    assert_error(response, 422, "VALIDATION_FAILED", "phone")
    assert_nothing_saved(database)


def test_a_missing_phone_is_a_validation_failure(
    client, database, existing, signed_in, room
):
    response = client.post(
        tenants_url(existing.id),
        json=without(new_body(room), "phone"),
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "phone")
    assert_nothing_saved(database)


@pytest.mark.parametrize("count", [0, 2, 3, 4])
def test_zero_or_two_to_four_emergency_contacts_are_accepted(
    client, database, existing, signed_in, room, count
):
    contacts = [
        {"name": f"C{n}", "relationship": "Teman", "phone": f"08123456789{n}"}
        for n in range(count)
    ]
    response = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=contacts
    )
    assert response.status_code == 201, response.text
    assert [c["name"] for c in response.json()["emergencyContacts"]] == [
        f"C{n}" for n in range(count)
    ]


def test_a_single_emergency_contact_is_a_validation_failure(
    client, database, existing, signed_in, room
):
    response = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=CONTACTS[:1]
    )
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert_nothing_saved(database)


def test_five_emergency_contacts_are_a_validation_failure(
    client, database, existing, signed_in, room
):
    response = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=CONTACTS * 3
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["field"] == "emergencyContacts"
    assert_nothing_saved(database)


def test_omitted_emergency_contacts_store_no_contact_rows(
    client, database, existing, signed_in, room
):
    from app.models import EmergencyContact

    response = client.post(
        tenants_url(existing.id),
        json=without(new_body(room), "emergencyContacts"),
        headers=signed_in.headers,
    )
    assert response.status_code == 201
    assert fetch_all(database, EmergencyContact) == []


@pytest.mark.parametrize("field", ["name", "relationship"])
@pytest.mark.parametrize("index", [0, 1])
def test_a_blank_emergency_contact_text_is_a_validation_failure(
    client, database, existing, signed_in, room, field, index
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index][field] = "   "
    response = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=contacts
    )
    assert_error(
        response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.{field}"
    )
    assert_nothing_saved(database)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("phone", ["+628123456789", "12345", "abc", "081234567"])
def test_an_invalid_emergency_contact_phone_is_a_validation_failure(
    client, database, existing, signed_in, room, index, phone
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index]["phone"] = phone
    response = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=contacts
    )
    assert_error(response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.phone")
    assert_nothing_saved(database)


def test_emergency_contact_phones_follow_the_same_normalization(
    client, database, existing, signed_in, room
):
    contacts = [
        {"name": "A", "relationship": "Ibu", "phone": "0812-3456-789"},
        {"name": "B", "relationship": "Ayah", "phone": "628123456789"},
    ]
    body = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=contacts
    ).json()
    assert [c["phone"] for c in body["emergencyContacts"]] == [
        "08123456789",
        "08123456789",
    ]


def test_emergency_contacts_keep_the_submitted_order_not_alphabetical(
    client, database, existing, signed_in, room
):
    contacts = [
        {"name": "Zed", "relationship": "Ayah", "phone": "081111111111"},
        {"name": "Abe", "relationship": "Ibu", "phone": "082222222222"},
        {"name": "Mia", "relationship": "Adik", "phone": "083333333333"},
    ]
    body = create(
        client, signed_in.headers, existing.id, room, emergencyContacts=contacts
    ).json()
    assert [c["name"] for c in body["emergencyContacts"]] == ["Zed", "Abe", "Mia"]


def test_an_end_date_before_the_start_date_is_a_validation_failure(
    client, database, existing, signed_in, room
):
    lease = lease_body(startDate="2099-03-01", endDate="2099-02-28")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.endDate")
    assert_nothing_saved(database)


def test_an_end_date_equal_to_the_start_date_is_accepted(
    client, database, existing, signed_in, room
):
    lease = lease_body(startDate="2099-03-01", endDate="2099-03-01")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "dates",
    [
        {"startDate": None, "endDate": None},
        {"startDate": "2099-01-10", "endDate": None},
        {"startDate": None, "endDate": "2099-12-31"},
    ],
)
def test_both_lease_dates_are_optional(
    client, database, existing, signed_in, room, dates
):
    lease = lease_body(**dates)
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.status_code == 201, response.text
    assert response.json()["lease"]["startDate"] == dates["startDate"]
    assert response.json()["lease"]["endDate"] == dates["endDate"]


def test_a_monthly_lease_without_rent_uses_the_base_rate_of_the_room(
    client, database, existing, signed_in, room
):
    from app.models import Lease

    lease = without(lease_body(), "rent")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.status_code == 201, response.text
    assert response.json()["lease"]["rent"] == 1750000
    (stored,) = fetch_all(database, Lease)
    assert stored.rent == 1750000


def test_a_monthly_lease_with_null_rent_uses_the_base_rate_of_the_room(
    client, database, existing, signed_in, room
):
    lease = lease_body(rent=None)
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.json()["lease"]["rent"] == 1750000


def test_a_lease_without_billing_cycle_is_monthly(
    client, database, existing, signed_in, room
):
    lease = without(lease_body(), "billingCycle", "rent")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.json()["lease"]["billingCycle"] == "monthly"
    assert response.json()["lease"]["rent"] == 1750000


@pytest.mark.parametrize("cycle", ["weekly", "quarterly", "semiannual", "annual"])
def test_a_lease_that_is_not_monthly_requires_rent(
    client, database, existing, signed_in, room, cycle
):
    lease = without(lease_body(billingCycle=cycle), "rent")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.rent")
    assert_nothing_saved(database)


@pytest.mark.parametrize("cycle", ["weekly", "quarterly", "semiannual", "annual"])
def test_a_lease_that_is_not_monthly_with_null_rent_is_a_validation_failure(
    client, database, existing, signed_in, room, cycle
):
    lease = lease_body(billingCycle=cycle, rent=None)
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.rent")


@pytest.mark.parametrize(
    "cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"]
)
def test_an_explicit_rent_is_kept_for_every_billing_cycle(
    client, database, existing, signed_in, room, cycle
):
    from app.models import Lease

    lease = lease_body(billingCycle=cycle, rent=333000)
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.status_code == 201, response.text
    assert response.json()["lease"]["rent"] == 333000
    assert response.json()["lease"]["billingCycle"] == cycle
    (stored,) = fetch_all(database, Lease)
    assert (stored.rent, stored.billing_cycle) == (333000, cycle)


def test_an_explicit_rent_wins_over_the_base_rate_for_a_monthly_lease(
    client, database, existing, signed_in, room
):
    lease = lease_body(billingCycle="monthly", rent=1)
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.json()["lease"]["rent"] == 1


def test_the_grace_period_defaults_to_zero(client, database, existing, signed_in, room):
    lease = without(lease_body(), "gracePeriodDays")
    response = create(client, signed_in.headers, existing.id, room, lease=lease)
    assert response.json()["lease"]["gracePeriodDays"] == 0


def test_the_lease_may_be_left_out_entirely(
    client, database, existing, signed_in, room
):
    response = client.post(
        tenants_url(existing.id),
        json=without(new_body(room), "lease"),
        headers=signed_in.headers,
    )
    assert response.status_code == 201, response.text
    lease = response.json()["lease"]
    assert lease["billingCycle"] == "monthly"
    assert lease["gracePeriodDays"] == 0
    assert lease["rent"] == 1750000
    assert lease["startDate"] is None
    assert lease["endDate"] is None
    assert lease["nextBillDate"] is None


def test_the_occupation_is_optional_and_blank_becomes_null(
    client, database, existing, signed_in, room, make_room
):
    from app.models import Tenant

    other = make_room(existing, number="A2")
    blank = create(client, signed_in.headers, existing.id, room, occupation="   ")
    missing = client.post(
        tenants_url(existing.id),
        json=without(new_body(other), "occupation"),
        headers=signed_in.headers,
    )
    assert blank.json()["occupation"] is None
    assert missing.json()["occupation"] is None
    assert {r.occupation for r in fetch_all(database, Tenant)} == {None}


def test_a_null_occupation_is_accepted(client, database, existing, signed_in, room):
    response = create(client, signed_in.headers, existing.id, room, occupation=None)
    assert response.status_code == 201
    assert response.json()["occupation"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"name": "  "},
        {"phone": "nope"},
        {"emergencyContacts": CONTACTS[:1]},
        {"lease": lease_body(startDate="2099-03-01", endDate="2099-01-01")},
        {"lease": without(lease_body(billingCycle="annual"), "rent")},
    ],
    ids=["name", "phone", "contacts", "end_date", "rent"],
)
def test_a_failed_field_rule_saves_nothing_and_leaves_the_room_free(
    client, database, existing, signed_in, room, change
):
    response = create(client, signed_in.headers, existing.id, room, **change)
    assert response.status_code == 422
    assert_nothing_saved(database)
    assert create(client, signed_in.headers, existing.id, room).status_code == 201


# POST: next bill date


def test_the_next_bill_date_of_a_future_start_is_the_start_date(
    client, database, existing, signed_in, room
):
    body = create(client, signed_in.headers, existing.id, room).json()
    assert body["lease"]["nextBillDate"] == "2099-01-10"


def test_the_next_bill_date_is_empty_when_the_lease_has_no_start_date(
    client, database, existing, signed_in, room
):
    lease = lease_body(startDate=None, endDate=None)
    body = create(client, signed_in.headers, existing.id, room, lease=lease).json()
    assert body["lease"]["nextBillDate"] is None


def test_the_next_bill_date_is_empty_when_the_lease_ended_in_the_past(
    client, database, existing, signed_in, room
):
    lease = lease_body(startDate="2000-01-10", endDate="2000-06-01")
    body = create(client, signed_in.headers, existing.id, room, lease=lease).json()
    assert body["lease"]["nextBillDate"] is None


def test_the_next_bill_date_of_a_past_start_is_after_today_in_jakarta(
    client, database, existing, signed_in, room
):
    lease = lease_body(startDate="2000-01-10", endDate=None)
    body = create(client, signed_in.headers, existing.id, room, lease=lease).json()
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    result = date.fromisoformat(body["lease"]["nextBillDate"])
    assert today < result <= today + timedelta(days=31)
    assert result.day == 10


# POST: invitation failure and atomicity


def test_the_tenant_is_saved_when_the_invitation_cannot_be_created(
    client, database, existing, signed_in, room, monkeypatch
):
    from app.models import EmergencyContact, Invitation, Lease, Tenant

    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    monkeypatch.setattr("app.services.invitations.create_invitation", fail)
    response = create(client, signed_in.headers, existing.id, room)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invitation"] is None
    assert body["accountStatus"] == "notActivated"
    assert body["lease"]["nextBillDate"] == "2099-01-10"
    assert len(body["emergencyContacts"]) == 2
    assert len(stored_tenant_users(database)) == 1
    assert len(fetch_all(database, Tenant)) == 1
    assert len(fetch_all(database, Lease)) == 1
    assert len(fetch_all(database, EmergencyContact)) == 2
    assert fetch_all(database, Invitation) == []


def test_a_tenant_saved_without_an_invitation_reads_back_without_one(
    client, database, existing, signed_in, room, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    monkeypatch.setattr("app.services.invitations.create_invitation", fail)
    created = create(client, signed_in.headers, existing.id, room).json()
    response = client.get(tenant_url(created["id"]), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == created


def test_the_room_is_taken_when_the_invitation_cannot_be_created(
    client, database, existing, signed_in, room, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", fail)
        create(client, signed_in.headers, existing.id, room)
    response = create(client, signed_in.headers, existing.id, room, name="Dewi")
    assert_error(response, 409, "ROOM_NOT_VACANT", "roomId")


def test_any_other_failure_saves_nothing(
    app, database, existing, owner, room, sign_in, monkeypatch
):
    from sqlalchemy.orm import Session as OrmSession

    from app.models import Lease

    headers = sign_in(owner).headers
    original = OrmSession.flush

    def failing_flush(self, *args, **kwargs):
        if any(isinstance(obj, Lease) for obj in self.new):
            raise RuntimeError("storage failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "flush", failing_flush)
    client = TestClient(app, raise_server_exceptions=False)
    response = create(client, headers, existing.id, room)
    monkeypatch.setattr(OrmSession, "flush", original)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert_nothing_saved(database)


# GET /properties/{propertyId}/tenants


def list_tenants(client, headers, property_id):
    return client.get(tenants_url(property_id), headers=headers)


def test_a_property_without_tenants_lists_an_empty_array(
    client, database, existing, signed_in, room
):
    response = list_tenants(client, signed_in.headers, existing.id)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_list_shows_tenants_as_summaries(
    client, database, existing, signed_in, room, make_tenant
):
    stored = make_tenant(
        room,
        name="Budi",
        end_date=date(2099, 12, 31),
        billing_cycle="quarterly",
    )
    response = list_tenants(client, signed_in.headers, existing.id)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == SUMMARY_FIELDS
    assert item["id"] == str(stored.id)
    assert item["name"] == "Budi"
    assert item["room"] == {"id": str(room.id), "number": "A1"}
    assert item["accountStatus"] == "notActivated"
    assert item["billingCycle"] == "quarterly"
    assert item["leaseEndDate"] == "2099-12-31"
    assert parse_time(item["invitationExpiresAt"]) == stored.invitation.expires_at


def test_a_lease_without_an_end_date_lists_a_null_end_date(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, end_date=None)
    (item,) = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert item["leaseEndDate"] is None


def test_an_activated_tenant_is_listed_active_without_an_invitation_expiry(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, activated=True, email="budi@example.com")
    (item,) = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert item["accountStatus"] == "active"
    assert item["invitationExpiresAt"] is None


def test_an_expired_invitation_still_lists_its_expiry(
    client, database, existing, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    (item,) = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert parse_time(item["invitationExpiresAt"]) == stored.invitation.expires_at
    assert parse_time(item["invitationExpiresAt"]) < datetime.now(UTC)


def test_a_tenant_without_an_invitation_lists_a_null_expiry(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, invitation=False)
    (item,) = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert item["accountStatus"] == "notActivated"
    assert item["invitationExpiresAt"] is None


def test_the_list_shows_the_expiry_of_the_current_invitation(
    client, database, existing, signed_in, room, make_tenant, db_session
):
    from app.services.invitations import create_invitation

    stored = make_tenant(room)
    newer, _ = create_invitation(db_session, stored.id)
    newer.expires_at = datetime.now(UTC) + timedelta(days=3)
    db_session.commit()
    (item,) = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert parse_time(item["invitationExpiresAt"]) == newer.expires_at


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        (["10", "2", "1", "21", "3"], ["1", "2", "3", "10", "21"]),
        (["A10", "A2", "A1", "A100", "A9"], ["A1", "A2", "A9", "A10", "A100"]),
        (["a10", "A2", "a1", "B1"], ["a1", "A2", "a10", "B1"]),
    ],
)
def test_tenants_are_listed_in_natural_order_of_their_room_number(
    client, database, existing, signed_in, make_room, make_tenant, numbers, expected
):
    for number in numbers:
        make_tenant(make_room(existing, number=number), name=f"T{number}")
    items = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert [i["room"]["number"] for i in items] == expected


def test_the_list_orders_by_room_number_before_name(
    client, database, existing, signed_in, make_room, make_tenant
):
    make_tenant(make_room(existing, number="2"), name="Aaa")
    make_tenant(make_room(existing, number="10"), name="Zzz")
    items = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert [i["name"] for i in items] == ["Aaa", "Zzz"]


def test_the_list_leaves_out_deleted_tenants_and_ended_leases(
    client, database, existing, signed_in, make_room, make_tenant
):
    kept = make_tenant(make_room(existing, number="1"), name="Kept")
    make_tenant(make_room(existing, number="2"), name="Deleted", deleted=True)
    make_tenant(make_room(existing, number="3"), name="Moved out", lease_ended=True)
    items = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert [i["id"] for i in items] == [str(kept.id)]


def test_the_list_leaves_out_tenants_of_other_properties(
    client, database, owner, existing, signed_in, make_property, make_room, make_tenant
):
    mine = make_tenant(make_room(existing, number="1"))
    other = make_property(owner, name="Other")
    make_tenant(make_room(other, number="1"), name="Elsewhere")
    items = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert [i["id"] for i in items] == [str(mine.id)]


def test_a_view_only_property_still_lists_its_tenants(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen))
    items = list_tenants(client, signed_in.headers, frozen.id).json()["items"]
    assert [i["id"] for i in items] == [str(stored.id)]


def test_a_manager_lists_the_tenants_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    stored = make_tenant(room)
    assign_manager(manager, existing)
    response = list_tenants(client, manager_in.headers, existing.id)
    assert response.status_code == 200
    assert [i["id"] for i in response.json()["items"]] == [str(stored.id)]


def test_an_unassigned_manager_cannot_list_the_tenants(
    client, database, manager_in, existing, room, make_tenant
):
    make_tenant(room)
    response = list_tenants(client, manager_in.headers, existing.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_a_manager_loses_access_to_the_list_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    make_tenant(room)
    assign_manager(manager, existing)
    assert list_tenants(client, manager_in.headers, existing.id).status_code == 200
    unassign(database, manager, existing)
    response = list_tenants(client, manager_in.headers, existing.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_tenants_of_an_unknown_property_is_not_found(
    client, database, signed_in
):
    response = list_tenants(client, signed_in.headers, uuid4())
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_tenants_of_another_owners_property_is_not_found(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    make_tenant(make_room(theirs))
    response = list_tenants(client, signed_in.headers, theirs.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_tenants_of_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = list_tenants(client, signed_in.headers, gone.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_with_a_malformed_property_id_is_a_validation_failure(
    client, database, signed_in
):
    response = list_tenants(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


# GET /tenants/{tenantId}


def get_tenant(client, headers, tenant_id):
    return client.get(tenant_url(tenant_id), headers=headers)


def test_an_owner_reads_a_tenant(
    client, database, existing, signed_in, room, make_tenant
):
    stored = make_tenant(
        room,
        name="Budi",
        phone="08123456789",
        occupation="Karyawan",
        contacts=[("Siti", "Ibu", "081234567890"), ("Agus", "Kakak", "08571234567")],
        start_date=date(2099, 1, 10),
        end_date=date(2099, 12, 31),
        billing_cycle="quarterly",
        rent=3000000,
        grace_period_days=5,
    )
    response = get_tenant(client, signed_in.headers, stored.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TENANT_FIELDS
    assert body["id"] == str(stored.id)
    assert body["name"] == "Budi"
    assert body["phone"] == "08123456789"
    assert body["email"] is None
    assert body["occupation"] == "Karyawan"
    assert body["accountStatus"] == "notActivated"
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["lease"] == {
        "startDate": "2099-01-10",
        "endDate": "2099-12-31",
        "rent": 3000000,
        "billingCycle": "quarterly",
        "gracePeriodDays": 5,
        "nextBillDate": "2099-01-10",
    }
    assert body["emergencyContacts"] == [
        {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
        {"name": "Agus", "relationship": "Kakak", "phone": "08571234567"},
    ]


def test_a_tenant_without_contacts_or_occupation_reads_empty_values(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, occupation=None, contacts=None)
    body = get_tenant(client, signed_in.headers, stored.id).json()
    assert body["occupation"] is None
    assert body["emergencyContacts"] == []


def test_emergency_contacts_are_read_in_stored_position_order(
    client, database, signed_in, room, make_tenant
):
    contacts = [
        ("Zed", "Ayah", "081111111111"),
        ("Abe", "Ibu", "082222222222"),
        ("Mia", "Adik", "083333333333"),
    ]
    stored = make_tenant(room, contacts=contacts)
    body = get_tenant(client, signed_in.headers, stored.id).json()
    assert [c["name"] for c in body["emergencyContacts"]] == ["Zed", "Abe", "Mia"]


def test_the_next_bill_date_is_computed_on_read(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    future = make_tenant(room, start_date=date(2099, 1, 10), end_date=None)
    none = make_tenant(make_room(existing, number="B1"), start_date=None)
    ended = make_tenant(
        make_room(existing, number="B2"),
        start_date=date(2000, 1, 10),
        end_date=date(2000, 6, 1),
    )
    results = [
        get_tenant(client, signed_in.headers, t.id).json()["lease"]["nextBillDate"]
        for t in (future, none, ended)
    ]
    assert results == ["2099-01-10", None, None]


def test_a_valid_invitation_shows_its_link(
    client, database, signed_in, room, make_tenant
):
    import hashlib

    stored = make_tenant(room)
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert set(invitation) == INVITATION_FIELDS
    assert invitation["expired"] is False
    assert parse_time(invitation["createdAt"]) == stored.invitation.created_at
    assert parse_time(invitation["expiresAt"]) == stored.invitation.expires_at
    assert invitation["url"] == f"{invitation_base()}/invitations/{stored.token}"
    token = invitation["url"].rsplit("/", 1)[1]
    assert hashlib.sha256(token.encode()).hexdigest() == stored.invitation.token_hash


def test_an_expired_invitation_has_no_link_and_is_marked_expired(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["expired"] is True
    assert invitation["url"] is None
    assert parse_time(invitation["expiresAt"]) == stored.invitation.expires_at
    assert parse_time(invitation["createdAt"]) == stored.invitation.created_at


def test_an_invitation_that_expires_after_being_read_becomes_expired(
    client, database, signed_in, room, make_tenant, db_session
):
    from app.models import Invitation

    stored = make_tenant(room)
    first = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    row = db_session.get(Invitation, stored.invitation.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    second = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert (first["expired"], first["url"] is not None) == (False, True)
    assert (second["expired"], second["url"]) == (True, None)


def test_a_used_invitation_has_no_link_and_is_not_expired(
    client, database, signed_in, room, make_tenant, db_session
):
    from app.models import Invitation

    stored = make_tenant(room)
    db_session.get(Invitation, stored.invitation.id).used_at = datetime.now(UTC)
    db_session.commit()
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] is None
    assert invitation["expired"] is False


def test_an_invalidated_invitation_has_no_link(
    client, database, signed_in, room, make_tenant, db_session
):
    from app.models import Invitation

    stored = make_tenant(room)
    db_session.get(Invitation, stored.invitation.id).invalidated_at = datetime.now(UTC)
    db_session.commit()
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] is None
    assert invitation["expired"] is False


def test_only_the_newest_invitation_is_shown(
    client, database, signed_in, room, make_tenant, db_session
):
    from app.services.invitations import create_invitation

    stored = make_tenant(room)
    newer, token = create_invitation(db_session, stored.id)
    db_session.commit()
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] == f"{invitation_base()}/invitations/{token}"
    assert invitation["url"] != f"{invitation_base()}/invitations/{stored.token}"
    assert parse_time(invitation["createdAt"]) == newer.created_at
    assert parse_time(invitation["expiresAt"]) == newer.expires_at


def test_a_tenant_without_any_invitation_reads_a_null_invitation(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, invitation=False)
    body = get_tenant(client, signed_in.headers, stored.id).json()
    assert body["accountStatus"] == "notActivated"
    assert body["invitation"] is None


def test_an_activated_tenant_is_active_with_an_email_and_no_invitation(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, activated=True, email="budi@example.com")
    body = get_tenant(client, signed_in.headers, stored.id).json()
    assert body["accountStatus"] == "active"
    assert body["email"] == "budi@example.com"
    assert body["invitation"] is None


def test_an_activated_tenant_shows_no_invitation_even_if_one_row_remains(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(
        room, activated=True, email="budi@example.com", invitation=True
    )
    assert get_tenant(client, signed_in.headers, stored.id).json()["invitation"] is None


def test_a_view_only_property_still_shows_its_tenants(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen))
    assert get_tenant(client, signed_in.headers, stored.id).status_code == 200


def test_a_manager_reads_a_tenant_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    stored = make_tenant(room)
    assign_manager(manager, existing)
    response = get_tenant(client, manager_in.headers, stored.id)
    assert response.status_code == 200
    assert response.json()["id"] == str(stored.id)


def test_a_manager_reads_the_tenants_of_the_assigned_property_only(
    client,
    database,
    owner,
    manager,
    manager_in,
    existing,
    room,
    make_property,
    make_room,
    make_tenant,
    assign_manager,
):
    assign_manager(manager, existing)
    unassigned = make_property(owner, name="Unassigned")
    hidden = make_tenant(make_room(unassigned))
    response = get_tenant(client, manager_in.headers, hidden.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_an_unassigned_manager_gets_tenant_not_found(
    client, database, manager_in, room, make_tenant
):
    stored = make_tenant(room)
    response = get_tenant(client, manager_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_manager_loses_access_to_a_tenant_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    stored = make_tenant(room)
    assign_manager(manager, existing)
    assert get_tenant(client, manager_in.headers, stored.id).status_code == 200
    unassign(database, manager, existing)
    response = get_tenant(client, manager_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_an_unknown_tenant_is_not_found(client, database, signed_in):
    response = get_tenant(client, signed_in.headers, uuid4())
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_the_id_of_a_user_who_is_not_a_tenant_is_not_found(
    client, database, owner, signed_in
):
    response = get_tenant(client, signed_in.headers, owner.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_deleted_tenant_is_not_found(client, database, signed_in, room, make_tenant):
    stored = make_tenant(room, deleted=True)
    response = get_tenant(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_tenant_without_an_active_lease_is_not_found(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, lease_ended=True)
    response = get_tenant(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_tenant_of_another_owners_property_is_not_found(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    stored = make_tenant(make_room(theirs))
    response = get_tenant(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_tenant_of_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_tenant(make_room(gone))
    response = get_tenant(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_malformed_tenant_id_is_a_validation_failure(client, database, signed_in):
    response = get_tenant(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "tenantId")


def test_the_tenant_id_is_the_user_account_id(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room)
    body = get_tenant(client, signed_in.headers, stored.id).json()
    assert UUID(body["id"]) == stored.user.id == stored.tenant.user_id


# PUT /tenants/{tenantId}


def edit_body(**overrides) -> dict:
    return {
        "name": "Budi Santoso",
        "phone": "081234567890",
        "occupation": "Mahasiswa",
        "emergencyContacts": CONTACTS,
        "lease": LEASE,
        **overrides,
    }


def edit(client, headers, tenant_id, **overrides):
    return client.put(
        tenant_url(tenant_id), json=edit_body(**overrides), headers=headers
    )


def tenant_state(database, tenant_id) -> dict:
    """Everything stored about a tenant that an edit may touch."""
    from app.models import EmergencyContact, Lease, Tenant, UserAccount

    with Session(database, expire_on_commit=False) as db:
        user = db.get(UserAccount, tenant_id)
        tenant = db.get(Tenant, tenant_id)
        contacts = db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.tenant_id == tenant_id)
            .order_by(EmergencyContact.position)
        )
        leases = db.scalars(select(Lease).where(Lease.tenant_id == tenant_id))
        return {
            "name": user.name,
            "email": user.email,
            "phone": tenant.phone,
            "occupation": tenant.occupation,
            "activated_at": tenant.activated_at,
            "contacts": [
                (c.position, c.name, c.relationship, c.phone) for c in contacts
            ],
            "leases": sorted(
                (
                    l.id,
                    l.room_id,
                    l.start_date,
                    l.end_date,
                    l.billing_cycle,
                    l.rent,
                    l.grace_period_days,
                    l.ended_at,
                )
                for l in leases
            ),
        }


def invitation_state(database, tenant_id) -> list:
    from app.models import Invitation

    with Session(database, expire_on_commit=False) as db:
        rows = db.scalars(
            select(Invitation)
            .where(Invitation.tenant_id == tenant_id)
            .order_by(Invitation.created_at)
        )
        return [
            (
                r.id,
                r.token_hash,
                r.created_at,
                r.expires_at,
                r.used_at,
                r.invalidated_at,
            )
            for r in rows
        ]


@pytest.fixture
def current(room, make_tenant):
    """A not yet activated tenant whose every editable value differs from `edit_body`."""
    return make_tenant(
        room,
        name="Old Name",
        phone="085555555555",
        occupation="Old job",
        contacts=[
            ("Old One", "Ayah", "081111111111"),
            ("Old Two", "Ibu", "082222222222"),
        ],
        start_date=date(2099, 2, 1),
        end_date=date(2099, 6, 30),
        billing_cycle="weekly",
        rent=500000,
        grace_period_days=1,
    )


@pytest.fixture
def active(room, make_tenant):
    """An activated tenant with two emergency contacts."""
    return make_tenant(
        room,
        name="Old Name",
        phone="085555555555",
        email="budi@example.com",
        activated=True,
        contacts=[
            ("Old One", "Ayah", "081111111111"),
            ("Old Two", "Ibu", "082222222222"),
        ],
    )


# PUT: success


def test_editing_a_tenant_answers_with_the_updated_tenant(
    client, database, signed_in, room, current
):
    response = edit(client, signed_in.headers, current.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TENANT_FIELDS
    assert body["id"] == str(current.id)
    assert body["name"] == "Budi Santoso"
    assert body["phone"] == "081234567890"
    assert body["email"] is None
    assert body["occupation"] == "Mahasiswa"
    assert body["accountStatus"] == "notActivated"
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["lease"] == {
        "startDate": "2099-01-10",
        "endDate": "2099-12-31",
        "rent": 1200000,
        "billingCycle": "monthly",
        "gracePeriodDays": 3,
        "nextBillDate": "2099-01-10",
    }
    assert body["emergencyContacts"] == [
        {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
        {"name": "Agus", "relationship": "Kakak", "phone": "08571234567"},
    ]


def test_the_edited_tenant_can_be_read_back_unchanged(
    client, database, signed_in, current
):
    edited = edit(client, signed_in.headers, current.id).json()
    response = get_tenant(client, signed_in.headers, current.id)
    assert response.status_code == 200
    assert response.json() == edited


def test_the_edited_values_are_stored(client, database, signed_in, room, current):
    edit(client, signed_in.headers, current.id)
    state = tenant_state(database, current.id)
    assert state["name"] == "Budi Santoso"
    assert state["phone"] == "081234567890"
    assert state["occupation"] == "Mahasiswa"
    (lease,) = state["leases"]
    assert lease[1:] == (
        room.id,
        date(2099, 1, 10),
        date(2099, 12, 31),
        "monthly",
        1200000,
        3,
        None,
    )


def test_the_emergency_contacts_are_replaced_in_the_order_given(
    client, database, signed_in, current
):
    contacts = [
        {"name": "Zed", "relationship": "Ayah", "phone": "081111111119"},
        {"name": "Abe", "relationship": "Ibu", "phone": "082222222228"},
        {"name": "Mia", "relationship": "Adik", "phone": "628333333337"},
    ]
    body = edit(client, signed_in.headers, current.id, emergencyContacts=contacts)
    assert [c["name"] for c in body.json()["emergencyContacts"]] == [
        "Zed",
        "Abe",
        "Mia",
    ]
    assert tenant_state(database, current.id)["contacts"] == [
        (0, "Zed", "Ayah", "081111111119"),
        (1, "Abe", "Ibu", "082222222228"),
        (2, "Mia", "Adik", "08333333337"),
    ]


def test_old_emergency_contacts_are_not_kept(client, database, signed_in, current):
    from app.models import EmergencyContact

    edit(client, signed_in.headers, current.id)
    names = {c.name for c in fetch_all(database, EmergencyContact)}
    assert names == {"Siti", "Agus"}


def test_the_tenant_keeps_the_same_room_and_the_same_lease_row(
    client, database, signed_in, room, current
):
    from app.models import Lease

    edit(client, signed_in.headers, current.id)
    (lease,) = fetch_all(database, Lease)
    assert lease.id == current.lease.id
    assert lease.room_id == room.id
    assert lease.tenant_id == current.id
    assert lease.ended_at is None
    assert counts(database)["users"] == 1


def test_the_edit_does_not_move_the_tenant_to_another_room(
    client, database, existing, signed_in, room, current, make_room
):
    other = make_room(existing, number="A2")
    response = client.put(
        tenant_url(current.id),
        json={**edit_body(), "roomId": str(other.id)},
        headers=signed_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["room"] == {"id": str(room.id), "number": "A1"}
    assert tenant_state(database, current.id)["leases"][0][1] == room.id


def test_editing_leaves_other_tenants_untouched(
    client, database, existing, signed_in, current, make_room, make_tenant
):
    other = make_tenant(make_room(existing, number="A2"), name="Dewi")
    before = tenant_state(database, other.id)
    edit(client, signed_in.headers, current.id)
    assert tenant_state(database, other.id) == before


def test_editing_does_not_change_the_invitation_or_the_account_status(
    client, database, signed_in, current
):
    before = invitation_state(database, current.id)
    body = edit(client, signed_in.headers, current.id).json()
    assert invitation_state(database, current.id) == before
    assert body["accountStatus"] == "notActivated"
    assert (
        body["invitation"]["url"] == f"{invitation_base()}/invitations/{current.token}"
    )
    assert body["invitation"]["expired"] is False


def test_editing_an_expired_invitation_leaves_it_expired(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    before = invitation_state(database, stored.id)
    body = edit(client, signed_in.headers, stored.id).json()
    assert invitation_state(database, stored.id) == before
    assert body["invitation"]["expired"] is True
    assert body["invitation"]["url"] is None


def test_editing_a_tenant_without_an_invitation_creates_none(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, invitation=False)
    body = edit(client, signed_in.headers, stored.id).json()
    assert body["invitation"] is None
    assert invitation_state(database, stored.id) == []


def test_editing_an_active_tenant_keeps_the_account_active_and_the_email(
    client, database, signed_in, active
):
    before = tenant_state(database, active.id)
    response = edit(client, signed_in.headers, active.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accountStatus"] == "active"
    assert body["email"] == "budi@example.com"
    assert body["invitation"] is None
    after = tenant_state(database, active.id)
    assert after["activated_at"] == before["activated_at"]
    assert after["email"] == "budi@example.com"
    assert after["name"] == "Budi Santoso"


def test_editing_with_the_same_values_succeeds(client, database, signed_in, room):
    from app.models import Lease

    stored = create(
        client, signed_in.headers, room.property_id, room, name="Budi Santoso"
    ).json()
    response = edit(client, signed_in.headers, stored["id"])
    assert response.status_code == 200, response.text
    assert response.json() == stored
    assert len(fetch_all(database, Lease)) == 1


def test_a_rent_or_billing_cycle_change_does_not_change_existing_bills(
    client, database, signed_in, current, make_rent_bill
):
    from rent_bill_support import stored_bill

    bills = [
        make_rent_bill(current.lease, amount=500000),
        make_rent_bill(
            current.lease,
            amount=500000,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 7),
        ),
    ]
    lease = lease_body(billingCycle="quarterly", rent=3600000)
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert response.status_code == 200, response.text
    assert response.json()["lease"]["rent"] == 3600000
    assert response.json()["lease"]["billingCycle"] == "quarterly"
    for bill in bills:
        assert stored_bill(database, bill).amount == 500000


# PUT: tenant access


def test_an_unknown_tenant_is_not_found_on_edit(client, database, signed_in):
    response = edit(client, signed_in.headers, uuid4())
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_the_id_of_a_user_who_is_not_a_tenant_is_not_found_on_edit(
    client, database, owner, signed_in
):
    response = edit(client, signed_in.headers, owner.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_deleted_tenant_is_not_found_on_edit(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, deleted=True)
    before = tenant_state(database, stored.id)
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert tenant_state(database, stored.id) == before


def test_a_tenant_without_an_active_lease_is_not_found_on_edit(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, lease_ended=True)
    before = tenant_state(database, stored.id)
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert tenant_state(database, stored.id) == before


def test_a_tenant_of_another_owners_property_is_not_found_on_edit(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    stored = make_tenant(make_room(theirs), name="Theirs Tenant")
    before = tenant_state(database, stored.id)
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert tenant_state(database, stored.id) == before


def test_a_tenant_of_a_deleted_property_is_not_found_on_edit(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_tenant(make_room(gone))
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_malformed_tenant_id_is_a_validation_failure_on_edit(
    client, database, signed_in
):
    response = edit(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "tenantId")


def test_a_manager_edits_a_tenant_of_an_assigned_property(
    client, database, manager, manager_in, existing, current, assign_manager
):
    assign_manager(manager, existing)
    response = edit(client, manager_in.headers, current.id)
    assert response.status_code == 200, response.text
    assert tenant_state(database, current.id)["name"] == "Budi Santoso"


def test_a_manager_cannot_edit_a_tenant_of_an_unassigned_property(
    client, database, manager_in, current
):
    before = tenant_state(database, current.id)
    response = edit(client, manager_in.headers, current.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert tenant_state(database, current.id) == before


def test_a_manager_loses_the_right_to_edit_a_tenant_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, current, assign_manager
):
    assign_manager(manager, existing)
    assert edit(client, manager_in.headers, current.id).status_code == 200
    unassign(database, manager, existing)
    response = edit(client, manager_in.headers, current.id, name="Again")
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert tenant_state(database, current.id)["name"] == "Budi Santoso"


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_a_forbidden_account_edits_nothing(
    client, database, make_user, sign_in, current, name
):
    headers = sign_in(make_user(role=role(name))).headers
    before = tenant_state(database, current.id)
    response = edit(client, headers, current.id)
    assert_error(response, 403, "FORBIDDEN")
    assert tenant_state(database, current.id) == before


# PUT: view-only property and room


def test_a_view_only_property_refuses_tenant_edits(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen), name="Old Name")
    before = tenant_state(database, stored.id)
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert tenant_state(database, stored.id) == before


def test_a_view_only_property_refuses_tenant_edits_from_a_manager(
    client,
    database,
    owner,
    manager,
    manager_in,
    make_property,
    make_room,
    make_tenant,
    assign_manager,
):
    frozen = make_property(owner, view_only=True)
    assign_manager(manager, frozen)
    stored = make_tenant(make_room(frozen), name="Old Name")
    response = edit(client, manager_in.headers, stored.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert tenant_state(database, stored.id)["name"] == "Old Name"


def test_a_view_only_room_refuses_tenant_edits(
    client, database, existing, signed_in, make_room, make_tenant
):
    frozen = make_room(existing, number="F1", view_only=True)
    stored = make_tenant(frozen, name="Old Name")
    before = tenant_state(database, stored.id)
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 403, "ROOM_READ_ONLY")
    assert tenant_state(database, stored.id) == before


def test_a_view_only_room_refuses_tenant_edits_from_a_manager(
    client,
    database,
    manager,
    manager_in,
    existing,
    make_room,
    make_tenant,
    assign_manager,
):
    assign_manager(manager, existing)
    stored = make_tenant(make_room(existing, number="F1", view_only=True))
    response = edit(client, manager_in.headers, stored.id)
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_not_found_is_reported_before_view_only_on_edit(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), view_only=True)
    stored = make_tenant(make_room(theirs, view_only=True))
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_an_unassigned_manager_gets_not_found_before_view_only(
    client, database, owner, manager_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True))
    response = edit(client, manager_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_missing_tenant_is_reported_before_field_rules(client, database, signed_in):
    response = edit(client, signed_in.headers, uuid4(), phone="bad", name="  ")
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_view_only_property_is_reported_before_view_only_room(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True))
    response = edit(client, signed_in.headers, stored.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_property_is_reported_before_field_rules_on_edit(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen))
    response = edit(client, signed_in.headers, stored.id, name="   ")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_room_is_reported_before_field_rules_on_edit(
    client, database, existing, signed_in, make_room, make_tenant
):
    stored = make_tenant(make_room(existing, number="F1", view_only=True))
    response = edit(client, signed_in.headers, stored.id, name="   ")
    assert_error(response, 403, "ROOM_READ_ONLY")
    response = edit(client, signed_in.headers, stored.id, phone="bad")
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_another_room_being_view_only_does_not_block_the_edit(
    client, database, existing, signed_in, current, make_room, make_tenant
):
    make_tenant(make_room(existing, number="F1", view_only=True), name="Frozen")
    assert edit(client, signed_in.headers, current.id).status_code == 200


# PUT: field rules


def test_the_name_is_trimmed_on_edit(client, database, signed_in, current):
    body = edit(client, signed_in.headers, current.id, name="  Budi \n").json()
    assert body["name"] == "Budi"
    assert tenant_state(database, current.id)["name"] == "Budi"


@pytest.mark.parametrize("value", [" ", " \t\n "])
def test_a_blank_name_is_a_validation_failure_on_edit(
    client, database, signed_in, current, value
):
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, name=value)
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert tenant_state(database, current.id) == before


def test_a_missing_name_is_a_validation_failure_on_edit(
    client, database, signed_in, current
):
    response = client.put(
        tenant_url(current.id),
        json=without(edit_body(), "name"),
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "name")


def test_a_missing_phone_is_a_validation_failure_on_edit(
    client, database, signed_in, current
):
    response = client.put(
        tenant_url(current.id),
        json=without(edit_body(), "phone"),
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "phone")


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("08123456789", "08123456789"),
        ("628123456789", "08123456789"),
        ("0812-3456-789", "08123456789"),
        ("0812 3456 789", "08123456789"),
        ("62 812-3456 789", "08123456789"),
        (" 08123456789 ", "08123456789"),
        ("0812345678", "0812345678"),
        ("08" + "1" * 11, "08" + "1" * 11),
        ("628" + "1" * 8, "08" + "1" * 8),
        ("628" + "1" * 11, "08" + "1" * 11),
    ],
)
def test_a_phone_is_normalized_to_digits_starting_with_08_on_edit(
    client, database, signed_in, current, submitted, expected
):
    response = edit(client, signed_in.headers, current.id, phone=submitted)
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == expected
    assert tenant_state(database, current.id)["phone"] == expected


@pytest.mark.parametrize(
    "submitted",
    [
        "+628123456789",
        "0812345678a",
        "abcdefgh",
        "0712345678",
        "8123456789",
        "081234567",
        "08123456789012",
        "628" + "1" * 7,
        "628" + "1" * 12,
        "0812.3456.789",
        "08",
        "   ",
    ],
)
def test_an_invalid_phone_is_a_validation_failure_on_edit(
    client, database, signed_in, current, submitted
):
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, phone=submitted)
    assert_error(response, 422, "VALIDATION_FAILED", "phone")
    assert tenant_state(database, current.id) == before


def test_the_occupation_is_trimmed_on_edit(client, database, signed_in, current):
    body = edit(client, signed_in.headers, current.id, occupation="  Dosen \n").json()
    assert body["occupation"] == "Dosen"
    assert tenant_state(database, current.id)["occupation"] == "Dosen"


@pytest.mark.parametrize("value", ["   ", "", None])
def test_a_blank_or_null_occupation_becomes_null_on_edit(
    client, database, signed_in, current, value
):
    response = edit(client, signed_in.headers, current.id, occupation=value)
    assert response.status_code == 200, response.text
    assert response.json()["occupation"] is None
    assert tenant_state(database, current.id)["occupation"] is None


@pytest.mark.parametrize("count", [2, 3, 4])
def test_two_to_four_emergency_contacts_are_accepted_on_edit(
    client, database, signed_in, current, count
):
    contacts = [
        {"name": f"C{n}", "relationship": "Teman", "phone": f"08123456789{n}"}
        for n in range(count)
    ]
    response = edit(client, signed_in.headers, current.id, emergencyContacts=contacts)
    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()["emergencyContacts"]] == [
        f"C{n}" for n in range(count)
    ]
    assert len(tenant_state(database, current.id)["contacts"]) == count


def test_a_tenant_that_is_not_activated_may_clear_the_emergency_contacts(
    client, database, signed_in, current
):
    response = edit(client, signed_in.headers, current.id, emergencyContacts=[])
    assert response.status_code == 200, response.text
    assert response.json()["emergencyContacts"] == []
    assert tenant_state(database, current.id)["contacts"] == []


def test_a_single_emergency_contact_is_a_validation_failure_on_edit(
    client, database, signed_in, current
):
    before = tenant_state(database, current.id)
    response = edit(
        client, signed_in.headers, current.id, emergencyContacts=CONTACTS[:1]
    )
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert tenant_state(database, current.id) == before


def test_five_emergency_contacts_are_a_validation_failure_on_edit(
    client, database, signed_in, current
):
    before = tenant_state(database, current.id)
    response = edit(
        client,
        signed_in.headers,
        current.id,
        emergencyContacts=(CONTACTS * 3)[:5],
    )
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert tenant_state(database, current.id) == before


@pytest.mark.parametrize("field", ["name", "relationship"])
@pytest.mark.parametrize("index", [0, 1])
def test_a_blank_emergency_contact_text_is_a_validation_failure_on_edit(
    client, database, signed_in, current, field, index
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index][field] = "   "
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, emergencyContacts=contacts)
    assert_error(
        response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.{field}"
    )
    assert tenant_state(database, current.id) == before


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("phone", ["+628123456789", "12345", "abc", "081234567"])
def test_an_invalid_emergency_contact_phone_is_a_validation_failure_on_edit(
    client, database, signed_in, current, index, phone
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index]["phone"] = phone
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.phone")
    assert tenant_state(database, current.id) == before


def test_emergency_contact_text_is_trimmed_and_phones_normalized_on_edit(
    client, database, signed_in, current
):
    contacts = [
        {"name": "  A ", "relationship": " Ibu\n", "phone": "0812-3456-789"},
        {"name": "B", "relationship": "Ayah", "phone": "628123456789"},
    ]
    body = edit(
        client, signed_in.headers, current.id, emergencyContacts=contacts
    ).json()
    assert body["emergencyContacts"] == [
        {"name": "A", "relationship": "Ibu", "phone": "08123456789"},
        {"name": "B", "relationship": "Ayah", "phone": "08123456789"},
    ]
    assert tenant_state(database, current.id)["contacts"] == [
        (0, "A", "Ibu", "08123456789"),
        (1, "B", "Ayah", "08123456789"),
    ]


@pytest.mark.parametrize("contacts", [[], CONTACTS[:1]])
def test_an_active_tenant_cannot_have_fewer_than_two_emergency_contacts(
    client, database, signed_in, active, contacts
):
    before = tenant_state(database, active.id)
    response = edit(client, signed_in.headers, active.id, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert tenant_state(database, active.id) == before


def test_an_active_tenant_may_replace_the_emergency_contacts(
    client, database, signed_in, active
):
    response = edit(client, signed_in.headers, active.id)
    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()["emergencyContacts"]] == [
        "Siti",
        "Agus",
    ]


def test_an_end_date_before_the_start_date_is_a_validation_failure_on_edit(
    client, database, signed_in, current
):
    before = tenant_state(database, current.id)
    lease = lease_body(startDate="2099-03-01", endDate="2099-02-28")
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.endDate")
    assert tenant_state(database, current.id) == before


def test_an_end_date_equal_to_the_start_date_is_accepted_on_edit(
    client, database, signed_in, current
):
    lease = lease_body(startDate="2099-03-01", endDate="2099-03-01")
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "dates",
    [
        {"startDate": None, "endDate": None},
        {"startDate": "2099-01-10", "endDate": None},
        {"startDate": None, "endDate": "2099-12-31"},
    ],
)
def test_both_lease_dates_are_optional_on_edit(
    client, database, signed_in, current, dates
):
    response = edit(client, signed_in.headers, current.id, lease=lease_body(**dates))
    assert response.status_code == 200, response.text
    assert response.json()["lease"]["startDate"] == dates["startDate"]
    assert response.json()["lease"]["endDate"] == dates["endDate"]
    (lease,) = tenant_state(database, current.id)["leases"]
    assert lease[2] == (
        date.fromisoformat(dates["startDate"]) if dates["startDate"] else None
    )


def test_clearing_the_lease_start_date_clears_the_next_bill_date(
    client, database, signed_in, current
):
    lease = lease_body(startDate=None, endDate=None)
    body = edit(client, signed_in.headers, current.id, lease=lease).json()
    assert body["lease"]["nextBillDate"] is None


@pytest.mark.parametrize("rent", [0, -5])
def test_a_rent_that_is_not_positive_is_a_validation_failure_on_edit(
    client, database, signed_in, current, rent
):
    before = tenant_state(database, current.id)
    lease = lease_body(rent=rent)
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.rent")
    assert tenant_state(database, current.id) == before


@pytest.mark.parametrize("omit", ["missing", "null"])
def test_a_monthly_lease_without_rent_uses_the_base_rate_of_the_room_on_edit(
    client, database, signed_in, current, omit
):
    lease = (
        without(lease_body(), "rent") if omit == "missing" else lease_body(rent=None)
    )
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert response.status_code == 200, response.text
    assert response.json()["lease"]["rent"] == 1750000
    (stored,) = tenant_state(database, current.id)["leases"]
    assert stored[5] == 1750000


@pytest.mark.parametrize("cycle", ["weekly", "quarterly", "semiannual", "annual"])
@pytest.mark.parametrize("omit", ["missing", "null"])
def test_a_lease_that_is_not_monthly_requires_rent_on_edit(
    client, database, signed_in, current, cycle, omit
):
    lease = (
        without(lease_body(billingCycle=cycle), "rent")
        if omit == "missing"
        else lease_body(billingCycle=cycle, rent=None)
    )
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert_error(response, 422, "VALIDATION_FAILED", "lease.rent")
    assert tenant_state(database, current.id) == before


@pytest.mark.parametrize(
    "cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"]
)
def test_an_explicit_rent_is_kept_for_every_billing_cycle_on_edit(
    client, database, signed_in, current, cycle
):
    lease = lease_body(billingCycle=cycle, rent=333000)
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert response.status_code == 200, response.text
    assert response.json()["lease"]["rent"] == 333000
    assert response.json()["lease"]["billingCycle"] == cycle
    (stored,) = tenant_state(database, current.id)["leases"]
    assert (stored[5], stored[4]) == (333000, cycle)


def test_the_grace_period_is_stored_on_edit(client, database, signed_in, current):
    lease = lease_body(gracePeriodDays=9)
    response = edit(client, signed_in.headers, current.id, lease=lease)
    assert response.json()["lease"]["gracePeriodDays"] == 9
    assert tenant_state(database, current.id)["leases"][0][6] == 9


# PUT: atomicity


@pytest.mark.parametrize(
    "change",
    [
        {"name": "  "},
        {"phone": "nope"},
        {"emergencyContacts": CONTACTS[:1]},
        {"lease": lease_body(startDate="2099-03-01", endDate="2099-01-01")},
        {"lease": without(lease_body(billingCycle="annual"), "rent")},
    ],
    ids=["name", "phone", "contacts", "end_date", "rent"],
)
def test_a_failed_field_rule_saves_nothing_on_edit(
    client, database, signed_in, current, change
):
    before = tenant_state(database, current.id)
    response = edit(client, signed_in.headers, current.id, **change)
    assert response.status_code == 422
    assert tenant_state(database, current.id) == before


def test_a_bad_second_contact_keeps_the_old_contacts_and_name(
    client, database, signed_in, current
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[1]["phone"] = "nope"
    before = tenant_state(database, current.id)
    response = edit(
        client,
        signed_in.headers,
        current.id,
        name="Changed Name",
        emergencyContacts=contacts,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts.1.phone")
    after = tenant_state(database, current.id)
    assert after == before
    assert after["name"] == "Old Name"
    assert [c[1] for c in after["contacts"]] == ["Old One", "Old Two"]


def test_any_other_failure_saves_nothing_on_edit(
    app, database, owner, current, sign_in, monkeypatch
):
    from sqlalchemy.orm import Session as OrmSession

    from app.models import EmergencyContact

    headers = sign_in(owner).headers
    original = OrmSession.flush

    def failing_flush(self, *args, **kwargs):
        if any(isinstance(obj, EmergencyContact) for obj in self.new):
            raise RuntimeError("storage failure")
        return original(self, *args, **kwargs)

    before = tenant_state(database, current.id)
    contacts = [
        {"name": f"C{n}", "relationship": "Teman", "phone": f"08123456789{n}"}
        for n in range(4)
    ]
    monkeypatch.setattr(OrmSession, "flush", failing_flush)
    client = TestClient(app, raise_server_exceptions=False)
    response = edit(
        client, headers, current.id, name="Changed Name", emergencyContacts=contacts
    )
    monkeypatch.setattr(OrmSession, "flush", original)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert tenant_state(database, current.id) == before


# POST /tenants/{tenantId}/invitation


def regenerate(client, headers, tenant_id):
    return client.post(f"{tenant_url(tenant_id)}/invitation", headers=headers)


def preview_status(client, token: str) -> str:
    response = client.post("/invitations/previews", json={"token": token})
    assert response.status_code == 200, response.text
    return response.json()["status"]


def token_of(url: str) -> str:
    prefix = f"{invitation_base()}/invitations/"
    assert url.startswith(prefix)
    return url.removeprefix(prefix)


def test_regenerating_answers_with_a_new_invitation(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room)
    before = datetime.now(UTC)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == INVITATION_FIELDS
    assert body["expired"] is False
    assert body["url"].startswith(f"{invitation_base()}/invitations/")
    assert body["url"] != f"{invitation_base()}/invitations/{stored.token}"
    created = parse_time(body["createdAt"])
    assert before - timedelta(minutes=1) <= created <= datetime.now(UTC)
    assert parse_time(body["expiresAt"]) - created == timedelta(days=7)


def test_the_new_invitation_is_stored_with_a_hashed_token(
    client, database, signed_in, room, make_tenant
):
    import hashlib

    stored = make_tenant(room)
    body = regenerate(client, signed_in.headers, stored.id).json()
    token = token_of(body["url"])
    rows = invitation_state(database, stored.id)
    assert len(rows) == 2
    newest = rows[-1]
    assert newest[1] == hashlib.sha256(token.encode()).hexdigest()
    assert newest[4] is None
    assert newest[5] is None
    assert newest[3] - newest[2] == timedelta(days=7)


def test_the_old_link_stops_working_and_the_new_link_is_valid(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room)
    assert preview_status(client, stored.token) == "valid"
    body = regenerate(client, signed_in.headers, stored.id).json()
    assert preview_status(client, stored.token) == "used"
    assert preview_status(client, token_of(body["url"])) == "valid"


def test_the_tenant_detail_shows_the_new_link(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room)
    body = regenerate(client, signed_in.headers, stored.id).json()
    invitation = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation == body
    assert invitation["url"] != f"{invitation_base()}/invitations/{stored.token}"


def test_an_expired_invitation_is_renewed(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    assert preview_status(client, stored.token) == "expired"
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["expired"] is False
    assert parse_time(body["expiresAt"]) > datetime.now(UTC) + timedelta(days=6)
    assert preview_status(client, token_of(body["url"])) == "valid"
    detail = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert detail["expired"] is False
    assert detail["url"] == body["url"]


def test_the_old_link_of_a_renewed_expired_invitation_is_not_valid(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    assert preview_status(client, stored.token) == "expired"
    regenerate(client, signed_in.headers, stored.id)
    assert preview_status(client, stored.token) == "used"


def test_a_tenant_without_an_invitation_gets_one(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, invitation=False)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    assert preview_status(client, token_of(response.json()["url"])) == "valid"
    assert len(invitation_state(database, stored.id)) == 1


def test_regenerating_does_not_change_the_tenant_data(
    client, database, signed_in, current
):
    before = tenant_state(database, current.id)
    regenerate(client, signed_in.headers, current.id)
    assert tenant_state(database, current.id) == before
    body = get_tenant(client, signed_in.headers, current.id).json()
    assert body["accountStatus"] == "notActivated"


def test_regenerating_twice_leaves_only_the_latest_link_valid(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room)
    first = regenerate(client, signed_in.headers, stored.id).json()
    second = regenerate(client, signed_in.headers, stored.id).json()
    assert first["url"] != second["url"]
    assert preview_status(client, stored.token) == "used"
    assert preview_status(client, token_of(first["url"])) == "used"
    assert preview_status(client, token_of(second["url"])) == "valid"
    assert len(invitation_state(database, stored.id)) == 3
    detail = get_tenant(client, signed_in.headers, stored.id).json()["invitation"]
    assert detail["url"] == second["url"]


def test_regenerating_leaves_other_tenants_links_valid(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    mine = make_tenant(room)
    other = make_tenant(make_room(existing, number="A2"), name="Dewi")
    regenerate(client, signed_in.headers, mine.id)
    assert preview_status(client, other.token) == "valid"


def test_an_active_tenant_cannot_get_a_new_invitation(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, activated=True, email="budi@example.com")
    before = invitation_state(database, stored.id)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "TENANT_ALREADY_ACTIVE"
    assert response.json()["message"]
    assert invitation_state(database, stored.id) == before


def test_an_active_tenant_without_an_invitation_row_gets_none_created(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(
        room, activated=True, email="budi@example.com", invitation=False
    )
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 409
    assert response.json()["code"] == "TENANT_ALREADY_ACTIVE"
    assert invitation_state(database, stored.id) == []


def test_a_view_only_property_still_allows_a_new_invitation(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen))
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    assert preview_status(client, token_of(response.json()["url"])) == "valid"
    assert preview_status(client, stored.token) == "used"


def test_a_view_only_room_still_allows_a_new_invitation(
    client, database, existing, signed_in, make_room, make_tenant
):
    stored = make_tenant(make_room(existing, number="F1", view_only=True))
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    assert preview_status(client, token_of(response.json()["url"])) == "valid"


def test_a_manager_regenerates_the_invitation_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    stored = make_tenant(room)
    assign_manager(manager, existing)
    response = regenerate(client, manager_in.headers, stored.id)
    assert response.status_code == 201, response.text
    assert preview_status(client, stored.token) == "used"


def test_a_manager_cannot_regenerate_the_invitation_of_an_unassigned_property(
    client, database, manager_in, room, make_tenant
):
    stored = make_tenant(room)
    response = regenerate(client, manager_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert preview_status(client, stored.token) == "valid"
    assert len(invitation_state(database, stored.id)) == 1


def test_a_manager_loses_the_right_to_regenerate_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    stored = make_tenant(room)
    assign_manager(manager, existing)
    assert regenerate(client, manager_in.headers, stored.id).status_code == 201
    unassign(database, manager, existing)
    response = regenerate(client, manager_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert len(invitation_state(database, stored.id)) == 2


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_a_forbidden_account_regenerates_nothing(
    client, database, make_user, sign_in, room, make_tenant, name
):
    stored = make_tenant(room)
    headers = sign_in(make_user(role=role(name))).headers
    response = regenerate(client, headers, stored.id)
    assert_error(response, 403, "FORBIDDEN")
    assert preview_status(client, stored.token) == "valid"
    assert len(invitation_state(database, stored.id)) == 1


def test_an_unknown_tenant_is_not_found_on_regenerate(client, database, signed_in):
    response = regenerate(client, signed_in.headers, uuid4())
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_the_id_of_a_user_who_is_not_a_tenant_is_not_found_on_regenerate(
    client, database, owner, signed_in
):
    response = regenerate(client, signed_in.headers, owner.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_deleted_tenant_is_not_found_on_regenerate(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, deleted=True)
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert len(invitation_state(database, stored.id)) == 1


def test_a_tenant_without_an_active_lease_is_not_found_on_regenerate(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, lease_ended=True)
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert len(invitation_state(database, stored.id)) == 1


def test_a_tenant_of_another_owners_property_is_not_found_on_regenerate(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    stored = make_tenant(make_room(theirs))
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")
    assert preview_status(client, stored.token) == "valid"
    assert len(invitation_state(database, stored.id)) == 1


def test_a_tenant_of_a_deleted_property_is_not_found_on_regenerate(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_tenant(make_room(gone))
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "TENANT_NOT_FOUND")


def test_a_malformed_tenant_id_is_a_validation_failure_on_regenerate(
    client, database, signed_in
):
    response = regenerate(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "tenantId")


def test_the_old_link_stays_valid_when_the_new_invitation_cannot_be_created(
    app, database, owner, sign_in, room, make_tenant, monkeypatch
):
    stored = make_tenant(room)
    headers = sign_in(owner).headers

    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    before = invitation_state(database, stored.id)
    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", fail)
        response = regenerate(client, headers, stored.id)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert invitation_state(database, stored.id) == before
    assert preview_status(client, stored.token) == "valid"
    detail = get_tenant(client, headers, stored.id).json()["invitation"]
    assert detail["url"] == f"{invitation_base()}/invitations/{stored.token}"


def test_the_old_link_stays_valid_when_creation_fails_after_replacing_it(
    app, database, owner, sign_in, room, make_tenant, monkeypatch
):
    from app.services import invitations

    stored = make_tenant(room)
    headers = sign_in(owner).headers
    create_invitation = invitations.create_invitation

    def create_then_fail(*args, **kwargs):
        create_invitation(*args, **kwargs)
        raise RuntimeError("failure after the new invitation was created")

    before = invitation_state(database, stored.id)
    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", create_then_fail)
        response = regenerate(client, headers, stored.id)
    assert response.status_code == 500
    assert invitation_state(database, stored.id) == before
    assert preview_status(client, stored.token) == "valid"


# DELETE /tenants/{tenantId}

ACTIVATION_URL = "/invitations/activations/password"
PREVIEW_URL = "/invitations/previews"
REFRESH_URL = "/auth/refresh"
ME_URL = "/me"
LOGIN_URL = "/auth/login"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"


def remove(client, headers, tenant_id):
    return client.delete(tenant_url(tenant_id), headers=headers)


def remove_ok(client, headers, tenant_id) -> None:
    response = remove(client, headers, tenant_id)
    assert response.status_code == 204, response.text


def tenant_row(database, tenant_id):
    from app.models import Tenant

    with Session(database, expire_on_commit=False) as db:
        return db.get(Tenant, tenant_id)


def session_rows(database, user_id) -> list:
    from app.models import UserSession

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at, UserSession.id)
            )
        )


def removal_state(database, tenant_id) -> dict:
    """Everything a removal may touch: the edit state, deletion time, sessions, links."""
    return {
        **tenant_state(database, tenant_id),
        "deleted_at": tenant_row(database, tenant_id).deleted_at,
        "sessions": [(s.id, s.revoked_at) for s in session_rows(database, tenant_id)],
        "invitations": invitation_state(database, tenant_id),
    }


def assert_just_now(value) -> None:
    assert value is not None
    now = datetime.now(UTC)
    assert now - timedelta(minutes=1) <= value <= now + timedelta(minutes=1)


def assert_access_rejected(response) -> None:
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def refresh_with(client, token: str):
    return client.post(REFRESH_URL, json={"refreshToken": token})


def assert_link_unknown(client, token: str) -> None:
    assert_error(
        client.post(PREVIEW_URL, json={"token": token}), 404, "INVITATION_NOT_FOUND"
    )
    body = {
        "token": token,
        "name": "Dewi Lestari",
        "email": "dewi.new@example.com",
        "password": PASSWORD,
        "device": DEVICE,
    }
    assert_error(client.post(ACTIVATION_URL, json=body), 404, "INVITATION_NOT_FOUND")


def set_password(database, user, password: str) -> None:
    from app.models import UserAccount
    from app.services.passwords import hash_password

    with Session(database) as db:
        db.get(UserAccount, user.id).password_hash = hash_password(password)
        db.commit()


@pytest.fixture
def member(room, make_verified_tenant):
    """An activated tenant with a verified email in `room`."""
    return make_verified_tenant(room, name="Budi Tenant")


# DELETE: success


def test_removing_a_tenant_answers_no_content(
    client, database, signed_in, room, current
):
    response = remove(client, signed_in.headers, current.id)
    assert response.status_code == 204, response.text
    assert response.content == b""


def test_the_tenant_row_is_soft_deleted_and_kept(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, name="Budi", occupation="Mahasiswa", phone="08123456789")
    assert remove(client, signed_in.headers, stored.id).status_code == 204
    row = tenant_row(database, stored.id)
    assert row is not None
    assert_just_now(row.deleted_at)
    assert row.phone == "08123456789"
    assert row.occupation == "Mahasiswa"
    assert row.user_id == stored.id


def test_the_user_account_row_is_kept(client, database, signed_in, current):
    from app.models import UserAccount

    remove_ok(client, signed_in.headers, current.id)
    with Session(database) as db:
        assert db.get(UserAccount, current.id).name == "Old Name"


def test_the_emergency_contacts_are_kept(client, database, signed_in, current):
    before = tenant_state(database, current.id)["contacts"]
    remove_ok(client, signed_in.headers, current.id)
    assert tenant_state(database, current.id)["contacts"] == before
    assert len(before) == 2


def test_the_active_lease_is_ended_and_kept(client, database, signed_in, room, current):
    from app.models import Lease

    remove(client, signed_in.headers, current.id)
    (lease,) = fetch_all(database, Lease)
    assert lease.id == current.lease.id
    assert lease.room_id == room.id
    assert lease.tenant_id == current.id
    assert lease.rent == 500000
    assert_just_now(lease.ended_at)


def test_the_room_shows_as_vacant_afterwards(
    client, database, existing, signed_in, room, current
):
    remove(client, signed_in.headers, current.id)
    detail = client.get(f"/rooms/{room.id}", headers=signed_in.headers).json()
    assert detail["occupancy"] == "vacant"
    assert detail["lease"] is None
    items = client.get(
        f"{PROPERTIES}/{existing.id}/rooms", headers=signed_in.headers
    ).json()["items"]
    (item,) = items
    assert item["occupancy"] == "vacant"
    assert item["lease"] is None


def test_the_room_itself_is_untouched(client, database, signed_in, room, current):
    remove_ok(client, signed_in.headers, current.id)
    detail = client.get(f"/rooms/{room.id}", headers=signed_in.headers).json()
    assert detail["number"] == "A1"
    assert detail["baseRate"] == 1750000
    assert detail["editable"] is True


def test_the_freed_room_accepts_a_new_tenant(
    client, database, existing, signed_in, room, current
):
    remove(client, signed_in.headers, current.id)
    response = create(client, signed_in.headers, existing.id, room, name="Dewi")
    assert response.status_code == 201, response.text
    assert response.json()["room"] == {"id": str(room.id), "number": "A1"}
    detail = client.get(f"/rooms/{room.id}", headers=signed_in.headers).json()
    assert detail["occupancy"] == "occupied"
    assert detail["lease"]["tenantName"] == "Dewi"


def test_the_removed_tenant_leaves_the_property_list_and_cannot_be_read(
    client, database, existing, signed_in, room, current
):
    assert list_tenants(client, signed_in.headers, existing.id).json()["items"]
    remove(client, signed_in.headers, current.id)
    assert list_tenants(client, signed_in.headers, existing.id).json() == {"items": []}
    assert_error(
        get_tenant(client, signed_in.headers, current.id), 404, "TENANT_NOT_FOUND"
    )


def test_removing_twice_answers_not_found_the_second_time(
    client, database, signed_in, current
):
    assert remove(client, signed_in.headers, current.id).status_code == 204
    after_first = removal_state(database, current.id)
    assert_error(remove(client, signed_in.headers, current.id), 404, "TENANT_NOT_FOUND")
    assert removal_state(database, current.id) == after_first


def test_other_tenants_are_untouched(
    client,
    database,
    existing,
    signed_in,
    current,
    make_room,
    make_verified_tenant,
    sign_in,
):
    other_room = make_room(existing, number="A2")
    other = make_verified_tenant(other_room, name="Dewi")
    other_in = sign_in(other.user)
    before = removal_state(database, other.id)
    assert remove(client, signed_in.headers, current.id).status_code == 204
    assert removal_state(database, other.id) == before
    items = list_tenants(client, signed_in.headers, existing.id).json()["items"]
    assert [i["id"] for i in items] == [str(other.id)]
    detail = client.get(f"/rooms/{other_room.id}", headers=signed_in.headers).json()
    assert detail["occupancy"] == "occupied"
    assert client.get(ME_URL, headers=other_in.headers).status_code == 200


def test_the_property_counts_drop(
    client, database, existing, signed_in, current, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A2"), name="Dewi")
    make_room(existing, number="A3")
    detail = client.get(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    assert detail.json()["roomCount"] == 3
    assert detail.json()["occupiedRoomCount"] == 2
    assert detail.json()["vacantRoomCount"] == 1
    remove(client, signed_in.headers, current.id)
    detail = client.get(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    assert detail.json()["roomCount"] == 3
    assert detail.json()["occupiedRoomCount"] == 1
    assert detail.json()["vacantRoomCount"] == 2
    (item,) = client.get(PROPERTIES, headers=signed_in.headers).json()["items"]
    assert (item["roomCount"], item["occupiedRoomCount"]) == (3, 1)


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
def test_a_tenant_in_any_account_state_can_be_removed(
    client, database, signed_in, room, make_tenant, options
):
    stored = make_tenant(room, **options)
    assert remove(client, signed_in.headers, stored.id).status_code == 204
    assert_just_now(tenant_row(database, stored.id).deleted_at)
    assert_just_now(tenant_state(database, stored.id)["leases"][0][7])


def test_a_manager_removes_a_tenant_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, member, assign_manager
):
    assign_manager(manager, existing)
    assert remove(client, manager_in.headers, member.id).status_code == 204
    assert_just_now(tenant_row(database, member.id).deleted_at)
    assert_just_now(tenant_state(database, member.id)["leases"][0][7])
    detail = client.get(f"/rooms/{room.id}", headers=manager_in.headers).json()
    assert detail["occupancy"] == "vacant"


def test_a_removed_tenant_can_no_longer_log_in(
    client, database, signed_in, room, make_verified_tenant
):
    stored = make_verified_tenant(room, email="budi@example.com")
    set_password(database, stored.user, PASSWORD)
    body = {"email": "budi@example.com", "password": PASSWORD, "device": DEVICE}
    assert client.post(LOGIN_URL, json=body).status_code == 200
    remove(client, signed_in.headers, stored.id)
    assert_error(client.post(LOGIN_URL, json=body), 401, "INVALID_CREDENTIALS")


# DELETE: tenant access


def test_an_unknown_tenant_is_not_found_on_removal(client, database, signed_in):
    assert_error(remove(client, signed_in.headers, uuid4()), 404, "TENANT_NOT_FOUND")


def test_the_id_of_a_user_who_is_not_a_tenant_is_not_found_on_removal(
    client, database, owner, signed_in
):
    assert_error(remove(client, signed_in.headers, owner.id), 404, "TENANT_NOT_FOUND")
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200


def test_an_already_deleted_tenant_is_not_found_on_removal(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, deleted=True)
    before = removal_state(database, stored.id)
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")
    assert removal_state(database, stored.id) == before


def test_a_tenant_without_an_active_lease_is_not_found_on_removal(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, lease_ended=True)
    before = removal_state(database, stored.id)
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")
    assert removal_state(database, stored.id) == before
    assert before["deleted_at"] is None


def test_a_tenant_of_another_owners_property_is_not_found_on_removal(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    stored = make_tenant(make_room(theirs))
    before = removal_state(database, stored.id)
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")
    assert removal_state(database, stored.id) == before
    assert before["deleted_at"] is None


def test_a_tenant_of_a_deleted_property_is_not_found_on_removal(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_tenant(make_room(gone))
    before = removal_state(database, stored.id)
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")
    assert removal_state(database, stored.id) == before


def test_a_malformed_tenant_id_is_a_validation_failure_on_removal(
    client, database, signed_in
):
    response = remove(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "tenantId")


def test_an_unassigned_manager_cannot_remove_a_tenant(
    client, database, manager_in, current
):
    before = removal_state(database, current.id)
    assert_error(
        remove(client, manager_in.headers, current.id), 404, "TENANT_NOT_FOUND"
    )
    assert removal_state(database, current.id) == before
    assert before["deleted_at"] is None


def test_a_manager_assigned_to_another_property_cannot_remove_a_tenant(
    client, database, owner, manager, manager_in, current, make_property, assign_manager
):
    assign_manager(manager, make_property(owner, name="Elsewhere"))
    before = removal_state(database, current.id)
    assert_error(
        remove(client, manager_in.headers, current.id), 404, "TENANT_NOT_FOUND"
    )
    assert removal_state(database, current.id) == before


def test_a_manager_loses_the_right_to_remove_a_tenant_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, current, assign_manager
):
    assign_manager(manager, existing)
    assert get_tenant(client, manager_in.headers, current.id).status_code == 200
    unassign(database, manager, existing)
    before = removal_state(database, current.id)
    assert_error(
        remove(client, manager_in.headers, current.id), 404, "TENANT_NOT_FOUND"
    )
    assert removal_state(database, current.id) == before
    assert before["deleted_at"] is None


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_a_forbidden_account_removes_nothing(
    client, database, make_user, sign_in, current, name
):
    headers = sign_in(make_user(role=role(name))).headers
    before = removal_state(database, current.id)
    assert_error(remove(client, headers, current.id), 403, "FORBIDDEN")
    assert removal_state(database, current.id) == before
    assert before["deleted_at"] is None


def test_a_tenant_cannot_remove_themselves(client, database, room, member, sign_in):
    own = sign_in(member.user)
    before = removal_state(database, member.id)
    assert_error(remove(client, own.headers, member.id), 403, "FORBIDDEN")
    assert removal_state(database, member.id) == before


# DELETE: view-only property and room


def test_a_view_only_property_refuses_removal(
    client,
    database,
    owner,
    signed_in,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    frozen = make_property(owner, view_only=True)
    stored = make_verified_tenant(make_room(frozen))
    sign_in(stored.user)
    before = removal_state(database, stored.id)
    response = remove(client, signed_in.headers, stored.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert removal_state(database, stored.id) == before
    assert before["deleted_at"] is None
    assert get_tenant(client, signed_in.headers, stored.id).status_code == 200


def test_a_view_only_property_refuses_removal_from_a_manager(
    client,
    database,
    owner,
    manager,
    manager_in,
    make_property,
    make_room,
    make_tenant,
    assign_manager,
):
    frozen = make_property(owner, view_only=True)
    assign_manager(manager, frozen)
    stored = make_tenant(make_room(frozen))
    before = removal_state(database, stored.id)
    assert_error(
        remove(client, manager_in.headers, stored.id), 403, "PROPERTY_READ_ONLY"
    )
    assert removal_state(database, stored.id) == before


def test_a_view_only_room_refuses_removal(
    client, database, existing, signed_in, make_room, make_verified_tenant, sign_in
):
    frozen = make_room(existing, number="F1", view_only=True)
    stored = make_verified_tenant(frozen)
    sign_in(stored.user)
    before = removal_state(database, stored.id)
    response = remove(client, signed_in.headers, stored.id)
    assert_error(response, 403, "ROOM_READ_ONLY")
    assert removal_state(database, stored.id) == before
    assert before["deleted_at"] is None
    detail = client.get(f"/rooms/{frozen.id}", headers=signed_in.headers).json()
    assert detail["occupancy"] == "occupied"


def test_a_view_only_room_refuses_removal_from_a_manager(
    client,
    database,
    manager,
    manager_in,
    existing,
    make_room,
    make_tenant,
    assign_manager,
):
    assign_manager(manager, existing)
    stored = make_tenant(make_room(existing, number="F1", view_only=True))
    before = removal_state(database, stored.id)
    assert_error(remove(client, manager_in.headers, stored.id), 403, "ROOM_READ_ONLY")
    assert removal_state(database, stored.id) == before


def test_view_only_property_is_reported_before_view_only_room_on_removal(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True))
    response = remove(client, signed_in.headers, stored.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_a_missing_tenant_is_reported_before_view_only_on_removal(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), view_only=True)
    stored = make_tenant(make_room(theirs, view_only=True))
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")


def test_an_already_deleted_tenant_is_reported_before_view_only(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True), deleted=True)
    assert_error(remove(client, signed_in.headers, stored.id), 404, "TENANT_NOT_FOUND")


def test_an_unassigned_manager_gets_not_found_before_view_only_on_removal(
    client, database, owner, manager_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True))
    assert_error(remove(client, manager_in.headers, stored.id), 404, "TENANT_NOT_FOUND")


def test_a_forbidden_role_is_reported_before_everything_else_on_removal(
    client, database, owner, make_user, sign_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    stored = make_tenant(make_room(frozen, view_only=True))
    headers = sign_in(make_user(role=role("tenant"))).headers
    assert_error(remove(client, headers, stored.id), 403, "FORBIDDEN")


def test_another_room_being_view_only_does_not_block_removal(
    client, database, existing, signed_in, current, make_room, make_tenant
):
    make_tenant(make_room(existing, number="F1", view_only=True), name="Frozen")
    assert remove(client, signed_in.headers, current.id).status_code == 204


# DELETE: history is kept


def test_the_rent_bills_of_a_removed_tenant_are_kept(
    client, database, scene, make_rent_bill
):
    from rent_bill_support import days_ago, png, snapshot

    from app.models import RentBill, RentBillReceipt, RentBillStatusChange

    lease = scene.tenant.lease
    bills = [
        make_rent_bill(lease),
        make_rent_bill(
            lease,
            period_start=days_ago(40),
            status="awaitingVerification",
            receipt=(png(), "image/png", datetime.now(UTC)),
        ),
        make_rent_bill(
            lease,
            period_start=days_ago(70),
            status="paid",
            method="cash",
            paid_on=days_ago(65),
        ),
    ]
    models = (RentBill, RentBillStatusChange, RentBillReceipt)
    before = [snapshot(database, b) for b in bills]
    sizes = [len(fetch_all(database, m)) for m in models]
    response = remove(client, scene.owner_in.headers, scene.tenant.id)
    assert response.status_code == 204, response.text
    assert [snapshot(database, b) for b in bills] == before
    assert [len(fetch_all(database, m)) for m in models] == sizes
    assert sizes == [3, 3, 1]


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_still_lists_the_bills_of_a_removed_tenant(
    client, database, scene, make_rent_bill, who
):
    from rent_bill_support import RENT_BILLS, days_ago

    first = make_rent_bill(scene.tenant.lease)
    second = make_rent_bill(scene.tenant.lease, period_start=days_ago(40))
    remove_ok(client, scene.owner_in.headers, scene.tenant.id)
    response = client.get(RENT_BILLS, headers=getattr(scene, who).headers)
    assert response.status_code == 200, response.text
    assert {i["id"] for i in response.json()["items"]} == {
        str(first.id),
        str(second.id),
    }


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_still_reads_a_bill_and_its_receipt_of_a_removed_tenant(
    client, database, scene, make_rent_bill, who
):
    from rent_bill_support import bill_url, png

    bill = make_rent_bill(
        scene.tenant.lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    remove_ok(client, scene.owner_in.headers, scene.tenant.id)
    headers = getattr(scene, who).headers
    detail = client.get(bill_url(bill), headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == str(bill.id)
    assert detail.json()["tenant"]["id"] == str(scene.tenant.id)
    assert detail.json()["payment"]["status"] == "awaitingVerification"
    receipt = client.get(bill_url(bill, "/receipt"), headers=headers)
    assert receipt.status_code == 200
    assert receipt.content == png()


def test_the_complaints_of_a_removed_tenant_are_kept(
    client, database, scene, make_complaint
):
    from app.models import Complaint, ComplaintStatusChange

    complaint = make_complaint(scene.tenant, scene.room)
    sizes = [len(fetch_all(database, m)) for m in (Complaint, ComplaintStatusChange)]
    assert remove(client, scene.owner_in.headers, scene.tenant.id).status_code == 204
    after = [len(fetch_all(database, m)) for m in (Complaint, ComplaintStatusChange)]
    assert after == sizes == [1, 1]
    (stored,) = fetch_all(database, Complaint)
    assert stored.id == complaint.id
    assert stored.tenant_id == scene.tenant.id
    assert stored.status == "new"


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_still_reads_the_complaints_of_a_removed_tenant(
    client, database, scene, make_complaint, who
):
    complaint = make_complaint(scene.tenant, scene.room)
    remove_ok(client, scene.owner_in.headers, scene.tenant.id)
    headers = getattr(scene, who).headers
    detail = client.get(f"/complaints/{complaint.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == str(complaint.id)
    assert detail.json()["tenantName"] == "Budi Tenant"
    listed = client.get("/complaints", headers=headers)
    assert [i["id"] for i in listed.json()["items"]] == [str(complaint.id)]


# DELETE: account access is revoked


def test_every_unrevoked_session_of_the_tenant_is_ended(
    client, database, signed_in, member, sign_in
):
    sessions = [sign_in(member.user, name) for name in ("Phone", "Tablet", "Laptop")]
    for session in sessions:
        assert client.get(ME_URL, headers=session.headers).status_code == 200
    assert remove(client, signed_in.headers, member.id).status_code == 204
    rows = session_rows(database, member.id)
    assert len(rows) == 3
    for row in rows:
        assert_just_now(row.revoked_at)


def test_the_access_tokens_of_the_tenant_stop_working_at_once(
    client, database, signed_in, member, sign_in
):
    sessions = [sign_in(member.user, name) for name in ("Phone", "Tablet")]
    remove(client, signed_in.headers, member.id)
    for session in sessions:
        assert_access_rejected(client.get(ME_URL, headers=session.headers))
        assert_access_rejected(client.get(PROPERTIES, headers=session.headers))


def test_the_refresh_tokens_of_the_tenant_stop_working(
    client, database, signed_in, member, sign_in
):
    sessions = [sign_in(member.user, name) for name in ("Phone", "Tablet")]
    remove(client, signed_in.headers, member.id)
    for session in sessions:
        assert_error(
            refresh_with(client, session.tokens.refresh_token),
            401,
            "REFRESH_TOKEN_INVALID",
        )


def test_a_session_ended_earlier_keeps_its_revocation_time(
    client, database, signed_in, member, sign_in, read_session
):
    ended = sign_in(member.user, "Old phone")
    live = sign_in(member.user, "Tablet")
    assert client.post("/auth/logout", headers=ended.headers).status_code == 204
    first_revoked_at = read_session(ended.session_id).revoked_at
    remove(client, signed_in.headers, member.id)
    assert read_session(ended.session_id).revoked_at == first_revoked_at
    assert_just_now(read_session(live.session_id).revoked_at)


def test_the_sessions_of_other_users_are_untouched(
    client,
    database,
    owner,
    manager,
    manager_in,
    signed_in,
    member,
    sign_in,
    make_verified_tenant,
    existing,
    make_room,
    read_session,
):
    sign_in(member.user)
    other = make_verified_tenant(make_room(existing, number="A2"), name="Dewi")
    other_in = sign_in(other.user)
    remove_ok(client, signed_in.headers, member.id)
    for session in (signed_in, manager_in, other_in):
        assert read_session(session.session_id).revoked_at is None
        assert client.get(ME_URL, headers=session.headers).status_code == 200
    assert refresh_with(client, other_in.tokens.refresh_token).status_code == 200


def test_a_tenant_that_never_activated_is_removed_without_sessions(
    client, database, signed_in, current
):
    assert session_rows(database, current.id) == []
    assert remove(client, signed_in.headers, current.id).status_code == 204
    assert session_rows(database, current.id) == []


def test_an_activated_tenant_without_a_session_is_removed(
    client, database, signed_in, member
):
    assert session_rows(database, member.id) == []
    assert remove(client, signed_in.headers, member.id).status_code == 204


# DELETE: invitation links


def test_the_unused_link_of_a_removed_tenant_is_unknown(
    client, database, signed_in, current
):
    remove(client, signed_in.headers, current.id)
    assert_link_unknown(client, current.token)


def test_the_expired_link_of_a_removed_tenant_is_unknown(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(room, expired=True)
    remove(client, signed_in.headers, stored.id)
    assert_link_unknown(client, stored.token)


def test_every_link_of_a_removed_tenant_is_unknown_after_regeneration(
    client, database, signed_in, current
):
    renewed = regenerate(client, signed_in.headers, current.id).json()
    remove(client, signed_in.headers, current.id)
    assert_link_unknown(client, current.token)
    assert_link_unknown(client, token_of(renewed["url"]))


def test_activation_with_the_link_of_a_removed_tenant_changes_nothing(
    client, database, signed_in, current
):
    from app.models import UserAccount

    remove(client, signed_in.headers, current.id)
    before = removal_state(database, current.id)
    users = len(fetch_all(database, UserAccount))
    assert_link_unknown(client, current.token)
    assert removal_state(database, current.id) == before
    assert len(fetch_all(database, UserAccount)) == users
    assert before["email"] is None


def test_the_links_of_other_tenants_stay_valid(
    client, database, existing, signed_in, current, make_room, make_tenant
):
    other = make_tenant(make_room(existing, number="A2"), name="Dewi")
    remove_ok(client, signed_in.headers, current.id)
    assert preview_status(client, other.token) == "valid"


# DELETE: failures save nothing


def test_a_failure_while_ending_sessions_saves_nothing(
    app, database, owner, room, member, sign_in, monkeypatch
):
    from app.services import sessions

    sign_in(member.user, "Phone")
    sign_in(member.user, "Tablet")
    headers = sign_in(owner).headers
    before = removal_state(database, member.id)
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
        response = remove(client, headers, member.id)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert len(calls) == 2
    after = removal_state(database, member.id)
    assert after == before
    assert after["deleted_at"] is None
    assert [revoked for _, revoked in after["sessions"]] == [None, None]
    assert get_tenant(client, headers, member.id).status_code == 200
    detail = client.get(f"/rooms/{room.id}", headers=headers).json()
    assert detail["occupancy"] == "occupied"


def test_a_tenant_can_be_removed_after_a_failed_attempt(
    app, database, owner, member, sign_in, monkeypatch
):
    from app.services import sessions

    sign_in(member.user)
    headers = sign_in(owner).headers

    def fail(db, session):
        raise RuntimeError("storage failure")

    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr(sessions, "end_session", fail)
        assert remove(client, headers, member.id).status_code == 500
    assert remove(client, headers, member.id).status_code == 204
    assert_just_now(tenant_row(database, member.id).deleted_at)
