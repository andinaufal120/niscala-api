"""End-to-end journeys of maintenance complaints: submitting, photos and handling."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from e2e.e2e_people import COMPLAINT_TEXT, EMERGENCY_CONTACTS, JPG_BYTES, PNG_BYTES
from e2e.e2e_world import ANGGREK, MELATI

PHOTO_LIMIT = 5 * 1024 * 1024


def assert_error(response, status, code, field=None):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code, body
    assert body["field"] == field, body


def ids(items):
    return [item["id"] for item in items]


def photo(content, name="photo.png", content_type="image/png"):
    return {"file": (name, content, content_type)}


def about(notifications, complaint):
    """The notifications that announce events of one complaint."""
    return [
        n
        for n in notifications
        if (n["complaint"] or {}).get("complaintId") == complaint["id"]
    ]


def of_type(notifications, type_):
    return [n for n in notifications if n["type"] == type_]


def end_lease(database, tenant_id):
    """Give a Tenant record an ended lease while keeping it and its sessions.

    No endpoint does this: deleting the record also ends the sessions, so the
    only Tenant without an active lease who can still call the API is built here.
    """
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from app.models import Lease

    with Session(database) as db:
        db.execute(
            update(Lease)
            .where(Lease.tenant_id == UUID(tenant_id))
            .values(ended_at=datetime.now(UTC))
        )
        db.commit()


def tenant_record(owner, prop, name):
    return next(t for t in owner.tenants(prop) if t["name"] == name)


# Submitting


def test_a_complaint_is_saved_announced_to_management_and_followed_to_done(
    seeded_world, world
):
    owner, manager, budi, sari = (
        seeded_world.owner,
        seeded_world.manager,
        seeded_world.budi,
        seeded_world.sari,
    )
    world.stubs.classifier_works(category="Air", urgency="medium")
    for person, device in ((owner, "device-rina"), (manager, "device-mira")):
        person.enable_push(device)
    budi.enable_push("device-budi")

    created = budi.submit_complaint(
        seeded_world.rooms["A1"], "The ceiling lamp flickers and sparks."
    )

    assert created["status"] == "new"
    assert created["description"] == "The ceiling lamp flickers and sparks."
    assert created["tenantName"] == "Budi Tenant"
    assert created["property"]["name"] == MELATI
    assert created["room"]["number"] == "A1"
    assert created["hasPhoto"] is False
    assert created["classification"] is None
    assert created["classificationState"] == "classifying"
    assert [c["status"] for c in created["statusChanges"]] == ["new"]
    for staff, device in ((owner, "device-rina"), (manager, "device-mira")):
        announced = about(staff.notifications(), created)
        assert [n["type"] for n in announced] == ["complaintSubmitted"]
        facts = announced[0]["complaint"]
        assert facts["category"] is None
        assert facts["urgency"] is None
        assert facts["status"] == "new"
        assert announced[0]["tenant"]["name"] == "Budi Tenant"
        assert announced[0]["room"]["number"] == "A1"
        assert announced[0]["property"]["name"] == MELATI
        world.stubs.assert_pushed(device, "complaintSubmitted")
    assert about(budi.notifications(), created) == []
    assert about(sari.notifications(), created) == []
    assert sari.complaints() == []
    assert_error(sari.get(f"/complaints/{created['id']}"), 404, "COMPLAINT_NOT_FOUND")

    path = f"/complaints/{created['id']}/status-changes"
    for tenant in (budi, sari):
        assert_error(tenant.post(path, json={"status": "inProgress"}), 403, "FORBIDDEN")
    for skipped in ("done", "new"):
        assert_error(
            owner.post(path, json={"status": skipped}),
            409,
            "COMPLAINT_STATUS_NOT_NEXT",
            "status",
        )
    assert owner.complaint(created)["status"] == "new"
    assert of_type(budi.notifications(), "complaintStatusChanged") == []

    moved = owner.post(
        path,
        json={"status": "inProgress", "handlingNote": "Electrician booked for Friday."},
        expect=201,
    ).json()

    assert moved["status"] == "inProgress"
    assert [(c["status"], c["handlingNote"]) for c in moved["statusChanges"]] == [
        ("new", None),
        ("inProgress", "Electrician booked for Friday."),
    ]
    detail = budi.complaint(created)
    assert detail["status"] == "inProgress"
    assert [(c["status"], c["handlingNote"]) for c in detail["statusChanges"]] == [
        ("new", None),
        ("inProgress", "Electrician booked for Friday."),
    ]
    assert next(c for c in budi.complaints() if c["id"] == created["id"])["status"] == (
        "inProgress"
    )
    [progress] = of_type(budi.notifications(), "complaintStatusChanged")
    assert progress["complaint"]["status"] == "inProgress"
    assert progress["complaint"]["handlingNote"] == "Electrician booked for Friday."
    assert progress["room"]["number"] == "A1"
    assert progress["property"]["name"] == MELATI
    world.stubs.assert_pushed("device-budi", "complaintStatusChanged")
    assert of_type(owner.notifications(), "complaintStatusChanged") == []

    finished = manager.post(
        path,
        json={"status": "done", "handlingNote": "Lamp replaced and tested."},
        expect=201,
    ).json()

    assert finished["status"] == "done"
    detail = budi.complaint(created)
    assert [(c["status"], c["handlingNote"]) for c in detail["statusChanges"]] == [
        ("new", None),
        ("inProgress", "Electrician booked for Friday."),
        ("done", "Lamp replaced and tested."),
    ]
    changed = of_type(budi.notifications(), "complaintStatusChanged")
    assert [
        (n["complaint"]["status"], n["complaint"]["handlingNote"]) for n in changed
    ] == [
        ("done", "Lamp replaced and tested."),
        ("inProgress", "Electrician booked for Friday."),
    ]
    assert world.stubs.pushes_to("device-budi") == ["complaintStatusChanged"] * 2

    for target in ("new", "inProgress", "done"):
        for staff in (owner, manager):
            assert_error(
                staff.post(path, json={"status": target, "handlingNote": "Again."}),
                409,
                "COMPLAINT_STATUS_NOT_NEXT",
                "status",
            )
    assert len(owner.complaint(created)["statusChanges"]) == 3
    assert len(of_type(budi.notifications(), "complaintStatusChanged")) == 2


def test_a_manager_sees_and_handles_only_complaints_of_assigned_properties(
    seeded_world, world
):
    owner, manager = seeded_world.owner, seeded_world.manager
    dewi = world.tenant_activates(seeded_world.dewi_token, email="dewi@example.com")
    world.stubs.classifier_works()
    owner.enable_push("device-rina")
    manager.enable_push("device-mira")

    elsewhere = dewi.submit_complaint(
        seeded_world.rooms["B1"], "The shower has no hot water."
    )
    assert elsewhere["property"]["name"] == ANGGREK

    assert set(ids(owner.complaints())) == {
        seeded_world.complaint["id"],
        elsewhere["id"],
    }
    assert ids(manager.complaints()) == [seeded_world.complaint["id"]]
    detail = f"/complaints/{elsewhere['id']}"
    assert_error(manager.get(detail), 404, "COMPLAINT_NOT_FOUND")
    assert_error(
        manager.post(f"{detail}/status-changes", json={"status": "inProgress"}),
        404,
        "COMPLAINT_NOT_FOUND",
    )
    assert_error(
        manager.put(
            f"{detail}/classification", json={"category": "Air", "urgency": "low"}
        ),
        404,
        "COMPLAINT_NOT_FOUND",
    )
    assert owner.complaint(elsewhere)["status"] == "new"
    assert [n["type"] for n in about(owner.notifications(), elsewhere)] == [
        "complaintSubmitted"
    ]
    assert about(manager.notifications(), elsewhere) == []
    world.stubs.assert_pushed("device-rina", "complaintSubmitted")
    world.stubs.assert_not_pushed("device-mira")

    dewi.put(f"{detail}/photo", files=photo(PNG_BYTES), expect=200)

    assert owner.get(f"{detail}/photo").status_code == 200
    assert_error(manager.get(f"{detail}/photo"), 404, "COMPLAINT_NOT_FOUND")
    moved = owner.post(
        f"{detail}/status-changes", json={"status": "inProgress"}, expect=201
    ).json()
    assert moved["status"] == "inProgress"
    assert_error(manager.get(detail), 404, "COMPLAINT_NOT_FOUND")
    assert ids(manager.complaints()) == [seeded_world.complaint["id"]]


def test_a_tenant_renting_in_two_places_picks_the_room_of_each_complaint(
    seeded_world, world
):
    owner, manager, budi, sari = (
        seeded_world.owner,
        seeded_world.manager,
        seeded_world.budi,
        seeded_world.sari,
    )
    rooms = seeded_world.rooms
    world.stubs.classifier_works()
    owner.enable_push("device-rina")
    manager.enable_push("device-mira")
    token = owner.add_tenant(rooms["B2"], "Budi Second", "081244444444")
    accepted = budi.post(
        "/invitations/acceptances",
        json={"token": token, "emergencyContacts": EMERGENCY_CONTACTS},
    )
    assert accepted.status_code < 300, accepted.text
    assert len(budi.leases()) == 2

    for foreign in (rooms["A2"], rooms["A3"], rooms["B1"], {"id": str(uuid4())}):
        refused = budi.post(
            "/complaints",
            json={"description": COMPLAINT_TEXT, "roomId": foreign["id"]},
        )
        assert_error(refused, 404, "ROOM_NOT_FOUND", "roomId")
    assert len(budi.complaints()) == 1

    here = budi.submit_complaint(rooms["A1"], "The window does not close.")
    there = budi.submit_complaint(rooms["B2"], "The door lock is stuck.")

    assert (here["property"]["name"], here["room"]["number"]) == (MELATI, "A1")
    assert (there["property"]["name"], there["room"]["number"]) == (ANGGREK, "B2")
    assert ids(budi.complaints()) == [
        there["id"],
        here["id"],
        seeded_world.complaint["id"],
    ]
    assert sari.complaints() == []
    assert set(ids(owner.complaints())) == set(ids(budi.complaints()))
    assert set(ids(manager.complaints())) == {here["id"], seeded_world.complaint["id"]}
    assert [n["type"] for n in about(owner.notifications(), there)] == [
        "complaintSubmitted"
    ]
    assert about(manager.notifications(), there) == []
    assert about(manager.notifications(), here) != []
    assert world.stubs.pushes_to("device-mira") == ["complaintSubmitted"]
    assert world.stubs.pushes_to("device-rina") == [
        "tenantActivated",
        "complaintSubmitted",
        "complaintSubmitted",
    ]
    assert budi.complaint(there)["room"]["number"] == "B2"

    owner.delete(
        f"/tenants/{tenant_record(owner, seeded_world.melati, 'Budi Tenant')['id']}",
        expect=204,
    )

    assert_error(
        budi.post(
            "/complaints",
            json={"description": COMPLAINT_TEXT, "roomId": rooms["A1"]["id"]},
        ),
        404,
        "ROOM_NOT_FOUND",
        "roomId",
    )
    budi.submit_complaint(rooms["B2"], "The door lock is stuck again.")
    assert budi.complaint(here)["status"] == "new"
    assert here["id"] in ids(budi.complaints())


def test_a_tenant_without_an_active_lease_cannot_submit_a_complaint(
    seeded_world, world, database
):
    owner, budi = seeded_world.owner, seeded_world.budi
    world.stubs.classifier_works()
    owner.enable_push("device-rina")
    end_lease(database, tenant_record(owner, seeded_world.melati, "Budi Tenant")["id"])
    calls = len(world.stubs.classifier.calls)

    refused = budi.post(
        "/complaints",
        json={"description": COMPLAINT_TEXT, "roomId": seeded_world.rooms["A1"]["id"]},
    )

    assert_error(refused, 403, "NO_ACTIVE_LEASE")
    assert ids(owner.complaints()) == [seeded_world.complaint["id"]]
    assert ids(budi.complaints()) == [seeded_world.complaint["id"]]
    assert len(world.stubs.classifier.calls) == calls
    world.stubs.assert_not_pushed("device-rina")


# Photos


def test_a_photo_is_attached_replaced_and_frozen_once_the_complaint_moves_on(
    seeded_world, world
):
    owner, manager, budi, sari = (
        seeded_world.owner,
        seeded_world.manager,
        seeded_world.budi,
        seeded_world.sari,
    )
    world.stubs.classifier_works()
    complaint = budi.submit_complaint(seeded_world.rooms["A1"], "The latch is broken.")
    path = f"/complaints/{complaint['id']}/photo"
    assert complaint["hasPhoto"] is False
    for person in (budi, owner, manager):
        assert_error(person.get(path), 404, "PHOTO_NOT_FOUND")

    assert_error(
        budi.put(path, files=photo(b"GIF89a" + bytes(64))),
        422,
        "PHOTO_TYPE_INVALID",
        "file",
    )
    assert_error(
        budi.put(
            path, files=photo(b"%PDF-1.4\n" + bytes(64), "scan.jpg", "image/jpeg")
        ),
        422,
        "PHOTO_TYPE_INVALID",
        "file",
    )
    too_big = PNG_BYTES + bytes(PHOTO_LIMIT + 1 - len(PNG_BYTES))
    assert_error(budi.put(path, files=photo(too_big)), 422, "PHOTO_TOO_LARGE", "file")
    assert budi.complaint(complaint)["hasPhoto"] is False
    assert_error(budi.get(path), 404, "PHOTO_NOT_FOUND")
    world.stubs.assert_files_stored(0)

    biggest = PNG_BYTES + bytes(PHOTO_LIMIT - len(PNG_BYTES))
    attached = budi.put(
        path, files=photo(biggest, "photo.txt", "text/plain"), expect=200
    ).json()
    assert attached["hasPhoto"] is True
    assert attached["status"] == "new"
    for person in (budi, owner, manager):
        shown = person.get(path, expect=200)
        assert shown.content == biggest
        assert shown.headers["content-type"] == "image/png"
    assert next(c for c in owner.complaints() if c["id"] == complaint["id"])["hasPhoto"]

    replaced = budi.put(path, files=photo(JPG_BYTES, "p.jpg", "image/jpeg"), expect=200)
    assert replaced.json()["hasPhoto"] is True
    for person in (budi, owner, manager):
        shown = person.get(path, expect=200)
        assert shown.content == JPG_BYTES
        assert shown.headers["content-type"] == "image/jpeg"
    world.stubs.assert_files_stored(1)

    assert_error(sari.get(path), 404, "COMPLAINT_NOT_FOUND")
    assert_error(sari.put(path, files=photo(PNG_BYTES)), 404, "COMPLAINT_NOT_FOUND")
    assert_error(owner.put(path, files=photo(PNG_BYTES)), 403, "FORBIDDEN")
    assert_error(manager.put(path, files=photo(PNG_BYTES)), 403, "FORBIDDEN")
    assert budi.get(path).content == JPG_BYTES

    owner.post(
        f"/complaints/{complaint['id']}/status-changes",
        json={"status": "inProgress"},
        expect=201,
    )

    assert_error(budi.put(path, files=photo(PNG_BYTES)), 409, "COMPLAINT_NOT_NEW")
    assert budi.get(path).content == JPG_BYTES
    assert budi.complaint(complaint)["hasPhoto"] is True
    world.stubs.assert_files_stored(1)

    bare = budi.submit_complaint(seeded_world.rooms["A1"], "The tap drips at night.")
    owner.post(
        f"/complaints/{bare['id']}/status-changes",
        json={"status": "inProgress"},
        expect=201,
    )
    assert_error(
        budi.put(f"/complaints/{bare['id']}/photo", files=photo(PNG_BYTES)),
        409,
        "COMPLAINT_NOT_NEW",
    )
    assert_error(budi.get(f"/complaints/{bare['id']}/photo"), 404, "PHOTO_NOT_FOUND")
    assert budi.complaint(bare)["hasPhoto"] is False
    world.stubs.assert_files_stored(1)
