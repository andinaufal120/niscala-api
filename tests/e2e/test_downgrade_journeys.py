"""Scenarios of scheduling a downgrade and living with view-only properties and rooms."""

from datetime import date
from uuid import uuid4

import pytest

from e2e.e2e_people import BANK_ACCOUNT
from e2e.e2e_rent import assert_field_error, edit_body
from e2e.e2e_subscription import (
    DOWNGRADE,
    by_number,
    day_after,
    editable_numbers,
    end_in_play,
    last_token,
    notify_play,
    play_plan_change,
    property_body,
    room_body,
    schedule_downgrade,
)

ROOM_NUMBERS = [f"R{number:02d}" for number in range(1, 18)]


def error(response, status: int, code: str, field: str | None = None) -> dict:
    return assert_field_error(response, status, code, field)


def put_property(owner, prop: dict, **changes):
    return owner.put(f"/properties/{prop['id']}", json=property_body(prop, **changes))


def put_room(person, room: dict, **changes):
    return person.put(f"/rooms/{room['id']}", json=room_body(room, **changes))


def lapse(world, owner, expire_subscription, *, google_reachable: bool = True) -> None:
    """End the owner's paid period for good.

    Google reports the purchase as ended, or cannot be asked at all while the
    daily job runs.
    """
    end_in_play(world, last_token(world))
    if not google_reachable:
        world.stubs.play_unreachable()
    expire_subscription(owner.namespace)


def add_numbered_rooms(owner, prop: dict) -> dict[str, dict]:
    return {number: owner.add_room(prop, number) for number in ROOM_NUMBERS}


def add_properties(owner, names: list[str]) -> dict[str, dict]:
    return {name: owner.add_property(name, bank_account=BANK_ACCOUNT) for name in names}


def editable_flags(owner) -> dict[str, bool]:
    return {p["name"]: p["editable"] for p in owner.properties()}


# Scheduling


def test_pro_owner_confirms_replaces_and_cancels_a_downgrade_to_basic(world):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    props = add_properties(owner, ["Kos A", "Kos B", "Kos C", "Kos D"])
    room_b = owner.add_room(props["Kos B"], "B1")
    stranger = world.owner_signs_up(email="toni@example.com", name="Toni Owner")
    foreign = stranger.add_property("Kos Asing")
    a, b, c, d = (props[name] for name in ("Kos A", "Kos B", "Kos C", "Kos D"))
    end_date = owner.subscription()["endDate"]

    bad_property_sets = {
        "too few": [b, c],
        "too many": [a, b, c, d],
        "a duplicate": [b, b, c],
        "an unknown property": [b, c, uuid4()],
        "someone else's property": [b, c, foreign],
        "none": [],
    }
    for label, kept in bad_property_sets.items():
        response = schedule_downgrade(owner, "basic", kept)
        assert response.status_code == 422, (label, response.text)
        error(response, 422, "KEPT_PROPERTIES_INVALID", "keptPropertyIds")
    error(
        schedule_downgrade(owner, "basic", [b, c, d], [room_b]),
        422,
        "KEPT_ROOMS_INVALID",
        "keptRoomIds",
    )
    error(
        schedule_downgrade(owner, "basic", [b], [room_b]),
        422,
        "KEPT_PROPERTIES_INVALID",
        "keptPropertyIds",
    )
    error(
        schedule_downgrade(owner, "pro", [a, b, c, d]),
        422,
        "SUBSCRIPTION_NOT_A_DOWNGRADE",
        "planCode",
    )
    error(
        schedule_downgrade(owner, "pro", []),
        422,
        "SUBSCRIPTION_NOT_A_DOWNGRADE",
        "planCode",
    )
    assert owner.subscription()["scheduledDowngrade"] is None

    confirmed = schedule_downgrade(owner, "basic", [b, c, d])

    assert confirmed.status_code == 200, confirmed.text
    expected = {
        "planCode": "basic",
        "effectiveDate": day_after(end_date),
        "keptPropertyIds": [b["id"], c["id"], d["id"]],
        "keptRoomIds": [],
    }
    assert confirmed.json() == expected
    assert owner.subscription()["scheduledDowngrade"] == expected
    assert owner.subscription()["planCode"] == "pro"

    replaced = schedule_downgrade(owner, "basic", [a, c, d])

    assert replaced.status_code == 200, replaced.text
    assert owner.subscription()["scheduledDowngrade"]["keptPropertyIds"] == [
        a["id"],
        c["id"],
        d["id"],
    ]

    cancelled = owner.delete(DOWNGRADE)
    assert cancelled.status_code == 204
    assert owner.subscription()["scheduledDowngrade"] is None
    assert owner.delete(DOWNGRADE).status_code == 204
    assert owner.subscription()["planCode"] == "pro"

    world.clock.run_daily_jobs()
    assert all(editable_flags(owner).values())

    assert schedule_downgrade(owner, "basic", [b, c, d]).status_code == 200


