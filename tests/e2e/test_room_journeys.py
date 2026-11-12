"""Scenarios of rooms, plan limits on rooms, and the occupancy dashboard."""

from uuid import uuid4

from e2e.e2e_people import describe
from e2e.e2e_world import ANGGREK, MELATI


def assert_error(response, status, code, field=None):
    """Require an error answer with the given status, code and, if given, field."""
    assert response.status_code == status, describe(response)
    body = response.json()
    assert body["code"] == code, describe(response)
    if field is not None:
        assert body["field"] == field, describe(response)


def room_body(room, **changes):
    """The full room body of an edit, from a room as the API returned it."""
    body = {
        "number": room["number"],
        "baseRate": room["baseRate"],
        "facilities": room["facilities"],
        "lengthM": room["lengthM"],
        "widthM": room["widthM"],
    }
    return body | changes


def numbers(rooms):
    return [room["number"] for room in rooms]


# Adding and listing rooms


def test_rooms_are_listed_in_natural_order_and_numbers_are_unique_per_property(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)

    for number in ("10", "2", "1"):
        owner.add_room(melati, number)
    assert numbers(owner.rooms(melati)) == ["1", "2", "10"]

    owner.add_room(melati, "A1")
    clash = owner.post(
        f"/properties/{melati['id']}/rooms",
        json={"number": "  a1 ", "baseRate": 900_000, "facilities": []},
    )
    assert_error(clash, 409, "ROOM_NUMBER_TAKEN", "number")
    assert numbers(owner.rooms(melati)) == ["1", "2", "10", "A1"]

    trimmed = owner.add_room(melati, "  B7 ")
    assert trimmed["number"] == "B7"

    elsewhere = owner.add_room(anggrek, "A1")
    assert elsewhere["propertyId"] == anggrek["id"]
    assert numbers(owner.rooms(anggrek)) == ["A1"]


def test_a_new_room_is_vacant_and_shows_in_the_property_counts(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)

    room = owner.add_room(
        prop, "A1", base_rate=900_000, facilities=["ac"], length_m=3, width_m=4.5
    )

    assert room["version"] == 1
    assert room["occupancy"] == "vacant"
    assert room["lease"] is None
    assert room["editable"] is True
    assert room["lengthM"] == 3
    assert room["widthM"] == 4.5
    detail = owner.read(f"/rooms/{room['id']}")
    assert detail["number"] == "A1"
    assert detail["baseRate"] == 900_000
    assert detail["propertyId"] == prop["id"]
    listed = owner.rooms(prop)[0]
    assert listed["id"] == room["id"]
    assert listed["lease"] is None
    counts = owner.read(f"/properties/{prop['id']}")
    assert counts["roomCount"] == 1
    assert counts["vacantRoomCount"] == 1


def test_facilities_are_normalized_and_suggested_across_the_owners_rooms(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    stranger_room = stranger.add_room(
        stranger.add_property("Kos Lain"), "Z1", facilities=["jacuzzi"]
    )

    room = owner.add_room(melati, "A1", facilities=["  AC ", "Wi  Fi", "ac", " "])
    owner.add_room(anggrek, "B1", facilities=["kasur", "ac", "kamar mandi dalam"])
    assert sorted(room["facilities"]) == ["ac", "wi fi"]
    assert len(room["facilities"]) == 2

    expected = ["ac", "kamar mandi dalam", "kasur", "wi fi"]
    for prop in (melati, anggrek):
        suggestions = owner.read(f"/properties/{prop['id']}/facility-suggestions")
        assert suggestions["items"] == expected
    assert stranger_room["facilities"] == ["jacuzzi"]
    assert stranger.read(
        f"/properties/{stranger_room['propertyId']}/facility-suggestions"
    )["items"] == ["jacuzzi"]

    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager"), email="mira@example.com"
    )
    seen = manager.read(f"/properties/{melati['id']}/facility-suggestions")
    assert seen["items"] == expected

    owner.delete(f"/rooms/{owner.rooms(anggrek)[0]['id']}", expect=204)
    after = owner.read(f"/properties/{melati['id']}/facility-suggestions")
    assert after["items"] == ["ac", "wi fi"]
    other = owner.read(f"/properties/{anggrek['id']}/facility-suggestions")
    assert other["items"] == ["ac", "wi fi"]


# Editing and deleting rooms


