"""Scenarios of an Owner adding, assigning, editing and removing Managers."""

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


def manager_body(manager, **changes):
    """The full body of a manager edit, from a manager as the API returned it."""
    body = {
        "name": manager["name"],
        "nickname": manager["nickname"],
        "phone": manager["phone"],
        "propertyIds": [prop["id"] for prop in manager["properties"]],
    }
    return body | changes


def names(items):
    return [item["name"] for item in items]


# Adding a manager


def test_owner_adds_a_manager_for_two_properties_who_activates_and_sees_both(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    cempaka = owner.add_property("Kos Cempaka")
    owner.add_room(melati, "A1")

    token = owner.add_manager(
        [melati, anggrek],
        name="Mira Manager",
        nickname="Bu Mira",
        phone="0812-0000-0001",
    )

    created = token.record
    assert created["version"] == 1
    assert created["accountStatus"] == "notActivated"
    assert created["email"] is None
    assert created["nickname"] == "Bu Mira"
    assert created["phone"] == "081200000001"
    assert names(created["properties"]) == sorted([MELATI, ANGGREK])
    assert created["invitation"]["url"].endswith(token)
    assert created["invitation"]["expired"] is False
    waiting = owner.read(f"/managers/{token.id}")
    assert waiting["invitation"]["url"].endswith(token)
    assert waiting["accountStatus"] == "notActivated"

    manager = world.manager_activates(token, email="mira@example.com")

    assert names(manager.properties()) == sorted([ANGGREK, MELATI])
    assert manager.read(f"/properties/{melati['id']}")["name"] == MELATI
    assert numbers_of(manager, melati) == ["A1"]
    cannot = manager.get(f"/properties/{cempaka['id']}")
    assert_error(cannot, 404, "PROPERTY_NOT_FOUND")
    activated = owner.read(f"/managers/{token.id}")
    assert activated["accountStatus"] == "active"
    assert activated["email"] == "mira@example.com"
    assert activated["invitation"] is None
    listed = owner.managers()
    assert names(listed) == ["Mira Manager"]
    assert listed[0]["nickname"] == "Bu Mira"
    assert listed[0]["accountStatus"] == "active"
    for prop in owner.properties():
        expected = ["Mira Manager"] if prop["name"] in (MELATI, ANGGREK) else []
        assert names(prop["managers"]) == expected


def numbers_of(person, prop):
    return [room["number"] for room in person.rooms(prop)]


def test_a_manager_can_only_be_given_properties_of_the_owner(world):
    owner = world.owner_signs_up(email="rina@example.com")
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    mine = owner.add_property(MELATI)
    theirs = stranger.add_property("Kos Lain")

    unknown = owner.post(
        "/managers",
        json={
            "name": "Mira Manager",
            "phone": "081200000001",
            "propertyIds": [mine["id"], theirs["id"]],
        },
    )
    missing = owner.post(
        "/managers",
        json={
            "name": "Mira Manager",
            "phone": "081200000001",
            "propertyIds": [str(uuid4())],
        },
    )

    assert_error(unknown, 404, "PROPERTY_NOT_FOUND", "propertyIds.1")
    assert_error(missing, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert owner.managers() == []
    assert stranger.managers() == []


def test_only_an_owner_manages_managers(seeded_world):
    owner, mira, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    record = owner.managers()[0]
    body = {
        "name": "Nina Manager",
        "phone": "081200000009",
        "propertyIds": [seeded_world.melati["id"]],
    }

    for person in (mira, budi):
        assert_error(person.get("/managers"), 403, "FORBIDDEN")
        assert_error(person.get(f"/managers/{record['id']}"), 403, "FORBIDDEN")
        assert_error(person.post("/managers", json=body), 403, "FORBIDDEN")
        assert_error(
            person.put(f"/managers/{record['id']}", json=manager_body(record)),
            403,
            "FORBIDDEN",
        )
        assert_error(person.delete(f"/managers/{record['id']}"), 403, "FORBIDDEN")
        assert_error(
            person.post(f"/managers/{record['id']}/invitation"), 403, "FORBIDDEN"
        )
    assert names(owner.managers()) == ["Mira Manager"]


def test_a_manager_of_another_owner_does_not_exist_for_an_owner(world):
    owner = world.owner_signs_up(email="rina@example.com")
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    token = owner.add_manager([owner.add_property(MELATI)], name="Mira Manager")
    path = f"/managers/{token.id}"

    assert stranger.managers() == []
    assert_error(stranger.get(path), 404, "MANAGER_NOT_FOUND")
    record = owner.read(path)
    assert_error(
        stranger.put(path, json=manager_body(record)), 404, "MANAGER_NOT_FOUND"
    )
    assert_error(stranger.delete(path), 404, "MANAGER_NOT_FOUND")
    assert_error(stranger.post(f"{path}/invitation"), 404, "MANAGER_NOT_FOUND")
    assert_error(stranger.get(f"/managers/{uuid4()}"), 404, "MANAGER_NOT_FOUND")
    assert names(owner.managers()) == ["Mira Manager"]


# Viewing managers


def test_managers_are_ordered_by_nickname_or_name_and_can_be_limited_to_a_property(
    world,
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI)
    anggrek = owner.add_property(ANGGREK)
    cempaka = owner.add_property("Kos Cempaka")
    owner.add_manager(
        [melati, anggrek], name="Zoe Manager", nickname="adi", phone="081200000001"
    )
    owner.add_manager([anggrek], name="bob Manager", phone="081200000002")
    owner.add_manager([melati], name="Citra Manager", phone="081200000003")

    everyone = owner.managers()
    assert [m["nickname"] or m["name"] for m in everyone] == [
        "adi",
        "bob Manager",
        "Citra Manager",
    ]
    assert names(everyone) == ["Zoe Manager", "bob Manager", "Citra Manager"]

    def at(prop):
        return owner.read("/managers", params={"propertyId": prop["id"]})["items"]

    assert [m["name"] for m in at(melati)] == ["Zoe Manager", "Citra Manager"]
    assert [m["name"] for m in at(anggrek)] == ["Zoe Manager", "bob Manager"]
    assert at(cempaka) == []
    zoe = at(anggrek)[0]
    assert names(zoe["properties"]) == sorted([MELATI, ANGGREK])


# Editing a manager


def test_owner_edits_the_assignments_and_access_to_a_removed_property_ends_at_once(
    seeded_world,
):
    owner, mira = seeded_world.owner, seeded_world.manager
    melati, anggrek = seeded_world.melati, seeded_world.anggrek
    record = owner.managers()[0]
    assert len(mira.rent_bills()) == 2
    assert len(mira.complaints()) == 1
    budi_bill = seeded_world.budi.rent_bills()[0]
    room_path = f"/rooms/{seeded_world.rooms['A1']['id']}"
    assert mira.read(room_path)["number"] == "A1"

    edited = owner.put(
        f"/managers/{record['id']}",
        json=manager_body(record, propertyIds=[anggrek["id"]], nickname="Bu Mira"),
        expect=200,
    ).json()

    assert names(edited["properties"]) == [ANGGREK]
    assert edited["version"] == record["version"] + 1
    assert names(mira.properties()) == [ANGGREK]
    assert_error(mira.get(f"/properties/{melati['id']}"), 404, "PROPERTY_NOT_FOUND")
    assert_error(
        mira.get(f"/properties/{melati['id']}/rooms"), 404, "PROPERTY_NOT_FOUND"
    )
    assert_error(mira.get(room_path), 404, "ROOM_NOT_FOUND")
    assert [b["tenant"]["name"] for b in mira.rent_bills()] == ["Dewi Tenant"]
    assert_error(mira.get(f"/rent-bills/{budi_bill['id']}"), 404, "RENT_BILL_NOT_FOUND")
    assert mira.complaints() == []
    assert_error(
        mira.get(f"/complaints/{seeded_world.complaint['id']}"),
        404,
        "COMPLAINT_NOT_FOUND",
    )
    assert names(mira.read("/occupancy-dashboard")["items"]) == [ANGGREK]
    assert len(mira.rooms(anggrek)) == 2
    assert names(owner.properties()[0]["managers"]) == ["Mira Manager"]
    assert owner.properties()[1]["managers"] == []

    owner.put(
        f"/managers/{record['id']}",
        json=manager_body(edited, propertyIds=[melati["id"], anggrek["id"]]),
        expect=200,
    )

    assert names(mira.properties()) == sorted([ANGGREK, MELATI])
    assert mira.read(room_path)["number"] == "A1"
    assert len(mira.rent_bills()) == 3
    assert len(mira.complaints()) == 1


def test_an_edit_keeps_at_least_one_property_and_only_the_owners_properties(world):
    owner = world.owner_signs_up(email="rina@example.com")
    stranger = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    melati = owner.add_property(MELATI)
    theirs = stranger.add_property("Kos Lain")
    token = owner.add_manager([melati], name="Mira Manager")
    record = owner.read(f"/managers/{token.id}")
    path = f"/managers/{token.id}"

    none_left = owner.put(path, json=manager_body(record, propertyIds=[]))
    foreign = owner.put(path, json=manager_body(record, propertyIds=[theirs["id"]]))

    assert_error(none_left, 422, "VALIDATION_FAILED", "propertyIds")
    assert_error(foreign, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    unchanged = owner.read(path)
    assert names(unchanged["properties"]) == [MELATI]
    assert unchanged["version"] == 1


def test_the_name_changes_only_until_the_manager_activates_and_other_fields_always(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    token = owner.add_manager([prop], name="Mira Manager", phone="081200000001")
    path = f"/managers/{token.id}"

    renamed = owner.put(
        path, json=manager_body(token.record, name="Mira Sari"), expect=200
    ).json()
    assert renamed["name"] == "Mira Sari"
    preview = world.client.post("/invitations/previews", json={"token": str(token)})
    assert preview.json()["name"] == "Mira Sari"

    manager = world.manager_activates(token, email="mira@example.com")
    active = owner.read(path)
    assert active["name"] == "Mira Sari"

    refused = owner.put(path, json=manager_body(active, name="Another Name"))
    assert_error(refused, 422, "MANAGER_NAME_NOT_EDITABLE", "name")
    unchanged = owner.read(path)
    assert unchanged["name"] == "Mira Sari"
    assert unchanged["version"] == active["version"]

    updated = owner.put(
        path,
        json=manager_body(active, nickname="Bu Mira", phone="081299999999"),
        expect=200,
    ).json()
    assert updated["name"] == "Mira Sari"
    assert updated["nickname"] == "Bu Mira"
    assert updated["phone"] == "081299999999"
    assert updated["email"] == "mira@example.com"
    assert updated["accountStatus"] == "active"
    listed = owner.managers()[0]
    assert listed["nickname"] == "Bu Mira"
    assert listed["phone"] == "081299999999"
    assert names(manager.properties()) == [MELATI]

    cleared = owner.put(path, json=manager_body(updated, nickname=None), expect=200)
    assert cleared.json()["nickname"] is None
    assert owner.managers()[0]["nickname"] is None


def test_the_invitation_link_is_replaced_only_while_the_manager_is_not_active(world):
    owner = world.owner_signs_up()
    prop = owner.add_property(MELATI)
    token = owner.add_manager([prop], name="Mira Manager")
    path = f"/managers/{token.id}"

    fresh = owner.post(f"{path}/invitation", expect=201).json()
    assert fresh["url"] is not None
    assert not fresh["url"].endswith(token)
    old = world.client.post("/invitations/previews", json={"token": str(token)})
    assert old.json()["status"] == "used"

    new_token = fresh["url"].rsplit("/", 1)[-1]
    world.manager_activates(new_token, email="mira@example.com")

    again = owner.post(f"{path}/invitation")
    assert_error(again, 409, "MANAGER_ALREADY_ACTIVE")


# Deleting a manager


def test_deleting_the_only_owners_manager_ends_their_access_and_their_login(
    seeded_world, world
):
    owner, mira = seeded_world.owner, seeded_world.manager
    record = owner.managers()[0]
    path = f"/managers/{record['id']}"
    assert names(mira.properties()) == [MELATI]

    owner.delete(path, expect=204)

    assert owner.managers() == []
    assert_error(owner.get(path), 404, "MANAGER_NOT_FOUND")
    assert_error(owner.put(path, json=manager_body(record)), 404, "MANAGER_NOT_FOUND")
    assert_error(owner.delete(path), 404, "MANAGER_NOT_FOUND")
    for prop in owner.properties():
        assert prop["managers"] == []
    assert_error(mira.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    login = world.client.post(
        "/auth/login",
        json={
            "email": mira.email,
            "password": mira.password,
            "device": {"name": "Pixel 8", "platform": "Android 14"},
        },
    )
    assert_error(login, 401, "INVALID_CREDENTIALS")
    assert owner.complaint(seeded_world.complaint)["tenantName"] == "Budi Tenant"
    assert len(owner.rent_bills()) == 3
    assert len(owner.properties()) == 2


def test_a_manager_of_two_owners_keeps_the_other_owners_access_when_one_deletes_them(
    world,
):
    first = world.owner_signs_up(email="rina@example.com")
    second = world.owner_signs_up(email="sinta@example.com", name="Sinta Owner")
    kos_one = first.add_property("Kos Satu")
    kos_two = second.add_property("Kos Dua")
    mira = world.manager_activates(
        first.add_manager(
            [kos_one], name="Mira Manager", nickname="Bu Mira", phone="081200000001"
        ),
        email="mira@example.com",
    )
    second_token = second.add_manager(
        [kos_two], name="Mira Manager", nickname="Mira Sinta", phone="081200000002"
    )

    mira.post("/invitations/acceptances", json={"token": str(second_token)}, expect=204)

    assert names(mira.properties()) == ["Kos Dua", "Kos Satu"]
    assert first.managers()[0]["nickname"] == "Bu Mira"
    assert first.managers()[0]["phone"] == "081200000001"
    assert second.managers()[0]["nickname"] == "Mira Sinta"
    assert second.managers()[0]["phone"] == "081200000002"
    assert second.managers()[0]["accountStatus"] == "active"
    assert second.managers()[0]["email"] == "mira@example.com"
    assert_error(
        second.get(f"/managers/{first.managers()[0]['id']}"), 404, "MANAGER_NOT_FOUND"
    )

    first.delete(f"/managers/{first.managers()[0]['id']}", expect=204)

    assert first.managers() == []
    assert names(second.managers()) == ["Mira Manager"]
    assert names(mira.properties()) == ["Kos Dua"]
    assert_error(mira.get(f"/properties/{kos_one['id']}"), 404, "PROPERTY_NOT_FOUND")
    again = world.login("mira@example.com")
    assert names(again.properties()) == ["Kos Dua"]

    second.delete(f"/managers/{second.managers()[0]['id']}", expect=204)

    assert second.managers() == []
    assert_error(mira.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(again.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    login = world.client.post(
        "/auth/login",
        json={
            "email": "mira@example.com",
            "password": mira.password,
            "device": {"name": "Pixel 8", "platform": "Android 14"},
        },
    )
    assert_error(login, 401, "INVALID_CREDENTIALS")


# Two devices editing the same manager


def test_the_second_device_to_save_a_manager_gets_a_conflict_until_it_reloads(world):
    first = world.owner_signs_up()
    second = world.login(first.email)
    prop = first.add_property(MELATI)
    token = first.add_manager([prop], name="Mira Manager", phone="081200000001")
    path = f"/managers/{token.id}"
    seen_by_first = first.read(path)
    seen_by_second = second.read(path)
    assert seen_by_first["version"] == 1
    assert seen_by_second["version"] == 1
    assert first.managers()[0]["version"] == 1

    saved = first.put(
        path,
        json=manager_body(seen_by_first, nickname="Bu Mira"),
        headers={"If-Match": '"1"'},
        expect=200,
    ).json()
    assert saved["version"] == 2
    assert first.read(path)["version"] == 2
    assert first.managers()[0]["version"] == 2

    conflict = second.put(
        path,
        json=manager_body(seen_by_second, phone="081299999999"),
        headers={"If-Match": '"1"'},
    )
    assert_error(conflict, 409, "RESOURCE_VERSION_CONFLICT")
    unchanged = second.read(path)
    assert unchanged["nickname"] == "Bu Mira"
    assert unchanged["phone"] == "081200000001"
    assert unchanged["version"] == 2

    resaved = second.put(
        path,
        json=manager_body(unchanged, phone="081299999999"),
        headers={"If-Match": f'"{unchanged["version"]}"'},
        expect=200,
    ).json()
    assert resaved["version"] == 3
    assert resaved["nickname"] == "Bu Mira"
    assert resaved["phone"] == "081299999999"
    assert first.read(path)["version"] == 3


def test_a_manager_save_without_the_header_always_applies_and_raises_the_version(
    world,
):
    owner = world.owner_signs_up()
    token = owner.add_manager([owner.add_property(MELATI)], name="Mira Manager")
    path = f"/managers/{token.id}"
    record = owner.read(path)
    owner.put(
        path,
        json=manager_body(record, nickname="One"),
        headers={"If-Match": '"1"'},
        expect=200,
    )

    stale_without_header = owner.put(path, json=manager_body(record, nickname="Two"))

    assert stale_without_header.status_code == 200
    assert stale_without_header.json()["version"] == 3
    assert owner.read(path)["nickname"] == "Two"
    same_values = owner.put(path, json=manager_body(record, nickname="Two"), expect=200)
    assert same_values.json()["version"] == 4
    assert owner.read(path)["version"] == 4


def test_a_manager_save_with_a_malformed_version_header_is_refused(world):
    owner = world.owner_signs_up()
    token = owner.add_manager([owner.add_property(MELATI)], name="Mira Manager")
    path = f"/managers/{token.id}"
    record = owner.read(path)

    for header in ("1", "abc", '"abc"'):
        response = owner.put(
            path,
            json=manager_body(record, nickname="One"),
            headers={"If-Match": header},
        )
        assert_error(response, 422, "VALIDATION_FAILED", "ifMatch")

    assert owner.read(path)["nickname"] is None
    assert owner.read(path)["version"] == 1


def test_a_managers_own_login_does_not_change_the_version_the_owner_sees(world):
    owner = world.owner_signs_up()
    token = owner.add_manager([owner.add_property(MELATI)], name="Mira Manager")
    world.manager_activates(token, email="mira@example.com")
    path = f"/managers/{token.id}"
    before = owner.read(path)["version"]

    manager = world.login("mira@example.com")
    manager.refresh()
    assert manager.properties()[0]["name"] == MELATI

    assert owner.read(path)["version"] == before
    assert owner.managers()[0]["version"] == before
