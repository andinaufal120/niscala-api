"""Classifying a complaint in the background after it was saved."""

import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
DESCRIPTION = "The air conditioner does not cool."
CATEGORIES = (
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
)


def stored_complaint(database, complaint_id):
    from uuid import UUID

    from app.models import Complaint

    with Session(database, expire_on_commit=False) as db:
        return db.get(Complaint, UUID(str(complaint_id)))


def stored_changes(database) -> list:
    from app.models import ComplaintStatusChange

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(ComplaintStatusChange)))


def result(category="Air", urgency="medium", action="Check the pipes."):
    from app.schemas.complaints import AiComplaintClassification

    return AiComplaintClassification(
        category=category, urgency=urgency, suggested_action=action
    )


@pytest.fixture
def owner(make_user, subscribe_owner):
    user = make_user(name="Rina Owner")
    subscribe_owner(user, "basic")
    return user


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati")


@pytest.fixture
def room(prop, make_room):
    return make_room(prop, number="A1")


@pytest.fixture
def tenant(room, make_verified_tenant):
    return make_verified_tenant(room)


@pytest.fixture
def headers(tenant, sign_in):
    return sign_in(tenant.user).headers


def submit(client, headers, description: str = DESCRIPTION):
    return client.post(COMPLAINTS, json={"description": description}, headers=headers)


def assert_awaiting(client, database, headers, response):
    assert response.status_code == 201, response.text
    row = stored_complaint(database, response.json()["id"])
    assert row.classification_state == "awaitingClassification"
    assert row.ai_category is None
    assert row.ai_urgency is None
    assert row.ai_suggested_action is None
    assert row.status == "new"
    detail = client.get(f"{COMPLAINTS}/{row.id}", headers=headers).json()
    assert detail["classificationState"] == "awaitingClassification"
    assert detail["classification"] is None
    assert detail["classificationWithheld"] is False
    assert detail["status"] == "new"
    assert [c["status"] for c in detail["statusChanges"]] == ["new"]


# A valid AI result


def test_a_valid_result_is_stored_on_the_complaint(
    client, database, headers, fake_classifier
):
    fake_classifier.result = result("Listrik", "high", "Send an electrician today.")
    response = submit(client, headers)
    assert response.status_code == 201, response.text
    row = stored_complaint(database, response.json()["id"])
    assert row.ai_category == "Listrik"
    assert row.ai_urgency == "high"
    assert row.ai_suggested_action == "Send an electrician today."
    assert row.classification_state is None


def test_a_valid_result_is_shown_on_the_detail(
    client, database, headers, fake_classifier
):
    fake_classifier.result = result("Listrik", "high", "Send an electrician today.")
    created = submit(client, headers).json()
    detail = client.get(f"{COMPLAINTS}/{created['id']}", headers=headers).json()
    assert detail["classification"] == {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
        "classifiedByName": None,
        "originalAiClassification": None,
    }
    assert detail["classificationState"] is None
    assert detail["classificationWithheld"] is False


def test_a_classified_complaint_keeps_status_and_history(
    client, database, headers, fake_classifier
):
    created = submit(client, headers).json()
    detail = client.get(f"{COMPLAINTS}/{created['id']}", headers=headers).json()
    assert detail["status"] == "new"
    assert [c["status"] for c in detail["statusChanges"]] == ["new"]
    assert len(stored_changes(database)) == 1


@pytest.mark.parametrize("urgency", ["low", "medium", "high"])
def test_every_urgency_is_stored(client, database, headers, fake_classifier, urgency):
    fake_classifier.result = result(urgency=urgency)
    created = submit(client, headers).json()
    assert stored_complaint(database, created["id"]).ai_urgency == urgency


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_of_the_list_is_accepted(
    client, database, headers, fake_classifier, category
):
    fake_classifier.result = result(category=category)
    created = submit(client, headers).json()
    assert stored_complaint(database, created["id"]).ai_category == category


def test_the_classifier_is_called_once_with_the_stored_description(
    client, database, headers, fake_classifier
):
    submit(client, headers, "   Lampu kamar mati total.   ")
    assert fake_classifier.calls == [("Lampu kamar mati total.", CATEGORIES)]


def test_the_classifier_receives_the_categories_in_order(
    client, database, headers, fake_classifier
):
    from app.config import COMPLAINT_CATEGORIES

    submit(client, headers)
    ((_, categories),) = fake_classifier.calls
    assert list(categories) == list(COMPLAINT_CATEGORIES)


def test_each_submission_is_classified_on_its_own(
    client, database, headers, fake_classifier
):
    submit(client, headers, "First problem in the room.")
    submit(client, headers, "Second problem in the room.")
    assert [d for d, _ in fake_classifier.calls] == [
        "First problem in the room.",
        "Second problem in the room.",
    ]


def test_a_stalling_classifier_under_the_timeout_still_classifies(
    client, database, headers, fake_classifier, monkeypatch
):
    from app.services import complaints

    monkeypatch.setattr(complaints, "CLASSIFICATION_TIMEOUT_SECONDS", 2.0)
    fake_classifier.delay = 0.05
    created = submit(client, headers).json()
    row = stored_complaint(database, created["id"])
    assert row.ai_category == "Listrik"
    assert row.classification_state is None


