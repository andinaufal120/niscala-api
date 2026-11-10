"""Applying plan limits when a paid period has ended, and restoring editability."""

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


# Registration as a daily job


def test_the_job_is_one_of_the_daily_jobs():
    from app.services.jobs import DAILY_JOBS

    assert "apply_plan_limits" in [job.__name__ for job in DAILY_JOBS]


def test_the_job_is_the_one_in_the_subscription_service():
    from app.services.jobs import DAILY_JOBS
    from app.services.subscriptions import apply_plan_limits

    assert apply_plan_limits in DAILY_JOBS


def test_the_daily_run_applies_the_limits(database, owner, make_properties):
    from app.services.jobs import run_daily_jobs

    first, second = make_properties(owner, 2)
    assert run_daily_jobs() == []
    assert not is_property_view_only(database, first)
    assert is_property_view_only(database, second)


# Properties: default choice


def test_an_owner_without_a_subscription_keeps_the_earliest_property(
    database, owner, make_properties
):
    props = make_properties(owner, 3)
    apply(database)
    assert view_only_properties(database, owner) == {props[1].id, props[2].id}


def test_an_owner_whose_period_ended_keeps_the_earliest_property(
    database, owner, make_properties
):
    props = make_properties(owner, 3)
    ended_period(database, owner, "pro")
    apply(database)
    assert view_only_properties(database, owner) == {props[1].id, props[2].id}


def test_the_earliest_created_property_is_kept_whatever_its_name(
    database, owner, make_property
):
    first = make_property(owner, name="Zebra")
    second = make_property(owner, name="Anggrek")
    apply(database)
    assert not is_property_view_only(database, first)
    assert is_property_view_only(database, second)


def test_basic_keeps_the_three_earliest_properties(database, owner, make_properties):
    props = make_properties(owner, 5)
    set_subscription(database, owner, plan="basic")
    apply(database)
    assert view_only_properties(database, owner) == {props[3].id, props[4].id}


def test_deleted_properties_are_ignored_when_choosing(database, owner, make_property):
    gone = make_property(owner, name="Kos Lama", deleted=True)
    first = make_property(owner, name="Kos A")
    second = make_property(owner, name="Kos B")
    apply(database)
    assert not is_property_view_only(database, gone)
    assert not is_property_view_only(database, first)
    assert is_property_view_only(database, second)


def test_a_deleted_property_does_not_count_against_the_limit(
    database, owner, make_property
):
    make_property(owner, name="Kos Lama", deleted=True)
    only = make_property(owner, name="Kos A")
    apply(database)
    assert view_only_properties(database, owner) == set()
    assert not is_property_view_only(database, only)


def test_only_the_owners_over_the_limit_are_touched(
    database, owner, make_user, make_properties
):
    other = make_user()
    mine = make_properties(owner, 2)
    theirs = [make_property_for(database, other, "Kos X")]
    apply(database)
    assert is_property_view_only(database, mine[1])
    assert not is_property_view_only(database, theirs[0])


def make_property_for(database, owner, name):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        row = Property(owner_id=owner.id, name=name, address="Jl. Lain 1")
        db.add(row)
        db.commit()
        return row


def test_every_owner_is_handled_by_the_same_run(
    database, owner, make_user, make_properties
):
    other = make_user()
    mine = make_properties(owner, 2)
    other_first = make_property_for(database, other, "Kos X")
    other_second = make_property_for(database, other, "Kos Y")
    apply(database)
    assert view_only_properties(database, owner) == {mine[1].id}
    assert view_only_properties(database, other) == {other_second.id}
    assert not is_property_view_only(database, other_first)


# Properties: a stored confirmation


def test_a_confirmation_decides_which_properties_stay_editable(
    database, owner, make_properties
):
    props = make_properties(owner, 3)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [props[2].id])
    apply(database)
    assert view_only_properties(database, owner) == {props[0].id, props[1].id}


def test_a_basic_confirmation_decides_which_properties_stay_editable(
    database, owner, make_properties
):
    props = make_properties(owner, 5)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "basic", [props[1].id, props[3].id, props[4].id])
    apply(database)
    assert view_only_properties(database, owner) == {props[0].id, props[2].id}


def test_the_confirmation_is_removed_once_applied(database, owner, make_properties):
    props = make_properties(owner, 2)
    store_schedule(database, owner, "free", [props[1].id])
    apply(database)
    assert schedule_row(database, owner) is None