def test_a_downgrade_to_free_asks_for_the_property_and_its_rooms(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property("Kos Melati")
    anggrek = owner.add_property("Kos Anggrek")
    owner.add_room(melati, "A1")
    rooms = add_numbered_rooms(owner, anggrek)
    keep = [rooms[number] for number in ROOM_NUMBERS[2:]]

    error(
        schedule_downgrade(owner, "free", [melati, anggrek], keep),
        422,
        "KEPT_PROPERTIES_INVALID",
        "keptPropertyIds",
    )
    error(
        schedule_downgrade(owner, "free", [], keep),
        422,
        "KEPT_PROPERTIES_INVALID",
        "keptPropertyIds",
    )
    bad_room_sets = {
        "14 rooms": keep[:-1],
        "16 rooms": [*keep, rooms["R02"]],
        "none": [],
        "a duplicate": [*keep[:-1], keep[0]],
        "a room of another property": [*keep[:-1], owner.rooms(melati)[0]],
        "an unknown room": [*keep[:-1], uuid4()],
    }
    for label, kept in bad_room_sets.items():
        response = schedule_downgrade(owner, "free", [anggrek], kept)
        assert response.status_code == 422, (label, response.text)
        error(response, 422, "KEPT_ROOMS_INVALID", "keptRoomIds")
    error(
        schedule_downgrade(owner, "free", [melati], keep),
        422,
        "KEPT_ROOMS_INVALID",
        "keptRoomIds",
    )
    assert owner.subscription()["scheduledDowngrade"] is None

    confirmed = schedule_downgrade(owner, "free", [anggrek], keep)

    assert confirmed.status_code == 200, confirmed.text
    scheduled = owner.subscription()["scheduledDowngrade"]
    assert scheduled["planCode"] == "free"
    assert scheduled["keptPropertyIds"] == [anggrek["id"]]
    assert sorted(scheduled["keptRoomIds"]) == sorted(r["id"] for r in keep)
    assert scheduled["effectiveDate"] == day_after(owner.subscription()["endDate"])

    upgraded = owner.subscribe("pro", "yearly")

    assert upgraded["planCode"] == "pro"
    assert upgraded["scheduledDowngrade"] is None


# Basic to Free with tenants


def test_the_property_that_is_not_kept_turns_view_only_but_its_business_continues(
    seeded_world, world, expire_subscription
):
    owner, manager = seeded_world.owner, seeded_world.manager
    budi, sari = seeded_world.budi, seeded_world.sari
    melati, anggrek = seeded_world.melati, seeded_world.anggrek
    rooms = seeded_world.rooms
    anggrek_rooms = [rooms["B1"], rooms["B2"]]

    error(
        schedule_downgrade(owner, "free", [anggrek], [rooms["B1"]]),
        422,
        "KEPT_ROOMS_INVALID",
        "keptRoomIds",
    )
    error(
        schedule_downgrade(owner, "free", [anggrek], [*anggrek_rooms, rooms["A1"]]),
        422,
        "KEPT_ROOMS_INVALID",
        "keptRoomIds",
    )
    other_choice = schedule_downgrade(
        owner, "free", [melati], [rooms["A1"], rooms["A2"], rooms["A3"]]
    )
    assert other_choice.status_code == 200, other_choice.text
    assert (
        schedule_downgrade(owner, "free", [anggrek], anggrek_rooms).status_code == 200
    )
    assert owner.delete(DOWNGRADE).status_code == 204
    assert owner.subscription()["scheduledDowngrade"] is None
    assert (
        schedule_downgrade(owner, "free", [anggrek], anggrek_rooms).status_code == 200
    )

    world.clock.run_daily_jobs()
    assert all(editable_flags(owner).values())
    assert put_property(owner, melati, name="Kos Melati Baru").status_code == 200
    assert put_property(owner, melati, name="Kos Melati").status_code == 200

    lapse(world, owner, expire_subscription, google_reachable=False)
    assert owner.subscription()["planCode"] == "free"
    assert all(editable_flags(owner).values())

    world.clock.run_daily_jobs()

    subscription = owner.subscription()
    assert subscription["planCode"] == "free"
    assert subscription["scheduledDowngrade"] is None
    assert subscription["propertyCount"] == 2
    assert editable_flags(owner) == {"Kos Melati": False, "Kos Anggrek": True}
    assert editable_flags(manager) == {"Kos Melati": False}
    assert editable_numbers(owner.rooms(melati), True) == []
    assert editable_numbers(owner.rooms(melati), False) == ["A1", "A2", "A3"]
    assert editable_numbers(owner.rooms(anggrek), True) == ["B1", "B2"]
    assert owner.read(f"/properties/{melati['id']}")["editable"] is False
    assert owner.read(f"/rooms/{rooms['A1']['id']}")["editable"] is False

    current = owner.read(f"/properties/{melati['id']}")
    error(put_property(owner, current), 403, "PROPERTY_READ_ONLY")
    error(put_room(owner, rooms["A3"]), 403, "PROPERTY_READ_ONLY")
    error(
        owner.post(
            f"/properties/{melati['id']}/rooms",
            json={"number": "A9", "baseRate": 900_000, "facilities": []},
        ),
        403,
        "PROPERTY_READ_ONLY",
    )
    budi_record = next(t for t in owner.tenants(melati) if t["name"] == "Budi Tenant")
    budi_detail = owner.read(f"/tenants/{budi_record['id']}")
    for staff in (owner, manager):
        error(
            staff.put(
                f"/tenants/{budi_record['id']}",
                json=edit_body(budi_detail, phone="081299999999"),
            ),
            403,
            "PROPERTY_READ_ONLY",
        )
    error(owner.delete(f"/tenants/{budi_record['id']}"), 403, "PROPERTY_READ_ONLY")
    error(
        owner.post(
            f"/properties/{melati['id']}/tenants",
            json={
                "roomId": rooms["A3"]["id"],
                "name": "Rudi Tenant",
                "phone": "081244444444",
                "lease": {},
                "emergencyContacts": [],
            },
        ),
        403,
        "PROPERTY_READ_ONLY",
    )
    error(owner.delete(f"/properties/{melati['id']}"), 409, "PROPERTY_HAS_ACTIVE_LEASE")
    assert [lease["room"]["number"] for lease in budi.leases()] == ["A1"]
    assert (
        put_property(owner, owner.read(f"/properties/{anggrek['id']}")).status_code
        == 200
    )
    assert put_room(owner, rooms["B1"], baseRate=850_000).status_code == 200

    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()
    budi_bills = budi.rent_bills()
    assert [bill["periodStart"] for bill in budi_bills] == ["2026-11-01", "2026-10-01"]
    uploaded = budi.upload_receipt(budi_bills[0])
    assert uploaded["payment"]["status"] == "awaitingVerification"
    verified = owner.post(f"/rent-bills/{uploaded['id']}/verification", expect=200)
    assert verified.json()["payment"]["status"] == "paid"
    sari_bill = sari.rent_bills()[0]
    cash = manager.post(
        f"/rent-bills/{sari_bill['id']}/cash-payment",
        json={"receivedOn": "2026-11-01"},
    )
    assert cash.status_code == 200, cash.text
    assert cash.json()["payment"]["method"] == "cash"
    complaint = budi.submit_complaint(rooms["A1"], "The ceiling fan makes a noise.")
    assert complaint["classificationState"] == "notClassified"
    moved = owner.post(
        f"/complaints/{complaint['id']}/status-changes",
        json={"status": "inProgress", "handlingNote": "Checking tomorrow."},
    )
    assert moved.status_code == 201, moved.text
    assert budi.complaint(complaint)["status"] == "inProgress"
    assert any(
        c["id"] == complaint["id"] and c["status"] == "inProgress"
        for c in manager.complaints()
    )

    world.stubs.play_reachable()
    resubscribed = owner.subscribe("basic")

    assert resubscribed["planCode"] == "basic"
    assert all(editable_flags(owner).values())
    assert editable_numbers(owner.rooms(melati), False) == []
    again = owner.read(f"/properties/{melati['id']}")
    assert put_property(owner, again, name="Kos Melati Indah").status_code == 200
    fresh = owner.read(f"/tenants/{budi_record['id']}")
    assert (
        manager.put(
            f"/tenants/{budi_record['id']}",
            json=edit_body(fresh, phone="081299999999"),
        ).status_code
        == 200
    )
    assert put_room(owner, rooms["A3"], baseRate=1_100_000).status_code == 200


# Pro to Basic through Google Play


def test_pro_to_basic_keeps_the_confirmed_properties_when_google_renews_as_basic(
    world, rtdn
):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    old_token = last_token(world)
    props = add_properties(owner, ["Kos A", "Kos B", "Kos C", "Kos D"])
    for prop in props.values():
        owner.add_room(prop, "1")
    keep = [props["Kos B"], props["Kos C"], props["Kos D"]]
    assert schedule_downgrade(owner, "basic", keep).status_code == 200
    world.clock.run_daily_jobs()
    assert all(editable_flags(owner).values())

    new_token = play_plan_change(world, owner, old_token, "basic")
    assert notify_play(world, new_token).status_code == 204
    assert owner.subscription()["planCode"] == "basic"
    world.clock.run_daily_jobs()

    subscription = owner.subscription()
    assert subscription["planCode"] == "basic"
    assert subscription["scheduledDowngrade"] is None
    assert subscription["propertyCount"] == 4
    assert editable_flags(owner) == {
        "Kos A": False,
        "Kos B": True,
        "Kos C": True,
        "Kos D": True,
    }
    for name, prop in props.items():
        rooms = owner.rooms(prop)
        assert [room["editable"] for room in rooms] == [name != "Kos A"]
    current = owner.read(f"/properties/{props['Kos A']['id']}")
    error(put_property(owner, current), 403, "PROPERTY_READ_ONLY")
    error(
        owner.post(
            f"/properties/{props['Kos A']['id']}/rooms",
            json={"number": "2", "baseRate": 900_000, "facilities": []},
        ),
        403,
        "PROPERTY_READ_ONLY",
    )
    error(
        owner.post("/properties", json={"name": "Kos E", "address": "Jl. Melati 5"}),
        403,
        "PROPERTY_LIMIT_REACHED",
    )

    deleted = owner.delete(f"/properties/{props['Kos A']['id']}")

    assert deleted.status_code == 204
    assert sorted(editable_flags(owner)) == ["Kos B", "Kos C", "Kos D"]
    assert owner.subscription()["propertyCount"] == 3
    error(
        owner.post("/properties", json={"name": "Kos E", "address": "Jl. Melati 5"}),
        403,
        "PROPERTY_LIMIT_REACHED",
    )
    assert owner.delete(f"/properties/{props['Kos D']['id']}").status_code == 204
    assert (
        owner.post(
            "/properties", json={"name": "Kos E", "address": "Jl. Melati 5"}
        ).status_code
        == 201
    )


# Pro to Free with rooms


def test_pro_to_free_keeps_the_confirmed_rooms_and_view_only_rooms_can_be_deleted(
    world, expire_subscription
):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    melati = owner.add_property("Kos Melati")
    anggrek = owner.add_property("Kos Anggrek", bank_account=BANK_ACCOUNT)
    owner.add_room(melati, "A1")
    rooms = add_numbered_rooms(owner, anggrek)
    token = owner.add_tenant(
        rooms["R01"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 1)},
    )
    budi = world.tenant_activates(token, email="budi@example.com")
    keep = [rooms[number] for number in ROOM_NUMBERS[2:]]
    assert schedule_downgrade(owner, "free", [anggrek], keep).status_code == 200

    lapse(world, owner, expire_subscription, google_reachable=False)
    world.clock.run_daily_jobs()

    assert editable_flags(owner) == {"Kos Melati": False, "Kos Anggrek": True}
    listed = owner.rooms(anggrek)
    assert editable_numbers(listed, False) == ["R01", "R02"]
    assert editable_numbers(listed, True) == ROOM_NUMBERS[2:]
    assert editable_numbers(owner.rooms(melati), False) == ["A1"]
    assert owner.read(f"/rooms/{rooms['R01']['id']}")["editable"] is False
    error(put_room(owner, rooms["R01"]), 403, "ROOM_READ_ONLY")
    assert put_room(owner, rooms["R03"], baseRate=1_100_000).status_code == 200
    error(put_room(owner, owner.rooms(melati)[0]), 403, "PROPERTY_READ_ONLY")
    record = owner.tenants(anggrek)[0]
    detail = owner.read(f"/tenants/{record['id']}")
    error(
        owner.put(
            f"/tenants/{record['id']}", json=edit_body(detail, phone="081299999999")
        ),
        403,
        "ROOM_READ_ONLY",
    )
    error(owner.delete(f"/tenants/{record['id']}"), 403, "ROOM_READ_ONLY")
    error(
        owner.post(
            f"/properties/{anggrek['id']}/tenants",
            json={
                "roomId": rooms["R02"]["id"],
                "name": "Rudi Tenant",
                "phone": "081244444444",
                "lease": {},
                "emergencyContacts": [],
            },
        ),
        403,
        "ROOM_READ_ONLY",
    )
    error(owner.delete(f"/rooms/{rooms['R01']['id']}"), 409, "ROOM_HAS_ACTIVE_LEASE")
    regenerated = owner.post(f"/tenants/{record['id']}/invitation")
    error(regenerated, 409, "TENANT_ALREADY_ACTIVE")

    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()
    assert len(budi.rent_bills()) == 2
    assert budi.rent_bills()[0]["payment"]["status"] == "unpaid"
    assert budi.leases()[0]["room"]["number"] == "R01"

    add_room = {"number": "R99", "baseRate": 900_000, "facilities": []}
    assert editable_numbers(owner.rooms(anggrek), True) == ROOM_NUMBERS[2:]
    assert owner.delete(f"/rooms/{rooms['R02']['id']}").status_code == 204
    assert "R02" not in by_number(owner.rooms(anggrek))
    error(
        owner.post(f"/properties/{anggrek['id']}/rooms", json=add_room),
        403,
        "ROOM_LIMIT_REACHED",
    )
    assert owner.delete(f"/rooms/{rooms['R03']['id']}").status_code == 204
    assert owner.delete(f"/rooms/{rooms['R04']['id']}").status_code == 204
    created = owner.post(f"/properties/{anggrek['id']}/rooms", json=add_room)
    assert created.status_code == 201, created.text
    assert owner.delete(f"/properties/{melati['id']}").status_code == 204
    assert [p["name"] for p in owner.properties()] == ["Kos Anggrek"]
    assert owner.subscription()["propertyCount"] == 1
    error(
        owner.post("/properties", json={"name": "Kos Baru", "address": "Jl. Baru 1"}),
        403,
        "PROPERTY_LIMIT_REACHED",
    )

    world.stubs.play_reachable()
    owner.subscribe("basic")

    assert editable_numbers(owner.rooms(anggrek), False) == []
    assert put_room(owner, rooms["R01"], baseRate=1_300_000).status_code == 200
    assert (
        owner.put(
            f"/tenants/{record['id']}", json=edit_body(detail, phone="081299999999")
        ).status_code
        == 200
    )


