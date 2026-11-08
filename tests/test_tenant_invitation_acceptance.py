"""Previewing and accepting a Tenant invitation with an existing Tenant account."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from manager_invitation_support import (
    ACCEPTANCE_PREVIEW_URL,
    ACCEPTANCE_URL,
    code_count,
    edit_invitation,
    preview,
    preview_status,
    stored_user,
)
from manager_support import assert_error, fetch_all, role, token_of
from notification_support import (
    assert_item,
    items,
    only,
    property_ref,
    room_ref,
    stored_for,
    stored_rows,
    tenant_ref,
    types,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from user_account_support import get_account, listed_ids, set_password

HOOK = "app.services.activation.notify_tenant_activated"
STORED_CONTACTS = [
    ("Siti", "Ibu", "081234567890"),
    ("Agus", "Kakak", "08571234567"),
]
CONTACTS = [
    {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
    {"name": "Wati", "relationship": "Adik", "phone": "628222222222"},
]
PREVIEW_FIELDS = {
    "invitation",
    "accountName",
    "accountEmail",
    "accountRole",
    "canAccept",
    "blocker",
}
CALLER_NAME = "Tomi Tenant"
CALLER_EMAIL = "tomi.tenant@example.com"
LEASE_COUNTS = [0, 1, 2]


def check(client, token: str, headers: dict | None = None):
    return client.post(ACCEPTANCE_PREVIEW_URL, json={"token": token}, headers=headers)


def accept(client, token: str, headers: dict | None = None, **extra):
    return client.post(ACCEPTANCE_URL, json={"token": token, **extra}, headers=headers)


def accept_ok(client, token: str, headers: dict, **extra) -> None:
    response = accept(client, token, headers, **extra)
    assert response.status_code == 204, response.text
    assert response.content == b""


def ordered(rows, *columns):
    return sorted(
        (tuple(getattr(row, c) for c in columns) for row in rows),
        key=lambda item: tuple(str(v) for v in item),
    )


def snapshot(database) -> dict:
    """Everything a refused acceptance must leave untouched."""
    from app.models import (
        EmergencyContact,
        Invitation,
        Lease,
        Notification,
        Tenant,
        UserAccount,
        UserSession,
    )

    return {
        "users": ordered(
            fetch_all(database, UserAccount),
            "id",
            "name",
            "email",
            "password_hash",
            "role",
            "email_verified",
            "status",
            "deleted_at",
        ),
        "tenants": ordered(
            fetch_all(database, Tenant),
            "id",
            "user_id",
            "phone",
            "occupation",
            "activated_at",
            "deleted_at",
        ),
        "contacts": ordered(
            fetch_all(database, EmergencyContact),
            "id",
            "tenant_id",
            "name",
            "relationship",
            "phone",
            "position",
        ),
        "leases": ordered(
            fetch_all(database, Lease),
            "id",
            "tenant_id",
            "room_id",
            "rent",
            "ended_at",
        ),
        "invitations": ordered(
            fetch_all(database, Invitation),
            "id",
            "tenant_id",
            "token_hash",
            "expires_at",
            "used_at",
            "invalidated_at",
        ),
        "sessions": ordered(fetch_all(database, UserSession), "id", "revoked_at"),
        "notifications": len(fetch_all(database, Notification)),
        "codes": code_count(database),
    }


def tenant_row(database, record_id):
    from app.models import Tenant

    with Session(database, expire_on_commit=False) as db:
        return db.get(Tenant, record_id)


def contact_rows(database, record_id) -> list:
    from app.models import EmergencyContact

    with Session(database, expire_on_commit=False) as db:
        rows = db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.tenant_id == record_id)
            .order_by(EmergencyContact.position)
        )
        return [(r.position, r.name, r.relationship, r.phone) for r in rows]


def leases_of(database, record_id) -> list:
    from app.models import Lease

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(Lease).where(Lease.tenant_id == record_id)))


def records_of(database, user_id) -> list:
    from app.models import Tenant

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(Tenant).where(Tenant.user_id == user_id)))


def my_leases(client, headers) -> list[dict]:
    response = client.get("/me/leases", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def melati(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def staff(make_user, melati, assign_manager, sign_in):
    """A Manager assigned to the property of the invitation, signed in."""
    user = make_user(name="Mira Manager", role=role("manager"))
    assign_manager(user, melati)
    return SimpleNamespace(user=user, headers=sign_in(user).headers)


@pytest.fixture
def invited(melati, make_room, make_tenant):
    """A record management added, with contacts, an id of its own and an invitation."""
    return make_tenant(
        make_room(melati, number="A1"),
        name="Budi Tenant",
        phone="081298765432",
        occupation="Mahasiswa",
        contacts=STORED_CONTACTS,
        start_date=date(2099, 1, 10),
        end_date=date(2099, 12, 31),
        billing_cycle="quarterly",
        rent=1250000,
        grace_period_days=4,
        distinct_id=True,
    )


@pytest.fixture
def bare(melati, make_room, make_tenant):
    """A record management added without any emergency contact."""
    return make_tenant(
        make_room(melati, number="A2"),
        name="Dewi Tenant",
        phone="081277776666",
        distinct_id=True,
    )


@pytest.fixture
def make_renter(make_user, make_property, make_room, make_verified_tenant, sign_in):
    """Build a signed-in Tenant account that already rents `leases` rooms elsewhere.

    With `ended`, those leases have ended; with no leases the account has no
    record at all.
    """

    def build(leases: int = 1, *, ended: bool = False):
        far = make_property(make_user(name="Far Owner"), name="Kos Jauh")
        user = None
        records = []
        for number in range(leases):
            room = make_room(far, number=f"Z{number + 1}")
            if user is None:
                stored = make_verified_tenant(
                    room, name=CALLER_NAME, email=CALLER_EMAIL, lease_ended=ended
                )
                user = stored.user
            else:
                stored = make_verified_tenant(room, user=user, lease_ended=ended)
            records.append(stored)
        if user is None:
            user = make_user(name=CALLER_NAME, email=CALLER_EMAIL, role=role("tenant"))
        return SimpleNamespace(
            user=user,
            id=user.id,
            records=records,
            headers=sign_in(user).headers,
            far=far,
        )

    return build


# Preview


@pytest.mark.parametrize("leases", LEASE_COUNTS)
def test_a_tenant_can_accept_whatever_leases_they_already_have(
    client, database, invited, make_renter, leases
):
    renter = make_renter(leases)
    response = check(client, invited.token, renter.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PREVIEW_FIELDS
    assert body["accountName"] == CALLER_NAME
    assert body["accountEmail"] == CALLER_EMAIL
    assert body["accountRole"] == "tenant"
    assert body["canAccept"] is True
    assert body["blocker"] is None


def test_a_tenant_whose_leases_ended_can_accept(client, database, invited, make_renter):
    renter = make_renter(1, ended=True)
    body = check(client, invited.token, renter.headers).json()
    assert body["canAccept"] is True
    assert body["blocker"] is None


def test_the_preview_describes_the_invited_record(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    body = check(client, invited.token, renter.headers).json()
    assert body["invitation"] == preview(client, invited.token).json()
    assert body["invitation"]["role"] == "tenant"
    assert body["invitation"]["status"] == "valid"
    assert body["invitation"]["inviterName"] == "Rina Owner"
    assert body["invitation"]["roomNumber"] == "A1"
    assert body["invitation"]["name"] == "Budi Tenant"
    assert body["invitation"]["properties"] == [
        {"name": "Kos Melati", "address": "Jl. Melati 5"}
    ]
    assert body["invitation"]["emergencyContactsRequired"] is False


def test_the_preview_says_when_emergency_contacts_are_required(
    client, database, bare, make_renter
):
    renter = make_renter(1)
    body = check(client, bare.token, renter.headers).json()
    assert body["invitation"]["emergencyContactsRequired"] is True
    assert body["canAccept"] is True


def test_the_preview_names_the_calling_account_not_the_invited_one(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    body = check(client, invited.token, renter.headers).json()
    assert body["accountName"] != body["invitation"]["name"]


def test_the_preview_changes_nothing_and_can_be_repeated(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    before = snapshot(database)
    first = check(client, invited.token, renter.headers)
    second = check(client, invited.token, renter.headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert snapshot(database) == before


def make_link(database, make_room, make_tenant, melati, how: str):
    """A Tenant invitation that is used, replaced or already activated."""
    stored = make_tenant(
        make_room(melati, number="B1"),
        contacts=STORED_CONTACTS,
        activated=(how == "activated"),
    )
    if how == "used":
        edit_invitation(database, stored.token, used_at=datetime.now(UTC))
    if how == "invalidated":
        edit_invitation(database, stored.token, invalidated_at=datetime.now(UTC))
    return stored


@pytest.mark.parametrize("how", ["used", "invalidated", "activated"])
def test_a_used_link_cannot_be_accepted_and_has_no_blocker(
    client, database, melati, make_room, make_tenant, make_renter, how
):
    stored = make_link(database, make_room, make_tenant, melati, how)
    renter = make_renter(1)
    body = check(client, stored.token, renter.headers).json()
    assert body["invitation"]["status"] == "used"
    assert body["canAccept"] is False
    assert body["blocker"] is None


def test_an_expired_link_cannot_be_accepted_and_has_no_blocker(
    client, database, melati, make_room, make_tenant, make_renter
):
    stored = make_tenant(make_room(melati, number="B1"), expired=True)
    body = check(client, stored.token, make_renter(1).headers).json()
    assert body["invitation"]["status"] == "expired"
    assert body["canAccept"] is False
    assert body["blocker"] is None


def test_the_preview_of_a_deleted_records_link_is_not_found(
    client, database, melati, make_room, make_tenant, make_renter
):
    stored = make_tenant(make_room(melati, number="B1"), deleted=True)
    response = check(client, stored.token, make_renter(1).headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")


def test_the_preview_after_the_acceptance_cannot_accept_again(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    body = check(client, invited.token, renter.headers).json()
    assert body["invitation"]["status"] == "used"
    assert body["canAccept"] is False
    assert body["blocker"] is None


# Accepting: the record moves


@pytest.mark.parametrize("leases", LEASE_COUNTS)
def test_accepting_answers_with_no_content(
    client, database, invited, make_renter, leases
):
    renter = make_renter(leases)
    response = accept(client, invited.token, renter.headers)
    assert response.status_code == 204, response.text
    assert response.content == b""


@pytest.mark.parametrize("leases", LEASE_COUNTS)
def test_the_record_moves_to_the_calling_account_and_keeps_its_id(
    client, database, invited, make_renter, leases
):
    renter = make_renter(leases)
    assert invited.id != invited.user.id
    accept_ok(client, invited.token, renter.headers)
    record = tenant_row(database, invited.id)
    assert record.id == invited.id
    assert record.user_id == renter.id
    assert record.deleted_at is None
    assert record.phone == "081298765432"
    assert record.occupation == "Mahasiswa"
    assert len(fetch_all(database, type(record))) == leases + 1


def test_the_record_is_marked_activated(client, database, invited, make_renter):
    renter = make_renter(1)
    before = datetime.now(UTC)
    accept_ok(client, invited.token, renter.headers)
    activated_at = tenant_row(database, invited.id).activated_at
    assert before - timedelta(seconds=5) <= activated_at <= datetime.now(UTC)


def test_the_invitation_is_used_and_not_invalidated(
    client, database, invited, make_renter
):
    from app.models import Invitation

    renter = make_renter(1)
    before = datetime.now(UTC)
    accept_ok(client, invited.token, renter.headers)
    (row,) = [i for i in fetch_all(database, Invitation) if i.tenant_id == invited.id]
    assert before - timedelta(seconds=5) <= row.used_at <= datetime.now(UTC)
    assert row.invalidated_at is None


def test_the_lease_and_the_emergency_contacts_stay_with_the_record(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    (lease,) = leases_of(database, invited.id)
    assert lease.id == invited.lease.id
    assert lease.room_id == invited.lease.room_id
    assert lease.rent == 1250000
    assert lease.billing_cycle == "quarterly"
    assert lease.grace_period_days == 4
    assert lease.start_date == date(2099, 1, 10)
    assert lease.end_date == date(2099, 12, 31)
    assert lease.ended_at is None
    assert contact_rows(database, invited.id) == [
        (0, "Siti", "Ibu", "081234567890"),
        (1, "Agus", "Kakak", "08571234567"),
    ]


@pytest.mark.parametrize("leases", LEASE_COUNTS)
def test_the_callers_name_email_password_and_sessions_are_untouched(
    client, database, invited, make_renter, sent_emails, leases
):
    renter = make_renter(leases)
    set_password(database, renter.user)
    before = snapshot(database)
    accept_ok(client, invited.token, renter.headers)
    after = snapshot(database)
    assert after["users"] == before["users"]
    assert after["sessions"] == before["sessions"]
    assert after["codes"] == before["codes"]
    user = stored_user(database, renter.id)
    assert user.name == CALLER_NAME
    assert user.email == CALLER_EMAIL
    assert user.email_verified is True
    assert sent_emails == []


def test_the_callers_other_records_and_leases_are_untouched(
    client, database, invited, make_renter
):
    renter = make_renter(2)
    before = snapshot(database)
    accept_ok(client, invited.token, renter.headers)
    after = snapshot(database)
    kept = {r.id for r in renter.records}
    assert {row for row in before["tenants"] if row[0] in kept} == {
        row for row in after["tenants"] if row[0] in kept
    }
    assert {row for row in before["leases"] if row[1] in kept} == {
        row for row in after["leases"] if row[1] in kept
    }
    assert {row for row in before["contacts"] if row[1] in kept} == {
        row for row in after["contacts"] if row[1] in kept
    }


def test_the_callers_session_keeps_working(client, database, invited, make_renter):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    assert client.get("/me", headers=renter.headers).status_code == 200


@pytest.mark.parametrize("leases", LEASE_COUNTS)
def test_the_new_lease_is_listed_among_the_callers_leases(
    client, database, invited, make_renter, leases
):
    renter = make_renter(leases)
    before = my_leases(client, renter.headers)
    assert len(before) == leases
    accept_ok(client, invited.token, renter.headers)
    after = my_leases(client, renter.headers)
    assert len(after) == leases + 1
    (new,) = [i for i in after if i["tenantId"] == str(invited.id)]
    assert new["room"]["number"] == "A1"
    assert new["property"]["name"] == "Kos Melati"
    assert new["rent"] == 1250000
    assert new["billingCycle"] == "quarterly"
    assert new["startDate"] == "2099-01-10"
    assert new["endDate"] == "2099-12-31"
    kept = {i["tenantId"] for i in before}
    assert kept <= {i["tenantId"] for i in after}


def test_a_caller_with_a_lease_in_the_same_property_can_accept_too(
    client, database, melati, invited, make_room, make_verified_tenant, sign_in
):
    resident = make_verified_tenant(make_room(melati, number="C1"), name=CALLER_NAME)
    headers = sign_in(resident.user).headers
    accept_ok(client, invited.token, headers)
    numbers = [i["room"]["number"] for i in my_leases(client, headers)]
    assert numbers == ["A1", "C1"]


def test_a_caller_can_accept_two_invitations_one_after_the_other(
    client, database, invited, bare, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    accept_ok(client, bare.token, renter.headers, emergencyContacts=CONTACTS)
    ids = {i["tenantId"] for i in my_leases(client, renter.headers)}
    assert ids == {str(renter.records[0].id), str(invited.id), str(bare.id)}
    assert {r.user_id for r in records_of(database, renter.id)} == {renter.id}
    assert len(records_of(database, renter.id)) == 3


def test_a_caller_whose_leases_ended_gets_the_new_one_listed_alone(
    client, database, invited, make_renter
):
    renter = make_renter(1, ended=True)
    accept_ok(client, invited.token, renter.headers)
    assert [i["tenantId"] for i in my_leases(client, renter.headers)] == [
        str(invited.id)
    ]


# Accepting: what management sees


def test_management_sees_the_record_as_active_under_the_callers_account(
    client, database, invited, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    response = client.get(f"/tenants/{invited.id}", headers=owner_in.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(invited.id)
    assert body["accountStatus"] == "active"
    assert body["name"] == CALLER_NAME
    assert body["email"] == CALLER_EMAIL
    assert body["invitation"] is None
    assert body["phone"] == "081298765432"
    assert body["occupation"] == "Mahasiswa"
    assert body["room"]["number"] == "A1"
    assert body["lease"]["rent"] == 1250000
    assert body["emergencyContacts"] == [
        {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
        {"name": "Agus", "relationship": "Kakak", "phone": "08571234567"},
    ]


def test_the_property_list_shows_the_callers_name_for_the_record(
    client, database, melati, invited, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    response = client.get(f"/properties/{melati.id}/tenants", headers=owner_in.headers)
    (item,) = response.json()["items"]
    assert item["id"] == str(invited.id)
    assert item["name"] == CALLER_NAME
    assert item["accountStatus"] == "active"
    assert item["invitationExpiresAt"] is None


def test_the_room_shows_the_callers_name_and_the_record_id(
    client, database, invited, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    room_id = invited.lease.room_id
    lease = client.get(f"/rooms/{room_id}", headers=owner_in.headers).json()["lease"]
    assert lease["tenantId"] == str(invited.id)
    assert lease["tenantName"] == CALLER_NAME
    assert lease["tenantPhone"] == "081298765432"


def test_the_name_of_the_accepted_record_is_locked_to_the_account(
    client, database, invited, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    body = {
        "name": "Someone Else",
        "phone": "081298765432",
        "emergencyContacts": [
            {"name": n, "relationship": r, "phone": p} for n, r, p in STORED_CONTACTS
        ],
    }
    response = client.put(f"/tenants/{invited.id}", json=body, headers=owner_in.headers)
    assert_error(response, 422, "TENANT_NAME_NOT_EDITABLE", "name")
    response = client.put(
        f"/tenants/{invited.id}",
        json={**body, "name": CALLER_NAME},
        headers=owner_in.headers,
    )
    assert response.status_code == 200, response.text


def test_no_new_link_can_be_made_for_the_accepted_record(
    client, database, invited, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    response = client.post(
        f"/tenants/{invited.id}/invitation", headers=owner_in.headers
    )
    assert_error(response, 409, "TENANT_ALREADY_ACTIVE")


def test_an_expired_link_renewed_by_management_can_be_accepted(
    client, database, melati, make_room, make_tenant, make_renter, owner_in
):
    stored = make_tenant(
        make_room(melati, number="B1"), contacts=STORED_CONTACTS, expired=True
    )
    renewed = client.post(f"/tenants/{stored.id}/invitation", headers=owner_in.headers)
    assert renewed.status_code == 201, renewed.text
    renter = make_renter(1)
    assert accept(client, stored.token, renter.headers).status_code == 409
    accept_ok(client, token_of(renewed.json()["url"]), renter.headers)
    assert tenant_row(database, stored.id).user_id == renter.id


def test_the_rent_bills_of_the_new_lease_show_to_the_caller(
    client, database, invited, make_renter, make_rent_bill, frozen_today
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    bill = make_rent_bill(invited.lease)
    listed = client.get("/rent-bills", headers=renter.headers).json()["items"]
    assert [i["id"] for i in listed] == [str(bill.id)]
    detail = client.get(f"/rent-bills/{bill.id}", headers=renter.headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["tenant"] == {"id": str(invited.id), "name": CALLER_NAME}


def test_the_caller_can_complain_about_the_new_room(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    response = client.post(
        "/complaints",
        json={
            "description": "The tap in the bathroom leaks badly.",
            "roomId": str(invited.lease.room_id),
        },
        headers=renter.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["room"]["number"] == "A1"
    assert response.json()["tenantName"] == CALLER_NAME


# Accepting: the placeholder account


def test_the_placeholder_account_stays_without_records_or_credentials(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    placeholder_id = invited.user.id
    accept_ok(client, invited.token, renter.headers)
    placeholder = stored_user(database, placeholder_id)
    assert placeholder is not None
    assert placeholder.email is None
    assert placeholder.password_hash is None
    assert placeholder.name == "Budi Tenant"
    assert records_of(database, placeholder_id) == []


def test_the_placeholder_account_is_hidden_from_the_admin(
    client, database, admin_in, invited, make_renter
):
    renter = make_renter(1)
    placeholder_id = invited.user.id
    accept_ok(client, invited.token, renter.headers)
    assert str(placeholder_id) not in listed_ids(client, admin_in.headers)
    assert str(placeholder_id) not in listed_ids(
        client, admin_in.headers, includeDeleted="true"
    )
    assert_error(
        get_account(client, admin_in.headers, placeholder_id),
        404,
        "USER_ACCOUNT_NOT_FOUND",
    )


def test_the_admin_sees_every_lease_of_the_caller(
    client, database, admin_in, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    body = get_account(client, admin_in.headers, renter.id).json()
    assert body["activeLeaseCount"] == 2
    assert sorted(t["roomNumber"] for t in body["tenancies"]) == ["A1", "Z1"]
    assert body["status"] == "active"


# Emergency contacts


def test_stored_contacts_are_kept_and_the_submitted_ones_ignored(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers, emergencyContacts=CONTACTS)
    assert contact_rows(database, invited.id) == [
        (0, "Siti", "Ibu", "081234567890"),
        (1, "Agus", "Kakak", "08571234567"),
    ]


def test_null_contacts_are_fine_when_management_stored_them(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers, emergencyContacts=None)


def test_contacts_are_required_when_none_are_stored(
    client, database, bare, make_renter
):
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, bare.token, renter.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert snapshot(database) == before
    assert preview_status(client, bare.token) == "valid"


def test_null_contacts_are_refused_when_they_are_required(
    client, database, bare, make_renter
):
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, bare.token, renter.headers, emergencyContacts=None)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert snapshot(database) == before


@pytest.mark.parametrize("count", [1, 5])
def test_too_few_or_too_many_contacts_are_refused(
    client, database, bare, make_renter, count
):
    renter = make_renter(1)
    before = snapshot(database)
    contacts = (CONTACTS * 3)[:count]
    response = accept(client, bare.token, renter.headers, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert snapshot(database) == before


@pytest.mark.parametrize("count", [2, 3, 4])
def test_two_to_four_contacts_are_stored_in_submitted_order(
    client, database, bare, make_renter, count
):
    renter = make_renter(1)
    contacts = [
        {"name": f"Zed {n}", "relationship": "Teman", "phone": f"08123456789{n}"}
        for n in reversed(range(count))
    ]
    accept_ok(client, bare.token, renter.headers, emergencyContacts=contacts)
    rows = contact_rows(database, bare.id)
    assert [r[0] for r in rows] == list(range(count))
    assert [r[1] for r in rows] == [c["name"] for c in contacts]
    assert tenant_row(database, bare.id).user_id == renter.id


def test_submitted_contacts_are_stored_with_normalized_phones(
    client, database, bare, make_renter
):
    renter = make_renter(1)
    contacts = [
        {"name": "A", "relationship": "Ibu", "phone": "0812-3456-789"},
        {"name": "B", "relationship": "Ayah", "phone": "62 812 3456 789"},
    ]
    accept_ok(client, bare.token, renter.headers, emergencyContacts=contacts)
    assert contact_rows(database, bare.id) == [
        (0, "A", "Ibu", "08123456789"),
        (1, "B", "Ayah", "08123456789"),
    ]


def test_submitted_contacts_show_in_the_tenant_detail(
    client, database, bare, make_renter, owner_in
):
    renter = make_renter(1)
    accept_ok(client, bare.token, renter.headers, emergencyContacts=CONTACTS)
    body = client.get(f"/tenants/{bare.id}", headers=owner_in.headers).json()
    assert body["emergencyContacts"] == [
        {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
        {"name": "Wati", "relationship": "Adik", "phone": "08222222222"},
    ]


@pytest.mark.parametrize("field", ["name", "relationship"])
@pytest.mark.parametrize("index", [0, 1])
def test_a_blank_contact_text_is_refused_and_nothing_is_saved(
    client, database, bare, make_renter, field, index
):
    renter = make_renter(1)
    contacts = [dict(c) for c in CONTACTS]
    contacts[index][field] = "   "
    before = snapshot(database)
    response = accept(client, bare.token, renter.headers, emergencyContacts=contacts)
    assert_error(
        response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.{field}"
    )
    assert snapshot(database) == before


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("phone", ["+628123456789", "12345", "abc", "081234567"])
def test_an_invalid_contact_phone_is_refused_and_nothing_is_saved(
    client, database, bare, make_renter, index, phone
):
    renter = make_renter(1)
    contacts = [dict(c) for c in CONTACTS]
    contacts[index]["phone"] = phone
    before = snapshot(database)
    response = accept(client, bare.token, renter.headers, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.phone")
    assert snapshot(database) == before


# Refusals


def test_an_unknown_token_is_not_found(client, database, invited, make_renter):
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, "unknown-token", renter.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert snapshot(database) == before


def test_the_token_of_a_deleted_record_is_not_found(
    client, database, melati, make_room, make_tenant, make_renter
):
    stored = make_tenant(make_room(melati, number="B1"), deleted=True)
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, stored.token, renter.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert snapshot(database) == before


@pytest.mark.parametrize("how", ["used", "invalidated", "activated"])
def test_a_used_link_is_refused(
    client, database, melati, make_room, make_tenant, make_renter, how
):
    stored = make_link(database, make_room, make_tenant, melati, how)
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, stored.token, renter.headers)
    assert_error(response, 409, "INVITATION_USED")
    assert snapshot(database) == before


def test_a_replaced_link_is_used_and_the_new_one_works(
    client, database, invited, make_renter, owner_in
):
    renter = make_renter(1)
    renewed = client.post(f"/tenants/{invited.id}/invitation", headers=owner_in.headers)
    new_token = token_of(renewed.json()["url"])
    assert_error(accept(client, invited.token, renter.headers), 409, "INVITATION_USED")
    accept_ok(client, new_token, renter.headers)
    assert tenant_row(database, invited.id).user_id == renter.id


def test_used_wins_over_expired(client, database, invited, make_renter):
    renter = make_renter(1)
    edit_invitation(
        database,
        invited.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(accept(client, invited.token, renter.headers), 409, "INVITATION_USED")


def test_an_expired_link_is_refused(
    client, database, melati, make_room, make_tenant, make_renter
):
    stored = make_tenant(
        make_room(melati, number="B1"), contacts=STORED_CONTACTS, expired=True
    )
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, stored.token, renter.headers)
    assert_error(response, 409, "INVITATION_EXPIRED")
    assert snapshot(database) == before
    assert preview_status(client, stored.token) == "expired"


@pytest.mark.parametrize("kind", ["owner", "admin"])
def test_a_tenant_link_is_refused_for_an_owner_or_an_admin(
    client, database, invited, make_user, sign_in, kind
):
    headers = sign_in(make_user(role=role(kind))).headers
    before = snapshot(database)
    response = accept(client, invited.token, headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before
    assert preview_status(client, invited.token) == "valid"


def test_a_tenant_link_is_refused_for_a_manager(client, database, invited, staff):
    before = snapshot(database)
    response = accept(client, invited.token, staff.headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before


def test_a_manager_link_is_refused_for_a_tenant(
    client, database, owner, melati, make_manager, make_renter
):
    link = make_manager(owner, [melati])
    renter = make_renter(1)
    before = snapshot(database)
    response = accept(client, link.token, renter.headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before


@pytest.mark.parametrize("kind", ["owner", "admin"])
def test_the_link_is_checked_before_the_role(
    client, database, invited, make_user, sign_in, kind
):
    headers = sign_in(make_user(role=role(kind))).headers
    edit_invitation(database, invited.token, used_at=datetime.now(UTC))
    assert_error(accept(client, invited.token, headers), 409, "INVITATION_USED")
    edit_invitation(
        database,
        invited.token,
        used_at=None,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(accept(client, invited.token, headers), 409, "INVITATION_EXPIRED")


def test_an_active_lease_never_blocks_the_acceptance(
    client, database, invited, make_renter
):
    renter = make_renter(2)
    response = accept(client, invited.token, renter.headers)
    assert response.status_code == 204, response.text


def test_the_link_is_checked_before_the_contacts(client, database, bare, make_renter):
    renter = make_renter(1)
    edit_invitation(database, bare.token, used_at=datetime.now(UTC))
    response = accept(client, bare.token, renter.headers)
    assert_error(response, 409, "INVITATION_USED")


def test_the_second_acceptance_of_a_link_is_refused_even_for_another_tenant(
    client, database, invited, make_renter, make_user, sign_in
):
    first = make_renter(1)
    accept_ok(client, invited.token, first.headers)
    other = sign_in(make_user(name="Lain Tenant", role=role("tenant"))).headers
    before = snapshot(database)
    assert_error(accept(client, invited.token, other), 409, "INVITATION_USED")
    assert snapshot(database) == before
    assert tenant_row(database, invited.id).user_id == first.id


def test_the_same_caller_cannot_accept_a_link_twice(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    before = snapshot(database)
    assert_error(accept(client, invited.token, renter.headers), 409, "INVITATION_USED")
    assert snapshot(database) == before
    assert len(records_of(database, renter.id)) == 2


def test_another_pending_invitation_is_left_alone(
    client, database, invited, bare, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    assert preview_status(client, bare.token) == "valid"
    assert tenant_row(database, bare.id).user_id == bare.user.id


# Notification


@pytest.mark.parametrize("who", ["owner_in", "staff"])
def test_accepting_notifies_the_owner_and_the_assigned_manager(
    client, database, melati, invited, make_renter, owner_in, staff, who
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    recipient = (
        owner_in if who == "owner_in" else SimpleNamespace(headers=staff.headers)
    )
    item = only(client, recipient, "tenantActivated")
    assert_item(
        item,
        "tenantActivated",
        tenant=tenant_ref(invited, CALLER_NAME),
        room=room_ref(SimpleNamespace(id=invited.lease.room_id, number="A1")),
        property=property_ref(melati),
    )
    assert types(client, recipient) == ["tenantActivated"]


def test_the_notification_names_the_property_of_the_accepted_record_only(
    client, database, owner, melati, invited, make_renter, owner_in
):
    renter = make_renter(2)
    accept_ok(client, invited.token, renter.headers)
    item = only(client, owner_in, "tenantActivated")
    assert item["property"]["name"] == "Kos Melati"
    assert item["room"]["number"] == "A1"
    assert item["tenant"]["id"] == str(invited.id)
    (row,) = stored_for(database, owner)
    assert row["property_id"] == melati.id


def test_accepting_notifies_nobody_else(
    client, database, invited, make_renter, staff, make_user, sign_in
):
    renter = make_renter(1)
    stranger = sign_in(make_user(name="Other Owner"))
    accept_ok(client, invited.token, renter.headers)
    assert stored_for(database, renter.user) == []
    assert items(client, stranger) == []
    assert len(stored_rows(database)) == 2


def test_a_refused_acceptance_creates_no_notification(
    client, database, bare, make_renter
):
    renter = make_renter(1)
    assert accept(client, bare.token, renter.headers).status_code == 422
    assert accept(client, "unknown-token", renter.headers).status_code == 404
    assert stored_rows(database) == []


def test_accepting_twice_creates_no_second_notification(
    client, database, invited, make_renter
):
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    assert accept(client, invited.token, renter.headers).status_code == 409
    assert len(stored_rows(database)) == 1


class Hook:
    """Stands in for the hook that announces an activated Tenant."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bool, object]] = []
        self.error = error

    def __call__(self, db, tenant_id) -> None:
        self.calls.append((isinstance(db, Session), tenant_id))
        if self.error is not None:
            raise self.error


