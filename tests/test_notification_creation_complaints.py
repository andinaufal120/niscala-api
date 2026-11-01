"""Notifications created when a complaint is submitted or moves to a new status."""

import pytest
from notification_support import (
    DESCRIPTION,
    assert_item,
    change_complaint,
    classify_manually,
    complaint_facts,
    items,
    list_all,
    of_type,
    only,
    property_ref,
    role,
    room_ref,
    stored_for,
    stored_rows,
    submit_complaint,
    tenant_ref,
    types,
    unassign,
)
from sqlalchemy.orm import Session

AI_HIGH = ("Listrik", "high", "Send an electrician today.")


@pytest.fixture
def complaint(make_complaint, scene):
    return make_complaint(scene.tenant, scene.room, description="The tap leaks badly.")


def submitted_facts(scene, complaint_id, description=DESCRIPTION) -> dict:
    return {
        "complaint": complaint_facts(complaint_id, "new", description=description),
        "tenant": tenant_ref(scene.tenant.user),
        "room": room_ref(scene.room),
        "property": property_ref(scene.prop),
    }


def progress_facts(scene, complaint, status, **options) -> dict:
    return {
        "complaint": complaint_facts(
            complaint.id, status, description=complaint.description, **options
        ),
        "room": room_ref(scene.room),
        "property": property_ref(scene.prop),
    }


# A tenant submits a complaint


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_submitting_notifies_the_owner_and_the_assigned_manager(
    client, database, scene, who
):
    created = submit_complaint(client, scene.tenant_in.headers).json()
    recipient = getattr(scene, who)
    item = only(client, recipient, "complaintSubmitted")
    assert_item(item, "complaintSubmitted", **submitted_facts(scene, created["id"]))
    assert types(client, recipient) == ["complaintSubmitted"]


def test_submitting_does_not_notify_the_tenant(client, database, scene):
    submit_complaint(client, scene.tenant_in.headers)
    assert items(client, scene.tenant_in) == []


def test_the_notification_carries_the_description_as_saved(client, database, scene):
    created = submit_complaint(
        client, scene.tenant_in.headers, "   Lampu kamar mati total.   "
    ).json()
    item = only(client, scene.owner_in, "complaintSubmitted")
    assert item["complaint"]["description"] == created["description"]
    assert item["complaint"]["description"] == "Lampu kamar mati total."


def test_every_submission_makes_its_own_notification(client, database, scene):
    first = submit_complaint(client, scene.tenant_in.headers, "First problem here.")
    second = submit_complaint(client, scene.tenant_in.headers, "Second problem here.")
    shown = [i["complaint"]["complaintId"] for i in items(client, scene.owner_in)]
    assert shown == [second.json()["id"], first.json()["id"]]


def test_other_managers_and_owners_are_not_notified(
    client, database, scene, make_user, make_site, sign_in
):
    outsider = make_user(name="Outside Manager", role=role("manager"))
    make_site(scene.owner, name="Kos Kedua", number="B1", managers=[outsider])
    stranger = make_user(name="Other Owner")
    submit_complaint(client, scene.tenant_in.headers)
    assert items(client, sign_in(outsider)) == []
    assert items(client, sign_in(stranger)) == []
    assert stored_for(database, outsider) == []


def test_every_assigned_manager_is_notified(
    client, database, scene, make_user, assign_manager, sign_in
):
    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(colleague, scene.prop)
    submit_complaint(client, scene.tenant_in.headers)
    assert types(client, sign_in(colleague)) == ["complaintSubmitted"]
    assert len(stored_rows(database)) == 3


def test_a_manager_unassigned_before_the_submission_is_not_notified(
    client, database, scene
):
    unassign(database, scene.manager, scene.prop)
    submit_complaint(client, scene.tenant_in.headers)
    assert stored_for(database, scene.manager) == []
    assert len(stored_for(database, scene.owner)) == 1


def test_the_notification_is_tied_to_the_property_of_the_complaint(
    client, database, scene
):
    submit_complaint(client, scene.tenant_in.headers)
    (row,) = stored_for(database, scene.owner)
    assert str(row["type"]) == "complaintSubmitted"
    assert row["property_id"] == scene.prop.id


def test_a_complaint_of_an_owner_without_a_subscription_is_still_notified(
    client, database, scene
):
    created = submit_complaint(client, scene.tenant_in.headers).json()
    assert created["classificationState"] == "notClassified"
    item = only(client, scene.owner_in, "complaintSubmitted")
    assert item["complaint"]["category"] is None
    assert item["complaint"]["urgency"] is None


