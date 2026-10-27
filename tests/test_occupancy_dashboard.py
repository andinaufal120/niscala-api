"""Occupancy dashboard: per-property room statuses and totals for the caller."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

URL = "/occupancy-dashboard"
ZERO_SUMMARY = {
    "propertyCount": 0,
    "roomCount": 0,
    "occupiedRoomCount": 0,
    "vacantRoomCount": 0,
    "occupancyPercentage": 0,
}


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def dashboard(client, headers) -> dict:
    response = client.get(URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def item_named(body: dict, name: str) -> dict:
    (item,) = [i for i in body["items"] if i["name"] == name]
    return item


def room_numbers(item: dict) -> list[str]:
    return [r["number"] for r in item["rooms"]]


def add_rooms(database, property_, count: int) -> None:
    """Commit many vacant rooms in one transaction."""
    from app.models import Room

    with Session(database) as db:
        db.add_all(
            Room(
                property_id=property_.id,
                number=f"R{n}",
                base_rate=1000000,
                facilities=[],
            )
            for n in range(count)
        )
        db.commit()


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


def expire_subscription(database, owner) -> None:
    from app.models import Subscription

    with Session(database) as db:
        db.get(Subscription, owner.id).ends_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()


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


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database):
    assert_error(client.get(URL), 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database):
    response = client.get(URL, headers={"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["owner", "manager"])
def test_a_request_from_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(client.get(URL, headers=session.headers), 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_tenants_and_admins_are_forbidden(client, database, make_user, sign_in, name):
    session = sign_in(make_user(role=role(name)))
    assert_error(client.get(URL, headers=session.headers), 403, "FORBIDDEN")


def test_a_tenant_with_an_active_lease_is_forbidden(
    client, database, existing, make_room, make_verified_tenant, sign_in
):
    stored = make_verified_tenant(make_room(existing, number="A1"))
    session = sign_in(stored.user)
    assert_error(client.get(URL, headers=session.headers), 403, "FORBIDDEN")


# Response shape


def test_the_response_has_exactly_a_summary_and_items(
    client, database, signed_in, existing
):
    assert set(dashboard(client, signed_in.headers)) == {"summary", "items"}


def test_the_summary_has_exactly_its_fields(client, database, signed_in, existing):
    summary = dashboard(client, signed_in.headers)["summary"]
    assert set(summary) == set(ZERO_SUMMARY)


def test_an_item_has_exactly_its_fields(client, database, signed_in, existing):
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert set(item) == {
        "id",
        "name",
        "roomCount",
        "occupiedRoomCount",
        "vacantRoomCount",
        "occupancyPercentage",
        "rooms",
    }


def test_a_room_has_exactly_its_fields(
    client, database, signed_in, existing, make_room
):
    make_room(existing, number="A1")
    (item,) = dashboard(client, signed_in.headers)["items"]
    (room,) = item["rooms"]
    assert set(room) == {"id", "number", "occupancy"}


# Empty states


def test_an_owner_without_properties_gets_an_empty_dashboard(
    client, database, signed_in
):
    assert dashboard(client, signed_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


def test_a_property_without_rooms_is_listed_with_zeros(
    client, database, signed_in, existing
):
    body = dashboard(client, signed_in.headers)
    assert body["items"] == [
        {
            "id": str(existing.id),
            "name": "Kos Melati",
            "roomCount": 0,
            "occupiedRoomCount": 0,
            "vacantRoomCount": 0,
            "occupancyPercentage": 0,
            "rooms": [],
        }
    ]


def test_a_property_without_rooms_counts_toward_the_property_count(
    client, database, signed_in, existing
):
    assert dashboard(client, signed_in.headers)["summary"] == {
        **ZERO_SUMMARY,
        "propertyCount": 1,
    }


def test_properties_without_rooms_do_not_change_the_percentage_of_the_others(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    make_property(owner, name="Empty")
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    summary = dashboard(client, signed_in.headers)["summary"]
    assert summary["propertyCount"] == 2
    assert summary["roomCount"] == 2
    assert summary["occupancyPercentage"] == 50


# Room status


def test_a_room_without_a_lease_is_vacant(
    client, database, signed_in, existing, make_room
):
    room = make_room(existing, number="A1")
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["rooms"] == [
        {"id": str(room.id), "number": "A1", "occupancy": "vacant"}
    ]


def test_a_room_with_an_active_lease_is_occupied(
    client, database, signed_in, existing, make_room, make_tenant
):
    room = make_room(existing, number="A1")
    make_tenant(room)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["rooms"] == [
        {"id": str(room.id), "number": "A1", "occupancy": "occupied"}
    ]


def test_a_room_whose_only_lease_ended_is_vacant(
    client, database, signed_in, existing, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"), lease_ended=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["rooms"][0]["occupancy"] == "vacant"
    assert item["occupiedRoomCount"] == 0
    assert item["vacantRoomCount"] == 1


def test_a_room_with_ended_leases_and_an_active_one_is_occupied(
    client, database, signed_in, existing, make_room, make_tenant
):
    room = make_room(existing, number="A1")
    make_tenant(room, name="First", lease_ended=True)
    make_tenant(room, name="Second", lease_ended=True)
    make_tenant(room, name="Current")
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert [r["occupancy"] for r in item["rooms"]] == ["occupied"]
    assert item["occupiedRoomCount"] == 1


def test_a_room_with_ended_leases_only_is_vacant(
    client, database, signed_in, existing, make_room, make_tenant
):
    room = make_room(existing, number="A1")
    make_tenant(room, name="First", lease_ended=True)
    make_tenant(room, name="Second", lease_ended=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert [r["occupancy"] for r in item["rooms"]] == ["vacant"]


def test_a_lease_occupies_only_its_own_room(
    client, database, signed_in, existing, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert {r["number"]: r["occupancy"] for r in item["rooms"]} == {
        "A1": "occupied",
        "A2": "vacant",
    }


def test_a_lease_in_another_property_does_not_occupy_a_room(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    make_room(existing, number="A1")
    make_tenant(make_room(make_property(owner, name="Other"), number="A1"))
    body = dashboard(client, signed_in.headers)
    assert item_named(body, "Kos Melati")["rooms"][0]["occupancy"] == "vacant"
    assert item_named(body, "Other")["rooms"][0]["occupancy"] == "occupied"


def test_a_view_only_room_with_an_active_lease_is_occupied(
    client, database, signed_in, existing, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1", view_only=True))
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["rooms"][0]["occupancy"] == "occupied"


def test_a_view_only_room_without_a_lease_is_listed_as_vacant(
    client, database, signed_in, existing, make_room
):
    make_room(existing, number="A1", view_only=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["rooms"][0]["occupancy"] == "vacant"
    assert item["roomCount"] == 1


def test_a_room_that_gets_an_active_lease_turns_occupied(
    client, database, signed_in, existing, make_room, make_tenant
):
    room = make_room(existing, number="A1")
    before = dashboard(client, signed_in.headers)["items"][0]
    make_tenant(room)
    after = dashboard(client, signed_in.headers)["items"][0]
    assert before["rooms"][0]["occupancy"] == "vacant"
    assert after["rooms"][0]["occupancy"] == "occupied"


def test_a_room_whose_lease_ends_turns_vacant(
    client, database, signed_in, existing, make_room, make_tenant
):
    from app.models import Lease

    stored = make_tenant(make_room(existing, number="A1"))
    assert dashboard(client, signed_in.headers)["summary"]["occupiedRoomCount"] == 1
    with Session(database) as db:
        db.get(Lease, stored.lease.id).ended_at = datetime.now(UTC)
        db.commit()
    summary = dashboard(client, signed_in.headers)["summary"]
    assert (summary["occupiedRoomCount"], summary["vacantRoomCount"]) == (0, 1)


# Deleted rooms and properties


def test_a_deleted_room_is_not_listed_or_counted(
    client, database, signed_in, existing, make_room
):
    make_room(existing, number="A1")
    make_room(existing, number="A2", deleted=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert room_numbers(item) == ["A1"]
    assert item["roomCount"] == 1
    assert item["vacantRoomCount"] == 1


def test_a_deleted_room_with_an_active_lease_is_not_occupied(
    client, database, signed_in, existing, make_room, make_tenant
):
    make_room(existing, number="A1")
    make_tenant(make_room(existing, number="A2", deleted=True))
    body = dashboard(client, signed_in.headers)
    (item,) = body["items"]
    assert room_numbers(item) == ["A1"]
    assert item["occupiedRoomCount"] == 0
    assert body["summary"]["occupiedRoomCount"] == 0


def test_a_deleted_property_is_not_listed_or_counted(
    client, database, owner, signed_in, existing, make_property, make_room
):
    make_room(existing, number="A1")
    gone = make_property(owner, name="Gone", deleted=True)
    make_room(gone, number="B1")
    make_room(gone, number="B2")
    body = dashboard(client, signed_in.headers)
    assert [i["name"] for i in body["items"]] == ["Kos Melati"]
    assert body["summary"]["propertyCount"] == 1
    assert body["summary"]["roomCount"] == 1


def test_a_deleted_property_with_an_active_lease_is_not_counted_as_occupied(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    gone = make_property(owner, name="Gone", deleted=True)
    make_tenant(make_room(gone, number="B1"))
    assert dashboard(client, signed_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


def test_an_owner_whose_only_property_is_deleted_gets_the_empty_dashboard(
    client, database, owner, signed_in, make_property
):
    make_property(owner, name="Gone", deleted=True)
    assert dashboard(client, signed_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


# Counts


def test_a_property_reports_its_room_counts(
    client, database, signed_in, existing, make_room, make_tenant
):
    make_tenant(make_room(existing, number="A1"), name="One")
    make_tenant(make_room(existing, number="A2"), name="Two")
    make_room(existing, number="A3")
    make_tenant(make_room(existing, number="A4"), lease_ended=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["roomCount"] == 4
    assert item["occupiedRoomCount"] == 2
    assert item["vacantRoomCount"] == 2
    assert item["occupancyPercentage"] == 50


def test_a_fully_occupied_property_is_one_hundred_percent(
    client, database, signed_in, existing, make_room, make_tenant
):
    for number in ["A1", "A2", "A3"]:
        make_tenant(make_room(existing, number=number), name=f"Tenant {number}")
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["vacantRoomCount"] == 0
    assert item["occupancyPercentage"] == 100


def test_a_fully_vacant_property_is_zero_percent(
    client, database, signed_in, existing, make_room
):
    make_room(existing, number="A1")
    make_room(existing, number="A2")
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert item["occupiedRoomCount"] == 0
    assert item["occupancyPercentage"] == 0


def test_each_property_counts_only_its_own_rooms(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    second = make_property(owner, name="Second")
    make_tenant(make_room(existing, number="A1"), name="One")
    make_room(existing, number="A2")
    make_tenant(make_room(second, number="B1"), name="Two")
    body = dashboard(client, signed_in.headers)
    first_item = item_named(body, "Kos Melati")
    second_item = item_named(body, "Second")
    assert (first_item["roomCount"], first_item["occupiedRoomCount"]) == (2, 1)
    assert (second_item["roomCount"], second_item["occupiedRoomCount"]) == (1, 1)
    assert first_item["id"] == str(existing.id)
    assert second_item["id"] == str(second.id)


def test_the_summary_sums_the_counts_of_all_properties(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    second = make_property(owner, name="Second")
    third = make_property(owner, name="Third")
    make_tenant(make_room(existing, number="A1"), name="One")
    make_room(existing, number="A2")
    make_tenant(make_room(second, number="B1"), name="Two")
    make_tenant(make_room(second, number="B2"), name="Three")
    make_room(third, number="C1")
    make_room(third, number="C2")
    make_room(third, number="C3")
    assert dashboard(client, signed_in.headers)["summary"] == {
        "propertyCount": 3,
        "roomCount": 7,
        "occupiedRoomCount": 3,
        "vacantRoomCount": 4,
        "occupancyPercentage": 43,
    }


def test_the_summary_percentage_comes_from_summed_counts_not_averaged_percentages(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    big = make_property(owner, name="Big")
    make_tenant(make_room(existing, number="A1"), name="One")
    make_room(existing, number="A2")
    make_tenant(make_room(big, number="B1"), name="Two")
    for n in range(2, 9):
        make_room(big, number=f"B{n}")
    body = dashboard(client, signed_in.headers)
    assert item_named(body, "Kos Melati")["occupancyPercentage"] == 50
    assert item_named(body, "Big")["occupancyPercentage"] == 13
    assert body["summary"]["roomCount"] == 10
    assert body["summary"]["occupiedRoomCount"] == 2
    assert body["summary"]["occupancyPercentage"] == 20


def test_a_property_without_rooms_does_not_drag_the_summary_percentage(
    client, database, owner, signed_in, existing, make_property, make_room, make_tenant
):
    make_property(owner, name="Empty")
    make_tenant(make_room(existing, number="A1"))
    summary = dashboard(client, signed_in.headers)["summary"]
    assert summary["occupancyPercentage"] == 100


# Percentage rounding


@pytest.mark.parametrize(
    ("rooms", "occupied", "expected"),
    [
        (0, 0, 0),
        (4, 0, 0),
        (4, 4, 100),
        (8, 1, 13),
        (3, 1, 33),
        (3, 2, 67),
        (2, 1, 50),
        (200, 1, 1),
        (8, 3, 38),
        (8, 5, 63),
        (6, 1, 17),
        (7, 3, 43),
    ],
)
def test_the_percentage_is_a_whole_number_with_halves_rounded_up(
    client, database, signed_in, existing, make_tenant, rooms, occupied, expected
):
    from app.models import Room

    add_rooms(database, existing, rooms)
    if occupied:
        with Session(database) as db:
            chosen = db.query(Room).order_by(Room.number).limit(occupied).all()
        for index, room in enumerate(chosen):
            make_tenant(room, name=f"Tenant {index}")
    body = dashboard(client, signed_in.headers)
    (item,) = body["items"]
    assert item["roomCount"] == rooms
    assert item["occupiedRoomCount"] == occupied
    assert item["vacantRoomCount"] == rooms - occupied
    assert item["occupancyPercentage"] == expected
    assert isinstance(item["occupancyPercentage"], int)
    assert body["summary"]["occupancyPercentage"] == expected
    assert isinstance(body["summary"]["occupancyPercentage"], int)


# Ordering


def test_properties_are_ordered_by_name(
    client, database, owner, signed_in, make_property
):
    for name in ["Charlie", "Alpha", "Bravo"]:
        make_property(owner, name=name)
    body = dashboard(client, signed_in.headers)
    assert [i["name"] for i in body["items"]] == ["Alpha", "Bravo", "Charlie"]


def test_properties_with_the_same_name_are_ordered_by_id(
    client,
    database,
    make_user,
    sign_in,
    manager,
    manager_in,
    make_property,
    assign_manager,
):
    first = make_property(make_user(name="Owner One"), name="Kos Melati")
    second = make_property(make_user(name="Owner Two"), name="Kos Melati")
    assign_manager(manager, first)
    assign_manager(manager, second)
    body = dashboard(client, manager_in.headers)
    assert [i["id"] for i in body["items"]] == sorted([str(first.id), str(second.id)])


def test_rooms_are_ordered_by_number_in_natural_order(
    client, database, signed_in, existing, make_room
):
    for number in ["10", "2", "1", "21", "3"]:
        make_room(existing, number=number)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert room_numbers(item) == ["1", "2", "3", "10", "21"]


def test_rooms_with_letter_prefixes_are_ordered_naturally(
    client, database, signed_in, existing, make_room
):
    for number in ["A10", "A2", "B1", "A1"]:
        make_room(existing, number=number)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert room_numbers(item) == ["A1", "A2", "A10", "B1"]


def test_room_number_ordering_ignores_letter_case(
    client, database, signed_in, existing, make_room
):
    for number in ["A10", "a2", "A1"]:
        make_room(existing, number=number)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert room_numbers(item) == ["A1", "a2", "A10"]


def test_rooms_are_ordered_regardless_of_occupancy(
    client, database, signed_in, existing, make_room, make_tenant
):
    rooms = {n: make_room(existing, number=n) for n in ["10", "2", "1"]}
    make_tenant(rooms["10"], name="Ten")
    make_tenant(rooms["1"], name="One", lease_ended=True)
    (item,) = dashboard(client, signed_in.headers)["items"]
    assert [(r["number"], r["occupancy"]) for r in item["rooms"]] == [
        ("1", "vacant"),
        ("2", "vacant"),
        ("10", "occupied"),
    ]


def test_rooms_stay_with_their_own_property(
    client, database, owner, signed_in, existing, make_property, make_room
):
    other = make_property(owner, name="Other")
    make_room(existing, number="A1")
    make_room(other, number="B1")
    body = dashboard(client, signed_in.headers)
    assert room_numbers(item_named(body, "Kos Melati")) == ["A1"]
    assert room_numbers(item_named(body, "Other")) == ["B1"]


# View-only properties and subscriptions


def test_a_view_only_property_is_included(
    client, database, owner, signed_in, make_property, make_room, make_tenant
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    make_tenant(make_room(frozen, number="A1"))
    make_room(frozen, number="A2")
    body = dashboard(client, signed_in.headers)
    item = item_named(body, "Frozen")
    assert (item["roomCount"], item["occupiedRoomCount"]) == (2, 1)
    assert body["summary"]["propertyCount"] == 1


def test_a_free_and_a_paid_owner_with_the_same_data_get_the_same_dashboard(
    client, database, make_user, sign_in, subscribe_owner, make_property, make_room
):
    free = make_user(name="Free Owner")
    paid = make_user(name="Paid Owner")
    subscribe_owner(paid, "basic")
    for owner in (free, paid):
        prop = make_property(owner, name="Kos Melati")
        make_room(prop, number="A1")
        make_room(prop, number="A2")

    def shape(user) -> dict:
        body = dashboard(client, sign_in(user).headers)
        for item in body["items"]:
            item.pop("id")
            for room in item["rooms"]:
                room.pop("id")
        return body

    assert shape(free) == shape(paid)


def test_an_owner_whose_subscription_expired_still_sees_every_property(
    client, database, owner, signed_in, subscribe_owner, make_property, make_room
):
    subscribe_owner(owner, "pro")
    first = make_property(owner, name="Alpha")
    second = make_property(owner, name="Bravo")
    make_room(first, number="A1")
    make_room(second, number="B1")
    before = dashboard(client, signed_in.headers)
    expire_subscription(database, owner)
    assert dashboard(client, signed_in.headers) == before


# Isolation between owners


def test_an_owner_never_sees_the_properties_of_another_owner(
    client,
    database,
    signed_in,
    existing,
    make_user,
    make_property,
    make_room,
    make_tenant,
):
    make_room(existing, number="A1")
    theirs = make_property(make_user(name="Other Owner"), name="Theirs")
    make_tenant(make_room(theirs, number="T1"))
    make_room(theirs, number="T2")
    body = dashboard(client, signed_in.headers)
    assert [i["name"] for i in body["items"]] == ["Kos Melati"]
    assert body["summary"] == {
        "propertyCount": 1,
        "roomCount": 1,
        "occupiedRoomCount": 0,
        "vacantRoomCount": 1,
        "occupancyPercentage": 0,
    }


def test_an_owner_without_properties_does_not_see_another_owners_data(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_property(make_user(name="Other Owner"), name="Theirs")
    make_room(theirs, number="T1")
    assert dashboard(client, signed_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


# Managers


def test_a_manager_sees_only_the_assigned_properties(
    client,
    database,
    owner,
    manager,
    manager_in,
    existing,
    make_property,
    make_room,
    make_tenant,
    assign_manager,
):
    other = make_property(owner, name="Not Assigned")
    make_room(other, number="X1")
    assign_manager(manager, existing)
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    body = dashboard(client, manager_in.headers)
    assert [i["name"] for i in body["items"]] == ["Kos Melati"]
    assert body["summary"] == {
        "propertyCount": 1,
        "roomCount": 2,
        "occupiedRoomCount": 1,
        "vacantRoomCount": 1,
        "occupancyPercentage": 50,
    }
    assert room_numbers(body["items"][0]) == ["A1", "A2"]


def test_a_manager_sees_the_same_property_figures_as_the_owner(
    client,
    database,
    manager,
    manager_in,
    signed_in,
    existing,
    make_room,
    make_tenant,
    assign_manager,
):
    assign_manager(manager, existing)
    make_tenant(make_room(existing, number="A1"))
    make_room(existing, number="A2")
    assert dashboard(client, manager_in.headers) == dashboard(client, signed_in.headers)


def test_a_manager_without_assignments_gets_the_empty_dashboard(
    client, database, manager_in, existing, make_room
):
    make_room(existing, number="A1")
    assert dashboard(client, manager_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


def test_removing_the_assignment_hides_the_property_at_once(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    assign_manager(manager, existing)
    make_room(existing, number="A1")
    assert len(dashboard(client, manager_in.headers)["items"]) == 1
    unassign(database, manager, existing)
    assert dashboard(client, manager_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


def test_a_manager_sees_a_view_only_assigned_property(
    client,
    database,
    owner,
    manager,
    manager_in,
    make_property,
    make_room,
    assign_manager,
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    make_room(frozen, number="A1")
    assign_manager(manager, frozen)
    body = dashboard(client, manager_in.headers)
    assert [i["name"] for i in body["items"]] == ["Frozen"]
    assert body["summary"]["roomCount"] == 1


def test_a_manager_does_not_see_an_assigned_property_that_was_deleted(
    client,
    database,
    owner,
    manager,
    manager_in,
    make_property,
    make_room,
    assign_manager,
):
    gone = make_property(owner, name="Gone", deleted=True)
    make_room(gone, number="A1")
    assign_manager(manager, gone)
    assert dashboard(client, manager_in.headers) == {
        "summary": ZERO_SUMMARY,
        "items": [],
    }


def test_a_manager_assigned_to_several_properties_gets_summed_totals_in_name_order(
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
    zulu = make_property(owner, name="Zulu")
    alpha = make_property(owner, name="Alpha")
    skipped = make_property(owner, name="Skipped")
    make_room(skipped, number="S1")
    assign_manager(manager, zulu)
    assign_manager(manager, alpha)
    make_tenant(make_room(zulu, number="Z1"))
    make_room(alpha, number="A1")
    make_room(alpha, number="A2")
    body = dashboard(client, manager_in.headers)
    assert [i["name"] for i in body["items"]] == ["Alpha", "Zulu"]
    assert body["summary"] == {
        "propertyCount": 2,
        "roomCount": 3,
        "occupiedRoomCount": 1,
        "vacantRoomCount": 2,
        "occupancyPercentage": 33,
    }


def test_two_managers_each_see_only_their_own_assignments(
    client,
    database,
    owner,
    make_user,
    sign_in,
    make_property,
    make_room,
    assign_manager,
):
    first = make_user(name="Manager One", role=role("manager"))
    second = make_user(name="Manager Two", role=role("manager"))
    alpha = make_property(owner, name="Alpha")
    bravo = make_property(owner, name="Bravo")
    make_room(alpha, number="A1")
    make_room(bravo, number="B1")
    assign_manager(first, alpha)
    assign_manager(second, bravo)
    first_names = [
        i["name"] for i in dashboard(client, sign_in(first).headers)["items"]
    ]
    second_names = [
        i["name"] for i in dashboard(client, sign_in(second).headers)["items"]
    ]
    assert first_names == ["Alpha"]
    assert second_names == ["Bravo"]