def test_a_confirmation_for_another_plan_is_ignored_and_removed(
    database, owner, make_properties
):
    props = make_properties(owner, 3)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "basic", [props[1].id, props[2].id])
    apply(database)
    assert view_only_properties(database, owner) == {props[1].id, props[2].id}
    assert schedule_row(database, owner) is None


def test_a_confirmation_for_the_free_plan_is_ignored_when_basic_applies(
    database, owner, make_properties
):
    props = make_properties(owner, 5)
    set_subscription(database, owner, plan="basic")
    store_schedule(database, owner, "free", [props[4].id])
    apply(database)
    assert view_only_properties(database, owner) == {props[3].id, props[4].id}
    assert schedule_row(database, owner) is None


def test_the_confirmation_of_another_owner_is_left_alone(
    database, owner, make_user, make_properties
):
    other = make_user()
    other_props = [make_property_for(database, other, "Kos X")]
    set_subscription(database, other, plan="pro")
    store_schedule(database, other, "free", [other_props[0].id])
    make_properties(owner, 2)
    apply(database)
    assert schedule_row(database, other) is not None


# Rooms of a free owner


def test_rooms_over_the_limit_of_the_only_property_become_view_only(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    apply(database)
    assert not is_property_view_only(database, prop)
    assert len(view_only_rooms(database, prop)) == 5
    assert all(not is_room_view_only(database, room) for room in rooms[:15])


def test_rooms_are_kept_by_lowest_number_in_natural_order(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    apply(database)
    assert view_only_rooms(database, prop) == {r.id for r in rooms[15:]}


def test_natural_order_puts_two_before_ten(database, owner, make_properties, make_room):
    (prop,) = make_properties(owner, 1)
    numbers = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"]
    numbers += ["14", "15", "100", "20"]
    rooms = {n: make_room(prop, number=n) for n in numbers}
    apply(database)
    assert view_only_rooms(database, prop) == {rooms["100"].id, rooms["20"].id}


def test_occupied_rooms_are_kept_before_the_lowest_numbers(
    database, owner, make_properties, make_rooms, make_tenant
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    make_tenant(rooms[17], invitation=False)
    make_tenant(rooms[19], invitation=False)
    apply(database)
    kept = {r.id for r in rooms[:13]} | {rooms[17].id, rooms[19].id}
    assert view_only_rooms(database, prop) == {r.id for r in rooms} - kept


def test_all_occupied_rooms_are_kept_in_number_order_when_there_are_too_many(
    database, owner, make_properties, make_rooms, make_tenant
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 17)
    for room in rooms[1:]:
        make_tenant(room, invitation=False)
    apply(database)
    assert view_only_rooms(database, prop) == {rooms[0].id, rooms[16].id}


def test_a_room_whose_lease_ended_is_not_occupied(
    database, owner, make_properties, make_rooms, make_tenant
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 16)
    make_tenant(rooms[15], invitation=False, lease_ended=True)
    apply(database)
    assert view_only_rooms(database, prop) == {rooms[15].id}


def test_a_room_of_a_deleted_tenant_is_not_occupied(
    database, owner, make_properties, make_rooms, make_tenant
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 16)
    make_tenant(rooms[15], invitation=False, deleted=True, lease_ended=True)
    apply(database)
    assert view_only_rooms(database, prop) == {rooms[15].id}


def test_fifteen_rooms_fit_the_free_plan(database, owner, make_properties, make_rooms):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 15)
    apply(database)
    assert view_only_rooms(database, prop) == set()


def test_deleted_rooms_do_not_count_against_the_room_limit(
    database, owner, make_properties, make_rooms, make_room
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 15)
    deleted = [make_room(prop, number=f"X{n}", deleted=True) for n in range(3)]
    apply(database)
    assert view_only_rooms(database, prop) == set()
    assert all(not is_room_view_only(database, room) for room in deleted)


def test_deleted_rooms_are_never_chosen_as_kept_rooms(
    database, owner, make_properties, make_rooms, make_room
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 16)
    deleted = make_room(prop, number="0", deleted=True)
    apply(database)
    assert view_only_rooms(database, prop) == {rooms[15].id}
    assert not is_room_view_only(database, deleted)


def test_only_the_rooms_of_the_kept_property_are_chosen(
    database, owner, make_properties, make_rooms
):
    first, second = make_properties(owner, 2)
    first_rooms = make_rooms(first, 18)
    second_rooms = make_rooms(second, 18)
    apply(database)
    assert is_property_view_only(database, second)
    assert view_only_rooms(database, first) == {r.id for r in first_rooms[15:]}
    assert view_only_rooms(database, second) == set()
    assert all(not is_room_view_only(database, r) for r in second_rooms)


def test_rooms_of_a_basic_owner_are_never_limited(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 30)
    set_subscription(database, owner, plan="basic")
    apply(database)
    assert view_only_rooms(database, prop) == set()


def test_rooms_of_basic_properties_that_are_not_kept_stay_as_they_are(
    database, owner, make_properties, make_rooms
):
    props = make_properties(owner, 4)
    rooms = make_rooms(props[3], 3)
    set_subscription(database, owner, plan="basic")
    apply(database)
    assert is_property_view_only(database, props[3])
    assert all(not is_room_view_only(database, r) for r in rooms)


# Rooms: a stored confirmation


def test_a_confirmation_decides_which_rooms_stay_editable(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms[5:]])
    apply(database)
    assert view_only_rooms(database, prop) == {r.id for r in rooms[:5]}
    assert schedule_row(database, owner) is None


def test_a_confirmation_overrides_occupancy_and_number_order(
    database, owner, make_properties, make_rooms, make_tenant
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 16)
    make_tenant(rooms[0], invitation=False)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [prop.id], [r.id for r in rooms[1:]])
    apply(database)
    assert view_only_rooms(database, prop) == {rooms[0].id}