def test_a_notification_is_created_at_submission_and_never_changed_by_the_classification(
    client, database, scene, subscribe_owner, fake_classifier
):
    subscribe_owner(scene.owner, "basic")
    created = submit_complaint(client, scene.tenant_in.headers).json()
    detail = client.get(f"/complaints/{created['id']}", headers=scene.owner_in.headers)
    assert detail.json()["classification"]["urgency"] == "high"
    for who in (scene.owner_in, scene.manager_in):
        (item,) = items(client, who)
        assert item["complaint"] == complaint_facts(
            created["id"], "new", description=DESCRIPTION
        )


def test_a_failed_classification_leaves_the_notification_as_it_was(
    client, database, scene, subscribe_owner, fake_classifier
):
    subscribe_owner(scene.owner, "basic")
    fake_classifier.error = RuntimeError("model down")
    created = submit_complaint(client, scene.tenant_in.headers).json()
    (item,) = items(client, scene.owner_in)
    assert item["complaint"] == complaint_facts(
        created["id"], "new", description=DESCRIPTION
    )


def test_the_classification_adds_no_second_notification(
    client, database, scene, subscribe_owner, fake_classifier
):
    subscribe_owner(scene.owner, "basic")
    submit_complaint(client, scene.tenant_in.headers)
    assert len(stored_for(database, scene.owner)) == 1
    assert len(stored_for(database, scene.manager)) == 1


def test_a_notification_does_not_change_when_the_complaint_moves_on(
    client, database, scene
):
    created = submit_complaint(client, scene.tenant_in.headers).json()
    (before,) = items(client, scene.owner_in)
    change_complaint(
        client, scene.owner_in.headers, created["id"], handlingNote="On it."
    )
    assert of_type(client, scene.owner_in, "complaintSubmitted") == [before]
    assert before["complaint"]["status"] == "new"
    assert before["complaint"]["handlingNote"] is None


# Submissions that fail create nothing


@pytest.mark.parametrize("description", ["", "          ", "too short"])
def test_a_rejected_description_creates_no_notification(
    client, database, scene, description
):
    response = submit_complaint(client, scene.tenant_in.headers, description)
    assert response.status_code == 422
    assert stored_rows(database) == []


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_a_forbidden_submission_creates_no_notification(client, database, scene, who):
    response = submit_complaint(client, getattr(scene, who).headers)
    assert response.status_code == 403
    assert stored_rows(database) == []


def test_a_tenant_without_an_active_lease_creates_no_notification(
    client, database, scene, make_room, make_verified_tenant, sign_in
):
    former = make_verified_tenant(
        make_room(scene.prop, number="A9"), name="Former Tenant", lease_ended=True
    )
    response = submit_complaint(client, sign_in(former.user).headers)
    assert response.status_code == 403
    assert response.json()["code"] == "NO_ACTIVE_LEASE"
    assert stored_rows(database) == []


# The submission hook


