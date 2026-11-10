"""Confirming, replacing and cancelling a scheduled downgrade."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from subscription_support import (
    assert_error,
    is_property_view_only,
    is_room_view_only,
    jakarta_date,
    schedule_row,
    set_subscription,
    store_schedule,
    stored_subscription,
)

URL = "/subscription/scheduled-downgrade"
SUBSCRIPTION_URL = "/subscription"


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def pro_owner(owner, database):
    """An owner whose Pro period is running."""
    set_subscription(
        database,
        owner,
        plan="pro",
        ends_at=datetime(2099, 3, 10, 20, 0, tzinfo=UTC),
    )
    return owner


@pytest.fixture
def basic_owner(owner, database):
    """An owner whose Basic period is running."""
    set_subscription(
        database,
        owner,
        plan="basic",
        ends_at=datetime(2099, 3, 10, 20, 0, tzinfo=UTC),
    )
    return owner


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


def put(client, headers, plan, properties, rooms=None):
    body = {"planCode": plan, "keptPropertyIds": [str(p) for p in properties]}
    if rooms is not None:
        body["keptRoomIds"] = [str(r) for r in rooms]
    return client.put(URL, json=body, headers=headers)


def pids(rows) -> list:
    return [row.id for row in rows]


def scheduled(client, headers):
    response = client.get(SUBSCRIPTION_URL, headers=headers)
    return response.json()["scheduledDowngrade"]


# Whether the request is a downgrade


@pytest.mark.parametrize("plan", ["free", "basic"])
def test_a_free_owner_cannot_schedule_a_downgrade(
    client, owner, owner_in, database, make_properties, plan
):
    props = make_properties(owner, 1)
    response = put(client, owner_in.headers, plan, pids(props))
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")
    assert schedule_row(database, owner) is None


@pytest.mark.parametrize("plan", ["free", "basic"])
def test_an_ended_paid_period_cannot_be_downgraded(
    client, owner, owner_in, pro_owner, expire_subscription, make_properties, plan
):
    expire_subscription(owner)
    props = make_properties(owner, 1)
    response = put(client, owner_in.headers, plan, pids(props))
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


def test_the_same_plan_is_not_a_downgrade_for_basic(
    client, owner_in, basic_owner, make_properties
):
    props = make_properties(basic_owner, 1)
    response = put(client, owner_in.headers, "basic", pids(props))
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


def test_the_same_plan_is_not_a_downgrade_for_pro(client, owner_in, pro_owner):
    response = put(client, owner_in.headers, "pro", [])
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


def test_a_higher_plan_is_not_a_downgrade(client, owner_in, basic_owner):
    response = put(client, owner_in.headers, "pro", [])
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


def test_a_free_owner_cannot_schedule_pro(client, owner_in):
    response = put(client, owner_in.headers, "pro", [])
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


@pytest.mark.parametrize("plan", ["free", "basic"])
def test_a_pro_owner_can_downgrade_to_a_lower_plan(
    client, owner, owner_in, pro_owner, make_properties, plan
):
    props = make_properties(owner, 1)
    response = put(client, owner_in.headers, plan, pids(props))
    assert response.status_code == 200, response.text


def test_a_basic_owner_can_downgrade_to_free(
    client, owner, owner_in, basic_owner, make_properties
):
    props = make_properties(owner, 1)
    assert put(client, owner_in.headers, "free", pids(props)).status_code == 200


# Order of the checks


def test_the_downgrade_is_checked_before_the_kept_properties(
    client, owner, owner_in, make_properties
):
    foreign = str(uuid4())
    response = client.put(
        URL,
        json={"planCode": "basic", "keptPropertyIds": [foreign, foreign]},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "SUBSCRIPTION_NOT_A_DOWNGRADE", "planCode")


def test_the_kept_properties_are_checked_before_the_kept_rooms(
    client, owner, owner_in, pro_owner, make_properties
):
    make_properties(owner, 2)
    response = client.put(
        URL,
        json={
            "planCode": "free",
            "keptPropertyIds": [],
            "keptRoomIds": [str(uuid4())],
        },
        headers=owner_in.headers,
    )
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_the_kept_rooms_are_checked_last(
    client, owner, owner_in, pro_owner, make_properties
):
    props = make_properties(owner, 2)
    response = put(client, owner_in.headers, "free", pids(props[:1]), [uuid4()])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


# Kept properties


@pytest.mark.parametrize(
    ("plan", "owned", "kept"),
    [
        ("free", 3, 1),
        ("free", 1, 1),
        ("basic", 5, 3),
        ("basic", 3, 3),
        ("basic", 2, 2),
        ("free", 0, 0),
    ],
)
def test_exactly_the_limit_or_all_properties_may_be_kept(
    client, owner, owner_in, pro_owner, make_properties, plan, owned, kept
):
    props = make_properties(owner, owned)
    response = put(client, owner_in.headers, plan, pids(props[:kept]))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("plan", "owned", "kept"),
    [
        ("free", 3, 0),
        ("free", 3, 2),
        ("free", 3, 3),
        ("free", 1, 0),
        ("basic", 5, 2),
        ("basic", 5, 4),
        ("basic", 5, 0),
        ("basic", 2, 1),
        ("basic", 1, 0),
    ],
)
def test_a_wrong_number_of_kept_properties_is_rejected(
    client, owner, owner_in, pro_owner, database, make_properties, plan, owned, kept
):
    props = make_properties(owner, owned)
    response = put(client, owner_in.headers, plan, pids(props[:kept]))
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")
    assert schedule_row(database, owner) is None


def test_a_property_of_another_owner_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_user, make_property, make_properties
):
    make_properties(owner, 2)
    foreign = make_property(make_user(), name="Kos Lain")
    response = put(client, owner_in.headers, "free", [foreign.id])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_an_unknown_property_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_properties
):
    make_properties(owner, 2)
    response = put(client, owner_in.headers, "free", [uuid4()])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_a_deleted_property_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_property, make_properties
):
    make_properties(owner, 2)
    deleted = make_property(owner, name="Kos Lama", deleted=True)
    response = put(client, owner_in.headers, "free", [deleted.id])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_deleted_properties_do_not_count_as_owned(
    client, owner, owner_in, pro_owner, make_property, make_properties
):
    props = make_properties(owner, 1)
    make_property(owner, name="Kos Lama", deleted=True)
    assert put(client, owner_in.headers, "free", pids(props)).status_code == 200


def test_a_view_only_property_can_be_kept(
    client, owner, owner_in, pro_owner, make_property, make_properties
):
    first = make_property(owner, name="Kos Tutup", view_only=True)
    make_properties(owner, 2)
    assert put(client, owner_in.headers, "free", [first.id]).status_code == 200


def test_view_only_properties_count_as_owned(
    client, owner, owner_in, pro_owner, make_property
):
    a = make_property(owner, name="Kos A", view_only=True)
    make_property(owner, name="Kos B")
    response = put(client, owner_in.headers, "basic", [a.id])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_a_property_cannot_be_listed_twice(
    client, owner, owner_in, pro_owner, make_properties
):
    props = make_properties(owner, 4)
    ids = pids(props)
    response = put(client, owner_in.headers, "basic", [ids[0], ids[0], ids[1]])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


def test_a_property_listed_twice_for_a_single_slot_is_rejected(
    client, owner, owner_in, pro_owner, make_properties
):
    props = make_properties(owner, 2)
    response = put(client, owner_in.headers, "free", [props[0].id, props[0].id])
    assert_error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")


# Kept rooms


def test_free_needs_every_room_of_a_kept_property_with_few_rooms(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 3)
    response = put(client, owner_in.headers, "free", [prop.id], pids(rooms))
    assert response.status_code == 200, response.text


def test_free_rejects_missing_rooms_of_a_kept_property_with_few_rooms(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 3)
    response = put(client, owner_in.headers, "free", [prop.id], pids(rooms[:2]))
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_free_without_rooms_listed_is_rejected_when_the_property_has_rooms(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 2)
    response = put(client, owner_in.headers, "free", [prop.id])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_free_with_a_property_without_rooms_keeps_no_rooms(
    client, owner, owner_in, pro_owner, make_properties
):
    (prop,) = make_properties(owner, 1)
    assert put(client, owner_in.headers, "free", [prop.id], []).status_code == 200
    assert put(client, owner_in.headers, "free", [prop.id]).status_code == 200


def test_free_needs_exactly_fifteen_of_many_rooms(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    response = put(client, owner_in.headers, "free", [prop.id], pids(rooms[5:]))
    assert response.status_code == 200, response.text


def test_exactly_fifteen_rooms_of_exactly_fifteen_is_accepted(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 15)
    assert (
        put(client, owner_in.headers, "free", [prop.id], pids(rooms)).status_code == 200
    )


@pytest.mark.parametrize("kept", [0, 1, 14, 16, 20])
def test_free_rejects_a_wrong_number_of_rooms_of_a_large_property(
    client, owner, owner_in, pro_owner, database, make_properties, make_rooms, kept
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 20)
    response = put(client, owner_in.headers, "free", [prop.id], pids(rooms[:kept]))
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")
    assert schedule_row(database, owner) is None


def test_a_room_of_another_property_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    first, second = make_properties(owner, 2)
    make_rooms(first, 1)
    (stray,) = make_rooms(second, 1)
    response = put(client, owner_in.headers, "free", [first.id], [stray.id])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_a_room_of_another_owner_cannot_be_kept(
    client,
    owner,
    owner_in,
    pro_owner,
    make_user,
    make_property,
    make_room,
    make_properties,
):
    (prop,) = make_properties(owner, 1)
    make_room(prop, number="1")
    stranger = make_room(make_property(make_user(), name="Kos Lain"), number="1")
    response = put(client, owner_in.headers, "free", [prop.id], [stranger.id])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_an_unknown_room_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 1)
    response = put(client, owner_in.headers, "free", [prop.id], [uuid4()])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_a_deleted_room_cannot_be_kept(
    client, owner, owner_in, pro_owner, make_properties, make_rooms, make_room
):
    (prop,) = make_properties(owner, 1)
    make_rooms(prop, 1)
    gone = make_room(prop, number="9", deleted=True)
    response = put(client, owner_in.headers, "free", [prop.id], [gone.id])
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_deleted_rooms_do_not_count_as_rooms_of_the_property(
    client, owner, owner_in, pro_owner, make_properties, make_rooms, make_room
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 2)
    make_room(prop, number="9", deleted=True)
    assert (
        put(client, owner_in.headers, "free", [prop.id], pids(rooms)).status_code == 200
    )


def test_a_view_only_room_can_be_kept(
    client, owner, owner_in, pro_owner, make_properties, make_room
):
    (prop,) = make_properties(owner, 1)
    room = make_room(prop, number="1", view_only=True)
    assert (
        put(client, owner_in.headers, "free", [prop.id], [room.id]).status_code == 200
    )


def test_a_room_cannot_be_listed_twice(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 2)
    response = put(
        client,
        owner_in.headers,
        "free",
        [prop.id],
        [rooms[0].id, rooms[0].id],
    )
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_a_duplicate_room_is_rejected_even_when_the_count_matches_the_limit(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 16)
    kept = [r.id for r in rooms[:14]] + [rooms[0].id]
    response = put(client, owner_in.headers, "free", [prop.id], kept)
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_rooms_of_a_property_that_is_not_kept_are_rejected(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    kept, other = make_properties(owner, 2)
    other_rooms = make_rooms(other, 2)
    response = put(client, owner_in.headers, "free", [kept.id], pids(other_rooms))
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


def test_basic_accepts_no_rooms(client, owner, owner_in, pro_owner, make_properties):
    props = make_properties(owner, 3)
    assert put(client, owner_in.headers, "basic", pids(props), []).status_code == 200
    assert put(client, owner_in.headers, "basic", pids(props)).status_code == 200


def test_basic_rejects_listed_rooms(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    props = make_properties(owner, 3)
    rooms = make_rooms(props[0], 2)
    response = put(client, owner_in.headers, "basic", pids(props), pids(rooms))
    assert_error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")


# The stored confirmation


def test_the_confirmation_is_answered_and_stored(
    client, owner, owner_in, pro_owner, database, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 3)
    response = put(client, owner_in.headers, "free", [prop.id], pids(rooms))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"planCode", "effectiveDate", "keptPropertyIds", "keptRoomIds"}
    assert body["planCode"] == "free"
    assert set(body["keptPropertyIds"]) == {str(prop.id)}
    assert set(body["keptRoomIds"]) == {str(r.id) for r in rooms}
    row = schedule_row(database, owner)
    assert row.plan == "free"
    assert set(row.kept_property_ids) == {prop.id}
    assert set(row.kept_room_ids) == {r.id for r in rooms}


def test_the_effective_date_is_the_day_after_the_period_ends(
    client, owner, owner_in, pro_owner, database, make_properties
):
    props = make_properties(owner, 1)
    body = put(client, owner_in.headers, "free", pids(props)).json()
    ends_at = stored_subscription(database, owner).ends_at
    assert jakarta_date(ends_at).isoformat() == "2099-03-11"
    assert body["effectiveDate"] == "2099-03-12"


def test_the_effective_date_follows_a_period_ending_in_the_morning(
    client, owner, owner_in, database, make_properties
):
    set_subscription(
        database, owner, plan="pro", ends_at=datetime(2099, 12, 31, 2, 0, tzinfo=UTC)
    )
    props = make_properties(owner, 1)
    body = put(client, owner_in.headers, "free", pids(props)).json()
    assert body["effectiveDate"] == "2100-01-01"


def test_a_basic_confirmation_has_no_rooms(
    client, owner, owner_in, pro_owner, make_properties
):
    props = make_properties(owner, 3)
    body = put(client, owner_in.headers, "basic", pids(props)).json()
    assert body["planCode"] == "basic"
    assert body["keptRoomIds"] == []
    assert set(body["keptPropertyIds"]) == {str(p.id) for p in props}


def test_the_confirmation_is_shown_in_the_subscription(
    client, owner, owner_in, pro_owner, make_properties, make_rooms
):
    (prop,) = make_properties(owner, 1)
    rooms = make_rooms(prop, 2)
    answer = put(client, owner_in.headers, "free", [prop.id], pids(rooms)).json()
    shown = scheduled(client, owner_in.headers)
    assert shown["planCode"] == "free"
    assert shown["effectiveDate"] == answer["effectiveDate"]
    assert set(shown["keptPropertyIds"]) == set(answer["keptPropertyIds"])
    assert set(shown["keptRoomIds"]) == set(answer["keptRoomIds"])


def test_scheduling_changes_nothing_until_the_period_ends(
    client, owner, owner_in, pro_owner, database, make_properties, make_rooms
):
    first, second = make_properties(owner, 2)
    rooms = make_rooms(first, 1)
    put(client, owner_in.headers, "free", [first.id], pids(rooms))
    assert not is_property_view_only(database, second)
    assert not is_property_view_only(database, first)
    assert not is_room_view_only(database, rooms[0])
    body = client.get(SUBSCRIPTION_URL, headers=owner_in.headers).json()
    assert body["planCode"] == "pro"
    assert body["status"] == "active"


def test_a_second_confirmation_replaces_the_first(
    client, owner, owner_in, pro_owner, database, make_properties, make_rooms
):
    first, second = make_properties(owner, 2)
    rooms = make_rooms(second, 2)
    put(client, owner_in.headers, "free", [first.id], [])
    answer = put(client, owner_in.headers, "free", [second.id], pids(rooms))
    assert answer.status_code == 200
    row = schedule_row(database, owner)
    assert row.kept_property_ids == [second.id]
    assert set(row.kept_room_ids) == {r.id for r in rooms}
    shown = scheduled(client, owner_in.headers)
    assert shown["keptPropertyIds"] == [str(second.id)]


def test_a_second_confirmation_may_change_the_plan(
    client, owner, owner_in, pro_owner, database, make_properties
):
    props = make_properties(owner, 3)
    put(client, owner_in.headers, "basic", pids(props))
    put(client, owner_in.headers, "free", pids(props[:1]))
    row = schedule_row(database, owner)
    assert row.plan == "free"
    assert row.kept_property_ids == [props[0].id]


def test_a_rejected_request_keeps_the_earlier_confirmation(
    client, owner, owner_in, pro_owner, database, make_properties
):
    props = make_properties(owner, 3)
    put(client, owner_in.headers, "basic", pids(props))
    rejected = put(client, owner_in.headers, "basic", pids(props[:1]))
    assert rejected.status_code == 422
    row = schedule_row(database, owner)
    assert row.plan == "basic"
    assert set(row.kept_property_ids) == {p.id for p in props}


def test_the_confirmation_of_one_owner_does_not_touch_another(
    client, owner, owner_in, pro_owner, database, make_user, make_properties
):
    other = make_user()
    other_props = make_properties(other, 1)
    set_subscription(database, other, plan="pro")
    store_schedule(database, other, "free", pids(other_props))
    mine = make_properties(owner, 1)
    put(client, owner_in.headers, "free", pids(mine))
    assert schedule_row(database, other).kept_property_ids == [other_props[0].id]


# Request body


def test_an_unknown_plan_is_a_validation_failure(client, owner_in, pro_owner):
    response = client.put(
        URL,
        json={"planCode": "gold", "keptPropertyIds": []},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "planCode")


def test_a_malformed_property_id_is_a_validation_failure(client, owner_in, pro_owner):
    response = client.put(
        URL,
        json={"planCode": "free", "keptPropertyIds": ["nope"]},
        headers=owner_in.headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["field"].startswith("keptPropertyIds")


# Cancelling


def test_cancelling_removes_the_confirmation(
    client, owner, owner_in, pro_owner, database, make_properties
):
    props = make_properties(owner, 1)
    put(client, owner_in.headers, "free", pids(props))
    response = client.delete(URL, headers=owner_in.headers)
    assert response.status_code == 204
    assert response.content == b""
    assert schedule_row(database, owner) is None
    assert scheduled(client, owner_in.headers) is None


def test_cancelling_when_nothing_is_scheduled_succeeds(client, owner_in):
    response = client.delete(URL, headers=owner_in.headers)
    assert response.status_code == 204
    assert response.content == b""


def test_cancelling_twice_succeeds(client, owner_in, pro_owner, make_properties):
    assert client.delete(URL, headers=owner_in.headers).status_code == 204
    assert client.delete(URL, headers=owner_in.headers).status_code == 204


def test_cancelling_leaves_the_subscription_and_properties_alone(
    client, owner, owner_in, pro_owner, database, make_properties
):
    props = make_properties(owner, 2)
    put(client, owner_in.headers, "free", pids(props[:1]))
    client.delete(URL, headers=owner_in.headers)
    body = client.get(SUBSCRIPTION_URL, headers=owner_in.headers).json()
    assert body["planCode"] == "pro"
    assert body["propertyCount"] == 2
    assert not is_property_view_only(database, props[1])


def test_cancelling_does_not_remove_the_confirmation_of_another_owner(
    client, owner_in, database, make_user, make_properties
):
    other = make_user()
    props = make_properties(other, 1)
    set_subscription(database, other, plan="pro")
    store_schedule(database, other, "free", pids(props))
    client.delete(URL, headers=owner_in.headers)
    assert schedule_row(database, other) is not None


def test_a_confirmation_can_be_made_again_after_cancelling(
    client, owner, owner_in, pro_owner, make_properties
):
    props = make_properties(owner, 1)
    put(client, owner_in.headers, "free", pids(props))
    client.delete(URL, headers=owner_in.headers)
    assert put(client, owner_in.headers, "free", pids(props)).status_code == 200
    assert scheduled(client, owner_in.headers) is not None


def test_the_period_end_is_unchanged_by_scheduling_and_cancelling(
    client, owner, owner_in, pro_owner, database, make_properties
):
    before = stored_subscription(database, owner).ends_at
    props = make_properties(owner, 1)
    put(client, owner_in.headers, "free", pids(props))
    client.delete(URL, headers=owner_in.headers)
    after = stored_subscription(database, owner).ends_at
    assert after == before
    assert after > datetime.now(UTC) + timedelta(days=1)
