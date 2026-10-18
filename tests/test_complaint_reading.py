"""Listing complaints, reading one, and withholding AI results without a plan."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
SUMMARY_FIELDS = {
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
}
DETAIL_FIELDS = {*SUMMARY_FIELDS, "statusChanges"}
NOW = datetime.now(UTC)


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


def listed(client, headers) -> list[dict]:
    response = client.get(COMPLAINTS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def ids(items: list[dict]) -> list[str]:
    return [item["id"] for item in items]


def detail(client, headers, complaint):
    return client.get(f"{COMPLAINTS}/{complaint.id}", headers=headers)


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


AI_HIGH = ("Listrik", "high", "Send an electrician today.")
AI_MEDIUM = ("Air", "medium", "Check the pipes.")
AI_LOW = ("Perabot", "low", "Tighten the hinge.")


@pytest.fixture
def owner(make_user, subscribe_owner):
    user = make_user(name="Rina Owner")
    subscribe_owner(user, "pro")
    return user


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
def other_world(make_user, make_property, make_room, make_verified_tenant):
    """A second owner with a property, a room, a tenant and a plan."""
    other_owner = make_user(name="Other Owner")
    other_prop = make_property(other_owner, name="Kos Lain")
    other_room = make_room(other_prop, number="Z9")
    other_tenant = make_verified_tenant(other_room, name="Other Tenant")
    return other_owner, other_prop, other_room, other_tenant


# Empty and shape


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_the_list_is_empty_but_successful_without_complaints(
    client, database, request, who
):
    headers = request.getfixturevalue(who).headers
    response = client.get(COMPLAINTS, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_a_list_item_has_the_summary_fields(
    client, database, tenant, room, tenant_in, make_complaint, prop
):
    complaint = make_complaint(tenant, room, ai=AI_HIGH)
    (item,) = listed(client, tenant_in.headers)
    assert set(item) == SUMMARY_FIELDS
    assert item["id"] == str(complaint.id)
    assert item["description"] == complaint.description
    assert item["status"] == "new"
    assert item["property"] == {"id": str(prop.id), "name": "Kos Melati"}
    assert item["room"] == {"id": str(room.id), "number": "A1"}
    assert item["tenantName"] == "Budi Tenant"
    assert item["hasPhoto"] is False
    assert item["classification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
        "classifiedByName": None,
        "originalAiClassification": None,
    }
    assert item["classificationState"] is None
    assert item["classificationWithheld"] is False
    assert datetime.fromisoformat(item["createdAt"]) == complaint.created_at


def test_the_detail_has_the_summary_fields_and_the_status_history(
    client, database, tenant, room, tenant_in, make_complaint
):
    complaint = make_complaint(tenant, room, ai=AI_LOW)
    response = detail(client, tenant_in.headers, complaint)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(complaint.id)
    assert body["classification"]["urgency"] == "low"


def test_the_status_history_is_oldest_first_with_notes(
    client, database, tenant, room, tenant_in, make_complaint
):
    complaint = make_complaint(
        tenant,
        room,
        status="done",
        created_at=ago(30),
        changes=[
            ("done", "All fixed.", ago(5)),
            ("new", None, ago(30)),
            ("inProgress", "Technician scheduled.", ago(15)),
        ],
    )
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["status"] == "done"
    assert [(c["status"], c["handlingNote"]) for c in body["statusChanges"]] == [
        ("new", None),
        ("inProgress", "Technician scheduled."),
        ("done", "All fixed."),
    ]
    times = [datetime.fromisoformat(c["changedAt"]) for c in body["statusChanges"]]
    assert times == sorted(times)


# Tenant list


def test_a_tenant_sees_only_their_own_complaints(
    client, database, tenant, room, tenant_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    mine = make_complaint(tenant, room)
    make_complaint(other_tenant, other_room)
    assert ids(listed(client, tenant_in.headers)) == [str(mine.id)]


def test_a_tenant_sees_their_complaints_newest_first_regardless_of_urgency(
    client, database, tenant, room, tenant_in, make_complaint
):
    old_high = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(30))
    new_low = make_complaint(tenant, room, ai=AI_LOW, created_at=ago(5))
    middle = make_complaint(tenant, room, created_at=ago(15))
    assert ids(listed(client, tenant_in.headers)) == [
        str(new_low.id),
        str(middle.id),
        str(old_high.id),
    ]


def test_a_tenant_whose_lease_ended_still_sees_their_complaints(
    client, database, room, make_verified_tenant, sign_in, make_complaint
):
    stored = make_verified_tenant(room, lease_ended=True)
    complaint = make_complaint(stored, room)
    headers = sign_in(stored.user).headers
    assert ids(listed(client, headers)) == [str(complaint.id)]
    assert detail(client, headers, complaint).status_code == 200


def test_a_tenant_without_complaints_sees_none_of_the_others(
    client, database, tenant_in, room, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    make_complaint(other_tenant, other_room)
    assert listed(client, tenant_in.headers) == []


# Owner and manager lists


def test_an_owner_sees_the_complaints_of_their_properties(
    client,
    database,
    tenant,
    room,
    owner_in,
    make_complaint,
    make_room,
    prop,
    make_verified_tenant,
):
    second_room = make_room(prop, number="A2")
    second_tenant = make_verified_tenant(second_room, name="Siti Tenant")
    first = make_complaint(tenant, room, created_at=ago(10))
    second = make_complaint(second_tenant, second_room, created_at=ago(5))
    items = listed(client, owner_in.headers)
    assert set(ids(items)) == {str(first.id), str(second.id)}
    assert {i["tenantName"] for i in items} == {"Budi Tenant", "Siti Tenant"}


def test_an_owner_never_sees_the_complaints_of_other_owners(
    client, database, tenant, room, owner_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    mine = make_complaint(tenant, room)
    make_complaint(other_tenant, other_room)
    assert ids(listed(client, owner_in.headers)) == [str(mine.id)]


def test_an_owner_does_not_see_complaints_of_a_deleted_property(
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
    make_complaint(gone_tenant, gone_room)
    assert listed(client, owner_in.headers) == []


def test_a_manager_sees_only_complaints_of_assigned_properties(
    client,
    database,
    owner,
    tenant,
    room,
    manager_in,
    make_complaint,
    make_property,
    make_room,
    make_verified_tenant,
):
    unassigned = make_property(owner, name="Kos Kedua")
    unassigned_room = make_room(unassigned, number="K1")
    unassigned_tenant = make_verified_tenant(unassigned_room)
    visible = make_complaint(tenant, room)
    make_complaint(unassigned_tenant, unassigned_room)
    assert ids(listed(client, manager_in.headers)) == [str(visible.id)]


def test_a_manager_loses_the_complaints_when_the_assignment_is_removed(
    client, database, tenant, room, manager, manager_in, prop, make_complaint
):
    make_complaint(tenant, room)
    assert len(listed(client, manager_in.headers)) == 1
    unassign(database, manager, prop)
    assert listed(client, manager_in.headers) == []


def test_a_manager_sees_complaints_of_properties_from_several_owners(
    client,
    database,
    manager,
    manager_in,
    tenant,
    room,
    other_world,
    assign_manager,
    make_complaint,
    subscribe_owner,
):
    _, other_prop, other_room, other_tenant = other_world
    assign_manager(manager, other_prop)
    first = make_complaint(tenant, room, created_at=ago(10))
    second = make_complaint(other_tenant, other_room, created_at=ago(5))
    assert ids(listed(client, manager_in.headers)) == [str(second.id), str(first.id)]


# Management ordering


def test_management_sees_urgency_high_medium_low_then_the_unclassified(
    client, database, tenant, room, owner_in, make_complaint
):
    low = make_complaint(tenant, room, ai=AI_LOW, created_at=ago(1))
    awaiting = make_complaint(
        tenant, room, classification_state="awaitingClassification", created_at=ago(2)
    )
    high = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(60))
    classifying = make_complaint(
        tenant, room, classification_state="classifying", created_at=ago(3)
    )
    medium = make_complaint(tenant, room, ai=AI_MEDIUM, created_at=ago(30))
    not_classified = make_complaint(
        tenant, room, classification_state="notClassified", created_at=ago(4)
    )
    assert ids(listed(client, owner_in.headers)) == [
        str(high.id),
        str(medium.id),
        str(low.id),
        str(awaiting.id),
        str(classifying.id),
        str(not_classified.id),
    ]


def test_complaints_of_one_urgency_are_newest_first(
    client, database, tenant, room, owner_in, make_complaint
):
    oldest = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(30))
    newest = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(5))
    middle = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(15))
    assert ids(listed(client, owner_in.headers)) == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]


def test_complaints_without_a_visible_classification_are_newest_first(
    client, database, tenant, room, owner_in, make_complaint
):
    oldest = make_complaint(
        tenant, room, classification_state="notClassified", created_at=ago(30)
    )
    newest = make_complaint(
        tenant, room, classification_state="awaitingClassification", created_at=ago(5)
    )
    middle = make_complaint(
        tenant, room, classification_state="classifying", created_at=ago(15)
    )
    assert ids(listed(client, owner_in.headers)) == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]


def test_a_withheld_result_ranks_with_the_unclassified_complaints(
    client,
    database,
    manager,
    manager_in,
    tenant,
    room,
    other_world,
    assign_manager,
    make_complaint,
):
    _, other_prop, other_room, other_tenant = other_world
    assign_manager(manager, other_prop)
    withheld_high = make_complaint(
        other_tenant, other_room, ai=AI_HIGH, created_at=ago(1)
    )
    visible_low = make_complaint(tenant, room, ai=AI_LOW, created_at=ago(50))
    awaiting = make_complaint(
        tenant, room, classification_state="awaitingClassification", created_at=ago(40)
    )
    assert ids(listed(client, manager_in.headers)) == [
        str(visible_low.id),
        str(withheld_high.id),
        str(awaiting.id),
    ]


# Gating on reads


def test_an_ai_result_is_withheld_once_the_owner_has_no_subscription(
    client,
    database,
    tenant,
    room,
    owner,
    tenant_in,
    make_complaint,
    expire_subscription,
):
    complaint = make_complaint(tenant, room, ai=AI_HIGH)
    expire_subscription(owner)
    (item,) = listed(client, tenant_in.headers)
    assert item["classification"] is None
    assert item["classificationState"] is None
    assert item["classificationWithheld"] is True
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["classification"] is None
    assert body["classificationState"] is None
    assert body["classificationWithheld"] is True


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_every_reader_gets_the_ai_result_withheld(
    client,
    database,
    request,
    tenant,
    room,
    owner,
    make_complaint,
    expire_subscription,
    who,
):
    headers = request.getfixturevalue(who).headers
    complaint = make_complaint(tenant, room, ai=AI_MEDIUM)
    expire_subscription(owner)
    (item,) = listed(client, headers)
    assert item["classification"] is None
    assert item["classificationWithheld"] is True
    body = detail(client, headers, complaint).json()
    assert body["classification"] is None
    assert body["classificationState"] is None
    assert body["classificationWithheld"] is True


def test_withheld_results_do_not_leak_the_urgency_or_category_anywhere(
    client,
    database,
    tenant,
    room,
    owner,
    owner_in,
    make_complaint,
    expire_subscription,
):
    make_complaint(tenant, room, ai=("Keamanan", "high", "Call security."))
    expire_subscription(owner)
    text = client.get(COMPLAINTS, headers=owner_in.headers).text
    assert "Keamanan" not in text
    assert "Call security." not in text


def test_a_complaint_without_an_ai_result_is_not_flagged_as_withheld(
    client,
    database,
    tenant,
    room,
    owner,
    tenant_in,
    make_complaint,
    expire_subscription,
):
    complaint = make_complaint(
        tenant, room, classification_state="awaitingClassification"
    )
    expire_subscription(owner)
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["classification"] is None
    assert body["classificationState"] == "awaitingClassification"
    assert body["classificationWithheld"] is False


def test_a_not_classified_complaint_keeps_its_state_and_is_not_withheld(
    client, database, tenant, room, tenant_in, make_complaint
):
    complaint = make_complaint(tenant, room, classification_state="notClassified")
    (item,) = listed(client, tenant_in.headers)
    assert item["classificationState"] == "notClassified"
    assert item["classificationWithheld"] is False
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["classificationState"] == "notClassified"
    assert body["classificationWithheld"] is False


def test_the_ai_result_is_visible_while_the_subscription_runs(
    client, database, tenant, room, tenant_in, make_complaint
):
    complaint = make_complaint(tenant, room, ai=AI_HIGH)
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["classification"]["category"] == "Listrik"
    assert body["classificationWithheld"] is False


def test_the_ai_result_returns_when_the_owner_subscribes_again(
    client,
    database,
    tenant,
    room,
    owner,
    tenant_in,
    make_complaint,
    expire_subscription,
    subscribe_owner,
):
    complaint = make_complaint(tenant, room, ai=AI_HIGH)
    expire_subscription(owner)
    assert detail(client, tenant_in.headers, complaint).json()["classificationWithheld"]
    subscribe_owner(owner, "basic")
    body = detail(client, tenant_in.headers, complaint).json()
    assert body["classification"]["urgency"] == "high"
    assert body["classificationWithheld"] is False


def test_a_complaint_of_an_owner_on_the_free_plan_with_an_ai_result_is_withheld(
    client, database, other_world, make_complaint, sign_in
):
    _, _, other_room, other_tenant = other_world
    complaint = make_complaint(other_tenant, other_room, ai=AI_LOW)
    body = detail(client, sign_in(other_tenant.user).headers, complaint).json()
    assert body["classification"] is None
    assert body["classificationWithheld"] is True


# Detail access


def test_an_owner_reads_a_complaint_of_their_property(
    client, database, tenant, room, owner_in, make_complaint
):
    complaint = make_complaint(tenant, room)
    response = detail(client, owner_in.headers, complaint)
    assert response.status_code == 200
    assert response.json()["id"] == str(complaint.id)


def test_a_manager_reads_a_complaint_of_an_assigned_property(
    client, database, tenant, room, manager_in, make_complaint
):
    complaint = make_complaint(tenant, room)
    assert detail(client, manager_in.headers, complaint).status_code == 200


def test_an_unknown_complaint_is_not_found(client, database, tenant_in):
    response = client.get(f"{COMPLAINTS}/{uuid4()}", headers=tenant_in.headers)
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")


def test_a_tenant_cannot_read_the_complaint_of_another_tenant(
    client, database, tenant_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    complaint = make_complaint(other_tenant, other_room)
    assert_error(
        detail(client, tenant_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_a_tenant_cannot_read_the_complaint_of_a_tenant_in_the_same_property(
    client, database, prop, make_room, make_verified_tenant, tenant_in, make_complaint
):
    neighbour_room = make_room(prop, number="A2")
    neighbour = make_verified_tenant(neighbour_room, name="Neighbour")
    complaint = make_complaint(neighbour, neighbour_room)
    assert_error(
        detail(client, tenant_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_owner_cannot_read_the_complaint_of_another_owner(
    client, database, owner_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    complaint = make_complaint(other_tenant, other_room)
    assert_error(
        detail(client, owner_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_owner_cannot_read_a_complaint_of_a_deleted_property(
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
    complaint = make_complaint(gone_tenant, gone_room)
    assert_error(
        detail(client, owner_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_unassigned_manager_cannot_read_a_complaint(
    client, database, tenant, room, make_user, sign_in, make_complaint
):
    stranger = sign_in(make_user(name="Stranger", role=role("manager")))
    complaint = make_complaint(tenant, room)
    assert_error(
        detail(client, stranger.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_a_manager_loses_access_to_the_detail_when_unassigned(
    client, database, tenant, room, manager, manager_in, prop, make_complaint
):
    complaint = make_complaint(tenant, room)
    assert detail(client, manager_in.headers, complaint).status_code == 200
    unassign(database, manager, prop)
    assert_error(
        detail(client, manager_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_a_malformed_complaint_id_is_a_validation_error(client, database, tenant_in):
    response = client.get(f"{COMPLAINTS}/not-a-uuid", headers=tenant_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "complaintId")
