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


# Operations that are not implemented yet


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param(
            "put",
            tenant_url(uuid4()),
            {"name": "Budi", "phone": "081234567890"},
            id="put",
        ),
        pytest.param("delete", tenant_url(uuid4()), None, id="delete"),
        pytest.param("post", tenant_url(uuid4()) + "/invitation", None, id="invite"),
    ],
)
def test_other_tenant_operations_are_still_not_implemented(
    client, database, signed_in, method, url, body
):
    response = client.request(method, url, json=body, headers=signed_in.headers)
    assert response.status_code == 501
