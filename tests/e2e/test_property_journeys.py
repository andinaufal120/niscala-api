"""Scenarios of an Owner building and running properties, and who may touch them."""

from e2e.e2e_people import BANK_ACCOUNT, PASSWORD, describe
from e2e.e2e_world import ANGGREK, MELATI

NEW_BANK_ACCOUNT = {
    "bankName": "Bank BCA",
    "accountNumber": "9876543210",
    "accountHolderName": "Rina Owner",
}


def assert_error(response, status, code, field=None):
    """Require an error answer with the given status, code and, if given, field."""
    assert response.status_code == status, describe(response)
    body = response.json()
    assert body["code"] == code, describe(response)
    if field is not None:
        assert body["field"] == field, describe(response)


def edit_body(prop, **changes):
    """The full property body of an edit, from a property as the API returned it."""
    body = {
        "name": prop["name"],
        "address": prop["address"],
        "bankAccount": prop["bankAccount"],
    }
    return body | changes


def names(items):
    return [item["name"] for item in items]


# Building a place


def test_owner_adds_a_property_and_sees_it_in_the_list_and_in_detail(world):
    owner = world.owner_signs_up()

    created = owner.add_property(
        "Kos Melati", address="Jl. Melati 5", bank_account=BANK_ACCOUNT
    )

    assert created["version"] == 1
    assert created["bankAccount"] == BANK_ACCOUNT
    assert created["editable"] is True
    listed = owner.properties()
    assert names(listed) == ["Kos Melati"]
    assert listed[0]["id"] == created["id"]
    assert listed[0]["roomCount"] == 0
    assert listed[0]["occupiedRoomCount"] == 0
    assert listed[0]["managers"] == []
    detail = owner.read(f"/properties/{created['id']}")
    assert detail["name"] == "Kos Melati"
    assert detail["address"] == "Jl. Melati 5"
    assert detail["bankAccount"] == BANK_ACCOUNT
    assert detail["roomCount"] == 0
    assert detail["vacantRoomCount"] == 0