# Failures leave the complaint saved


def test_an_unavailable_classifier_leaves_the_complaint_awaiting(
    client, database, headers, fake_classifier
):
    from app.ai.classifier import ClassificationUnavailable

    fake_classifier.error = ClassificationUnavailable("down")
    assert_awaiting(client, database, headers, submit(client, headers))


def test_an_unexpected_classifier_error_leaves_the_complaint_awaiting(
    client, database, headers, fake_classifier
):
    fake_classifier.error = RuntimeError("boom")
    assert_awaiting(client, database, headers, submit(client, headers))


def test_a_category_outside_the_list_leaves_the_complaint_awaiting(
    client, database, headers, fake_classifier
):
    fake_classifier.result = result(category="Astrologi")
    assert_awaiting(client, database, headers, submit(client, headers))


def test_a_category_differing_only_by_case_is_outside_the_list(
    client, database, headers, fake_classifier
):
    fake_classifier.result = result(category="listrik")
    assert_awaiting(client, database, headers, submit(client, headers))


def test_a_classifier_slower_than_the_timeout_leaves_the_complaint_awaiting(
    client, database, headers, fake_classifier, monkeypatch
):
    from app.services import complaints

    monkeypatch.setattr(complaints, "CLASSIFICATION_TIMEOUT_SECONDS", 0.2)
    fake_classifier.delay = 0.6
    assert_awaiting(client, database, headers, submit(client, headers))


def test_a_result_arriving_after_the_timeout_is_discarded(
    client, database, headers, fake_classifier, monkeypatch
):
    from app.services import complaints

    monkeypatch.setattr(complaints, "CLASSIFICATION_TIMEOUT_SECONDS", 0.2)
    fake_classifier.delay = 0.6
    created = submit(client, headers).json()
    time.sleep(1.2)
    row = stored_complaint(database, created["id"])
    assert row.classification_state == "awaitingClassification"
    assert row.ai_category is None
    assert row.ai_urgency is None
    assert row.ai_suggested_action is None


@pytest.mark.parametrize(
    "error",
    [
        pytest.param("unavailable", id="unavailable"),
        pytest.param("runtime", id="runtime_error"),
    ],
)
def test_a_failing_classifier_never_turns_the_request_into_an_error(
    client, database, headers, fake_classifier, error
):
    from app.ai.classifier import ClassificationUnavailable

    fake_classifier.error = (
        ClassificationUnavailable("down") if error == "unavailable" else RuntimeError()
    )
    response = submit(client, headers)
    assert response.status_code == 201
    assert response.json()["status"] == "new"
    assert stored_complaint(database, response.json()["id"]) is not None


def test_a_failing_classifier_keeps_the_saved_complaint_and_history(
    client, database, headers, fake_classifier, tenant, room
):
    fake_classifier.error = RuntimeError("boom")
    created = submit(client, headers).json()
    row = stored_complaint(database, created["id"])
    assert row.tenant_id == tenant.id
    assert row.room_id == room.id
    assert row.description == DESCRIPTION
    assert len(stored_changes(database)) == 1


def test_the_post_response_is_not_changed_by_a_failing_classifier(
    client, database, headers, fake_classifier
):
    fake_classifier.error = RuntimeError("boom")
    body = submit(client, headers).json()
    assert body["classificationState"] == "classifying"
    assert body["classification"] is None


def test_a_later_submission_works_after_a_failed_one(
    client, database, headers, fake_classifier
):
    fake_classifier.error = RuntimeError("boom")
    first = submit(client, headers).json()
    fake_classifier.error = None
    second = submit(client, headers, "A second problem occurred.").json()
    assert (
        stored_complaint(database, first["id"]).classification_state
        == "awaitingClassification"
    )
    assert stored_complaint(database, second["id"]).classification_state is None
    assert stored_complaint(database, second["id"]).ai_category == "Listrik"


# The default classifier


def test_the_default_classifier_leaves_a_subscribed_owners_complaint_awaiting(
    client, database, headers, app, monkeypatch
):
    from app.ai.classifier import get_complaint_classifier
    from app.config import get_settings

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    assert get_complaint_classifier not in app.dependency_overrides
    assert_awaiting(client, database, headers, submit(client, headers))


# Skipped classification


def test_a_skipped_complaint_keeps_its_not_classified_state(
    client,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
    fake_classifier,
):
    free_owner = make_user(name="Free Owner")
    room = make_room(make_property(free_owner, name="Kos Gratis"), number="Z1")
    tenant = make_verified_tenant(room)
    created = submit(client, sign_in(tenant.user).headers).json()
    row = stored_complaint(database, created["id"])
    assert row.classification_state == "notClassified"
    assert fake_classifier.calls == []


# Reading a stored interim state


def test_a_complaint_still_being_classified_shows_the_interim_state(
    client, database, headers, tenant, room, make_complaint
):
    complaint = make_complaint(tenant, room, classification_state="classifying")
    detail = client.get(f"{COMPLAINTS}/{complaint.id}", headers=headers).json()
    assert detail["classificationState"] == "classifying"
    assert detail["classification"] is None
    assert detail["classificationWithheld"] is False