def test_a_confirmation_decides_properties_and_rooms_together(
    database, owner, make_properties, make_rooms
):
    first, second, third = make_properties(owner, 3)
    make_rooms(first, 3)
    rooms = make_rooms(second, 18)
    third_rooms = make_rooms(third, 2)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "free", [second.id], [r.id for r in rooms[3:]])
    apply(database)
    assert view_only_properties(database, owner) == {first.id, third.id}
    assert view_only_rooms(database, second) == {r.id for r in rooms[:3]}
    assert all(not is_room_view_only(database, r) for r in third_rooms)


def test_a_mismatched_confirmation_does_not_choose_rooms(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 18)
    ended_period(database, owner, "pro")
    store_schedule(database, owner, "basic", [prop.id])
    apply(database)
    assert view_only_rooms(database, prop) == {r.id for r in rooms[15:]}
    assert schedule_row(database, owner) is None


# Nothing to limit


def test_an_owner_within_the_free_limits_is_untouched(
    database, owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 15)
    before = snapshot(database)
    apply(database)
    assert snapshot(database) == before


def test_an_owner_without_properties_is_untouched(database, owner):
    apply(database)
    assert snapshot(database) == {}


def test_a_running_pro_period_is_never_limited(
    database, owner, make_properties, make_rooms
):
    props = make_properties(owner, 5)
    make_rooms(props[0], 30)
    set_subscription(database, owner, plan="pro")
    before = snapshot(database)
    apply(database)
    assert snapshot(database) == before


def test_a_running_basic_period_within_its_limits_is_untouched(
    database, owner, make_properties, make_rooms
):
    props = make_properties(owner, 3)
    make_rooms(props[0], 30)
    set_subscription(database, owner, plan="basic")
    before = snapshot(database)
    apply(database)
    assert snapshot(database) == before


def test_a_scheduled_downgrade_waits_while_the_period_runs(
    database, owner, make_properties
):
    props = make_properties(owner, 4)
    set_subscription(database, owner, plan="pro")
    store_schedule(database, owner, "free", [props[3].id])
    before = snapshot(database)
    apply(database)
    assert snapshot(database) == before
    assert schedule_row(database, owner) is not None


def test_properties_that_are_already_view_only_stay_view_only(
    database, owner, make_property
):
    make_property(owner, name="Kos A")
    old = make_property(owner, name="Kos B", view_only=True)
    apply(database)
    assert is_property_view_only(database, old)


def test_a_second_run_changes_nothing(
    database, owner, make_properties, make_rooms, make_tenant
):
    first, second = make_properties(owner, 2)
    rooms = make_rooms(first, 20)
    make_tenant(rooms[19], invitation=False)
    make_rooms(second, 2)
    apply(database)
    after_first = snapshot(database)
    apply(database)
    assert snapshot(database) == after_first