# Defaults and confirmations that no longer apply


@pytest.mark.parametrize("google_reachable", [True, False])
def test_without_a_confirmation_the_earliest_properties_and_occupied_rooms_stay(
    world, expire_subscription, google_reachable
):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    anggrek = owner.add_property("Kos Anggrek")
    owner.add_property("Kos Bakung")
    owner.add_property("Kos Cempaka")
    rooms = add_numbered_rooms(owner, anggrek)
    for number, phone in (("R16", "081211111116"), ("R17", "081211111117")):
        owner.add_tenant(rooms[number], f"Tenant {number}", phone)
    kept = [rooms[number] for number in ROOM_NUMBERS[2:]]
    assert schedule_downgrade(owner, "free", [anggrek], kept).status_code == 200
    assert owner.delete(DOWNGRADE).status_code == 204

    lapse(world, owner, expire_subscription, google_reachable=google_reachable)
    world.clock.run_daily_jobs()

    assert editable_flags(owner) == {
        "Kos Anggrek": True,
        "Kos Bakung": False,
        "Kos Cempaka": False,
    }
    listed = owner.rooms(anggrek)
    assert editable_numbers(listed, False) == ["R14", "R15"]
    assert "R16" in editable_numbers(listed, True)
    assert "R17" in editable_numbers(listed, True)
    assert "R01" in editable_numbers(listed, True)
    assert len(editable_numbers(listed, True)) == 15
    error(put_room(owner, by_number(listed)["R14"]), 403, "ROOM_READ_ONLY")