def test_the_activation_hook_is_called_once_on_success(
    client, database, invited, make_renter, monkeypatch
):
    hook = Hook()
    monkeypatch.setattr(HOOK, hook)
    renter = make_renter(1)
    accept_ok(client, invited.token, renter.headers)
    assert len(hook.calls) == 1
    assert hook.calls[0][0] is True


def test_the_activation_hook_is_not_called_for_a_refused_acceptance(
    client, database, bare, make_renter, make_user, sign_in, monkeypatch
):
    hook = Hook()
    monkeypatch.setattr(HOOK, hook)
    renter = make_renter(1)
    owner_headers = sign_in(make_user(name="Some Owner")).headers
    accept(client, "unknown-token", renter.headers)
    accept(client, bare.token, renter.headers)
    accept(client, bare.token, owner_headers, emergencyContacts=CONTACTS)
    assert hook.calls == []


def test_a_failing_activation_hook_does_not_undo_the_acceptance(
    client, database, invited, make_renter, monkeypatch
):
    hook = Hook(error=RuntimeError("notification down"))
    monkeypatch.setattr(HOOK, hook)
    renter = make_renter(1)
    response = accept(client, invited.token, renter.headers)
    assert response.status_code == 204, response.text
    assert len(hook.calls) == 1
    assert tenant_row(database, invited.id).user_id == renter.id
    assert tenant_row(database, invited.id).activated_at is not None
    assert preview_status(client, invited.token) == "used"
    assert stored_rows(database) == []