def test_property_name_is_unique_ignoring_case_and_spaces_until_it_is_deleted(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    first = owner.add_property("Kos Melati")

    again = owner.post("/properties", json={"name": "  kos melati  ", "address": "x"})
    assert_error(again, 409, "PROPERTY_NAME_TAKEN", "name")
    assert names(owner.properties()) == ["Kos Melati"]

    other = owner.add_property("Kos Anggrek")
    assert other["id"] != first["id"]

    owner.delete(f"/properties/{first['id']}", expect=204)
    reused = owner.add_property("KOS MELATI")
    assert reused["id"] != first["id"]
    assert sorted(names(owner.properties())) == ["KOS MELATI", "Kos Anggrek"]


def test_two_owners_can_use_the_same_property_name(world):
    first = world.owner_signs_up(email="rina@example.com")
    second = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")

    first.add_property("Kos Melati")
    second.add_property("Kos Melati")

    assert names(first.properties()) == ["Kos Melati"]
    assert names(second.properties()) == ["Kos Melati"]


def test_a_bank_account_needs_all_three_parts_and_saves_nothing_otherwise(world):
    owner = world.owner_signs_up()

    response = owner.post(
        "/properties",
        json={
            "name": "Kos Melati",
            "address": "x",
            "bankAccount": {"bankName": "Bank Mandiri", "accountNumber": "123"},
        },
    )

    assert_error(response, 422, "VALIDATION_FAILED", "bankAccount.accountHolderName")
    assert owner.properties() == []


def test_name_and_address_change_freely_but_a_new_bank_account_needs_reauthentication(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati", bank_account=BANK_ACCOUNT)
    path = f"/properties/{prop['id']}"

    renamed = owner.put(
        path,
        json=edit_body(prop, name="Kos Melati Indah", address="Jl. Baru 9"),
        expect=200,
    ).json()
    assert renamed["name"] == "Kos Melati Indah"
    assert renamed["address"] == "Jl. Baru 9"
    assert renamed["bankAccount"] == BANK_ACCOUNT

    refused = owner.put(path, json=edit_body(renamed, bankAccount=NEW_BANK_ACCOUNT))
    assert_error(refused, 403, "REAUTHENTICATION_REQUIRED")
    assert owner.read(path)["bankAccount"] == BANK_ACCOUNT
    assert owner.read(path)["version"] == renamed["version"]

    wrong = owner.post("/me/reauthentication/password", json={"password": "nope nope"})
    assert_error(wrong, 422, "PASSWORD_INCORRECT", "password")

    owner.post("/me/reauthentication/password", json={"password": PASSWORD}, expect=200)
    changed = owner.put(
        path, json=edit_body(renamed, bankAccount=NEW_BANK_ACCOUNT), expect=200
    ).json()
    assert changed["bankAccount"] == NEW_BANK_ACCOUNT
    assert owner.read(path)["bankAccount"] == NEW_BANK_ACCOUNT


def test_reauthentication_belongs_to_the_session_that_did_it(world):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati")
    path = f"/properties/{prop['id']}"
    other_device = world.login(owner.email)

    owner.post("/me/reauthentication/password", json={"password": PASSWORD}, expect=200)

    added = owner.put(
        path, json=edit_body(prop, bankAccount=BANK_ACCOUNT), expect=200
    ).json()
    assert added["bankAccount"] == BANK_ACCOUNT
    refused = other_device.put(path, json=edit_body(added, bankAccount=None))
    assert_error(refused, 403, "REAUTHENTICATION_REQUIRED")
    assert owner.read(path)["bankAccount"] == BANK_ACCOUNT


def test_removing_a_bank_account_needs_reauthentication(world):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati", bank_account=BANK_ACCOUNT)
    path = f"/properties/{prop['id']}"

    refused = owner.put(path, json=edit_body(prop, bankAccount=None))
    assert_error(refused, 403, "REAUTHENTICATION_REQUIRED")
    assert owner.read(path)["bankAccount"] == BANK_ACCOUNT

    owner.post("/me/reauthentication/password", json={"password": PASSWORD}, expect=200)
    removed = owner.put(path, json=edit_body(prop, bankAccount=None), expect=200).json()
    assert removed["bankAccount"] is None


def test_renaming_to_another_propertys_name_is_refused_but_the_own_name_is_not(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)

    clash = owner.put(
        f"/properties/{melati['id']}", json=edit_body(melati, name=" kos anggrek ")
    )
    assert_error(clash, 409, "PROPERTY_NAME_TAKEN", "name")
    assert owner.read(f"/properties/{melati['id']}")["name"] == MELATI

    same = owner.put(
        f"/properties/{melati['id']}", json=edit_body(melati, name="KOS MELATI")
    )
    assert same.status_code == 200
    assert same.json()["name"] == "KOS MELATI"
    assert owner.read(f"/properties/{anggrek['id']}")["name"] == ANGGREK


def test_property_list_and_detail_count_rooms_and_name_assigned_managers(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    rooms = [owner.add_room(melati, number) for number in ("A1", "A2", "A3")]
    owner.add_room(anggrek, "B1")
    owner.add_tenant(rooms[0], "Budi Tenant", "081211111111")
    owner.add_tenant(rooms[1], "Sari Tenant", "081222222222")
    owner.add_manager([melati, anggrek], name="Mira Manager")

    listed = {p["name"]: p for p in owner.properties()}
    detail = owner.read(f"/properties/{melati['id']}")

    assert listed[MELATI]["roomCount"] == 3
    assert listed[MELATI]["occupiedRoomCount"] == 2
    assert listed[ANGGREK]["roomCount"] == 1
    assert listed[ANGGREK]["occupiedRoomCount"] == 0
    for item in listed.values():
        assert [m["name"] for m in item["managers"]] == ["Mira Manager"]
    assert detail["roomCount"] == 3
    assert detail["occupiedRoomCount"] == 2
    assert detail["vacantRoomCount"] == 1
    assert [m["name"] for m in detail["managers"]] == ["Mira Manager"]


def test_a_property_with_an_active_lease_cannot_be_deleted_until_the_tenant_is_removed(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1")
    tenant = owner.add_tenant(room, "Budi Tenant", "081211111111")
    path = f"/properties/{prop['id']}"

    refused = owner.delete(path)
    assert_error(refused, 409, "PROPERTY_HAS_ACTIVE_LEASE")
    assert names(owner.properties()) == [MELATI]
    assert [r["number"] for r in owner.rooms(prop)] == ["A1"]
    assert owner.read(f"/rooms/{room['id']}")["occupancy"] == "occupied"

    owner.delete(f"/tenants/{tenant.id}", expect=204)
    owner.delete(path, expect=204)

    assert owner.properties() == []


def test_deleting_a_property_removes_its_rooms_and_manager_assignments(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    room = owner.add_room(melati, "A1")
    owner.add_room(anggrek, "B1")
    manager = world.manager_activates(
        owner.add_manager([melati, anggrek], name="Mira Manager"),
        email="mira@example.com",
    )
    assert names(manager.properties()) == sorted([ANGGREK, MELATI])

    owner.delete(f"/properties/{melati['id']}", expect=204)

    assert names(owner.properties()) == [ANGGREK]
    assert_error(owner.get(f"/properties/{melati['id']}"), 404, "PROPERTY_NOT_FOUND")
    assert_error(
        owner.get(f"/properties/{melati['id']}/rooms"), 404, "PROPERTY_NOT_FOUND"
    )
    assert_error(owner.get(f"/rooms/{room['id']}"), 404, "ROOM_NOT_FOUND")
    assert names(manager.properties()) == [ANGGREK]
    assert_error(manager.get(f"/properties/{melati['id']}"), 404, "PROPERTY_NOT_FOUND")
    listed = owner.managers()
    assert [m["name"] for m in listed] == ["Mira Manager"]
    assert names(listed[0]["properties"]) == [ANGGREK]
    assert [m["name"] for m in owner.properties()[0]["managers"]] == ["Mira Manager"]


def test_a_deleted_property_cannot_be_edited_or_deleted_again(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    owner.delete(f"/properties/{prop['id']}", expect=204)

    edited = owner.put(f"/properties/{prop['id']}", json=edit_body(prop))
    deleted = owner.delete(f"/properties/{prop['id']}")

    assert_error(edited, 404, "PROPERTY_NOT_FOUND")
    assert_error(deleted, 404, "PROPERTY_NOT_FOUND")


# Plan limits


def test_the_free_plan_allows_one_property_and_paid_plans_raise_the_limit(world):
    owner = world.owner_signs_up()
    plans = {p["code"]: p for p in owner.read("/subscription-plans")["items"]}
    free_limit = plans["free"]["maxProperties"]
    basic_limit = plans["basic"]["maxProperties"]
    assert free_limit == 1
    assert basic_limit is not None
    assert plans["pro"]["maxProperties"] is None

    for index in range(free_limit):
        owner.add_property(f"Kos Free {index}")
    refused = owner.post("/properties", json={"name": "Kos Extra", "address": "x"})
    assert_error(refused, 403, "PROPERTY_LIMIT_REACHED")
    assert len(owner.properties()) == free_limit

    owner.subscribe("basic")
    for index in range(basic_limit - free_limit):
        owner.add_property(f"Kos Basic {index}")
    refused = owner.post("/properties", json={"name": "Kos Extra", "address": "x"})
    assert_error(refused, 403, "PROPERTY_LIMIT_REACHED")
    assert len(owner.properties()) == basic_limit

    owner.subscribe("pro")
    for index in range(2):
        owner.add_property(f"Kos Pro {index}")
    assert len(owner.properties()) == basic_limit + 2


def test_deleting_a_property_frees_a_place_under_the_limit(world):
    owner = world.owner_signs_up()
    first = owner.add_property("Kos Melati")
    refused = owner.post("/properties", json={"name": "Kos Anggrek", "address": "x"})
    assert_error(refused, 403, "PROPERTY_LIMIT_REACHED")

    owner.delete(f"/properties/{first['id']}", expect=204)
    owner.add_property("Kos Anggrek")

    assert names(owner.properties()) == ["Kos Anggrek"]


# Who may use properties


def test_a_manager_sees_and_edits_only_assigned_properties_and_cannot_manage_properties(
    world,
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI, bank_account=BANK_ACCOUNT)
    anggrek = owner.add_property(ANGGREK)
    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager"), email="mira@example.com"
    )

    assert names(manager.properties()) == [MELATI]
    assert manager.read(f"/properties/{melati['id']}")["name"] == MELATI
    other = manager.get(f"/properties/{anggrek['id']}")
    assert_error(other, 404, "PROPERTY_NOT_FOUND")
    other_rooms = manager.get(f"/properties/{anggrek['id']}/rooms")
    assert_error(other_rooms, 404, "PROPERTY_NOT_FOUND")

    added = manager.post("/properties", json={"name": "Kos Baru", "address": "x"})
    assert_error(added, 403, "FORBIDDEN")
    edited = manager.put(f"/properties/{melati['id']}", json=edit_body(melati))
    assert_error(edited, 403, "FORBIDDEN")
    deleted = manager.delete(f"/properties/{melati['id']}")
    assert_error(deleted, 403, "FORBIDDEN")
    assert sorted(names(owner.properties())) == sorted([MELATI, ANGGREK])
    assert owner.read(f"/properties/{melati['id']}")["version"] == 1


def test_a_property_of_another_owner_does_not_exist_for_an_owner(world):
    owner = world.owner_signs_up(email="rina@example.com")
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    prop = owner.add_property(MELATI)
    room = owner.add_room(prop, "A1")

    assert stranger.properties() == []
    path = f"/properties/{prop['id']}"
    assert_error(stranger.get(path), 404, "PROPERTY_NOT_FOUND")
    assert_error(stranger.put(path, json=edit_body(prop)), 404, "PROPERTY_NOT_FOUND")
    assert_error(stranger.delete(path), 404, "PROPERTY_NOT_FOUND")
    assert_error(stranger.get(f"{path}/rooms"), 404, "PROPERTY_NOT_FOUND")
    assert_error(stranger.get(f"/rooms/{room['id']}"), 404, "ROOM_NOT_FOUND")
    assert names(owner.properties()) == [MELATI]


def test_a_tenant_is_refused_every_property_and_management_endpoint(seeded_world):
    budi = seeded_world.budi
    melati = seeded_world.melati
    room = seeded_world.rooms["A1"]

    responses = [
        budi.get("/properties"),
        budi.get(f"/properties/{melati['id']}"),
        budi.post("/properties", json={"name": "Kos Baru", "address": "x"}),
        budi.put(f"/properties/{melati['id']}", json=edit_body(melati)),
        budi.delete(f"/properties/{melati['id']}"),
        budi.get(f"/properties/{melati['id']}/rooms"),
        budi.get(f"/rooms/{room['id']}"),
        budi.delete(f"/rooms/{room['id']}"),
        budi.get("/occupancy-dashboard"),
        budi.get("/managers"),
    ]

    for response in responses:
        assert_error(response, 403, "FORBIDDEN")
    assert len(seeded_world.owner.properties()) == 2


def test_requests_without_a_session_cannot_reach_properties(world):
    world.owner_signs_up()

    for response in (
        world.client.get("/properties"),
        world.client.post("/properties", json={"name": "x", "address": "y"}),
        world.client.get("/occupancy-dashboard"),
    ):
        assert_error(response, 401, "ACCESS_TOKEN_INVALID")


# Two devices editing the same property


def test_the_second_device_to_save_a_property_gets_a_conflict_until_it_reloads(world):
    first = world.owner_signs_up()
    second = world.login(first.email)
    prop = first.add_property(MELATI, bank_account=BANK_ACCOUNT)
    path = f"/properties/{prop['id']}"
    seen_by_first = first.read(path)
    seen_by_second = second.read(path)
    assert seen_by_first["version"] == 1
    assert seen_by_second["version"] == 1

    saved = first.put(
        path,
        json=edit_body(seen_by_first, name="Kos Melati Indah"),
        headers={"If-Match": '"1"'},
        expect=200,
    ).json()
    assert saved["version"] == 2
    assert first.read(path)["version"] == 2

    conflict = second.put(
        path,
        json=edit_body(seen_by_second, address="Jl. Lain 1"),
        headers={"If-Match": '"1"'},
    )
    assert_error(conflict, 409, "RESOURCE_VERSION_CONFLICT")
    unchanged = second.read(path)
    assert unchanged["name"] == "Kos Melati Indah"
    assert unchanged["address"] == "Jl. Melati 5"
    assert unchanged["version"] == 2

    resaved = second.put(
        path,
        json=edit_body(unchanged, address="Jl. Lain 1"),
        headers={"If-Match": f'"{unchanged["version"]}"'},
        expect=200,
    ).json()
    assert resaved["version"] == 3
    assert resaved["name"] == "Kos Melati Indah"
    assert resaved["address"] == "Jl. Lain 1"
    final = first.read(path)
    assert final["version"] == 3
    assert [p["version"] for p in first.properties()] == [3]


def test_a_property_save_without_the_header_always_applies_and_raises_the_version(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    path = f"/properties/{prop['id']}"
    owner.put(
        path,
        json=edit_body(prop, name="Kos A"),
        headers={"If-Match": '"1"'},
        expect=200,
    )

    stale_without_header = owner.put(path, json=edit_body(prop, name="Kos B"))

    assert stale_without_header.status_code == 200
    assert stale_without_header.json()["version"] == 3
    assert owner.read(path)["name"] == "Kos B"

    same_values = owner.put(path, json=edit_body(prop, name="Kos B"), expect=200).json()
    assert same_values["version"] == 4
    assert owner.read(path)["version"] == 4


def test_a_property_save_with_a_malformed_version_header_is_refused(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    path = f"/properties/{prop['id']}"

    for header in ("1", "abc", '"abc"'):
        response = owner.put(
            path, json=edit_body(prop, name="Kos B"), headers={"If-Match": header}
        )
        assert_error(response, 422, "VALIDATION_FAILED", "ifMatch")

    assert owner.read(path)["name"] == MELATI
    assert owner.read(path)["version"] == 1


def test_a_stale_version_is_checked_before_reauthentication_is_asked_for(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI, bank_account=BANK_ACCOUNT)
    path = f"/properties/{prop['id']}"
    owner.put(path, json=edit_body(prop, name="Kos A"), expect=200)

    response = owner.put(
        path,
        json=edit_body(prop, bankAccount=NEW_BANK_ACCOUNT),
        headers={"If-Match": '"1"'},
    )

    assert_error(response, 409, "RESOURCE_VERSION_CONFLICT")
    assert owner.read(path)["bankAccount"] == BANK_ACCOUNT
