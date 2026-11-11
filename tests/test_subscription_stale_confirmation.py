"""Applying plan limits when the stored confirmation names properties or rooms that are gone."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from subscription_support import (
    is_property_view_only,
    is_room_view_only,
    schedule_row,
    set_subscription,
    store_schedule,
    view_only_properties,
    view_only_rooms,
)


def apply(database) -> None:
    from app.services.subscriptions import apply_plan_limits

    with Session(database) as db:
        apply_plan_limits(db)
        db.commit()


def snapshot(database) -> dict:
    """The view-only flag of every property and room, deleted ones included."""
    from app.models import Property, Room

    with Session(database) as db:
        rows = {
            ("property", row.id): row.view_only for row in db.scalars(select(Property))
        }
        rows.update(
            {("room", row.id): row.view_only for row in db.scalars(select(Room))}
        )
        return rows


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def make_properties(make_property):
    def build(owner, count: int) -> list:
        return [make_property(owner, name=f"Kos {n}") for n in range(count)]

    return build


@pytest.fixture
def make_rooms(make_room):
    def build(property_, count: int, start: int = 1) -> list:
        return [
            make_room(property_, number=str(n)) for n in range(start, start + count)
        ]

    return build


def ended_period(database, owner, plan: str = "pro") -> None:
    set_subscription(
        database,
        owner,
        plan=plan,
        ends_at=datetime.now(UTC) - timedelta(days=1),
    )


# Properties


def test_a_deleted_confirmed_property_is_replaced_by_the_earliest_remaining(
    database, owner, make_property
):
    first = make_property(owner, name="Kos A")
    confirmed = make_property(owner, name="Kos B", deleted=True)
    second = make_property(owner, name="Kos C")
    third = make_property(owner, name="Kos D")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [confirmed.id])
    apply(database)
    assert view_only_properties(database, owner) == {second.id, third.id}
    assert not is_property_view_only(database, first)
    assert not is_property_view_only(database, confirmed)
    assert schedule_row(database, owner) is None


def test_the_replacement_is_the_earliest_created_not_the_first_listed(
    database, owner, make_property
):
    early = make_property(owner, name="Zebra")
    gone = make_property(owner, name="Kos B", deleted=True)
    late = make_property(owner, name="Anggrek")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone.id])
    apply(database)
    assert not is_property_view_only(database, early)
    assert is_property_view_only(database, late)


def test_surviving_confirmed_properties_stay_and_the_earliest_other_fills_the_gap(
    database, owner, make_properties, make_property
):
    props = make_properties(owner, 5)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [props[1].id, props[3].id, props[4].id])
    delete_property(database, props[3])
    apply(database)
    assert view_only_properties(database, owner) == {props[2].id}


def delete_property(database, property_) -> None:
    from app.models import Property

    with Session(database) as db:
        db.get(Property, property_.id).deleted_at = datetime.now(UTC)
        db.commit()


def delete_room(database, room) -> None:
    from app.models import Room

    with Session(database) as db:
        db.get(Room, room.id).deleted_at = datetime.now(UTC)
        db.commit()


def test_basic_with_a_deleted_confirmed_property_keeps_three_editable(
    database, owner, make_property
):
    props = [make_property(owner, name=f"Kos {n}") for n in range(5)]
    gone = make_property(owner, name="Kos Hapus", deleted=True)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [props[2].id, props[3].id, gone.id])
    apply(database)
    assert view_only_properties(database, owner) == {props[1].id, props[4].id}


def test_all_confirmed_properties_deleted_falls_back_to_the_default_choice(
    database, owner, make_property
):
    gone_a = make_property(owner, name="Kos A", deleted=True)
    first = make_property(owner, name="Kos C")
    second = make_property(owner, name="Kos D")
    third = make_property(owner, name="Kos E")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone_a.id])
    apply(database)
    assert not is_property_view_only(database, first)
    assert view_only_properties(database, owner) == {second.id, third.id}


def test_all_basic_confirmed_properties_deleted_keeps_the_three_earliest(
    database, owner, make_property
):
    gone = [make_property(owner, name=f"Kos X{n}", deleted=True) for n in range(3)]
    props = [make_property(owner, name=f"Kos {n}") for n in range(5)]
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [g.id for g in gone])
    apply(database)
    assert view_only_properties(database, owner) == {props[3].id, props[4].id}
    assert schedule_row(database, owner) is None


def test_a_confirmation_whose_properties_all_exist_is_followed_exactly(
    database, owner, make_properties
):
    props = make_properties(owner, 4)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [props[3].id])
    apply(database)
    assert view_only_properties(database, owner) == {
        props[0].id,
        props[1].id,
        props[2].id,
    }


def test_a_confirmed_view_only_property_is_not_revived(database, owner, make_property):
    first = make_property(owner, name="Kos A")
    old = make_property(owner, name="Kos B", view_only=True)
    third = make_property(owner, name="Kos C")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [old.id])
    apply(database)
    assert is_property_view_only(database, old)
    assert not is_property_view_only(database, first)
    assert is_property_view_only(database, third)


def test_a_confirmed_view_only_property_does_not_take_a_basic_place(
    database, owner, make_property
):
    props = [make_property(owner, name=f"Kos {n}") for n in range(4)]
    old = make_property(owner, name="Kos Lama", view_only=True)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [old.id, props[2].id, props[3].id])
    apply(database)
    assert is_property_view_only(database, old)
    assert view_only_properties(database, owner) == {old.id, props[1].id}


def test_the_deleted_confirmed_property_is_never_made_view_only_or_revived(
    database, owner, make_property
):
    gone = make_property(owner, name="Kos A", deleted=True)
    make_property(owner, name="Kos B")
    make_property(owner, name="Kos C")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone.id])
    apply(database)
    assert not is_property_view_only(database, gone)


# Rooms of a confirmed property


def test_surviving_confirmed_rooms_stay_and_free_places_go_to_occupied_then_lowest(
    database, owner, make_property, make_rooms, make_room, make_tenant
):
    prop = make_property(owner, name="Kos A")
    low = make_rooms(prop, 5)
    gone = [make_room(prop, number=str(n)) for n in (6, 7)]
    confirmed = make_rooms(prop, 13, start=8)
    make_tenant(low[4], invitation=False)
    ended_period(database, owner, "pro")
    store_schedule(
        database,
        owner,
        "free",
        [prop.id],
        [r.id for r in confirmed] + [r.id for r in gone],
    )
    for room in gone:
        delete_room(database, room)
    apply(database)
    assert view_only_rooms(database, prop) == {low[1].id, low[2].id, low[3].id}
    assert schedule_row(database, owner) is None


def test_the_kept_rooms_total_exactly_the_limit_after_a_confirmed_room_is_deleted(
    database, owner, make_property, make_rooms
):
    prop = make_property(owner, name="Kos A")
    rooms = make_rooms(prop, 20)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms[5:]])
    delete_room(database, rooms[10])
    apply(database)
    assert len(view_only_rooms(database, prop)) == 4
    assert view_only_rooms(database, prop) == {r.id for r in rooms[1:5]}
    assert not is_room_view_only(database, rooms[0])


def test_all_confirmed_rooms_deleted_falls_back_to_the_default_rule(
    database, owner, make_property, make_rooms, make_room, make_tenant
):
    prop = make_property(owner, name="Kos A")
    gone = [make_room(prop, number=f"X{n}") for n in range(15)]
    rooms = make_rooms(prop, 20)
    make_tenant(rooms[19], invitation=False)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in gone])
    for room in gone:
        delete_room(database, room)
    apply(database)
    kept = {r.id for r in rooms[:14]} | {rooms[19].id}
    assert view_only_rooms(database, prop) == {r.id for r in rooms} - kept
    assert all(not is_room_view_only(database, r) for r in gone)


def test_default_fill_uses_natural_number_order(
    database, owner, make_property, make_room
):
    prop = make_property(owner, name="Kos A")
    gone = make_room(prop, number="A1")
    confirmed = [make_room(prop, number=f"B{n}") for n in range(14)]
    ten = make_room(prop, number="10")
    two = make_room(prop, number="2")
    ended_period(database, owner, "pro")
    store_schedule(
        database,
        owner,
        "free",
        [prop.id],
        [r.id for r in confirmed] + [gone.id],
    )
    delete_room(database, gone)
    apply(database)
    assert view_only_rooms(database, prop) == {ten.id}
    assert not is_room_view_only(database, two)


def test_a_room_added_after_confirming_stays_view_only_while_confirmed_rooms_remain(
    database, owner, make_property, make_rooms, make_room
):
    prop = make_property(owner, name="Kos A")
    rooms = make_rooms(prop, 15, start=2)
    added = make_room(prop, number="1")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms])
    apply(database)
    assert view_only_rooms(database, prop) == {added.id}


def test_a_confirmed_view_only_room_is_not_revived_by_the_default_fill(
    database, owner, make_property, make_rooms, make_room
):
    prop = make_property(owner, name="Kos A")
    old = make_room(prop, number="1", view_only=True)
    gone = make_room(prop, number="2")
    confirmed = make_rooms(prop, 14, start=3)
    make_room(prop, number="30")
    extra = make_room(prop, number="31")
    ended_period(database, owner, "pro")
    store_schedule(
        database,
        owner,
        "free",
        [prop.id],
        [r.id for r in confirmed] + [gone.id],
    )
    delete_room(database, gone)
    apply(database)
    assert is_room_view_only(database, old)
    assert view_only_rooms(database, prop) == {old.id, extra.id}


def test_confirmed_room_ids_of_another_property_are_ignored(
    database, owner, make_property, make_rooms
):
    prop = make_property(owner, name="Kos A")
    other = make_property(owner, name="Kos B")
    rooms = make_rooms(prop, 20)
    foreign = make_rooms(other, 5)
    ended_period(database, owner, "pro")
    store_schedule(
        database,
        owner,
        "free",
        [prop.id],
        [r.id for r in rooms[10:]] + [r.id for r in foreign],
    )
    apply(database)
    assert view_only_rooms(database, prop) == {r.id for r in rooms[5:10]}
    assert is_property_view_only(database, other)


def test_the_rooms_of_a_confirmed_property_that_exceed_the_limit_never_exceed_it(
    database, owner, make_property, make_rooms
):
    prop = make_property(owner, name="Kos A")
    rooms = make_rooms(prop, 20)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms])
    apply(database)
    assert len(view_only_rooms(database, prop)) == 5


# Rooms of a property added by the top-up


def test_a_topped_up_property_follows_the_default_room_rule(
    database, owner, make_property, make_rooms, make_tenant
):
    gone = make_property(owner, name="Kos A", deleted=True)
    topped = make_property(owner, name="Kos B")
    make_property(owner, name="Kos C")
    rooms = make_rooms(topped, 20)
    make_tenant(rooms[19], invitation=False)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone.id], [r.id for r in rooms[5:]])
    apply(database)
    kept = {r.id for r in rooms[:14]} | {rooms[19].id}
    assert not is_property_view_only(database, topped)
    assert view_only_rooms(database, topped) == {r.id for r in rooms} - kept


def test_a_topped_up_basic_property_is_not_room_limited(
    database, owner, make_property, make_rooms
):
    props = [make_property(owner, name=f"Kos {n}") for n in range(5)]
    gone = make_property(owner, name="Kos Hapus", deleted=True)
    make_rooms(props[0], 30)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [props[3].id, props[4].id, gone.id])
    apply(database)
    assert view_only_properties(database, owner) == {props[1].id, props[2].id}
    assert view_only_rooms(database, props[0]) == set()


# Unaffected cases


def test_a_confirmation_for_another_plan_still_gives_the_default_choice(
    database, owner, make_property
):
    first = make_property(owner, name="Kos A")
    second = make_property(owner, name="Kos B", deleted=True)
    third = make_property(owner, name="Kos C")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "basic", [second.id])
    apply(database)
    assert not is_property_view_only(database, first)
    assert is_property_view_only(database, third)
    assert schedule_row(database, owner) is None


def test_a_second_run_after_a_stale_confirmation_changes_nothing(
    database, owner, make_property, make_rooms
):
    gone = make_property(owner, name="Kos A", deleted=True)
    first = make_property(owner, name="Kos B")
    make_property(owner, name="Kos C")
    make_rooms(first, 20)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone.id])
    apply(database)
    after_first = snapshot(database)
    apply(database)
    assert snapshot(database) == after_first
    assert schedule_row(database, owner) is None


def test_a_second_run_after_stale_confirmed_rooms_changes_nothing(
    database, owner, make_property, make_rooms
):
    prop = make_property(owner, name="Kos A")
    rooms = make_rooms(prop, 20)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms[5:]])
    delete_room(database, rooms[7])
    apply(database)
    after_first = snapshot(database)
    apply(database)
    assert snapshot(database) == after_first


def test_another_owners_rows_and_confirmation_are_untouched(
    database, owner, make_user, make_property, make_rooms
):
    other = make_user()
    other_first = make_property(other, name="Kos X")
    other_second = make_property(other, name="Kos Y")
    other_rooms = make_rooms(other_first, 3)
    set_subscription(database, other, plan="pro")
    store_schedule(database, other, "free", [other_second.id])
    gone = make_property(owner, name="Kos A", deleted=True)
    make_property(owner, name="Kos B")
    make_property(owner, name="Kos C")
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [gone.id])
    apply(database)
    assert not is_property_view_only(database, other_first)
    assert not is_property_view_only(database, other_second)
    assert all(not is_room_view_only(database, r) for r in other_rooms)
    assert schedule_row(database, other) is not None
