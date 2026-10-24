"""Reading the calling tenant's own lease."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

LEASE_URL = "/me/lease"
LEASE_FIELDS = {
    "room",
    "property",
    "startDate",
    "endDate",
    "rent",
    "billingCycle",
}
ROOM_FIELDS = {"id", "number", "facilities", "lengthM", "widthM"}
PROPERTY_FIELDS = {"id", "name", "address"}
CONTACTS = [
    {"name": "Siti", "relationship": "Ibu", "phone": "081234567890"},
    {"name": "Agus", "relationship": "Kakak", "phone": "628571234567"},
]


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def end_lease(database, lease) -> None:
    from app.models import Lease

    with Session(database) as db:
        db.get(Lease, lease.id).ended_at = datetime.now(UTC)
        db.commit()


def set_view_only(database, model, row, value: bool = True) -> None:
    with Session(database) as db:
        db.get(model, row.id).view_only = value
        db.commit()


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def room(prop, make_room):
    return make_room(prop, number="A1", base_rate=1750000)


def get_lease(client, tenant_in):
    return client.get(LEASE_URL, headers=tenant_in.headers)


def lease_of(client, sign_in, tenant) -> dict:
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    return response.json()


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database):
    assert_error(client.get(LEASE_URL), 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database):
    response = client.get(LEASE_URL, headers={"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_tenant_with_an_unverified_email_is_rejected(
    client, database, make_user, sign_in
):
    user = make_user(role=role("tenant"), email_verified=False)
    assert_error(
        get_lease(client, sign_in(user)),
        403,
        "EMAIL_NOT_VERIFIED",
    )


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_staff_and_admins_are_forbidden(client, database, make_user, sign_in, name):
    session = sign_in(make_user(role=role(name)))
    assert_error(get_lease(client, session), 403, "FORBIDDEN")


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_an_unverified_non_tenant_is_told_to_verify_the_email(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(get_lease(client, session), 403, "EMAIL_NOT_VERIFIED")


# Success


def test_a_tenant_with_an_active_lease_gets_exactly_the_lease_fields(
    client, database, prop, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    body = lease_of(client, sign_in, tenant)
    assert set(body) == {"lease"}
    assert set(body["lease"]) == LEASE_FIELDS
    assert set(body["lease"]["room"]) == ROOM_FIELDS
    assert set(body["lease"]["property"]) == PROPERTY_FIELDS


def test_the_lease_carries_the_stored_room(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    room = make_room(
        prop,
        number="B7",
        facilities=["ac", "wifi"],
        length_m=3.5,
        width_m=4,
    )
    tenant = make_verified_tenant(room)
    assert lease_of(client, sign_in, tenant)["lease"]["room"] == {
        "id": str(room.id),
        "number": "B7",
        "facilities": ["ac", "wifi"],
        "lengthM": 3.5,
        "widthM": 4,
    }


def test_a_room_without_facilities_or_dimensions_answers_empty_and_null(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    assert lease_of(client, sign_in, tenant)["lease"]["room"] == {
        "id": str(room.id),
        "number": "A1",
        "facilities": [],
        "lengthM": None,
        "widthM": None,
    }


def test_a_single_facility_is_listed(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    room = make_room(prop, facilities=["kamar mandi dalam"])
    tenant = make_verified_tenant(room)
    facilities = lease_of(client, sign_in, tenant)["lease"]["room"]["facilities"]
    assert facilities == ["kamar mandi dalam"]


def test_many_facilities_are_all_listed(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    tags = ["ac", "wifi", "kasur", "lemari", "meja", "kamar mandi dalam"]
    room = make_room(prop, facilities=tags)
    tenant = make_verified_tenant(room)
    facilities = lease_of(client, sign_in, tenant)["lease"]["room"]["facilities"]
    assert sorted(facilities) == sorted(tags)


def test_the_lease_carries_the_property_name_and_address(
    client, database, prop, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    assert lease_of(client, sign_in, tenant)["lease"]["property"] == {
        "id": str(prop.id),
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
    }


def test_the_lease_carries_its_dates_when_set(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(
        room, start_date=date(2099, 1, 10), end_date=date(2099, 12, 31)
    )
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert lease["startDate"] == "2099-01-10"
    assert lease["endDate"] == "2099-12-31"


def test_the_lease_dates_are_null_when_unset(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, start_date=None, end_date=None)
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert lease["startDate"] is None
    assert lease["endDate"] is None


def test_an_open_ended_lease_has_a_start_date_and_a_null_end_date(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, start_date=date(2099, 3, 1), end_date=None)
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert lease["startDate"] == "2099-03-01"
    assert lease["endDate"] is None


@pytest.mark.parametrize(
    "cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"]
)
def test_the_lease_carries_its_billing_cycle(
    client, database, room, make_verified_tenant, sign_in, cycle
):
    tenant = make_verified_tenant(room, billing_cycle=cycle)
    assert lease_of(client, sign_in, tenant)["lease"]["billingCycle"] == cycle


def test_the_rent_is_the_lease_rent_and_not_the_room_base_rate(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, rent=1234500)
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert room.base_rate == 1750000
    assert lease["rent"] == 1234500


def test_the_rent_is_an_integer_of_rupiah_per_billing_cycle(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, billing_cycle="quarterly", rent=4800000)
    rent = lease_of(client, sign_in, tenant)["lease"]["rent"]
    assert rent == 4800000
    assert isinstance(rent, int)


def test_the_rent_equal_to_the_base_rate_is_returned_as_is(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, rent=1750000)
    assert lease_of(client, sign_in, tenant)["lease"]["rent"] == 1750000


def test_the_lease_never_exposes_bank_account_or_owner_details(
    client, database, room, make_verified_tenant, sign_in, owner
):
    from app.models import Property

    with Session(database) as db:
        row = db.get(Property, room.property_id)
        row.bank_name = "Bank Mandiri"
        row.bank_account_number = "1234567890"
        row.bank_account_holder_name = "Rina Owner"
        db.commit()
    tenant = make_verified_tenant(room)
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    lease = response.json()["lease"]
    assert set(lease["property"]) == PROPERTY_FIELDS
    for secret in ("Bank Mandiri", "1234567890", "Rina Owner", str(owner.id)):
        assert secret not in response.text


def test_the_lease_does_not_expose_other_rooms_of_the_property(
    client, database, prop, room, make_room, make_verified_tenant, sign_in
):
    make_room(prop, number="Z9")
    tenant = make_verified_tenant(room)
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert "Z9" not in response.text


def test_the_lease_does_not_expose_the_tenant_account_or_grace_period(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, grace_period_days=5, phone="081299990000")
    response = get_lease(client, sign_in(tenant.user))
    lease = response.json()["lease"]
    assert set(lease) == LEASE_FIELDS
    assert "081299990000" not in response.text


# Which lease is returned


def test_a_tenant_gets_their_own_lease_among_other_tenants_and_rooms(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    room_a = make_room(prop, number="A1", facilities=["ac"])
    room_b = make_room(prop, number="A2", facilities=["wifi"])
    room_c = make_room(prop, number="A3")
    tenant_a = make_verified_tenant(room_a, rent=1100000, billing_cycle="weekly")
    tenant_b = make_verified_tenant(room_b, rent=2200000, billing_cycle="annual")
    make_verified_tenant(room_c, rent=3300000)
    lease_a = lease_of(client, sign_in, tenant_a)["lease"]
    lease_b = lease_of(client, sign_in, tenant_b)["lease"]
    assert lease_a["room"]["id"] == str(room_a.id)
    assert lease_a["room"]["number"] == "A1"
    assert lease_a["room"]["facilities"] == ["ac"]
    assert lease_a["rent"] == 1100000
    assert lease_a["billingCycle"] == "weekly"
    assert lease_b["room"]["id"] == str(room_b.id)
    assert lease_b["room"]["number"] == "A2"
    assert lease_b["room"]["facilities"] == ["wifi"]
    assert lease_b["rent"] == 2200000
    assert lease_b["billingCycle"] == "annual"


def test_a_tenant_of_one_property_sees_only_that_property(
    client, database, make_user, make_property, make_room, make_verified_tenant, sign_in
):
    owner_a = make_user(name="Owner A")
    owner_b = make_user(name="Owner B")
    prop_a = make_property(owner_a, name="Kos Anggrek", address="Jl. Anggrek 1")
    prop_b = make_property(owner_b, name="Kos Dahlia", address="Jl. Dahlia 2")
    tenant_a = make_verified_tenant(make_room(prop_a, number="A1"))
    tenant_b = make_verified_tenant(make_room(prop_b, number="A1"))
    lease_a = lease_of(client, sign_in, tenant_a)["lease"]
    lease_b = lease_of(client, sign_in, tenant_b)["lease"]
    assert lease_a["property"] == {
        "id": str(prop_a.id),
        "name": "Kos Anggrek",
        "address": "Jl. Anggrek 1",
    }
    assert lease_b["property"] == {
        "id": str(prop_b.id),
        "name": "Kos Dahlia",
        "address": "Jl. Dahlia 2",
    }


def test_the_response_does_not_mention_other_properties(
    client, database, make_user, make_property, make_room, make_verified_tenant, sign_in
):
    other = make_property(make_user(name="Other"), name="Kos Dahlia")
    make_room(other, number="Q1")
    tenant = make_verified_tenant(make_room(make_property(make_user()), number="A1"))
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert "Kos Dahlia" not in response.text
    assert str(other.id) not in response.text


def test_the_lease_is_repeatable_across_calls(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    session = sign_in(tenant.user)
    first = get_lease(client, session)
    second = get_lease(client, session)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert first.json()["lease"] is not None


# No active lease


def test_a_tenant_whose_lease_has_ended_gets_a_null_lease(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    end_lease(database, tenant.lease)
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert response.json() == {"lease": None}


def test_a_tenant_whose_lease_was_created_already_ended_gets_a_null_lease(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, lease_ended=True)
    response = get_lease(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert response.json() == {"lease": None}


def test_a_tenant_without_a_lease_row_gets_a_null_lease(
    client, database, make_user, sign_in
):
    from app.models import Tenant

    user = make_user(role=role("tenant"), email_verified=True)
    with Session(database) as db:
        db.add(Tenant(user_id=user.id, phone="081234567890"))
        db.commit()
    response = get_lease(client, sign_in(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"lease": None}


def test_an_ended_lease_does_not_hide_the_lease_of_another_tenant(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    ended = make_verified_tenant(make_room(prop, number="A1"))
    active = make_verified_tenant(make_room(prop, number="A2"))
    end_lease(database, ended.lease)
    assert lease_of(client, sign_in, ended) == {"lease": None}
    assert lease_of(client, sign_in, active)["lease"]["room"]["number"] == "A2"


# Management edits


def edit_body(**lease) -> dict:
    return {
        "name": "Budi Tenant",
        "phone": "081234567890",
        "emergencyContacts": CONTACTS,
        "lease": lease,
    }


def test_an_edited_rent_shows_on_the_next_call(
    client, database, owner_in, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, rent=1000000)
    session = sign_in(tenant.user)
    assert get_lease(client, session).json()["lease"]["rent"] == 1000000
    edit = client.put(
        f"/tenants/{tenant.id}",
        json=edit_body(billingCycle="monthly", rent=1500000),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    assert get_lease(client, session).json()["lease"]["rent"] == 1500000


def test_an_edited_billing_cycle_shows_on_the_next_call(
    client, database, owner_in, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, billing_cycle="monthly", rent=1000000)
    session = sign_in(tenant.user)
    edit = client.put(
        f"/tenants/{tenant.id}",
        json=edit_body(billingCycle="quarterly", rent=2900000),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    lease = get_lease(client, session).json()["lease"]
    assert lease["billingCycle"] == "quarterly"
    assert lease["rent"] == 2900000


def test_edited_dates_show_on_the_next_call(
    client, database, owner_in, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, start_date=None, end_date=None)
    session = sign_in(tenant.user)
    edit = client.put(
        f"/tenants/{tenant.id}",
        json=edit_body(
            startDate="2099-02-01",
            endDate="2099-08-31",
            billingCycle="monthly",
            rent=1000000,
        ),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    lease = get_lease(client, session).json()["lease"]
    assert lease["startDate"] == "2099-02-01"
    assert lease["endDate"] == "2099-08-31"


def test_clearing_the_end_date_shows_on_the_next_call(
    client, database, owner_in, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(
        room, start_date=date(2099, 1, 10), end_date=date(2099, 12, 31)
    )
    session = sign_in(tenant.user)
    edit = client.put(
        f"/tenants/{tenant.id}",
        json=edit_body(startDate="2099-01-10", billingCycle="monthly", rent=1000000),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    lease = get_lease(client, session).json()["lease"]
    assert lease["startDate"] == "2099-01-10"
    assert lease["endDate"] is None


# View-only states


def test_a_view_only_room_does_not_hide_the_lease(
    client, database, room, make_verified_tenant, sign_in
):
    from app.models import Room

    tenant = make_verified_tenant(room)
    set_view_only(database, Room, room)
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert lease["room"]["id"] == str(room.id)


def test_a_view_only_property_does_not_hide_the_lease(
    client, database, prop, room, make_verified_tenant, sign_in
):
    from app.models import Property

    tenant = make_verified_tenant(room)
    set_view_only(database, Property, prop)
    lease = lease_of(client, sign_in, tenant)["lease"]
    assert lease["room"]["id"] == str(room.id)
    assert lease["rent"] == 1000000


def test_a_view_only_property_still_returns_its_name_and_address(
    client, database, prop, room, make_verified_tenant, sign_in
):
    from app.models import Property

    tenant = make_verified_tenant(room)
    set_view_only(database, Property, prop)
    assert lease_of(client, sign_in, tenant)["lease"]["property"] == {
        "id": str(prop.id),
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
    }
