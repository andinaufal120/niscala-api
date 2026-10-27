"""Management classifying a complaint by hand, and how that shows up everywhere."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
CATEGORIES = [
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
]
STATUSES = ["new", "inProgress", "done"]
URGENCIES = ["low", "medium", "high"]
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
CLASSIFICATION_FIELDS = {
    "category",
    "urgency",
    "suggestedAction",
    "classifiedByName",
    "originalAiClassification",
}
AI_HIGH = ("Listrik", "high", "Send an electrician today.")
AI_MEDIUM = ("Air", "medium", "Check the pipes.")
AI_LOW = ("Perabot", "low", "Tighten the hinge.")
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


def classification_url(complaint_id) -> str:
    return f"{COMPLAINTS}/{complaint_id}/classification"


def classify(client, headers, complaint, category="Listrik", urgency="high"):
    return client.put(
        classification_url(complaint.id),
        json={"category": category, "urgency": urgency},
        headers=headers,
    )


def stored(database, complaint):
    from app.models import Complaint

    with Session(database, expire_on_commit=False) as db:
        return db.get(Complaint, complaint.id)


def stored_changes(database, complaint) -> list:
    from sqlalchemy import select

    from app.models import ComplaintStatusChange

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(ComplaintStatusChange).where(
                    ComplaintStatusChange.complaint_id == complaint.id
                )
            )
        )


def detail(client, headers, complaint) -> dict:
    response = client.get(f"{COMPLAINTS}/{complaint.id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def listed(client, headers) -> list[dict]:
    response = client.get(COMPLAINTS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def ids(items: list[dict]) -> list[str]:
    return [item["id"] for item in items]


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


def assert_nothing_saved(database, complaint) -> None:
    row = stored(database, complaint)
    assert row.manual_category is None
    assert row.manual_urgency is None
    assert row.classified_by_id is None
    assert row.classified_at is None


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
def complaint(make_complaint, tenant, room):
    return make_complaint(tenant, room, classification_state="notClassified")


@pytest.fixture
def ai_complaint(make_complaint, tenant, room):
    return make_complaint(tenant, room, ai=AI_HIGH)


@pytest.fixture
def other_world(make_user, make_property, make_room, make_verified_tenant):
    other_owner = make_user(name="Other Owner")
    other_prop = make_property(other_owner, name="Kos Lain")
    other_room = make_room(other_prop, number="Z9")
    other_tenant = make_verified_tenant(other_room, name="Other Tenant")
    return other_owner, other_prop, other_room, other_tenant


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database, complaint):
    response = client.put(
        classification_url(complaint.id), json={"category": "Air", "urgency": "low"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database, complaint):
    response = classify(client, {"Authorization": "Bearer garbage"}, complaint)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["owner", "manager", "tenant"])
def test_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, complaint, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    response = classify(client, session.headers, complaint)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
    assert_nothing_saved(database, complaint)


def test_a_tenant_cannot_classify_their_own_complaint(
    client, database, tenant_in, complaint
):
    assert_error(classify(client, tenant_in.headers, complaint), 403, "FORBIDDEN")
    assert_nothing_saved(database, complaint)


def test_an_admin_cannot_classify_a_complaint(
    client, database, make_user, sign_in, complaint
):
    session = sign_in(make_user(role=role("admin")))
    assert_error(classify(client, session.headers, complaint), 403, "FORBIDDEN")
    assert_nothing_saved(database, complaint)


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_a_forbidden_role_is_refused_before_the_complaint_is_looked_up(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name)))
    response = client.put(
        classification_url(uuid4()),
        json={"category": "Air", "urgency": "low"},
        headers=session.headers,
    )
    assert_error(response, 403, "FORBIDDEN")


# Successful classification


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_classifies_a_complaint_nobody_has_classified(
    client, database, request, complaint, who
):
    headers = request.getfixturevalue(who).headers
    response = classify(client, headers, complaint, "Air", "medium")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(complaint.id)


def test_the_response_is_the_full_complaint_detail(
    client, database, manager_in, complaint, prop, room
):
    body = classify(client, manager_in.headers, complaint, "Air", "medium").json()
    assert set(body) == DETAIL_FIELDS
    assert body["description"] == complaint.description
    assert body["status"] == "new"
    assert body["property"] == {"id": str(prop.id), "name": "Kos Melati"}
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["tenantName"] == "Budi Tenant"
    assert body["hasPhoto"] is False
    assert [c["status"] for c in body["statusChanges"]] == ["new"]


def test_the_response_classification_is_the_manual_one(
    client, database, manager_in, complaint
):
    body = classify(client, manager_in.headers, complaint, "Air", "medium").json()
    assert body["classification"] == {
        "category": "Air",
        "urgency": "medium",
        "suggestedAction": None,
        "classifiedByName": "Mira Manager",
        "originalAiClassification": None,
    }
    assert set(body["classification"]) == CLASSIFICATION_FIELDS
    assert body["classificationState"] is None
    assert body["classificationWithheld"] is False


def test_the_owner_is_named_as_the_classifier_when_they_classify(
    client, database, owner_in, complaint
):
    body = classify(client, owner_in.headers, complaint).json()
    assert body["classification"]["classifiedByName"] == "Rina Owner"


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_of_the_list_is_accepted(
    client, database, owner_in, complaint, category
):
    response = classify(client, owner_in.headers, complaint, category, "low")
    assert response.status_code == 200, response.text
    assert response.json()["classification"]["category"] == category
    assert stored(database, complaint).manual_category == category


@pytest.mark.parametrize("urgency", URGENCIES)
def test_every_urgency_is_accepted(client, database, owner_in, complaint, urgency):
    response = classify(client, owner_in.headers, complaint, "Air", urgency)
    assert response.status_code == 200, response.text
    assert response.json()["classification"]["urgency"] == urgency
    assert stored(database, complaint).manual_urgency == urgency


def test_the_manual_values_actor_and_time_are_stored(
    client, database, manager, manager_in, complaint
):
    before = datetime.now(UTC)
    classify(client, manager_in.headers, complaint, "Air", "medium")
    after = datetime.now(UTC)
    row = stored(database, complaint)
    assert row.manual_category == "Air"
    assert row.manual_urgency == "medium"
    assert row.classified_by_id == manager.id
    assert row.classified_at.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=5) <= row.classified_at <= after
    assert row.classified_at <= datetime.now(UTC)


def test_the_stored_ai_columns_are_left_untouched(
    client, database, owner_in, ai_complaint
):
    classify(client, owner_in.headers, ai_complaint, "Air", "low")
    row = stored(database, ai_complaint)
    assert (row.ai_category, row.ai_urgency, row.ai_suggested_action) == AI_HIGH


def test_the_status_and_history_are_not_changed(client, database, owner_in, complaint):
    classify(client, owner_in.headers, complaint)
    assert stored(database, complaint).status == "new"
    assert [c.status for c in stored_changes(database, complaint)] == ["new"]


def test_other_complaints_are_not_changed(
    client, database, owner_in, complaint, make_complaint, tenant, room
):
    bystander = make_complaint(tenant, room, classification_state="notClassified")
    classify(client, owner_in.headers, complaint)
    assert_nothing_saved(database, bystander)
    assert stored(database, bystander).classification_state == "notClassified"


# Every status and every classification state


@pytest.mark.parametrize("status", STATUSES)
def test_a_complaint_can_be_classified_in_every_status(
    client, database, owner_in, make_complaint, tenant, room, status
):
    steps = [
        ("new", None, ago(30)),
        ("inProgress", None, ago(20)),
        ("done", None, ago(10)),
    ]
    complaint = make_complaint(
        tenant,
        room,
        status=status,
        created_at=ago(30),
        changes=steps[: STATUSES.index(status) + 1],
        classification_state="notClassified",
    )
    response = classify(client, owner_in.headers, complaint, "Air", "low")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    assert response.json()["classification"]["category"] == "Air"


@pytest.mark.parametrize(
    "state", ["classifying", "awaitingClassification", "notClassified"]
)
def test_a_complaint_can_be_classified_in_every_interim_state(
    client, database, owner_in, tenant_in, make_complaint, tenant, room, state
):
    complaint = make_complaint(tenant, room, classification_state=state)
    body = classify(client, owner_in.headers, complaint, "Air", "low").json()
    assert body["classification"]["category"] == "Air"
    assert body["classificationState"] is None
    assert detail(client, owner_in.headers, complaint)["classificationState"] is None
    assert detail(client, tenant_in.headers, complaint)["classificationState"] is None


def test_an_ai_classified_complaint_can_be_corrected(
    client, database, owner_in, ai_complaint
):
    body = classify(client, owner_in.headers, ai_complaint, "Air", "low").json()
    assert body["classification"]["category"] == "Air"
    assert body["classification"]["urgency"] == "low"
    assert body["classification"]["classifiedByName"] == "Rina Owner"


def test_the_correction_carries_the_original_ai_result(
    client, database, owner_in, ai_complaint
):
    body = classify(client, owner_in.headers, ai_complaint, "Air", "low").json()
    assert body["classification"]["suggestedAction"] is None
    assert body["classification"]["originalAiClassification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
    }
    assert body["classificationWithheld"] is False


def test_a_manually_classified_complaint_can_be_classified_again(
    client, database, owner_in, complaint
):
    classify(client, owner_in.headers, complaint, "Air", "low")
    body = classify(client, owner_in.headers, complaint, "Internet", "high").json()
    assert body["classification"]["category"] == "Internet"
    assert body["classification"]["urgency"] == "high"
    row = stored(database, complaint)
    assert (row.manual_category, row.manual_urgency) == ("Internet", "high")


# Reclassifying by someone else


def test_a_second_classifier_replaces_values_actor_and_time(
    client, database, owner, owner_in, manager_in, complaint
):
    classify(client, manager_in.headers, complaint, "Air", "low")
    first = stored(database, complaint)
    body = classify(client, owner_in.headers, complaint, "Internet", "high").json()
    second = stored(database, complaint)
    assert body["classification"]["classifiedByName"] == "Rina Owner"
    assert (second.manual_category, second.manual_urgency) == ("Internet", "high")
    assert second.classified_by_id == owner.id
    assert second.classified_at > first.classified_at


def test_reclassifying_keeps_the_original_ai_result(
    client, database, owner_in, manager_in, ai_complaint
):
    classify(client, manager_in.headers, ai_complaint, "Air", "low")
    body = classify(client, owner_in.headers, ai_complaint, "Internet", "medium").json()
    assert body["classification"]["originalAiClassification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
    }


# Submitting the values already shown changes nothing


def test_resubmitting_manual_values_by_another_user_keeps_actor_and_time(
    client, database, manager, owner_in, manager_in, complaint
):
    classify(client, manager_in.headers, complaint, "Air", "medium")
    first = stored(database, complaint)
    response = classify(client, owner_in.headers, complaint, "Air", "medium")
    assert response.status_code == 200, response.text
    assert response.json()["classification"]["classifiedByName"] == "Mira Manager"
    second = stored(database, complaint)
    assert second.classified_by_id == manager.id
    assert second.classified_at == first.classified_at


def test_resubmitting_manual_values_by_the_same_user_keeps_the_time(
    client, database, owner_in, complaint
):
    classify(client, owner_in.headers, complaint, "Air", "medium")
    first = stored(database, complaint)
    assert (
        classify(client, owner_in.headers, complaint, "Air", "medium").status_code
        == 200
    )
    assert stored(database, complaint).classified_at == first.classified_at


@pytest.mark.parametrize(
    ("category", "urgency"), [("Air", "high"), ("Internet", "medium")]
)
def test_changing_only_one_manual_value_is_a_change(
    client, database, manager, owner, owner_in, manager_in, complaint, category, urgency
):
    classify(client, manager_in.headers, complaint, "Air", "medium")
    first = stored(database, complaint)
    classify(client, owner_in.headers, complaint, category, urgency)
    second = stored(database, complaint)
    assert (second.manual_category, second.manual_urgency) == (category, urgency)
    assert second.classified_by_id == owner.id
    assert second.classified_at > first.classified_at


def test_submitting_the_visible_ai_values_stores_no_manual_classification(
    client, database, owner_in, ai_complaint
):
    response = classify(client, owner_in.headers, ai_complaint, "Listrik", "high")
    assert response.status_code == 200, response.text
    assert_nothing_saved(database, ai_complaint)
    assert response.json()["classification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
        "classifiedByName": None,
        "originalAiClassification": None,
    }


@pytest.mark.parametrize(("category", "urgency"), [("Listrik", "low"), ("Air", "high")])
def test_changing_one_value_of_a_visible_ai_result_stores_a_manual_classification(
    client, database, manager, manager_in, ai_complaint, category, urgency
):
    body = classify(client, manager_in.headers, ai_complaint, category, urgency).json()
    row = stored(database, ai_complaint)
    assert (row.manual_category, row.manual_urgency) == (category, urgency)
    assert row.classified_by_id == manager.id
    assert body["classification"]["classifiedByName"] == "Mira Manager"
    assert body["classification"]["suggestedAction"] is None


def test_submitting_the_values_of_a_withheld_ai_result_stores_a_manual_one(
    client, database, owner, owner_in, ai_complaint, expire_subscription
):
    expire_subscription(owner)
    body = classify(client, owner_in.headers, ai_complaint, "Listrik", "high").json()
    row = stored(database, ai_complaint)
    assert (row.manual_category, row.manual_urgency) == ("Listrik", "high")
    assert row.classified_by_id == owner.id
    assert row.classified_at is not None
    assert body["classification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": None,
        "classifiedByName": "Rina Owner",
        "originalAiClassification": None,
    }
    assert body["classificationWithheld"] is False


# Subscription


def test_classifying_needs_no_subscription_on_the_free_plan(
    client, database, other_world, make_complaint, sign_in
):
    other_owner, _, other_room, other_tenant = other_world
    complaint = make_complaint(
        other_tenant, other_room, classification_state="notClassified"
    )
    body = classify(
        client, sign_in(other_owner).headers, complaint, "Air", "low"
    ).json()
    assert body["classification"]["category"] == "Air"
    assert body["classification"]["classifiedByName"] == "Other Owner"
    assert body["classificationWithheld"] is False


def test_classifying_works_after_the_subscription_expired(
    client, database, owner, owner_in, complaint, expire_subscription
):
    expire_subscription(owner)
    response = classify(client, owner_in.headers, complaint, "Air", "low")
    assert response.status_code == 200, response.text
    assert response.json()["classification"]["category"] == "Air"


def test_a_manual_classification_is_never_withheld(
    client, database, owner, owner_in, tenant_in, ai_complaint, expire_subscription
):
    expire_subscription(owner)
    classify(client, owner_in.headers, ai_complaint, "Air", "low")
    for headers in (owner_in.headers, tenant_in.headers):
        body = detail(client, headers, ai_complaint)
        assert body["classification"]["category"] == "Air"
        assert body["classificationWithheld"] is False
        (item,) = listed(client, headers)
        assert item["classification"]["category"] == "Air"
        assert item["classificationWithheld"] is False


def test_the_original_ai_result_is_hidden_without_a_subscription(
    client, database, owner, owner_in, ai_complaint, expire_subscription
):
    expire_subscription(owner)
    body = classify(client, owner_in.headers, ai_complaint, "Air", "low").json()
    assert body["classification"]["originalAiClassification"] is None
    text = client.get(COMPLAINTS, headers=owner_in.headers).text
    assert "Send an electrician today." not in text


def test_the_original_ai_result_returns_when_the_owner_subscribes_again(
    client,
    database,
    owner,
    owner_in,
    ai_complaint,
    expire_subscription,
    subscribe_owner,
):
    expire_subscription(owner)
    classify(client, owner_in.headers, ai_complaint, "Air", "low")
    subscribe_owner(owner, "basic")
    original = detail(client, owner_in.headers, ai_complaint)["classification"][
        "originalAiClassification"
    ]
    assert original == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
    }


# View-only


def test_a_complaint_of_a_view_only_property_can_be_classified(
    client,
    database,
    owner,
    owner_in,
    manager,
    manager_in,
    assign_manager,
    make_property,
    make_room,
    make_verified_tenant,
    make_complaint,
):
    view_only = make_property(owner, name="Kos Baca", view_only=True)
    view_room = make_room(view_only, number="V1")
    view_tenant = make_verified_tenant(view_room)
    assign_manager(manager, view_only)
    first = make_complaint(view_tenant, view_room, classification_state="notClassified")
    second = make_complaint(
        view_tenant, view_room, classification_state="notClassified"
    )
    assert classify(client, owner_in.headers, first).status_code == 200
    assert classify(client, manager_in.headers, second).status_code == 200
    assert stored(database, first).manual_category == "Listrik"
    assert stored(database, second).manual_category == "Listrik"


def test_a_complaint_of_a_view_only_room_can_be_classified(
    client, database, prop, owner_in, make_room, make_verified_tenant, make_complaint
):
    view_room = make_room(prop, number="V2", view_only=True)
    view_tenant = make_verified_tenant(view_room)
    view_complaint = make_complaint(
        view_tenant, view_room, classification_state="notClassified"
    )
    assert classify(client, owner_in.headers, view_complaint).status_code == 200


# Validation


@pytest.mark.parametrize(
    "category",
    ["Astrologi", "listrik", "LISTRIK", " Listrik", "Listrik ", "\tAir", "Plumbing"],
)
def test_a_category_outside_the_list_is_rejected_and_nothing_is_saved(
    client, database, owner_in, complaint, category
):
    response = classify(client, owner_in.headers, complaint, category, "high")
    assert_error(response, 422, "COMPLAINT_CATEGORY_INVALID", "category")
    assert_nothing_saved(database, complaint)


def test_a_rejected_category_leaves_an_existing_manual_classification(
    client, database, owner_in, complaint
):
    classify(client, owner_in.headers, complaint, "Air", "low")
    before = stored(database, complaint)
    response = classify(client, owner_in.headers, complaint, "Astrologi", "high")
    assert_error(response, 422, "COMPLAINT_CATEGORY_INVALID", "category")
    after = stored(database, complaint)
    assert (after.manual_category, after.manual_urgency) == ("Air", "low")
    assert after.classified_at == before.classified_at


def test_an_empty_category_is_a_validation_error_on_the_category_field(
    client, database, owner_in, complaint
):
    response = classify(client, owner_in.headers, complaint, "", "high")
    assert_error(response, 422, "VALIDATION_FAILED", "category")
    assert_nothing_saved(database, complaint)


@pytest.mark.parametrize("category", [None, 5, ["Air"]])
def test_a_non_text_category_is_a_validation_error_on_the_category_field(
    client, database, owner_in, complaint, category
):
    response = classify(client, owner_in.headers, complaint, category, "high")
    assert_error(response, 422, "VALIDATION_FAILED", "category")
    assert_nothing_saved(database, complaint)


@pytest.mark.parametrize(
    "urgency", ["critical", "HIGH", "High", "", None, 1, ["high"], "urgent"]
)
def test_an_invalid_urgency_is_a_validation_error_on_the_urgency_field(
    client, database, owner_in, complaint, urgency
):
    response = classify(client, owner_in.headers, complaint, "Air", urgency)
    assert_error(response, 422, "VALIDATION_FAILED", "urgency")
    assert_nothing_saved(database, complaint)


def test_a_missing_category_is_a_validation_error_on_the_category_field(
    client, database, owner_in, complaint
):
    response = client.put(
        classification_url(complaint.id),
        json={"urgency": "high"},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "category")
    assert_nothing_saved(database, complaint)


def test_a_missing_urgency_is_a_validation_error_on_the_urgency_field(
    client, database, owner_in, complaint
):
    response = client.put(
        classification_url(complaint.id),
        json={"category": "Air"},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "urgency")
    assert_nothing_saved(database, complaint)


def test_a_missing_body_is_a_validation_error(client, database, owner_in, complaint):
    response = client.put(classification_url(complaint.id), headers=owner_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert_nothing_saved(database, complaint)


def test_an_empty_body_is_a_validation_error(client, database, owner_in, complaint):
    response = client.put(
        classification_url(complaint.id), json={}, headers=owner_in.headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_malformed_complaint_id_is_a_validation_error(client, database, owner_in):
    response = client.put(
        f"{COMPLAINTS}/not-a-uuid/classification",
        json={"category": "Air", "urgency": "low"},
        headers=owner_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "complaintId")


# Access to the complaint


def test_an_unknown_complaint_is_not_found(client, database, owner_in, manager_in):
    for headers in (owner_in.headers, manager_in.headers):
        response = client.put(
            classification_url(uuid4()),
            json={"category": "Air", "urgency": "low"},
            headers=headers,
        )
        assert_error(response, 404, "COMPLAINT_NOT_FOUND")


def test_an_owner_cannot_classify_the_complaint_of_another_owner(
    client, database, owner_in, make_complaint, other_world
):
    _, _, other_room, other_tenant = other_world
    other = make_complaint(
        other_tenant, other_room, classification_state="notClassified"
    )
    assert_error(classify(client, owner_in.headers, other), 404, "COMPLAINT_NOT_FOUND")
    assert_nothing_saved(database, other)


def test_an_owner_cannot_classify_a_complaint_of_a_deleted_property(
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
        classify(client, owner_in.headers, gone_complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert_nothing_saved(database, gone_complaint)


def test_a_manager_cannot_classify_a_complaint_of_an_unassigned_property(
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
    assert_error(
        classify(client, manager_in.headers, other), 404, "COMPLAINT_NOT_FOUND"
    )
    assert_nothing_saved(database, other)


def test_an_unassigned_manager_cannot_classify_a_complaint(
    client, database, make_user, sign_in, complaint
):
    stranger = sign_in(make_user(name="Stranger", role=role("manager")))
    assert_error(
        classify(client, stranger.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert_nothing_saved(database, complaint)


def test_a_manager_loses_the_right_to_classify_when_unassigned(
    client, database, manager, manager_in, prop, complaint
):
    unassign(database, manager, prop)
    assert_error(
        classify(client, manager_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )
    assert_nothing_saved(database, complaint)


def test_a_manager_may_classify_complaints_of_properties_from_several_owners(
    client, database, manager, manager_in, other_world, assign_manager, make_complaint
):
    _, other_prop, other_room, other_tenant = other_world
    assign_manager(manager, other_prop)
    other = make_complaint(
        other_tenant, other_room, classification_state="notClassified"
    )
    assert classify(client, manager_in.headers, other).status_code == 200
    assert stored(database, other).classified_by_id == manager.id


# What every reader sees afterwards


def test_management_reads_the_manual_classification_in_the_detail_and_the_list(
    client, database, owner_in, manager_in, complaint
):
    classify(client, manager_in.headers, complaint, "Air", "medium")
    expected = {
        "category": "Air",
        "urgency": "medium",
        "suggestedAction": None,
        "classifiedByName": "Mira Manager",
        "originalAiClassification": None,
    }
    for headers in (owner_in.headers, manager_in.headers):
        body = detail(client, headers, complaint)
        assert body["classification"] == expected
        assert body["classificationState"] is None
        assert body["classificationWithheld"] is False
        (item,) = listed(client, headers)
        assert item["classification"] == expected
        assert item["classificationState"] is None
        assert item["classificationWithheld"] is False


def test_the_tenant_sees_the_manual_category_urgency_and_classifier(
    client, database, manager_in, tenant_in, complaint
):
    classify(client, manager_in.headers, complaint, "Air", "medium")
    body = detail(client, tenant_in.headers, complaint)
    assert body["classification"]["category"] == "Air"
    assert body["classification"]["urgency"] == "medium"
    assert body["classification"]["classifiedByName"] == "Mira Manager"
    assert body["classificationState"] is None
    assert body["classificationWithheld"] is False
    (item,) = listed(client, tenant_in.headers)
    assert item["classification"]["category"] == "Air"
    assert item["classification"]["urgency"] == "medium"
    assert item["classification"]["classifiedByName"] == "Mira Manager"


def test_the_manual_classification_shows_in_the_response_of_a_status_change(
    client, database, owner_in, complaint
):
    classify(client, owner_in.headers, complaint, "Air", "low")
    response = client.post(
        f"{COMPLAINTS}/{complaint.id}/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["classification"]["category"] == "Air"
    assert response.json()["classification"]["classifiedByName"] == "Rina Owner"


# List order for management


def test_a_manual_urgency_moves_an_ai_low_complaint_to_the_top(
    client, database, owner_in, tenant, room, make_complaint
):
    medium = make_complaint(tenant, room, ai=AI_MEDIUM, created_at=ago(5))
    high = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(10))
    low = make_complaint(tenant, room, ai=AI_LOW, created_at=ago(60))
    assert ids(listed(client, owner_in.headers)) == [
        str(high.id),
        str(medium.id),
        str(low.id),
    ]
    classify(client, owner_in.headers, low, "Perabot", "high")
    assert ids(listed(client, owner_in.headers)) == [
        str(high.id),
        str(low.id),
        str(medium.id),
    ]


def test_a_manual_urgency_can_demote_an_ai_high_complaint(
    client, database, owner_in, tenant, room, make_complaint
):
    medium = make_complaint(tenant, room, ai=AI_MEDIUM, created_at=ago(5))
    high = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(10))
    classify(client, owner_in.headers, high, "Listrik", "low")
    assert ids(listed(client, owner_in.headers)) == [str(medium.id), str(high.id)]


def test_a_previously_unclassified_complaint_reclassified_high_leads_the_list(
    client, database, owner_in, manager_in, tenant, room, make_complaint
):
    medium_new = make_complaint(tenant, room, ai=AI_MEDIUM, created_at=ago(1))
    medium_old = make_complaint(tenant, room, ai=AI_MEDIUM, created_at=ago(50))
    unclassified = make_complaint(
        tenant, room, classification_state="awaitingClassification", created_at=ago(90)
    )
    classify(client, manager_in.headers, unclassified, "Air", "high")
    for headers in (owner_in.headers, manager_in.headers):
        assert ids(listed(client, headers)) == [
            str(unclassified.id),
            str(medium_new.id),
            str(medium_old.id),
        ]


def test_complaints_without_a_visible_classification_stay_last(
    client, database, owner_in, tenant, room, make_complaint
):
    classified = make_complaint(
        tenant, room, classification_state="notClassified", created_at=ago(90)
    )
    awaiting = make_complaint(
        tenant, room, classification_state="awaitingClassification", created_at=ago(1)
    )
    low = make_complaint(tenant, room, ai=AI_LOW, created_at=ago(30))
    classify(client, owner_in.headers, classified, "Air", "low")
    assert ids(listed(client, owner_in.headers)) == [
        str(low.id),
        str(classified.id),
        str(awaiting.id),
    ]


def test_equal_manual_and_ai_urgencies_are_ordered_newest_first(
    client, database, owner_in, tenant, room, make_complaint
):
    ai_high = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(30))
    manual_high = make_complaint(
        tenant, room, classification_state="notClassified", created_at=ago(5)
    )
    classify(client, owner_in.headers, manual_high, "Air", "high")
    assert ids(listed(client, owner_in.headers)) == [
        str(manual_high.id),
        str(ai_high.id),
    ]


def test_the_tenant_list_stays_newest_first_after_a_manual_classification(
    client, database, owner_in, tenant_in, tenant, room, make_complaint
):
    newer = make_complaint(tenant, room, ai=AI_HIGH, created_at=ago(5))
    older = make_complaint(
        tenant, room, classification_state="notClassified", created_at=ago(30)
    )
    classify(client, owner_in.headers, older, "Air", "high")
    assert ids(listed(client, tenant_in.headers)) == [str(newer.id), str(older.id)]


# An AI result arriving after a manual classification


def run_late_ai(complaint, fake) -> None:
    from app.services.complaints import classify_complaint

    classify_complaint(complaint.id, complaint.description, fake)


def test_a_late_ai_result_never_overwrites_the_manual_values(
    client, database, manager, manager_in, make_complaint, tenant, room, fake_classifier
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, manager_in.headers, complaint, "Air", "low")
    first = stored(database, complaint)
    run_late_ai(complaint, fake_classifier)
    row = stored(database, complaint)
    assert (row.manual_category, row.manual_urgency) == ("Air", "low")
    assert row.classified_by_id == manager.id
    assert row.classified_at == first.classified_at


def test_a_late_ai_result_is_kept_as_the_original(
    client, database, manager_in, make_complaint, tenant, room, fake_classifier
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, manager_in.headers, complaint, "Air", "low")
    run_late_ai(complaint, fake_classifier)
    row = stored(database, complaint)
    assert row.ai_category == "Listrik"
    assert row.ai_urgency == "high"
    assert row.ai_suggested_action == "Send an electrician today."
    body = detail(client, manager_in.headers, complaint)
    assert body["classification"] == {
        "category": "Air",
        "urgency": "low",
        "suggestedAction": None,
        "classifiedByName": "Mira Manager",
        "originalAiClassification": {
            "category": "Listrik",
            "urgency": "high",
            "suggestedAction": "Send an electrician today.",
        },
    }
    assert body["classificationState"] is None
    assert body["classificationWithheld"] is False


def test_a_late_ai_result_stays_hidden_without_a_subscription(
    client,
    database,
    owner,
    owner_in,
    make_complaint,
    tenant,
    room,
    fake_classifier,
    expire_subscription,
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, owner_in.headers, complaint, "Air", "low")
    run_late_ai(complaint, fake_classifier)
    expire_subscription(owner)
    body = detail(client, owner_in.headers, complaint)
    assert body["classification"]["category"] == "Air"
    assert body["classification"]["originalAiClassification"] is None
    assert body["classificationWithheld"] is False


def test_a_late_ai_result_leaves_the_manual_classification_in_the_list(
    client, database, owner_in, make_complaint, tenant, room, fake_classifier
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, owner_in.headers, complaint, "Air", "low")
    run_late_ai(complaint, fake_classifier)
    (item,) = listed(client, owner_in.headers)
    assert item["classification"]["category"] == "Air"
    assert item["classification"]["urgency"] == "low"
    assert item["classificationState"] is None


@pytest.mark.parametrize("error", [RuntimeError("boom"), ValueError("bad")])
def test_a_failing_ai_attempt_keeps_the_manual_classification_shown(
    client,
    database,
    owner_in,
    tenant_in,
    make_complaint,
    tenant,
    room,
    fake_classifier,
    error,
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, owner_in.headers, complaint, "Air", "low")
    fake_classifier.error = error
    run_late_ai(complaint, fake_classifier)
    for headers in (owner_in.headers, tenant_in.headers):
        body = detail(client, headers, complaint)
        assert body["classification"]["category"] == "Air"
        assert body["classification"]["urgency"] == "low"
        assert body["classificationState"] is None
        assert body["classificationWithheld"] is False
    row = stored(database, complaint)
    assert (row.manual_category, row.manual_urgency) == ("Air", "low")
    assert row.ai_category is None


def test_an_unavailable_ai_attempt_keeps_the_manual_classification_shown(
    client, database, owner_in, make_complaint, tenant, room, fake_classifier
):
    from app.ai.classifier import ClassificationUnavailable

    complaint = make_complaint(tenant, room, classification_state="classifying")
    classify(client, owner_in.headers, complaint, "Air", "low")
    fake_classifier.error = ClassificationUnavailable("down")
    run_late_ai(complaint, fake_classifier)
    body = detail(client, owner_in.headers, complaint)
    assert body["classification"]["category"] == "Air"
    assert body["classificationState"] is None
