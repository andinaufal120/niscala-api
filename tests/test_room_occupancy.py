"""Room occupancy, lease details on rooms, occupied counts and deletion guards."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

PROPERTIES = "/properties"
LIST_LEASE_FIELDS = {"tenantName", "endDate"}
DETAIL_LEASE_FIELDS = {
    "tenantId",
    "tenantName",
    "tenantPhone",
    "startDate",
    "endDate",
    "rent",
}
BODY = {"number": "A1", "baseRate": 1500000}


def rooms_url(property_id) -> str:
    return f"{PROPERTIES}/{property_id}/rooms"


def room_url(room_id) -> str:
    return f"/rooms/{room_id}"


def property_url(property_id) -> str:
    return f"{PROPERTIES}/{property_id}"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def stored_room(database, room_id):
    from app.models import Room

    with Session(database, expire_on_commit=False) as db:
        return db.get(Room, UUID(str(room_id)))


def stored_property(database, property_id):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        return db.get(Property, UUID(str(property_id)))


def assignments(database, property_id) -> list:
    from app.models import ManagerAssignment

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(ManagerAssignment).where(
                    ManagerAssignment.property_id == UUID(str(property_id))
                )
            )
        )


def subscribe(database, owner, plan: str = "pro", days: int = 30) -> None:
    from app.schemas.subscriptions import PaidPlanCode
    from app.services.subscriptions import grant_subscription

    with Session(database) as db:
        grant_subscription(db, owner, PaidPlanCode(plan), days)
        db.commit()


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


def list_rooms(client, headers, property_id) -> list[dict]:
    response = client.get(rooms_url(property_id), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def by_number(items: list[dict]) -> dict[str, dict]:
    return {i["number"]: i for i in items}


def get_room(client, headers, room_id) -> dict:
    response = client.get(room_url(room_id), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def property_detail(client, headers, property_id) -> dict:
    response = client.get(property_url(property_id), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def property_list(client, headers) -> list[dict]:
    return client.get(PROPERTIES, headers=headers).json()["items"]


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
    return make_room(existing, number="A1", base_rate=1000000)


# Room occupancy


def test_a_room_without_a_lease_is_vacant_with_a_null_lease(
    client, database, signed_in, room
):
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "vacant"
    assert body["lease"] is None


def test_a_room_with_an_active_lease_is_occupied(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room)
    assert get_room(client, signed_in.headers, room.id)["occupancy"] == "occupied"


def test_a_room_whose_only_lease_has_ended_is_vacant_with_a_null_lease(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "vacant"
    assert body["lease"] is None


def test_a_room_with_several_ended_leases_is_vacant(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, name="First", lease_ended=True)
    make_tenant(room, name="Second", lease_ended=True)
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "vacant"
    assert body["lease"] is None


def test_a_room_with_an_ended_lease_and_a_new_active_one_shows_the_new_tenant(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, name="Old Tenant", phone="081111111111", lease_ended=True)
    make_tenant(room, name="New Tenant", phone="082222222222")
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "occupied"
    assert body["lease"]["tenantName"] == "New Tenant"
    assert body["lease"]["tenantPhone"] == "082222222222"
    (item,) = list_rooms(client, signed_in.headers, room.property_id)
    assert item["occupancy"] == "occupied"
    assert item["lease"]["tenantName"] == "New Tenant"


def test_only_the_leased_room_is_occupied(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    other = make_room(existing, number="A2")
    make_tenant(room)
    assert get_room(client, signed_in.headers, room.id)["occupancy"] == "occupied"
    assert get_room(client, signed_in.headers, other.id)["occupancy"] == "vacant"


def test_a_lease_in_another_property_does_not_occupy_the_room(
    client, database, owner, signed_in, room, make_property, make_room, make_tenant
):
    other_room = make_room(make_property(owner, name="Other"), number="A1")
    make_tenant(other_room)
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "vacant"
    assert body["lease"] is None


def test_a_view_only_room_with_an_active_lease_is_occupied(
    client, database, existing, signed_in, make_room, make_tenant
):
    row = make_room(existing, number="A1", view_only=True)
    make_tenant(row)
    body = get_room(client, signed_in.headers, row.id)
    assert body["occupancy"] == "occupied"
    assert body["editable"] is False


def test_an_occupied_room_is_occupied_for_a_manager_of_the_property(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    assign_manager(manager, existing)
    make_tenant(room, name="Budi Tenant")
    body = get_room(client, manager_in.headers, room.id)
    assert body["occupancy"] == "occupied"
    assert body["lease"]["tenantName"] == "Budi Tenant"
    (item,) = list_rooms(client, manager_in.headers, existing.id)
    assert item["occupancy"] == "occupied"


def test_a_tenant_added_through_the_api_occupies_the_room(
    client, database, existing, signed_in, room
):
    response = client.post(
        f"{PROPERTIES}/{existing.id}/tenants",
        json={
            "name": "Budi Santoso",
            "phone": "081234567890",
            "roomId": str(room.id),
            "lease": {"startDate": "2099-01-10", "rent": 900000},
        },
        headers=signed_in.headers,
    )
    assert response.status_code == 201, response.text
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "occupied"
    assert body["lease"]["tenantId"] == response.json()["id"]
    assert body["lease"]["tenantName"] == "Budi Santoso"
    assert body["lease"]["rent"] == 900000
    assert (
        property_detail(client, signed_in.headers, existing.id)["occupiedRoomCount"]
        == 1
    )


# Room detail lease


def test_the_detail_lease_describes_the_active_lease(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(
        room,
        name="Budi Tenant",
        phone="081234567890",
        start_date=date(2099, 1, 10),
        end_date=date(2099, 12, 31),
        rent=1200000,
    )
    body = get_room(client, signed_in.headers, room.id)
    assert set(body["lease"]) == DETAIL_LEASE_FIELDS
    assert body["lease"] == {
        "tenantId": str(stored.id),
        "tenantName": "Budi Tenant",
        "tenantPhone": "081234567890",
        "startDate": "2099-01-10",
        "endDate": "2099-12-31",
        "rent": 1200000,
    }


def test_the_detail_lease_end_date_may_be_null(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, end_date=None)
    assert get_room(client, signed_in.headers, room.id)["lease"]["endDate"] is None


def test_the_detail_lease_rent_is_the_leases_not_the_rooms_base_rate(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, rent=750000)
    body = get_room(client, signed_in.headers, room.id)
    assert body["baseRate"] == 1000000
    assert body["lease"]["rent"] == 750000


def test_the_detail_lease_phone_is_stored_with_a_leading_zero(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, phone="08571234567")
    assert (
        get_room(client, signed_in.headers, room.id)["lease"]["tenantPhone"]
        == "08571234567"
    )


def test_the_detail_lease_belongs_to_the_rooms_own_tenant(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    other = make_room(existing, number="A2")
    make_tenant(room, name="Tenant One", rent=111000)
    make_tenant(other, name="Tenant Two", rent=222000)
    one = get_room(client, signed_in.headers, room.id)["lease"]
    two = get_room(client, signed_in.headers, other.id)["lease"]
    assert (one["tenantName"], one["rent"]) == ("Tenant One", 111000)
    assert (two["tenantName"], two["rent"]) == ("Tenant Two", 222000)


def test_editing_the_base_rate_never_changes_the_lease_rent(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, rent=1000000)
    response = client.put(
        room_url(room.id),
        json={"number": "A1", "baseRate": 2500000},
        headers=signed_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["baseRate"] == 2500000
    assert response.json()["lease"]["rent"] == 1000000
    assert get_room(client, signed_in.headers, room.id)["lease"]["rent"] == 1000000


def test_editing_the_base_rate_does_not_change_the_stored_lease(
    client, database, signed_in, room, make_tenant
):
    from app.models import Lease

    stored = make_tenant(room, rent=1000000)
    client.put(
        room_url(room.id),
        json={"number": "A1", "baseRate": 2500000},
        headers=signed_in.headers,
    )
    with Session(database) as db:
        assert db.get(Lease, stored.lease.id).rent == 1000000


# Room edit response


def test_editing_an_occupied_room_answers_with_its_lease(
    client, database, signed_in, room, make_tenant
):
    stored = make_tenant(
        room, name="Budi Tenant", rent=800000, end_date=date(2099, 6, 30)
    )
    response = client.put(
        room_url(room.id),
        json={"number": "B2", "baseRate": 1000000},
        headers=signed_in.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["number"] == "B2"
    assert body["occupancy"] == "occupied"
    assert body["lease"] == {
        "tenantId": str(stored.id),
        "tenantName": "Budi Tenant",
        "tenantPhone": "081234567890",
        "startDate": "2099-01-10",
        "endDate": "2099-06-30",
        "rent": 800000,
    }


def test_editing_a_vacant_room_answers_vacant(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    response = client.put(
        room_url(room.id),
        json={"number": "A1", "baseRate": 1000000},
        headers=signed_in.headers,
    )
    assert response.status_code == 200
    assert response.json()["occupancy"] == "vacant"
    assert response.json()["lease"] is None


def test_the_edit_response_equals_the_detail_of_an_occupied_room(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room)
    response = client.put(
        room_url(room.id),
        json={"number": "A9", "baseRate": 5},
        headers=signed_in.headers,
    )
    assert response.json() == get_room(client, signed_in.headers, room.id)


def test_a_newly_added_room_is_vacant_even_when_another_room_is_occupied(
    client, database, signed_in, existing, room, make_tenant
):
    make_tenant(room)
    response = client.post(
        rooms_url(existing.id),
        json={"number": "A2", "baseRate": 1000000},
        headers=signed_in.headers,
    )
    assert response.status_code == 201
    assert response.json()["occupancy"] == "vacant"
    assert response.json()["lease"] is None


# Room list


def test_the_list_shows_the_tenant_name_and_end_date_of_occupied_rooms(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    vacant = make_room(existing, number="A2")
    make_tenant(room, name="Budi Tenant", end_date=date(2099, 12, 31), rent=555000)
    items = by_number(list_rooms(client, signed_in.headers, existing.id))
    assert items["A1"]["occupancy"] == "occupied"
    assert set(items["A1"]["lease"]) == LIST_LEASE_FIELDS
    assert items["A1"]["lease"] == {
        "tenantName": "Budi Tenant",
        "endDate": "2099-12-31",
    }
    assert items["A2"]["id"] == str(vacant.id)
    assert items["A2"]["occupancy"] == "vacant"
    assert items["A2"]["lease"] is None


def test_the_list_lease_end_date_may_be_null(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, end_date=None)
    (item,) = list_rooms(client, signed_in.headers, existing.id)
    assert item["lease"] == {"tenantName": "Budi Tenant", "endDate": None}


def test_the_list_shows_a_room_with_only_an_ended_lease_as_vacant(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    (item,) = list_rooms(client, signed_in.headers, existing.id)
    assert item["occupancy"] == "vacant"
    assert item["lease"] is None


def test_the_list_pairs_each_room_with_its_own_tenant_in_number_order(
    client, database, existing, signed_in, make_room, make_tenant
):
    rooms = {n: make_room(existing, number=n) for n in ["10", "2", "1", "3"]}
    make_tenant(rooms["10"], name="Ten", end_date=date(2099, 10, 10))
    make_tenant(rooms["2"], name="Two", end_date=date(2099, 2, 2))
    make_tenant(rooms["3"], name="Three", lease_ended=True)
    items = list_rooms(client, signed_in.headers, existing.id)
    assert [
        (i["number"], i["occupancy"], i["lease"] and i["lease"]["tenantName"])
        for i in items
    ] == [
        ("1", "vacant", None),
        ("2", "occupied", "Two"),
        ("3", "vacant", None),
        ("10", "occupied", "Ten"),
    ]


def test_the_list_does_not_show_leases_of_other_properties(
    client, database, owner, existing, signed_in, make_room, make_property, make_tenant
):
    make_room(existing, number="A1")
    other_room = make_room(make_property(owner, name="Other"), number="A1")
    make_tenant(other_room, name="Elsewhere")
    (item,) = list_rooms(client, signed_in.headers, existing.id)
    assert item["occupancy"] == "vacant"
    assert item["lease"] is None


def test_the_list_marks_an_occupied_view_only_room_as_occupied_and_not_editable(
    client, database, existing, signed_in, make_room, make_tenant
):
    row = make_room(existing, number="A1", view_only=True)
    make_tenant(row)
    (item,) = list_rooms(client, signed_in.headers, existing.id)
    assert item["occupancy"] == "occupied"
    assert item["editable"] is False


def test_the_list_leaves_out_a_deleted_room_that_has_a_lease(
    client, database, existing, signed_in, make_room, make_tenant
):
    gone = make_room(existing, number="A1", deleted=True)
    make_tenant(gone)
    assert list_rooms(client, signed_in.headers, existing.id) == []


def test_the_list_and_the_detail_agree_on_occupancy(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    (item,) = list_rooms(client, signed_in.headers, existing.id)
    body = get_room(client, signed_in.headers, room.id)
    assert item["occupancy"] == body["occupancy"]
    assert item["lease"]["tenantName"] == body["lease"]["tenantName"]
    assert item["lease"]["endDate"] == body["lease"]["endDate"]


# Property counts


def test_the_counts_cover_vacant_occupied_and_ended_rooms(
    client, database, existing, signed_in, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    make_tenant(make_room(existing, number="A3"), lease_ended=True)
    both = make_room(existing, number="A4")
    make_tenant(both, name="Gone", lease_ended=True)
    make_tenant(both, name="Here")
    make_tenant(make_room(existing, number="A5", view_only=True))
    body = property_detail(client, signed_in.headers, existing.id)
    assert body["roomCount"] == 5
    assert body["occupiedRoomCount"] == 3
    assert body["vacantRoomCount"] == 2
    (item,) = property_list(client, signed_in.headers)
    assert item["roomCount"] == 5
    assert item["occupiedRoomCount"] == 3


def test_a_fully_occupied_property_has_no_vacant_rooms(
    client, database, existing, signed_in, make_room, make_tenant
):
    for number in ["A1", "A2", "A3"]:
        make_tenant(make_room(existing, number=number), name=f"Tenant {number}")
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["occupiedRoomCount"]) == (3, 3)
    assert body["vacantRoomCount"] == 0


def test_a_property_with_only_ended_leases_has_no_occupied_rooms(
    client, database, existing, signed_in, make_room, make_tenant
):
    for number in ["A1", "A2"]:
        make_tenant(make_room(existing, number=number), lease_ended=True)
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["occupiedRoomCount"]) == (2, 0)
    assert body["vacantRoomCount"] == 2
    (item,) = property_list(client, signed_in.headers)
    assert item["occupiedRoomCount"] == 0


def test_deleted_rooms_do_not_count_even_with_an_active_lease(
    client, database, existing, signed_in, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    make_tenant(make_room(existing, number="A3", deleted=True))
    body = property_detail(client, signed_in.headers, existing.id)
    assert body["roomCount"] == 2
    assert body["occupiedRoomCount"] == 1
    assert body["vacantRoomCount"] == 1
    (item,) = property_list(client, signed_in.headers)
    assert (item["roomCount"], item["occupiedRoomCount"]) == (2, 1)


def test_the_counts_are_per_property(
    client, database, owner, existing, signed_in, make_property, make_room, make_tenant
):
    subscribe(database, owner)
    second = make_property(owner, name="Second")
    third = make_property(owner, name="Third")
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    make_tenant(make_room(second, number="B1"), name="One")
    make_tenant(make_room(second, number="B2"), name="Two")
    make_room(third, number="C1")
    items = property_list(client, signed_in.headers)
    counts = {i["name"]: (i["roomCount"], i["occupiedRoomCount"]) for i in items}
    assert counts == {"Kos Melati": (2, 1), "Second": (2, 2), "Third": (1, 0)}
    assert property_detail(client, signed_in.headers, second.id)["vacantRoomCount"] == 0
    assert property_detail(client, signed_in.headers, third.id)["vacantRoomCount"] == 1


def test_a_lease_in_another_owners_property_does_not_count(
    client,
    database,
    existing,
    signed_in,
    make_user,
    make_property,
    make_room,
    make_tenant,
):
    make_room(existing, number="A1")
    make_tenant(make_room(make_property(make_user(), name="Theirs"), number="A1"))
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["occupiedRoomCount"]) == (1, 0)


def test_a_manager_sees_the_occupied_counts_of_an_assigned_property(
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
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    body = property_detail(client, manager_in.headers, existing.id)
    assert (body["roomCount"], body["occupiedRoomCount"]) == (2, 1)
    assert body["vacantRoomCount"] == 1
    (item,) = property_list(client, manager_in.headers)
    assert item["occupiedRoomCount"] == 1


def test_a_view_only_property_counts_its_occupied_rooms(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    make_tenant(make_room(frozen, number="A1"))
    make_room(frozen, number="A2")
    body = property_detail(client, signed_in.headers, frozen.id)
    assert (body["roomCount"], body["occupiedRoomCount"]) == (2, 1)
    assert body["vacantRoomCount"] == 1


def test_editing_a_property_answers_with_its_occupied_counts(
    client, database, existing, signed_in, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    make_room(existing, number="A3")
    response = client.put(
        property_url(existing.id),
        json={"name": "Kos Melati", "address": "Jl. Baru 1"},
        headers=signed_in.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roomCount"] == 3
    assert body["occupiedRoomCount"] == 1
    assert body["vacantRoomCount"] == 2


def test_the_counts_follow_a_lease_ending(
    client, database, existing, signed_in, room, make_tenant
):
    from app.models import Lease

    stored = make_tenant(room)
    assert (
        property_detail(client, signed_in.headers, existing.id)["occupiedRoomCount"]
        == 1
    )
    with Session(database) as db:
        db.get(Lease, stored.lease.id).ended_at = datetime.now(UTC)
        db.commit()
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["occupiedRoomCount"], body["vacantRoomCount"]) == (0, 1)
    assert get_room(client, signed_in.headers, room.id)["occupancy"] == "vacant"


# DELETE /rooms/{roomId}


def test_a_room_with_an_active_lease_cannot_be_deleted(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room)
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert stored_room(database, room.id).deleted_at is None


def test_a_refused_room_deletion_leaves_the_room_and_its_lease_readable(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, name="Budi Tenant")
    client.delete(room_url(room.id), headers=signed_in.headers)
    body = get_room(client, signed_in.headers, room.id)
    assert body["occupancy"] == "occupied"
    assert body["lease"]["tenantName"] == "Budi Tenant"


def test_a_refused_room_deletion_can_be_repeated_with_the_same_answer(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room)
    for _ in range(2):
        response = client.delete(room_url(room.id), headers=signed_in.headers)
        assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")


def test_a_room_whose_lease_ended_can_be_deleted(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_room(database, room.id).deleted_at is not None


def test_a_room_with_ended_leases_and_no_active_one_can_be_deleted(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, name="First", lease_ended=True)
    make_tenant(room, name="Second", lease_ended=True)
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert response.status_code == 204


def test_a_room_with_an_ended_and_an_active_lease_cannot_be_deleted(
    client, database, signed_in, room, make_tenant
):
    make_tenant(room, name="Old", lease_ended=True)
    make_tenant(room, name="New")
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert stored_room(database, room.id).deleted_at is None


def test_another_rooms_lease_does_not_block_the_deletion(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A2"))
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert response.status_code == 204


def test_a_refused_deletion_does_not_touch_other_rooms(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    other = make_room(existing, number="A2")
    make_tenant(room)
    client.delete(room_url(room.id), headers=signed_in.headers)
    assert stored_room(database, other.id).deleted_at is None


def test_a_manager_cannot_delete_an_occupied_room_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    assign_manager(manager, existing)
    make_tenant(room)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert stored_room(database, room.id).deleted_at is None


def test_a_manager_can_delete_a_room_whose_lease_ended(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    assign_manager(manager, existing)
    make_tenant(room, lease_ended=True)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert response.status_code == 204


def test_an_occupied_view_only_room_cannot_be_deleted(
    client, database, existing, signed_in, make_room, make_tenant
):
    row = make_room(existing, view_only=True)
    make_tenant(row)
    response = client.delete(room_url(row.id), headers=signed_in.headers)
    assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert stored_room(database, row.id).deleted_at is None


def test_an_occupied_room_of_a_view_only_property_cannot_be_deleted(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    row = make_room(make_property(owner, view_only=True))
    make_tenant(row)
    response = client.delete(room_url(row.id), headers=signed_in.headers)
    assert_error(response, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert stored_room(database, row.id).deleted_at is None


def test_a_vacant_view_only_room_whose_lease_ended_can_be_deleted(
    client, database, existing, signed_in, make_room, make_tenant
):
    row = make_room(existing, view_only=True)
    make_tenant(row, lease_ended=True)
    response = client.delete(room_url(row.id), headers=signed_in.headers)
    assert response.status_code == 204


def test_a_room_of_another_owner_with_a_lease_is_not_found_not_conflicting(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_room(make_property(make_user(), name="Theirs"), number="T1")
    make_tenant(theirs)
    response = client.delete(room_url(theirs.id), headers=signed_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert stored_room(database, theirs.id).deleted_at is None


def test_a_room_of_an_unassigned_property_with_a_lease_is_not_found_for_a_manager(
    client, database, manager_in, room, make_tenant
):
    make_tenant(room)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_a_deleted_room_with_a_lease_is_not_found(
    client, database, existing, signed_in, make_room, make_tenant
):
    gone = make_room(existing, deleted=True)
    make_tenant(gone)
    response = client.delete(room_url(gone.id), headers=signed_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_a_manager_who_lost_the_assignment_gets_not_found_for_an_occupied_room(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    assign_manager(manager, existing)
    make_tenant(room)
    unassign(database, manager, existing)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_a_tenant_account_is_forbidden_before_the_lease_check(
    client, database, room, make_user, sign_in, make_tenant
):
    make_tenant(room)
    headers = sign_in(make_user(role=role("tenant"))).headers
    response = client.delete(room_url(room.id), headers=headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_malformed_room_id_is_still_a_validation_failure(client, database, signed_in):
    response = client.delete(room_url("not-a-uuid"), headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "roomId")


def test_the_number_of_a_refused_room_is_still_taken(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    client.delete(room_url(room.id), headers=signed_in.headers)
    response = client.post(rooms_url(existing.id), json=BODY, headers=signed_in.headers)
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")


# DELETE /properties/{propertyId}


def test_a_property_with_an_occupied_room_cannot_be_deleted(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert_error(response, 409, "PROPERTY_HAS_ACTIVE_LEASE")
    assert stored_property(database, existing.id).deleted_at is None


def test_a_refused_property_deletion_deletes_none_of_its_rooms(
    client, database, existing, signed_in, room, make_room, make_tenant
):
    vacant = make_room(existing, number="A2")
    view_only = make_room(existing, number="A3", view_only=True)
    make_tenant(room)
    client.delete(property_url(existing.id), headers=signed_in.headers)
    for row in (room, vacant, view_only):
        assert stored_room(database, row.id).deleted_at is None


def test_a_refused_property_deletion_keeps_the_manager_assignments(
    client,
    database,
    existing,
    signed_in,
    room,
    make_user,
    make_tenant,
    assign_manager,
):
    assign_manager(make_user(role=role("manager")), existing)
    assign_manager(make_user(role=role("manager")), existing)
    make_tenant(room)
    client.delete(property_url(existing.id), headers=signed_in.headers)
    assert len(assignments(database, existing.id)) == 2


def test_a_refused_property_deletion_leaves_it_readable_and_listed(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room)
    client.delete(property_url(existing.id), headers=signed_in.headers)
    body = property_detail(client, signed_in.headers, existing.id)
    assert body["occupiedRoomCount"] == 1
    assert [i["id"] for i in property_list(client, signed_in.headers)] == [
        str(existing.id)
    ]
    assert len(list_rooms(client, signed_in.headers, existing.id)) == 1


def test_one_occupied_room_among_vacant_ones_blocks_the_deletion(
    client, database, existing, signed_in, make_room, make_tenant
):
    for number in ["A1", "A2", "A3"]:
        make_room(existing, number=number)
    make_tenant(make_room(existing, number="A4"))
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert_error(response, 409, "PROPERTY_HAS_ACTIVE_LEASE")


def test_an_occupied_view_only_room_blocks_the_property_deletion(
    client, database, existing, signed_in, make_room, make_tenant
):
    make_tenant(make_room(existing, view_only=True))
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert_error(response, 409, "PROPERTY_HAS_ACTIVE_LEASE")
    assert stored_property(database, existing.id).deleted_at is None


def test_a_view_only_property_with_an_occupied_room_cannot_be_deleted(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, view_only=True)
    row = make_room(frozen)
    make_tenant(row)
    response = client.delete(property_url(frozen.id), headers=signed_in.headers)
    assert_error(response, 409, "PROPERTY_HAS_ACTIVE_LEASE")
    assert stored_property(database, frozen.id).deleted_at is None
    assert stored_room(database, row.id).deleted_at is None


def test_a_property_whose_rooms_only_have_ended_leases_can_be_deleted(
    client, database, existing, signed_in, make_room, make_tenant
):
    first = make_room(existing, number="A1")
    second = make_room(existing, number="A2")
    make_tenant(first, name="One", lease_ended=True)
    make_tenant(second, name="Two", lease_ended=True)
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_property(database, existing.id).deleted_at is not None
    for row in (first, second):
        assert stored_room(database, row.id).deleted_at is not None


def test_a_property_with_only_vacant_rooms_can_be_deleted(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing)
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_room(database, row.id).deleted_at is not None


def test_a_deleted_room_with_an_active_lease_does_not_block_the_property_deletion(
    client, database, existing, signed_in, make_room, make_tenant
):
    gone = make_room(existing, number="A1", deleted=True)
    make_tenant(gone)
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_property(database, existing.id).deleted_at is not None


def test_a_lease_in_another_property_does_not_block_the_deletion(
    client,
    database,
    owner,
    existing,
    signed_in,
    make_property,
    make_room,
    make_tenant,
):
    subscribe(database, owner)
    other = make_property(owner, name="Other")
    make_tenant(make_room(other, number="A1"))
    make_room(existing, number="A1")
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_property(database, other.id).deleted_at is None


def test_a_refused_deletion_leaves_the_other_property_untouched(
    client,
    database,
    owner,
    existing,
    signed_in,
    make_property,
    make_room,
    make_tenant,
):
    subscribe(database, owner)
    other = make_property(owner, name="Other")
    other_room = make_room(other, number="B1")
    make_tenant(make_room(existing, number="A1"))
    client.delete(property_url(existing.id), headers=signed_in.headers)
    assert stored_property(database, other.id).deleted_at is None
    assert stored_room(database, other_room.id).deleted_at is None


def test_the_name_of_a_property_whose_deletion_was_refused_is_still_taken(
    client, database, owner, existing, signed_in, room, make_tenant
):
    subscribe(database, owner)
    make_tenant(room)
    client.delete(property_url(existing.id), headers=signed_in.headers)
    response = client.post(
        PROPERTIES,
        json={"name": "Kos Melati", "address": "Elsewhere"},
        headers=signed_in.headers,
    )
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")


def test_a_property_becomes_deletable_once_its_lease_ends(
    client, database, existing, signed_in, room, make_tenant
):
    from app.models import Lease

    stored = make_tenant(room)
    refused = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert_error(refused, 409, "PROPERTY_HAS_ACTIVE_LEASE")
    with Session(database) as db:
        db.get(Lease, stored.lease.id).ended_at = datetime.now(UTC)
        db.commit()
    response = client.delete(property_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204


def test_a_manager_is_forbidden_before_the_lease_check(
    client, database, manager, manager_in, existing, room, make_tenant, assign_manager
):
    assign_manager(manager, existing)
    make_tenant(room)
    response = client.delete(property_url(existing.id), headers=manager_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_another_owners_occupied_property_is_not_found_not_conflicting(
    client, database, signed_in, make_user, make_property, make_room, make_tenant
):
    theirs = make_property(make_user(), name="Theirs")
    make_tenant(make_room(theirs, number="A1"))
    response = client.delete(property_url(theirs.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored_property(database, theirs.id).deleted_at is None


def test_a_deleted_property_with_an_active_lease_is_not_found(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    make_tenant(make_room(gone, number="A1"))
    response = client.delete(property_url(gone.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_an_unknown_property_is_not_found(client, database, signed_in):
    response = client.delete(property_url(uuid4()), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


# Tenants are unaffected


def test_the_tenant_list_and_detail_still_work_for_occupied_rooms(
    client, database, existing, signed_in, room, make_tenant
):
    stored = make_tenant(room, name="Budi Tenant")
    listing = client.get(
        f"{PROPERTIES}/{existing.id}/tenants", headers=signed_in.headers
    )
    assert listing.status_code == 200
    assert [i["id"] for i in listing.json()["items"]] == [str(stored.id)]
    detail = client.get(f"/tenants/{stored.id}", headers=signed_in.headers)
    assert detail.status_code == 200
    assert detail.json()["room"] == {"id": str(room.id), "number": "A1"}
    assert detail.json()["name"] == "Budi Tenant"


def test_a_tenant_list_leaves_out_a_tenant_whose_lease_ended(
    client, database, existing, signed_in, room, make_tenant
):
    make_tenant(room, lease_ended=True)
    listing = client.get(
        f"{PROPERTIES}/{existing.id}/tenants", headers=signed_in.headers
    )
    assert listing.json() == {"items": []}


def test_ended_lease_dates_are_not_shown_on_the_room(
    client, database, signed_in, room, make_tenant
):
    make_tenant(
        room, lease_ended=True, start_date=date(2020, 1, 1), end_date=date(2020, 6, 1)
    )
    body = get_room(client, signed_in.headers, room.id)
    assert body["lease"] is None
    assert "2020" not in str(body)