def test_changing_the_base_rate_never_changes_the_rent_of_an_existing_lease(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1", base_rate=1_000_000, facilities=["ac"])
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")
    assert token.record["lease"]["rent"] == 1_000_000

    edited = owner.put(
        f"/rooms/{room['id']}",
        json=room_body(room, baseRate=1_500_000, lengthM=3, widthM=4),
        expect=200,
    ).json()

    assert edited["version"] == 2
    assert edited["baseRate"] == 1_500_000
    assert edited["occupancy"] == "occupied"
    assert edited["lease"]["rent"] == 1_000_000
    detail = owner.read(f"/rooms/{room['id']}")
    assert detail["baseRate"] == 1_500_000
    assert detail["lease"]["rent"] == 1_000_000
    assert owner.read(f"/tenants/{token.id}")["lease"]["rent"] == 1_000_000

    owner.delete(f"/tenants/{token.id}", expect=204)
    newcomer = owner.add_tenant(room, "Sari Tenant", "081222222222")
    assert newcomer.record["lease"]["rent"] == 1_500_000


def test_room_detail_shows_the_tenant_and_lease_of_an_occupied_room(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    occupied = owner.add_room(prop, "A1", base_rate=1_200_000)
    vacant = owner.add_room(prop, "A2")
    token = owner.add_tenant(
        occupied,
        "Budi Tenant",
        "0812-1111-1111",
        lease={"startDate": "2026-10-01", "endDate": "2027-09-30"},
    )

    detail = owner.read(f"/rooms/{occupied['id']}")
    listed = {r["number"]: r for r in owner.rooms(prop)}

    assert detail["occupancy"] == "occupied"
    assert detail["lease"]["tenantId"] == token.id
    assert detail["lease"]["tenantName"] == "Budi Tenant"
    assert detail["lease"]["tenantPhone"] == "081211111111"
    assert detail["lease"]["startDate"] == "2026-10-01"
    assert detail["lease"]["endDate"] == "2027-09-30"
    assert detail["lease"]["rent"] == 1_200_000
    assert listed["A1"]["occupancy"] == "occupied"
    assert listed["A1"]["lease"]["tenantName"] == "Budi Tenant"
    assert listed["A1"]["lease"]["endDate"] == "2027-09-30"
    assert listed["A2"]["occupancy"] == "vacant"
    assert listed["A2"]["lease"] is None
    assert owner.read(f"/rooms/{vacant['id']}")["lease"] is None


def test_editing_a_room_to_a_taken_number_is_refused_but_its_own_number_is_not(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    first = owner.add_room(prop, "A1")
    second = owner.add_room(prop, "A2")

    clash = owner.put(f"/rooms/{second['id']}", json=room_body(second, number=" a1 "))
    assert_error(clash, 409, "ROOM_NUMBER_TAKEN", "number")
    assert owner.read(f"/rooms/{second['id']}")["number"] == "A2"
    assert owner.read(f"/rooms/{second['id']}")["version"] == 1

    same = owner.put(f"/rooms/{first['id']}", json=room_body(first, number="a1"))
    assert same.status_code == 200
    assert same.json()["number"] == "a1"


def test_a_room_with_an_active_lease_can_only_be_deleted_after_the_tenant_is_removed(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")
    path = f"/rooms/{room['id']}"

    refused = owner.delete(path)
    assert_error(refused, 409, "ROOM_HAS_ACTIVE_LEASE")
    assert numbers(owner.rooms(prop)) == ["A1"]
    assert owner.read(path)["occupancy"] == "occupied"

    owner.delete(f"/tenants/{token.id}", expect=204)
    assert owner.read(path)["occupancy"] == "vacant"
    owner.delete(path, expect=204)

    assert owner.rooms(prop) == []
    assert_error(owner.get(path), 404, "ROOM_NOT_FOUND")
    assert_error(owner.put(path, json=room_body(room)), 404, "ROOM_NOT_FOUND")
    assert_error(owner.delete(path), 404, "ROOM_NOT_FOUND")
    assert owner.read(f"/properties/{prop['id']}")["roomCount"] == 0
    reused = owner.add_room(prop, "A1")
    assert reused["id"] != room["id"]


def test_a_room_of_another_owner_does_not_exist_for_an_owner(world):
    owner = world.owner_signs_up(email="rina@example.com")
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1")
    path = f"/rooms/{room['id']}"

    assert_error(stranger.get(path), 404, "ROOM_NOT_FOUND")
    assert_error(stranger.put(path, json=room_body(room)), 404, "ROOM_NOT_FOUND")
    assert_error(stranger.delete(path), 404, "ROOM_NOT_FOUND")
    assert_error(stranger.get(f"/rooms/{uuid4()}"), 404, "ROOM_NOT_FOUND")
    added = stranger.post(
        f"/properties/{prop['id']}/rooms",
        json={"number": "A2", "baseRate": 1_000_000, "facilities": []},
    )
    assert_error(added, 404, "PROPERTY_NOT_FOUND")
    assert numbers(owner.rooms(prop)) == ["A1"]
    assert owner.read(path)["version"] == 1


def test_a_manager_works_on_rooms_of_assigned_properties_only(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    own_room = owner.add_room(melati, "A1")
    other_room = owner.add_room(anggrek, "B1")
    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager"), email="mira@example.com"
    )

    added = manager.add_room(melati, "A2", base_rate=900_000)
    assert numbers(manager.rooms(melati)) == ["A1", "A2"]
    edited = manager.put(
        f"/rooms/{added['id']}", json=room_body(added, baseRate=950_000), expect=200
    ).json()
    assert edited["baseRate"] == 950_000
    assert manager.read(f"/rooms/{own_room['id']}")["number"] == "A1"

    cannot_add = manager.post(
        f"/properties/{anggrek['id']}/rooms",
        json={"number": "B9", "baseRate": 1_000_000, "facilities": []},
    )
    assert_error(cannot_add, 404, "PROPERTY_NOT_FOUND")
    assert_error(
        manager.get(f"/properties/{anggrek['id']}/rooms"), 404, "PROPERTY_NOT_FOUND"
    )
    other_path = f"/rooms/{other_room['id']}"
    assert_error(manager.get(other_path), 404, "ROOM_NOT_FOUND")
    assert_error(
        manager.put(other_path, json=room_body(other_room)), 404, "ROOM_NOT_FOUND"
    )
    assert_error(manager.delete(other_path), 404, "ROOM_NOT_FOUND")

    manager.delete(f"/rooms/{added['id']}", expect=204)
    assert numbers(owner.rooms(melati)) == ["A1"]
    assert numbers(owner.rooms(anggrek)) == ["B1"]


# Plan limits


def test_the_free_plan_limits_rooms_per_property_and_a_paid_plan_lifts_it(world):
    owner = world.owner_signs_up()
    plans = {p["code"]: p for p in owner.read("/subscription-plans")["items"]}
    limit = plans["free"]["maxRoomsPerProperty"]
    assert limit == 15
    assert plans["basic"]["maxRoomsPerProperty"] is None
    prop = owner.add_property(MELATI)
    manager = world.manager_activates(
        owner.add_manager([prop], name="Mira Manager"), email="mira@example.com"
    )
    for index in range(limit):
        owner.add_room(prop, f"R{index + 1}")

    body = {"number": "Extra", "baseRate": 1_000_000, "facilities": []}
    refused = owner.post(f"/properties/{prop['id']}/rooms", json=body)
    assert_error(refused, 403, "ROOM_LIMIT_REACHED")
    by_manager = manager.post(f"/properties/{prop['id']}/rooms", json=body)
    assert_error(by_manager, 403, "ROOM_LIMIT_REACHED")
    taken = owner.post(f"/properties/{prop['id']}/rooms", json=body | {"number": "R1"})
    assert_error(taken, 409, "ROOM_NUMBER_TAKEN", "number")
    assert len(owner.rooms(prop)) == limit

    last = owner.rooms(prop)[-1]
    owner.delete(f"/rooms/{last['id']}", expect=204)
    owner.add_room(prop, "Replacement")
    assert len(owner.rooms(prop)) == limit
    again = owner.post(f"/properties/{prop['id']}/rooms", json=body)
    assert_error(again, 403, "ROOM_LIMIT_REACHED")

    owner.subscribe("basic")
    owner.add_room(prop, "Extra")
    manager.add_room(prop, "Extra 2")
    assert len(owner.rooms(prop)) == limit + 2


def test_the_room_limit_applies_to_each_property_separately(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    first = owner.add_property(MELATI)
    second = owner.add_property(ANGGREK)
    owner.add_room(first, "A1")
    owner.add_room(first, "A2")

    owner.add_room(second, "A1")

    assert len(owner.rooms(first)) == 2
    assert len(owner.rooms(second)) == 1


# Occupancy dashboard


def figures(entry):
    return (
        entry["roomCount"],
        entry["occupiedRoomCount"],
        entry["vacantRoomCount"],
        entry["occupancyPercentage"],
    )


def test_an_owner_with_no_properties_or_rooms_sees_zeros(world):
    owner = world.owner_signs_up()

    empty = owner.read("/occupancy-dashboard")
    assert empty["items"] == []
    assert empty["summary"] == {
        "propertyCount": 0,
        "roomCount": 0,
        "occupiedRoomCount": 0,
        "vacantRoomCount": 0,
        "occupancyPercentage": 0,
    }

    owner.add_property(MELATI)
    no_rooms = owner.read("/occupancy-dashboard")
    assert [item["name"] for item in no_rooms["items"]] == [MELATI]
    assert figures(no_rooms["items"][0]) == (0, 0, 0, 0)
    assert no_rooms["items"][0]["rooms"] == []
    assert no_rooms["summary"]["propertyCount"] == 1
    assert figures(no_rooms["summary"]) == (0, 0, 0, 0)


def test_dashboard_figures_follow_tenants_added_and_removed_and_round_half_up(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    cempaka = owner.add_property("Kos Cempaka")
    melati_rooms = {
        number: owner.add_room(melati, number)
        for number in ("10", "9", "8", "7", "6", "5", "4", "3")
    }
    anggrek_rooms = {n: owner.add_room(anggrek, n) for n in ("B10", "B2")}
    cempaka_rooms = {n: owner.add_room(cempaka, n) for n in ("C3", "C2", "C1")}

    def dashboard():
        shown = owner.read("/occupancy-dashboard")
        return shown["summary"], {item["name"]: item for item in shown["items"]}, shown

    summary, items, shown = dashboard()
    assert [item["name"] for item in shown["items"]] == [ANGGREK, "Kos Cempaka", MELATI]
    assert [r["number"] for r in items[MELATI]["rooms"]] == [
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
    ]
    assert [r["number"] for r in items[ANGGREK]["rooms"]] == ["B2", "B10"]
    assert {r["occupancy"] for r in items[MELATI]["rooms"]} == {"vacant"}
    assert summary["propertyCount"] == 3
    assert figures(summary) == (13, 0, 13, 0)

    first = owner.add_tenant(melati_rooms["10"], "Budi Tenant", "081211111111")
    summary, items, _ = dashboard()
    assert figures(items[MELATI]) == (8, 1, 7, 13)
    assert figures(items[ANGGREK]) == (2, 0, 2, 0)
    assert figures(summary) == (13, 1, 12, 8)
    assert {r["number"]: r["occupancy"] for r in items[MELATI]["rooms"]}["10"] == (
        "occupied"
    )

    owner.add_tenant(cempaka_rooms["C1"], "Sari Tenant", "081222222222")
    summary, items, _ = dashboard()
    assert figures(items["Kos Cempaka"]) == (3, 1, 2, 33)
    assert figures(summary) == (13, 2, 11, 15)

    owner.add_tenant(anggrek_rooms["B2"], "Dewi Tenant", "081233333333")
    summary, items, _ = dashboard()
    assert figures(items[ANGGREK]) == (2, 1, 1, 50)
    assert figures(summary) == (13, 3, 10, 23)

    owner.add_tenant(melati_rooms["9"], "Joko Tenant", "081244444444")
    owner.add_tenant(melati_rooms["8"], "Wati Tenant", "081255555555")
    summary, items, _ = dashboard()
    assert figures(items[MELATI]) == (8, 3, 5, 38)
    assert figures(summary) == (13, 5, 8, 38)

    owner.delete(f"/tenants/{first.id}", expect=204)
    summary, items, _ = dashboard()
    assert figures(items[MELATI]) == (8, 2, 6, 25)
    assert figures(summary) == (13, 4, 9, 31)
    assert {r["number"]: r["occupancy"] for r in items[MELATI]["rooms"]}["10"] == (
        "vacant"
    )

    owner.delete(f"/properties/{cempaka['id']}", expect=409)
    summary, items, _ = dashboard()
    assert summary["propertyCount"] == 3


def test_the_dashboard_summary_is_computed_from_summed_counts(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    small = owner.add_property(ANGGREK)
    large = owner.add_property(MELATI)
    small_rooms = [owner.add_room(small, f"S{i}") for i in range(1, 3)]
    large_rooms = [owner.add_room(large, f"L{i}") for i in range(1, 9)]

    owner.add_tenant(small_rooms[0], "Budi Tenant", "081211111111")
    owner.add_tenant(large_rooms[0], "Sari Tenant", "081222222222")

    shown = owner.read("/occupancy-dashboard")
    by_name = {item["name"]: item for item in shown["items"]}
    assert by_name[ANGGREK]["occupancyPercentage"] == 50
    assert by_name[MELATI]["occupancyPercentage"] == 13
    assert shown["summary"]["occupancyPercentage"] == 20


def test_a_manager_sees_the_dashboard_of_assigned_properties_only(seeded_world):
    owner, manager = seeded_world.owner, seeded_world.manager

    seen = manager.read("/occupancy-dashboard")
    everything = owner.read("/occupancy-dashboard")

    assert [item["name"] for item in seen["items"]] == [MELATI]
    assert figures(seen["items"][0]) == (3, 2, 1, 67)
    assert seen["summary"]["propertyCount"] == 1
    assert figures(seen["summary"]) == (3, 2, 1, 67)
    assert [item["name"] for item in everything["items"]] == [ANGGREK, MELATI]
    assert figures(everything["items"][0]) == (2, 1, 1, 50)
    assert figures(everything["summary"]) == (5, 3, 2, 60)


def test_the_dashboard_does_not_depend_on_the_subscription(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1")
    owner.add_tenant(room, "Budi Tenant", "081211111111")

    shown = owner.read("/occupancy-dashboard")

    assert figures(shown["summary"]) == (1, 1, 0, 100)


# Two devices editing the same room


def test_the_second_device_to_save_a_room_gets_a_conflict_until_it_reloads(world):
    first = world.owner_signs_up()
    second = world.login(first.email)
    prop = first.add_property(MELATI)
    room = first.add_room(prop, "A1", base_rate=1_000_000, facilities=["ac"])
    path = f"/rooms/{room['id']}"
    seen_by_first = first.read(path)
    seen_by_second = second.read(path)
    assert seen_by_first["version"] == 1
    assert seen_by_second["version"] == 1
    assert first.rooms(prop)[0]["version"] == 1

    saved = first.put(
        path,
        json=room_body(seen_by_first, baseRate=1_100_000),
        headers={"If-Match": '"1"'},
        expect=200,
    ).json()
    assert saved["version"] == 2
    assert first.read(path)["version"] == 2
    assert first.rooms(prop)[0]["version"] == 2

    conflict = second.put(
        path,
        json=room_body(seen_by_second, facilities=["wifi"]),
        headers={"If-Match": '"1"'},
    )
    assert_error(conflict, 409, "RESOURCE_VERSION_CONFLICT")
    unchanged = second.read(path)
    assert unchanged["baseRate"] == 1_100_000
    assert unchanged["facilities"] == ["ac"]
    assert unchanged["version"] == 2

    resaved = second.put(
        path,
        json=room_body(unchanged, facilities=["wifi"]),
        headers={"If-Match": f'"{unchanged["version"]}"'},
        expect=200,
    ).json()
    assert resaved["version"] == 3
    assert resaved["baseRate"] == 1_100_000
    assert resaved["facilities"] == ["wifi"]
    assert first.read(path)["version"] == 3


def test_a_room_save_without_the_header_always_applies_and_raises_the_version(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property(MELATI), "A1", base_rate=1_000_000)
    path = f"/rooms/{room['id']}"
    owner.put(
        path,
        json=room_body(room, baseRate=1_100_000),
        headers={"If-Match": '"1"'},
        expect=200,
    )

    stale_without_header = owner.put(path, json=room_body(room, baseRate=1_200_000))

    assert stale_without_header.status_code == 200
    assert stale_without_header.json()["version"] == 3
    assert owner.read(path)["baseRate"] == 1_200_000
    same_values = owner.put(path, json=room_body(room, baseRate=1_200_000), expect=200)
    assert same_values.json()["version"] == 4
    assert owner.read(path)["version"] == 4


def test_a_room_save_with_a_malformed_version_header_is_refused(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property(MELATI), "A1")
    path = f"/rooms/{room['id']}"

    for header in ("1", "abc", '"abc"'):
        response = owner.put(
            path, json=room_body(room, baseRate=2_000_000), headers={"If-Match": header}
        )
        assert_error(response, 422, "VALIDATION_FAILED", "ifMatch")

    assert owner.read(path)["baseRate"] == 1_000_000
    assert owner.read(path)["version"] == 1