def test_a_second_run_after_a_confirmation_changes_nothing(
    database, owner, make_properties
):
    props = make_properties(owner, 3)
    store_schedule(database, owner, "free", [props[2].id])
    apply(database)
    after_first = snapshot(database)
    apply(database)
    assert snapshot(database) == after_first
    assert schedule_row(database, owner) is None


def test_the_job_flushes_but_does_not_commit(database, owner, make_properties):
    from app.services.subscriptions import apply_plan_limits

    props = make_properties(owner, 2)
    with Session(database) as db:
        apply_plan_limits(db)
        db.flush()
        assert not is_property_view_only(database, props[1])
        db.rollback()
    assert not is_property_view_only(database, props[1])


# Restoring editability


def restore(database, owner) -> None:
    from app.services.subscriptions import restore_editability

    with Session(database) as db:
        restore_editability(db, owner.id)
        db.commit()


def test_restoring_makes_properties_and_rooms_editable_again(
    database, owner, make_property, make_room
):
    prop = make_property(owner, name="Kos A", view_only=True)
    room = make_room(prop, number="1", view_only=True)
    other_room = make_room(make_property(owner, name="Kos B"), number="1")
    restore(database, owner)
    assert not is_property_view_only(database, prop)
    assert not is_room_view_only(database, room)
    assert not is_room_view_only(database, other_room)


def test_restoring_removes_the_scheduled_downgrade(database, owner, make_property):
    prop = make_property(owner, name="Kos A")
    store_schedule(database, owner, "free", [prop.id])
    restore(database, owner)
    assert schedule_row(database, owner) is None


def test_restoring_without_anything_to_restore_succeeds(database, owner):
    restore(database, owner)


def test_restoring_leaves_other_owners_alone(
    database, owner, make_user, make_property, make_room
):
    other = make_user()
    prop = make_property(other, name="Kos X", view_only=True)
    room = make_room(prop, number="1", view_only=True)
    store_schedule(database, other, "free", [prop.id])
    restore(database, owner)
    assert is_property_view_only(database, prop)
    assert is_room_view_only(database, room)
    assert schedule_row(database, other) is not None


def test_restoring_flushes_but_does_not_commit(database, owner, make_property):
    from app.services.subscriptions import restore_editability

    prop = make_property(owner, name="Kos A", view_only=True)
    with Session(database) as db:
        restore_editability(db, owner.id)
        db.flush()
        assert is_property_view_only(database, prop)
        db.rollback()
    assert is_property_view_only(database, prop)


# Granting restores editability


def grant(database, owner, plan: str = "pro", days: int = 30) -> None:
    from app.schemas.subscriptions import PaidPlanCode
    from app.services.subscriptions import grant_subscription

    with Session(database) as db:
        grant_subscription(db, owner, PaidPlanCode(plan), days)
        db.commit()


def test_a_grant_makes_view_only_properties_and_rooms_editable(
    database, owner, make_property, make_room
):
    prop = make_property(owner, name="Kos A", view_only=True)
    room = make_room(prop, number="1", view_only=True)
    grant(database, owner)
    assert not is_property_view_only(database, prop)
    assert not is_room_view_only(database, room)


def test_a_grant_removes_the_scheduled_downgrade(database, owner, make_property):
    prop = make_property(owner, name="Kos A")
    store_schedule(database, owner, "free", [prop.id])
    grant(database, owner, "basic")
    assert schedule_row(database, owner) is None


def test_a_grant_leaves_other_owners_view_only_properties(
    database, owner, make_user, make_property
):
    other_prop = make_property(make_user(), name="Kos X", view_only=True)
    grant(database, owner)
    assert is_property_view_only(database, other_prop)


def test_the_grant_command_restores_editability(
    database, owner, make_property, make_room
):
    from app.cli import main

    prop = make_property(owner, name="Kos A", view_only=True)
    room = make_room(prop, number="1", view_only=True)
    store_schedule(database, owner, "free", [prop.id])
    assert main(["grant-subscription", owner.email, "pro"]) == 0
    assert not is_property_view_only(database, prop)
    assert not is_room_view_only(database, room)
    assert schedule_row(database, owner) is None
