"""Moving a complaint forward one status at a time, with an optional handling note."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
STATUSES = ["new", "inProgress", "done"]
ALLOWED = {("new", "inProgress"), ("inProgress", "done")}
ALL_PAIRS = [(a, b) for a in STATUSES for b in STATUSES]
DETAIL_FIELDS = {
    "id",
    "description",
    "status",
    "property",
    "room",
    "tenantName",
    "createdAt",
    "hasPhoto",
    "classification",
    "classificationState",
    "classificationWithheld",
    "statusChanges",
}
NOW = datetime.now(UTC)
AI_HIGH = ("Listrik", "high", "Send an electrician today.")


def ago(minutes: int) -> datetime:
    return NOW - timedelta(minutes=minutes)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def change_url(complaint_id) -> str:
    return f"{COMPLAINTS}/{complaint_id}/status-changes"


def change(client, headers, complaint, status="inProgress", **extra):
    return client.post(
        change_url(complaint.id), json={"status": status, **extra}, headers=headers
    )


def history_until(status: str) -> list[tuple[str, str | None, datetime]]:
    steps = [
        ("new", None, ago(30)),
        ("inProgress", "Technician scheduled.", ago(20)),
        ("done", "All fixed.", ago(10)),
    ]
    return steps[: STATUSES.index(status) + 1]


def complaint_at(make_complaint, tenant, room, status: str, **options):
    return make_complaint(
        tenant,
        room,
        status=status,
        created_at=ago(30),
        changes=history_until(status),
        **options,
    )


def stored_status(database, complaint) -> str:
    from app.models import Complaint

    with Session(database) as db:
        return str(db.get(Complaint, complaint.id).status)


def stored_changes(database, complaint) -> list:
    from app.models import ComplaintStatusChange

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(ComplaintStatusChange)
                .where(ComplaintStatusChange.complaint_id == complaint.id)
                .order_by(ComplaintStatusChange.changed_at)
            )
        )


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati")


@pytest.fixture
def room(prop, make_room):
    return make_room(prop, number="A1")


@pytest.fixture
def tenant(room, make_verified_tenant):
    return make_verified_tenant(room, name="Budi Tenant")


@pytest.fixture
def tenant_in(tenant, sign_in):
    return sign_in(tenant.user)


@pytest.fixture
def manager(make_user, prop, assign_manager):
    user = make_user(name="Mira Manager", role=role("manager"))
    assign_manager(user, prop)
    return user


@pytest.fixture
def manager_in(manager, sign_in):
    return sign_in(manager)


@pytest.fixture
def complaint(make_complaint, tenant, room):
    return complaint_at(make_complaint, tenant, room, "new")


@pytest.fixture
def other_world(make_user, make_property, make_room, make_verified_tenant):
    other_owner = make_user(name="Other Owner")
    other_prop = make_property(other_owner, name="Kos Lain")
    other_room = make_room(other_prop, number="Z9")
    other_tenant = make_verified_tenant(other_room, name="Other Tenant")
    return other_owner, other_prop, other_room, other_tenant


@pytest.fixture
def hook_calls(monkeypatch):
    """Record calls to the notification hook as `(complaint, change)` tuples."""
    calls: list[tuple] = []

    def record(complaint, change):
        calls.append((complaint, change))

    monkeypatch.setattr(
        "app.services.complaints.notify_complaint_status_change", record
    )
    return calls


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database, complaint):
    response = client.post(change_url(complaint.id), json={"status": "inProgress"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database, complaint):
    response = change(client, {"Authorization": "Bearer garbage"}, complaint)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["owner", "manager", "tenant"])
def test_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, complaint, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(change(client, session.headers, complaint), 403, "EMAIL_NOT_VERIFIED")


def test_a_tenant_cannot_change_the_status_of_their_own_complaint(
    client, database, tenant_in, complaint
):
    response = change(client, tenant_in.headers, complaint)
    assert_error(response, 403, "FORBIDDEN")
    assert stored_status(database, complaint) == "new"
    assert len(stored_changes(database, complaint)) == 1


def test_an_admin_cannot_change_the_status(
    client, database, make_user, sign_in, complaint
):
    session = sign_in(make_user(role=role("admin")))
    response = change(client, session.headers, complaint)
    assert_error(response, 403, "FORBIDDEN")
    assert stored_status(database, complaint) == "new"
    assert len(stored_changes(database, complaint)) == 1


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_a_forbidden_role_is_refused_before_the_complaint_is_looked_up(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name)))
    response = client.post(
        change_url(uuid4()), json={"status": "inProgress"}, headers=session.headers
    )
    assert_error(response, 403, "FORBIDDEN")


# Successful changes


def test_an_owner_moves_a_new_complaint_to_in_progress(
    client, database, owner_in, complaint
):
    response = change(client, owner_in.headers, complaint)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == str(complaint.id)
    assert body["status"] == "inProgress"
    assert stored_status(database, complaint) == "inProgress"


def test_a_manager_of_the_property_moves_a_new_complaint_to_in_progress(
    client, database, manager_in, complaint
):
    response = change(client, manager_in.headers, complaint)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "inProgress"
    assert stored_status(database, complaint) == "inProgress"


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_moves_an_in_progress_complaint_to_done(
    client, database, request, make_complaint, tenant, room, who
):
    headers = request.getfixturevalue(who).headers
    complaint = complaint_at(make_complaint, tenant, room, "inProgress")
    response = change(client, headers, complaint, "done")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "done"
    assert stored_status(database, complaint) == "done"


def test_the_response_is_the_full_complaint_detail(
    client, database, owner_in, complaint, prop, room
):
    body = change(client, owner_in.headers, complaint).json()
    assert set(body) == DETAIL_FIELDS
    assert body["description"] == complaint.description
    assert body["property"] == {"id": str(prop.id), "name": "Kos Melati"}
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["tenantName"] == "Budi Tenant"
    assert body["hasPhoto"] is False


def test_a_complaint_goes_through_every_status_in_turn(
    client, database, owner_in, complaint
):
    first = change(client, owner_in.headers, complaint, "inProgress", handlingNote="a")
    second = change(client, owner_in.headers, complaint, "done", handlingNote="b")
    assert first.status_code == 201
    assert second.status_code == 201
    entries = second.json()["statusChanges"]
    assert [(e["status"], e["handlingNote"]) for e in entries] == [
        ("new", None),
        ("inProgress", "a"),
        ("done", "b"),
    ]
    assert [c.status for c in stored_changes(database, complaint)] == STATUSES


def test_a_second_change_to_the_same_status_is_rejected_after_a_success(
    client, database, owner_in, complaint
):
    assert change(client, owner_in.headers, complaint).status_code == 201
    response = change(client, owner_in.headers, complaint)
    assert_error(response, 409, "COMPLAINT_STATUS_NOT_NEXT", "status")
    assert len(stored_changes(database, complaint)) == 2


# Status history


def test_the_new_entry_is_appended_after_the_creation_entry(
    client, database, owner_in, complaint
):
    entries = change(client, owner_in.headers, complaint).json()["statusChanges"]
    assert [e["status"] for e in entries] == ["new", "inProgress"]
    assert entries[0]["handlingNote"] is None
    assert set(entries[1]) == {"status", "handlingNote", "changedAt"}


def test_the_new_entry_is_timestamped_in_utc_after_the_previous_entry(
    client, database, owner_in, complaint
):
    before = datetime.now(UTC)
    entries = change(client, owner_in.headers, complaint).json()["statusChanges"]
    after = datetime.now(UTC)
    first = datetime.fromisoformat(entries[0]["changedAt"])
    added = datetime.fromisoformat(entries[1]["changedAt"])
    assert added.utcoffset() == timedelta(0)
    assert first < added
    assert before - timedelta(seconds=5) <= added <= after + timedelta(seconds=5)


def test_the_stored_change_matches_the_response(client, database, owner_in, complaint):
    entries = change(
        client, owner_in.headers, complaint, handlingNote="Technician scheduled."
    ).json()["statusChanges"]
    stored = stored_changes(database, complaint)
    assert [c.status for c in stored] == ["new", "inProgress"]
    assert stored[1].handling_note == "Technician scheduled."
    assert stored[1].changed_at == datetime.fromisoformat(entries[1]["changedAt"])


def test_earlier_entries_and_their_notes_are_kept_in_order(
    client, database, owner_in, make_complaint, tenant, room
):
    complaint = complaint_at(make_complaint, tenant, room, "inProgress")
    entries = change(
        client, owner_in.headers, complaint, "done", handlingNote="Closed."
    ).json()["statusChanges"]
    assert [(e["status"], e["handlingNote"]) for e in entries] == [
        ("new", None),
        ("inProgress", "Technician scheduled."),
        ("done", "Closed."),
    ]
    times = [datetime.fromisoformat(e["changedAt"]) for e in entries]
    assert times == sorted(times)


def test_the_complaint_status_reflects_the_change_in_the_detail_and_the_lists(
    client, database, owner_in, manager_in, tenant_in, complaint
):
    change(client, owner_in.headers, complaint)
    for headers in (owner_in.headers, manager_in.headers, tenant_in.headers):
        (item,) = client.get(COMPLAINTS, headers=headers).json()["items"]
        assert item["status"] == "inProgress"
        got = client.get(f"{COMPLAINTS}/{complaint.id}", headers=headers).json()
        assert got["status"] == "inProgress"
        assert [e["status"] for e in got["statusChanges"]] == ["new", "inProgress"]


# Handling note


def test_a_handling_note_is_returned_and_stored(client, database, owner_in, complaint):
    body = change(
        client, owner_in.headers, complaint, handlingNote="Technician scheduled."
    ).json()
    assert body["statusChanges"][-1]["handlingNote"] == "Technician scheduled."
    assert stored_changes(database, complaint)[-1].handling_note == (
        "Technician scheduled."
    )


def test_a_handling_note_is_trimmed(client, database, owner_in, complaint):
    body = change(
        client, owner_in.headers, complaint, handlingNote="  \n Come tomorrow.\t "
    ).json()
    assert body["statusChanges"][-1]["handlingNote"] == "Come tomorrow."
    assert stored_changes(database, complaint)[-1].handling_note == "Come tomorrow."


def test_a_note_keeps_its_inner_whitespace(client, database, owner_in, complaint):
    body = change(
        client, owner_in.headers, complaint, handlingNote="First line.\n\nSecond  line."
    ).json()
    assert body["statusChanges"][-1]["handlingNote"] == "First line.\n\nSecond  line."


@pytest.mark.parametrize("note", ["", " ", "   \n\t  ", None])
def test_a_blank_or_null_note_is_stored_as_none(
    client, database, owner_in, complaint, note
):
    response = change(client, owner_in.headers, complaint, handlingNote=note)
    assert response.status_code == 201, response.text
    assert response.json()["statusChanges"][-1]["handlingNote"] is None
    assert stored_changes(database, complaint)[-1].handling_note is None


def test_an_omitted_note_is_stored_as_none(client, database, owner_in, complaint):
    response = change(client, owner_in.headers, complaint)
    assert response.json()["statusChanges"][-1]["handlingNote"] is None
    assert stored_changes(database, complaint)[-1].handling_note is None


def test_the_tenant_sees_the_note_in_the_detail(
    client, database, owner_in, tenant_in, complaint
):
    change(client, owner_in.headers, complaint, handlingNote="Technician scheduled.")
    body = client.get(f"{COMPLAINTS}/{complaint.id}", headers=tenant_in.headers).json()
    assert [(e["status"], e["handlingNote"]) for e in body["statusChanges"]] == [
        ("new", None),
        ("inProgress", "Technician scheduled."),
    ]


def test_the_tenant_sees_the_note_in_the_list_after_a_manager_change(
    client, database, manager_in, tenant_in, complaint
):
    change(client, manager_in.headers, complaint, handlingNote="On it.")
    (item,) = client.get(COMPLAINTS, headers=tenant_in.headers).json()["items"]
    assert item["status"] == "inProgress"
    detail = client.get(f"{COMPLAINTS}/{item['id']}", headers=tenant_in.headers)
    assert detail.json()["statusChanges"][-1]["handlingNote"] == "On it."


# Every status pair


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS)
def test_only_the_next_status_is_accepted(
    client, database, owner_in, make_complaint, tenant, room, current, target
):
    complaint = complaint_at(make_complaint, tenant, room, current)
    before = len(stored_changes(database, complaint))
    response = change(client, owner_in.headers, complaint, target)
    if (current, target) in ALLOWED:
        assert response.status_code == 201, response.text
        assert response.json()["status"] == target
        assert stored_status(database, complaint) == target
        assert len(stored_changes(database, complaint)) == before + 1
    else:
        assert_error(response, 409, "COMPLAINT_STATUS_NOT_NEXT", "status")
        assert stored_status(database, complaint) == current
        assert len(stored_changes(database, complaint)) == before


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS)
def test_a_manager_is_held_to_the_same_transitions(
    client, database, manager_in, make_complaint, tenant, room, current, target
):
    complaint = complaint_at(make_complaint, tenant, room, current)
    response = change(client, manager_in.headers, complaint, target)
    assert response.status_code == (201 if (current, target) in ALLOWED else 409)


@pytest.mark.parametrize(
    ("current", "target"), [p for p in ALL_PAIRS if p not in ALLOWED]
)
def test_a_rejected_change_saves_neither_the_status_nor_the_note(
    client, database, owner_in, make_complaint, tenant, room, current, target
):
    complaint = complaint_at(make_complaint, tenant, room, current)
    before = [(c.status, c.handling_note) for c in stored_changes(database, complaint)]
    change(client, owner_in.headers, complaint, target, handlingNote="Ignored.")
    after = [(c.status, c.handling_note) for c in stored_changes(database, complaint)]
    assert after == before
    assert stored_status(database, complaint) == current


def test_nothing_changes_once_the_complaint_is_done(
    client, database, owner_in, make_complaint, tenant, room
):
    complaint = complaint_at(make_complaint, tenant, room, "done")
    for target in STATUSES:
        response = change(client, owner_in.headers, complaint, target)
        assert_error(response, 409, "COMPLAINT_STATUS_NOT_NEXT", "status")
    assert [c.status for c in stored_changes(database, complaint)] == STATUSES


# Validation


@pytest.mark.parametrize(
    "status",
    ["closed", "in_progress", "NEW", "Done", "new_", "", None, 1, ["done"]],
)
def test_an_invalid_status_is_a_validation_error_on_the_status_field(
    client, database, owner_in, complaint, status
):
    response = client.post(
        change_url(complaint.id), json={"status": status}, headers=owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "status")
    assert len(stored_changes(database, complaint)) == 1


@pytest.mark.parametrize(
    "body", [{}, {"handlingNote": "Fixed."}], ids=["empty", "note_only"]
)
def test_a_missing_status_is_a_validation_error_on_the_status_field(
    client, database, owner_in, complaint, body
):
    response = client.post(
        change_url(complaint.id), json=body, headers=owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "status")
    assert stored_status(database, complaint) == "new"


def test_a_missing_body_is_a_validation_error(client, database, owner_in, complaint):
    response = client.post(change_url(complaint.id), headers=owner_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_non_text_note_is_a_validation_error_on_its_field(
    client, database, owner_in, complaint
):
    response = change(client, owner_in.headers, complaint, handlingNote=5)
    assert_error(response, 422, "VALIDATION_FAILED", "handlingNote")
    assert stored_status(database, complaint) == "new"


def test_a_malformed_complaint_id_is_a_validation_error(client, database, owner_in):
    response = client.post(
        f"{COMPLAINTS}/not-a-uuid/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "complaintId")


# Access to the complaint


def test_an_unknown_complaint_is_not_found(client, database, owner_in, manager_in):
    for headers in (owner_in.headers, manager_in.headers):
        response = client.post(
            change_url(uuid4()), json={"status": "inProgress"}, headers=headers
        )
        assert_error(response, 404, "COMPLAINT_NOT_FOUND")


def test_an_owner_cannot_change_the_complaint_of_another_owner(
    client, database, owner_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    other = make_complaint(other_tenant, other_room)
    assert_error(change(client, owner_in.headers, other), 404, "COMPLAINT_NOT_FOUND")
    assert stored_status(database, other) == "new"
    assert len(stored_changes(database, other)) == 1


def test_an_owner_cannot_change_a_complaint_of_a_deleted_property(
    client,
    database,
    owner,
    owner_in,
    make_property,
    make_room,
    make_verified_tenant,
    make_complaint,
):
    gone = make_property(owner, name="Kos Lama", deleted=True)
    gone_room = make_room(gone, number="G1")
    gone_tenant = make_verified_tenant(gone_room)
    gone_complaint = make_complaint(gone_tenant, gone_room)
    assert_error(
        change(client, owner_in.headers, gone_complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert stored_status(database, gone_complaint) == "new"


def test_a_manager_cannot_change_a_complaint_of_an_unassigned_property(
    client,
    database,
    owner,
    manager_in,
    make_property,
    make_room,
    make_verified_tenant,
    make_complaint,
):
    other_prop = make_property(owner, name="Kos Kedua")
    other_room = make_room(other_prop, number="K1")
    other_tenant = make_verified_tenant(other_room)
    other = make_complaint(other_tenant, other_room)
    assert_error(change(client, manager_in.headers, other), 404, "COMPLAINT_NOT_FOUND")
    assert stored_status(database, other) == "new"
    assert len(stored_changes(database, other)) == 1


def test_an_unassigned_manager_cannot_change_a_complaint(
    client, database, make_user, sign_in, complaint
):
    stranger = sign_in(make_user(name="Stranger", role=role("manager")))
    assert_error(
        change(client, stranger.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert stored_status(database, complaint) == "new"


def test_a_manager_loses_the_right_to_change_when_unassigned(
    client, database, manager, manager_in, prop, complaint
):
    unassign(database, manager, prop)
    assert_error(
        change(client, manager_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert stored_status(database, complaint) == "new"
    assert len(stored_changes(database, complaint)) == 1


def test_a_manager_may_change_complaints_of_properties_from_several_owners(
    client, database, manager, manager_in, other_world, assign_manager, make_complaint
):
    _, other_prop, other_room, other_tenant = other_world
    assign_manager(manager, other_prop)
    other = make_complaint(other_tenant, other_room)
    response = change(client, manager_in.headers, other)
    assert response.status_code == 201, response.text
    assert stored_status(database, other) == "inProgress"


# Gating and view-only


def test_the_change_does_not_need_a_subscription(
    client, database, owner, owner_in, complaint, subscribe_owner, expire_subscription
):
    subscribe_owner(owner, "basic")
    expire_subscription(owner)
    response = change(client, owner_in.headers, complaint)
    assert response.status_code == 201, response.text


def test_a_complaint_of_a_view_only_property_can_change_status(
    client,
    database,
    owner,
    owner_in,
    manager_in,
    make_property,
    make_room,
    make_verified_tenant,
    make_complaint,
    assign_manager,
    manager,
):
    view_only = make_property(owner, name="Kos Baca", view_only=True)
    view_room = make_room(view_only, number="V1")
    view_tenant = make_verified_tenant(view_room)
    assign_manager(manager, view_only)
    first = make_complaint(view_tenant, view_room)
    second = make_complaint(view_tenant, view_room)
    assert change(client, owner_in.headers, first).status_code == 201
    assert change(client, manager_in.headers, second).status_code == 201
    assert stored_status(database, first) == "inProgress"
    assert stored_status(database, second) == "inProgress"


def test_a_complaint_of_a_view_only_room_can_change_status(
    client,
    database,
    prop,
    owner_in,
    make_room,
    make_verified_tenant,
    make_complaint,
):
    view_room = make_room(prop, number="V2", view_only=True)
    view_tenant = make_verified_tenant(view_room)
    view_complaint = make_complaint(view_tenant, view_room)
    response = change(client, owner_in.headers, view_complaint)
    assert response.status_code == 201, response.text
    assert stored_status(database, view_complaint) == "inProgress"


# Other fields stay as they were


def test_the_classification_and_other_fields_are_untouched(
    client, database, owner, owner_in, subscribe_owner, make_complaint, tenant, room
):
    subscribe_owner(owner, "pro")
    complaint = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(30))
    before = client.get(f"{COMPLAINTS}/{complaint.id}", headers=owner_in.headers).json()
    after = change(client, owner_in.headers, complaint).json()
    assert after["classification"] == before["classification"]
    assert after["classification"]["urgency"] == "high"
    for field in DETAIL_FIELDS - {"status", "statusChanges"}:
        assert after[field] == before[field], field


def test_a_withheld_classification_stays_withheld_in_the_response(
    client, database, owner_in, make_complaint, tenant, room
):
    complaint = make_complaint(tenant, room, ai=AI_HIGH)
    body = change(client, owner_in.headers, complaint).json()
    assert body["classification"] is None
    assert body["classificationWithheld"] is True


def test_other_complaints_are_not_changed(
    client, database, owner_in, complaint, make_complaint, tenant, room
):
    bystander = make_complaint(tenant, room)
    change(client, owner_in.headers, complaint)
    assert stored_status(database, bystander) == "new"
    assert len(stored_changes(database, bystander)) == 1


# Notification hook


def test_the_hook_is_called_once_with_the_complaint_and_the_new_change(
    client, database, owner_in, complaint, hook_calls
):
    response = change(
        client, owner_in.headers, complaint, handlingNote="Technician scheduled."
    )
    assert response.status_code == 201, response.text
    ((notified, added),) = hook_calls
    assert notified.id == complaint.id
    assert added.status == "inProgress"
    assert added.handling_note == "Technician scheduled."


def test_the_hook_sees_the_new_status_when_a_manager_finishes_a_complaint(
    client, database, manager_in, make_complaint, tenant, room, hook_calls
):
    complaint = complaint_at(make_complaint, tenant, room, "inProgress")
    change(client, manager_in.headers, complaint, "done")
    ((notified, added),) = hook_calls
    assert notified.id == complaint.id
    assert added.status == "done"


@pytest.mark.parametrize(
    ("current", "target"), [p for p in ALL_PAIRS if p not in ALLOWED]
)
def test_the_hook_is_not_called_for_a_rejected_transition(
    client,
    database,
    owner_in,
    make_complaint,
    tenant,
    room,
    hook_calls,
    current,
    target,
):
    complaint = complaint_at(make_complaint, tenant, room, current)
    change(client, owner_in.headers, complaint, target)
    assert hook_calls == []


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_the_hook_is_not_called_for_a_forbidden_role(
    client, database, make_user, sign_in, complaint, hook_calls, name
):
    session = sign_in(make_user(role=role(name)))
    change(client, session.headers, complaint)
    assert hook_calls == []


def test_the_hook_is_not_called_for_an_inaccessible_or_invalid_request(
    client, database, owner_in, make_user, sign_in, complaint, hook_calls
):
    stranger = sign_in(make_user(name="Stranger", role=role("manager")))
    change(client, stranger.headers, complaint)
    client.post(
        change_url(uuid4()), json={"status": "inProgress"}, headers=owner_in.headers
    )
    change(client, owner_in.headers, complaint, "bogus")
    client.post(change_url(complaint.id), headers={"Authorization": "Bearer garbage"})
    assert hook_calls == []


def test_a_failing_hook_does_not_undo_the_change(
    client, database, owner_in, complaint, tenant_in, monkeypatch
):
    def explode(complaint, change):
        raise RuntimeError("push service down")

    monkeypatch.setattr(
        "app.services.complaints.notify_complaint_status_change", explode
    )
    response = change(client, owner_in.headers, complaint, handlingNote="Scheduled.")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "inProgress"
    assert stored_status(database, complaint) == "inProgress"
    stored = stored_changes(database, complaint)
    assert [c.status for c in stored] == ["new", "inProgress"]
    assert stored[-1].handling_note == "Scheduled."
    detail = client.get(f"{COMPLAINTS}/{complaint.id}", headers=tenant_in.headers)
    assert detail.json()["status"] == "inProgress"