class SubmissionHook:
    """Stands in for the hook that announces a new complaint."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bool, object]] = []
        self.error = error

    def __call__(self, db, complaint) -> None:
        self.calls.append((isinstance(db, Session), complaint.id))
        if self.error is not None:
            raise self.error


def test_the_submission_hook_is_called_once_with_the_session_and_the_complaint(
    client, database, scene, monkeypatch
):
    hook = SubmissionHook()
    monkeypatch.setattr("app.services.complaints.notify_complaint_submitted", hook)
    created = submit_complaint(client, scene.tenant_in.headers).json()
    assert [(is_session, str(i)) for is_session, i in hook.calls] == [
        (True, created["id"])
    ]


def test_the_submission_hook_is_not_called_for_a_rejected_submission(
    client, database, scene, monkeypatch
):
    hook = SubmissionHook()
    monkeypatch.setattr("app.services.complaints.notify_complaint_submitted", hook)
    submit_complaint(client, scene.tenant_in.headers, "short")
    submit_complaint(client, scene.owner_in.headers)
    assert hook.calls == []


def test_a_failing_submission_hook_does_not_undo_the_complaint(
    client, database, scene, monkeypatch
):
    hook = SubmissionHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.complaints.notify_complaint_submitted", hook)
    response = submit_complaint(client, scene.tenant_in.headers)
    assert response.status_code == 201, response.text
    assert len(hook.calls) == 1
    listed = client.get("/complaints", headers=scene.tenant_in.headers).json()["items"]
    assert [c["id"] for c in listed] == [response.json()["id"]]


def test_a_failing_submission_hook_does_not_stop_the_classification(
    client, database, scene, subscribe_owner, fake_classifier, monkeypatch
):
    subscribe_owner(scene.owner, "basic")
    hook = SubmissionHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.complaints.notify_complaint_submitted", hook)
    created = submit_complaint(client, scene.tenant_in.headers).json()
    detail = client.get(f"/complaints/{created['id']}", headers=scene.owner_in.headers)
    assert detail.json()["classification"]["category"] == "Listrik"
    assert len(fake_classifier.calls) == 1


# Management moves a complaint to a new status


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_moving_a_complaint_on_notifies_the_tenant_with_the_status_and_note(
    client, database, scene, complaint, who
):
    response = change_complaint(
        client,
        getattr(scene, who).headers,
        complaint.id,
        handlingNote="Technician scheduled.",
    )
    assert response.status_code == 201, response.text
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert_item(
        item,
        "complaintStatusChanged",
        **progress_facts(
            scene, complaint, "inProgress", handling_note="Technician scheduled."
        ),
    )
    assert types(client, scene.tenant_in) == ["complaintStatusChanged"]


def test_the_note_is_the_trimmed_note_of_that_change(
    client, database, scene, complaint
):
    change_complaint(
        client,
        scene.owner_in.headers,
        complaint.id,
        handlingNote="  \n Come tomorrow.\t ",
    )
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["handlingNote"] == "Come tomorrow."


@pytest.mark.parametrize("note", ["", "   ", None, "omitted"])
def test_a_change_without_a_note_carries_no_note(
    client, database, scene, complaint, note
):
    extra = {} if note == "omitted" else {"handlingNote": note}
    change_complaint(client, scene.owner_in.headers, complaint.id, **extra)
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["handlingNote"] is None


def test_finishing_a_complaint_notifies_the_tenant_again(
    client, database, scene, complaint
):
    change_complaint(
        client,
        scene.owner_in.headers,
        complaint.id,
        handlingNote="Technician scheduled.",
    )
    change_complaint(
        client,
        scene.manager_in.headers,
        complaint.id,
        "done",
        handlingNote="All fixed.",
    )
    newest, oldest = of_type(client, scene.tenant_in, "complaintStatusChanged")
    assert newest["complaint"]["status"] == "done"
    assert newest["complaint"]["handlingNote"] == "All fixed."
    assert oldest["complaint"]["status"] == "inProgress"
    assert oldest["complaint"]["handlingNote"] == "Technician scheduled."


def test_moving_a_complaint_on_does_not_notify_management(
    client, database, scene, complaint
):
    change_complaint(client, scene.manager_in.headers, complaint.id)
    assert items(client, scene.owner_in) == []
    assert items(client, scene.manager_in) == []


def test_only_the_tenant_of_the_complaint_is_notified(
    client, database, scene, complaint, make_site
):
    neighbour = make_site(scene.owner, name="Kos Kedua", number="B1")
    change_complaint(client, scene.owner_in.headers, complaint.id)
    assert items(client, neighbour.tenant_in) == []
    assert len(stored_rows(database)) == 1


def test_the_notification_is_tied_to_the_property_of_the_complaint_for_the_tenant(
    client, database, scene, complaint
):
    change_complaint(client, scene.owner_in.headers, complaint.id)
    (row,) = stored_for(database, scene.tenant.user)
    assert str(row["type"]) == "complaintStatusChanged"
    assert row["property_id"] == scene.prop.id


def test_an_ai_classification_is_shown_when_the_owner_has_a_subscription(
    client, database, scene, subscribe_owner, make_complaint
):
    subscribe_owner(scene.owner, "pro")
    classified = make_complaint(scene.tenant, scene.room, ai=AI_HIGH)
    change_complaint(client, scene.owner_in.headers, classified.id)
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["category"] == "Listrik"
    assert item["complaint"]["urgency"] == "high"


def test_a_manual_classification_is_shown(client, database, scene, make_complaint):
    classified = make_complaint(scene.tenant, scene.room)
    assert (
        classify_manually(
            client, scene.owner_in.headers, classified.id, "Air", "low"
        ).status_code
        == 200
    )
    change_complaint(client, scene.owner_in.headers, classified.id)
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["category"] == "Air"
    assert item["complaint"]["urgency"] == "low"


def test_a_manual_classification_replaces_the_ai_result_in_the_notification(
    client, database, scene, subscribe_owner, make_complaint
):
    subscribe_owner(scene.owner, "pro")
    classified = make_complaint(scene.tenant, scene.room, ai=AI_HIGH)
    classify_manually(client, scene.owner_in.headers, classified.id, "Air", "low")
    change_complaint(client, scene.owner_in.headers, classified.id)
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["category"] == "Air"
    assert item["complaint"]["urgency"] == "low"


def test_the_classification_is_the_one_at_the_time_of_each_change(
    client, database, scene, complaint
):
    change_complaint(client, scene.owner_in.headers, complaint.id)
    classify_manually(client, scene.owner_in.headers, complaint.id, "Air", "medium")
    change_complaint(client, scene.owner_in.headers, complaint.id, "done")
    newest, oldest = of_type(client, scene.tenant_in, "complaintStatusChanged")
    assert (newest["complaint"]["category"], newest["complaint"]["urgency"]) == (
        "Air",
        "medium",
    )
    assert (oldest["complaint"]["category"], oldest["complaint"]["urgency"]) == (
        None,
        None,
    )


def test_an_unclassified_complaint_has_no_category_or_urgency(
    client, database, scene, complaint
):
    change_complaint(client, scene.owner_in.headers, complaint.id)
    item = only(client, scene.tenant_in, "complaintStatusChanged")
    assert item["complaint"]["category"] is None
    assert item["complaint"]["urgency"] is None


def test_a_status_notification_keeps_its_facts_when_the_complaint_moves_on(
    client, database, scene, complaint
):
    change_complaint(
        client, scene.owner_in.headers, complaint.id, handlingNote="First."
    )
    (first,) = items(client, scene.tenant_in)
    change_complaint(
        client, scene.owner_in.headers, complaint.id, "done", handlingNote="Last."
    )
    by_id = {i["id"]: i for i in items(client, scene.tenant_in)}
    assert len(by_id) == 2
    assert by_id[first["id"]] == first


# Refused changes create nothing


def test_a_refused_target_creates_no_notification(client, database, scene, complaint):
    response = change_complaint(client, scene.owner_in.headers, complaint.id, "done")
    assert response.status_code == 409
    assert stored_rows(database) == []


def test_a_finished_complaint_creates_no_notification_for_a_further_change(
    client, database, scene, complaint
):
    change_complaint(client, scene.owner_in.headers, complaint.id)
    change_complaint(client, scene.owner_in.headers, complaint.id, "done")
    assert len(stored_rows(database)) == 2
    response = change_complaint(client, scene.owner_in.headers, complaint.id, "done")
    assert response.status_code == 409
    assert len(stored_rows(database)) == 2


def test_a_tenant_cannot_move_their_complaint_and_nothing_is_created(
    client, database, scene, complaint
):
    response = change_complaint(client, scene.tenant_in.headers, complaint.id)
    assert response.status_code == 403
    assert stored_rows(database) == []


def test_an_unassigned_manager_creates_no_notification(
    client, database, scene, complaint
):
    unassign(database, scene.manager, scene.prop)
    response = change_complaint(client, scene.manager_in.headers, complaint.id)
    assert response.status_code == 404
    assert stored_rows(database) == []


def test_an_invalid_status_creates_no_notification(client, database, scene, complaint):
    response = change_complaint(client, scene.owner_in.headers, complaint.id, "bogus")
    assert response.status_code == 422
    assert list_all(client, scene.tenant_in) == {"items": [], "unreadCount": 0}


# The status change hook


class StatusChangeHook:
    """Stands in for the hook that announces a complaint status change."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bool, object, str, str | None]] = []
        self.error = error

    def __call__(self, db, complaint, change) -> None:
        self.calls.append(
            (
                isinstance(db, Session),
                complaint.id,
                str(change.status),
                change.handling_note,
            )
        )
        if self.error is not None:
            raise self.error


def test_the_status_hook_receives_the_session_the_complaint_and_the_change(
    client, database, scene, complaint, monkeypatch
):
    hook = StatusChangeHook()
    monkeypatch.setattr("app.services.complaints.notify_complaint_status_change", hook)
    change_complaint(client, scene.owner_in.headers, complaint.id, handlingNote="Soon.")
    assert hook.calls == [(True, complaint.id, "inProgress", "Soon.")]


def test_a_failing_status_hook_does_not_undo_the_change(
    client, database, scene, complaint, monkeypatch
):
    hook = StatusChangeHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.complaints.notify_complaint_status_change", hook)
    response = change_complaint(
        client, scene.owner_in.headers, complaint.id, handlingNote="Soon."
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "inProgress"
    detail = client.get(f"/complaints/{complaint.id}", headers=scene.tenant_in.headers)
    assert detail.json()["status"] == "inProgress"
    assert detail.json()["statusChanges"][-1]["handlingNote"] == "Soon."
    assert len(hook.calls) == 1
