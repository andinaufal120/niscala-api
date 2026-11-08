"""Reading the calling tenant's own active leases."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

LEASES_URL = "/me/leases"
LEASE_FIELDS = {
    "tenantId",
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


def get_leases(client, tenant_in):
    return client.get(LEASES_URL, headers=tenant_in.headers)


def items_of(client, sign_in, tenant) -> list[dict]:
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}
    return body["items"]


def lease_of(client, sign_in, tenant) -> dict:
    (item,) = items_of(client, sign_in, tenant)
    return item


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database):
    assert_error(client.get(LEASES_URL), 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database):
    response = client.get(LEASES_URL, headers={"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_tenant_with_an_unverified_email_is_rejected(
    client, database, make_user, sign_in
):
    user = make_user(role=role("tenant"), email_verified=False)
    assert_error(get_leases(client, sign_in(user)), 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_staff_and_admins_are_forbidden(client, database, make_user, sign_in, name):
    session = sign_in(make_user(role=role(name)))
    assert_error(get_leases(client, session), 403, "FORBIDDEN")


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_an_unverified_non_tenant_is_told_to_verify_the_email(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(get_leases(client, session), 403, "EMAIL_NOT_VERIFIED")


def test_the_single_lease_endpoint_is_gone(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    response = client.get("/me/lease", headers=sign_in(tenant.user).headers)
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


# Success


def test_a_tenant_with_an_active_lease_gets_exactly_the_lease_fields(
    client, database, prop, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    (item,) = items_of(client, sign_in, tenant)
    assert set(item) == LEASE_FIELDS
    assert set(item["room"]) == ROOM_FIELDS
    assert set(item["property"]) == PROPERTY_FIELDS


def test_the_lease_names_the_tenant_record(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, distinct_id=True)
    assert tenant.id != tenant.user.id
    assert lease_of(client, sign_in, tenant)["tenantId"] == str(tenant.id)


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
    assert lease_of(client, sign_in, tenant)["room"] == {
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
    assert lease_of(client, sign_in, tenant)["room"] == {
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
    facilities = lease_of(client, sign_in, tenant)["room"]["facilities"]
    assert facilities == ["kamar mandi dalam"]


def test_many_facilities_are_all_listed(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    tags = ["ac", "wifi", "kasur", "lemari", "meja", "kamar mandi dalam"]
    room = make_room(prop, facilities=tags)
    tenant = make_verified_tenant(room)
    facilities = lease_of(client, sign_in, tenant)["room"]["facilities"]
    assert sorted(facilities) == sorted(tags)


def test_the_lease_carries_the_property_name_and_address(
    client, database, prop, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    assert lease_of(client, sign_in, tenant)["property"] == {
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
    lease = lease_of(client, sign_in, tenant)
    assert lease["startDate"] == "2099-01-10"
    assert lease["endDate"] == "2099-12-31"


def test_the_lease_dates_are_null_when_unset(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, start_date=None, end_date=None)
    lease = lease_of(client, sign_in, tenant)
    assert lease["startDate"] is None
    assert lease["endDate"] is None


def test_an_open_ended_lease_has_a_start_date_and_a_null_end_date(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, start_date=date(2099, 3, 1), end_date=None)
    lease = lease_of(client, sign_in, tenant)
    assert lease["startDate"] == "2099-03-01"
    assert lease["endDate"] is None


@pytest.mark.parametrize(
    "cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"]
)
def test_the_lease_carries_its_billing_cycle(
    client, database, room, make_verified_tenant, sign_in, cycle
):
    tenant = make_verified_tenant(room, billing_cycle=cycle)
    assert lease_of(client, sign_in, tenant)["billingCycle"] == cycle


def test_the_rent_is_the_lease_rent_and_not_the_room_base_rate(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, rent=1234500)
    lease = lease_of(client, sign_in, tenant)
    assert room.base_rate == 1750000
    assert lease["rent"] == 1234500


def test_the_rent_is_an_integer_of_rupiah_per_billing_cycle(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, billing_cycle="quarterly", rent=4800000)
    rent = lease_of(client, sign_in, tenant)["rent"]
    assert rent == 4800000
    assert isinstance(rent, int)


def test_the_rent_equal_to_the_base_rate_is_returned_as_is(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, rent=1750000)
    assert lease_of(client, sign_in, tenant)["rent"] == 1750000


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
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    (lease,) = response.json()["items"]
    assert set(lease["property"]) == PROPERTY_FIELDS
    for secret in ("Bank Mandiri", "1234567890", "Rina Owner", str(owner.id)):
        assert secret not in response.text


def test_the_lease_does_not_expose_other_rooms_of_the_property(
    client, database, prop, room, make_room, make_verified_tenant, sign_in
):
    make_room(prop, number="Z9")
    tenant = make_verified_tenant(room)
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert "Z9" not in response.text


def test_the_lease_does_not_expose_the_tenant_account_or_grace_period(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, grace_period_days=5, phone="081299990000")
    response = get_leases(client, sign_in(tenant.user))
    (lease,) = response.json()["items"]
    assert set(lease) == LEASE_FIELDS
    assert "081299990000" not in response.text


# Which leases are returned


def test_a_tenant_gets_their_own_lease_among_other_tenants_and_rooms(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    room_a = make_room(prop, number="A1", facilities=["ac"])
    room_b = make_room(prop, number="A2", facilities=["wifi"])
    room_c = make_room(prop, number="A3")
    tenant_a = make_verified_tenant(room_a, rent=1100000, billing_cycle="weekly")
    tenant_b = make_verified_tenant(room_b, rent=2200000, billing_cycle="annual")
    make_verified_tenant(room_c, rent=3300000)
    lease_a = lease_of(client, sign_in, tenant_a)
    lease_b = lease_of(client, sign_in, tenant_b)
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
    lease_a = lease_of(client, sign_in, tenant_a)
    lease_b = lease_of(client, sign_in, tenant_b)
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
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert "Kos Dahlia" not in response.text
    assert str(other.id) not in response.text


def test_the_leases_are_repeatable_across_calls(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    session = sign_in(tenant.user)
    first = get_leases(client, session)
    second = get_leases(client, session)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert len(first.json()["items"]) == 1


# Several leases


@pytest.fixture
def two_places(owner, make_property, make_room, make_verified_tenant):
    """One account renting a room in two properties through two records."""
    kos_zeta = make_property(owner, name="Kos Zeta", address="Jl. Zeta 1")
    kos_alpha = make_property(owner, name="kos alpha", address="Jl. Alpha 2")
    first = make_verified_tenant(
        make_room(kos_zeta, number="Z1"), rent=1100000, billing_cycle="weekly"
    )
    second = make_verified_tenant(
        make_room(kos_alpha, number="A1"),
        user=first.user,
        rent=2200000,
        billing_cycle="annual",
    )
    return first, second, kos_zeta, kos_alpha


def test_a_tenant_renting_in_two_places_gets_both_leases(
    client, database, sign_in, two_places
):
    first, second, kos_zeta, kos_alpha = two_places
    assert second.id != first.id
    items = items_of(client, sign_in, first)
    assert len(items) == 2
    by_tenant = {item["tenantId"]: item for item in items}
    assert set(by_tenant) == {str(first.id), str(second.id)}
    assert by_tenant[str(first.id)]["property"]["id"] == str(kos_zeta.id)
    assert by_tenant[str(first.id)]["rent"] == 1100000
    assert by_tenant[str(first.id)]["billingCycle"] == "weekly"
    assert by_tenant[str(second.id)]["property"]["id"] == str(kos_alpha.id)
    assert by_tenant[str(second.id)]["rent"] == 2200000
    assert by_tenant[str(second.id)]["billingCycle"] == "annual"


def test_the_leases_are_ordered_by_property_name_ignoring_case(
    client, database, sign_in, two_places
):
    first, _, _, _ = two_places
    names = [item["property"]["name"] for item in items_of(client, sign_in, first)]
    assert names == ["kos alpha", "Kos Zeta"]


def test_the_leases_of_one_property_are_ordered_by_room_number_ignoring_case(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    first = make_verified_tenant(make_room(prop, number="B1"))
    make_verified_tenant(make_room(prop, number="a2"), user=first.user)
    make_verified_tenant(make_room(prop, number="C3"), user=first.user)
    numbers = [item["room"]["number"] for item in items_of(client, sign_in, first)]
    assert numbers == ["a2", "B1", "C3"]


def test_the_property_name_orders_before_the_room_number(
    client, database, owner, make_property, make_room, make_verified_tenant, sign_in
):
    late = make_property(owner, name="Kos B")
    early = make_property(owner, name="Kos A")
    first = make_verified_tenant(make_room(late, number="1"))
    make_verified_tenant(make_room(early, number="9"), user=first.user)
    rows = [
        (item["property"]["name"], item["room"]["number"])
        for item in items_of(client, sign_in, first)
    ]
    assert rows == [("Kos A", "9"), ("Kos B", "1")]


def test_a_lease_that_ended_is_left_out_while_the_other_is_listed(
    client, database, sign_in, two_places
):
    first, second, _, _ = two_places
    end_lease(database, first.lease)
    (item,) = items_of(client, sign_in, first)
    assert item["tenantId"] == str(second.id)


def test_a_deleted_record_is_left_out_even_when_its_lease_row_is_open(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    live = make_verified_tenant(make_room(prop, number="A1"))
    make_verified_tenant(make_room(prop, number="A2"), user=live.user, deleted=True)
    (item,) = items_of(client, sign_in, live)
    assert item["tenantId"] == str(live.id)


def test_the_leases_of_other_accounts_are_never_listed(
    client, database, prop, make_room, make_verified_tenant, sign_in, two_places
):
    first, _, _, _ = two_places
    other = make_verified_tenant(make_room(prop, number="Q1"))
    assert len(items_of(client, sign_in, first)) == 2
    assert [i["tenantId"] for i in items_of(client, sign_in, other)] == [str(other.id)]


def test_view_only_places_are_still_listed(client, database, sign_in, two_places):
    from app.models import Property

    first, _, kos_zeta, kos_alpha = two_places
    set_view_only(database, Property, kos_zeta)
    set_view_only(database, Property, kos_alpha)
    assert len(items_of(client, sign_in, first)) == 2


# No active lease


def test_a_tenant_whose_lease_has_ended_gets_no_items(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room)
    end_lease(database, tenant.lease)
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_a_tenant_whose_lease_was_created_already_ended_gets_no_items(
    client, database, room, make_verified_tenant, sign_in
):
    tenant = make_verified_tenant(room, lease_ended=True)
    response = get_leases(client, sign_in(tenant.user))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_a_tenant_without_a_lease_row_gets_no_items(
    client, database, make_user, sign_in
):
    from app.models import Tenant

    user = make_user(role=role("tenant"), email_verified=True)
    with Session(database) as db:
        db.add(Tenant(user_id=user.id, phone="081234567890"))
        db.commit()
    response = get_leases(client, sign_in(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_a_tenant_without_any_record_gets_no_items(
    client, database, make_user, sign_in
):
    user = make_user(role=role("tenant"), email_verified=True)
    response = get_leases(client, sign_in(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_an_ended_lease_does_not_hide_the_lease_of_another_tenant(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    ended = make_verified_tenant(make_room(prop, number="A1"))
    active = make_verified_tenant(make_room(prop, number="A2"))
    end_lease(database, ended.lease)
    assert items_of(client, sign_in, ended) == []
    assert lease_of(client, sign_in, active)["room"]["number"] == "A2"


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
    assert get_leases(client, session).json()["items"][0]["rent"] == 1000000
    edit = client.put(
        f"/tenants/{tenant.id}",
        json=edit_body(billingCycle="monthly", rent=1500000),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    assert get_leases(client, session).json()["items"][0]["rent"] == 1500000


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
    (lease,) = get_leases(client, session).json()["items"]
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
    (lease,) = get_leases(client, session).json()["items"]
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
    (lease,) = get_leases(client, session).json()["items"]
    assert lease["startDate"] == "2099-01-10"
    assert lease["endDate"] is None


def test_editing_one_record_changes_only_its_lease(
    client, database, owner_in, sign_in, two_places
):
    first, second, _, _ = two_places
    edit = client.put(
        f"/tenants/{second.id}",
        json=edit_body(billingCycle="monthly", rent=3300000),
        headers=owner_in.headers,
    )
    assert edit.status_code == 200, edit.text
    by_tenant = {i["tenantId"]: i for i in items_of(client, sign_in, first)}
    assert by_tenant[str(second.id)]["rent"] == 3300000
    assert by_tenant[str(first.id)]["rent"] == 1100000


def test_deleting_one_record_leaves_the_lease_of_the_other(
    client, database, owner_in, sign_in, two_places
):
    first, second, _, _ = two_places
    response = client.delete(f"/tenants/{first.id}", headers=owner_in.headers)
    assert response.status_code == 204, response.text
    (item,) = items_of(client, sign_in, second)
    assert item["tenantId"] == str(second.id)


# View-only states


def test_a_view_only_room_does_not_hide_the_lease(
    client, database, room, make_verified_tenant, sign_in
):
    from app.models import Room

    tenant = make_verified_tenant(room)
    set_view_only(database, Room, room)
    lease = lease_of(client, sign_in, tenant)
    assert lease["room"]["id"] == str(room.id)


def test_a_view_only_property_does_not_hide_the_lease(
    client, database, prop, room, make_verified_tenant, sign_in
):
    from app.models import Property

    tenant = make_verified_tenant(room)
    set_view_only(database, Property, prop)
    lease = lease_of(client, sign_in, tenant)
    assert lease["room"]["id"] == str(room.id)
    assert lease["rent"] == 1000000


def test_a_view_only_property_still_returns_its_name_and_address(
    client, database, prop, room, make_verified_tenant, sign_in
):
    from app.models import Property

    tenant = make_verified_tenant(room)
    set_view_only(database, Property, prop)
    assert lease_of(client, sign_in, tenant)["property"] == {
        "id": str(prop.id),
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
    }