def test_a_confirmation_for_a_plan_that_did_not_follow_does_not_decide(
    world, expire_subscription
):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    props = add_properties(owner, ["Kos A", "Kos B", "Kos C", "Kos D"])
    keep = [props["Kos B"], props["Kos C"], props["Kos D"]]
    assert schedule_downgrade(owner, "basic", keep).status_code == 200

    lapse(world, owner, expire_subscription, google_reachable=False)
    world.clock.run_daily_jobs()

    assert owner.subscription()["planCode"] == "free"
    assert editable_flags(owner) == {
        "Kos A": True,
        "Kos B": False,
        "Kos C": False,
        "Kos D": False,
    }


def test_a_confirmed_property_that_was_deleted_is_skipped_and_its_place_is_refilled(
    world, rtdn
):
    owner = world.owner_signs_up()
    owner.subscribe("pro")
    old_token = last_token(world)
    props = add_properties(owner, ["Kos A", "Kos B", "Kos C", "Kos D", "Kos E"])
    keep = [props["Kos C"], props["Kos D"], props["Kos E"]]
    assert schedule_downgrade(owner, "basic", keep).status_code == 200
    assert owner.delete(f"/properties/{props['Kos D']['id']}").status_code == 204

    assert (
        notify_play(
            world, play_plan_change(world, owner, old_token, "basic")
        ).status_code
        == 204
    )
    world.clock.run_daily_jobs()

    assert editable_flags(owner) == {
        "Kos A": True,
        "Kos B": False,
        "Kos C": True,
        "Kos E": True,
    }
    assert owner.subscription()["propertyCount"] == 4
    assert owner.subscription()["scheduledDowngrade"] is None
