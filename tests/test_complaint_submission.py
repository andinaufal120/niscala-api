"""Submitting a complaint and reading the complaint categories."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
CATEGORIES_URL = "/complaint-categories"
DESCRIPTION = "The air conditioner does not cool."
COMPLAINT_FIELDS = {
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
CATEGORY_NAMES = [
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
]


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def stored_complaints(database) -> list:
    from app.models import Complaint

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(Complaint)))


def stored_changes(database) -> list:
    from app.models import ComplaintStatusChange

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(ComplaintStatusChange)))


def submit(client, headers, description: str = DESCRIPTION):
    return client.post(COMPLAINTS, json={"description": description}, headers=headers)


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


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


# Authentication and roles

REQUESTS = [
    pytest.param("post", COMPLAINTS, {"description": DESCRIPTION}, id="create"),
    pytest.param("get", COMPLAINTS, None, id="list"),
    pytest.param("get", f"{COMPLAINTS}/{uuid4()}", None, id="get"),
    pytest.param("get", CATEGORIES_URL, None, id="categories"),
]


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_without_a_token_is_rejected(client, database, method, url, body):
    assert_error(client.request(method, url, json=body), 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_with_a_garbage_token_is_rejected(
    client, database, method, url, body
):
    response = client.request(
        method, url, json=body, headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_from_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, name, method, url, body
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_only_tenants_may_submit_a_complaint(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name)))
    response = submit(client, session.headers)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("name", ["owner", "manager", "admin"])
def test_a_forbidden_account_submits_nothing(
    client, database, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name)))
    submit(client, session.headers)
    assert stored_complaints(database) == []
    assert stored_changes(database) == []


def test_admins_cannot_list_complaints(client, database, make_user, sign_in):
    session = sign_in(make_user(role=role("admin")))
    assert_error(client.get(COMPLAINTS, headers=session.headers), 403, "FORBIDDEN")


def test_admins_cannot_read_a_complaint(
    client, database, make_user, sign_in, tenant, room, make_complaint
):
    complaint = make_complaint(tenant, room)
    session = sign_in(make_user(role=role("admin")))
    response = client.get(f"{COMPLAINTS}/{complaint.id}", headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


# Description validation


@pytest.mark.parametrize(
    "description",
    [
        "",
        "          ",
        "123456789",
        "   123456789   ",
        "\n\tshort\n\t",
    ],
    ids=["empty", "whitespace", "nine", "nine_trimmed", "short_padded"],
)
def test_a_too_short_description_is_rejected_on_its_field(
    client, database, tenant_in, description
):
    response = submit(client, tenant_in.headers, description)
    assert_error(response, 422, "VALIDATION_FAILED", "description")


def test_a_rejected_description_saves_nothing(client, database, tenant_in):
    submit(client, tenant_in.headers, "short")
    assert stored_complaints(database) == []
    assert stored_changes(database) == []


@pytest.mark.parametrize(
    "description",
    [
        "1234567890",
        "   1234567890   ",
        "a" * 5000,
        "Pintu kamar rusak.\nEngsel lepas.",
    ],
    ids=["exactly_ten", "ten_trimmed", "five_thousand", "multiline"],
)
def test_a_description_of_enough_characters_is_accepted(
    client, database, tenant_in, description
):
    response = submit(client, tenant_in.headers, description)
    assert response.status_code == 201, response.text


def test_the_description_is_stored_and_returned_trimmed(client, database, tenant_in):
    response = submit(client, tenant_in.headers, "   Lampu mati total.   \n")
    assert response.status_code == 201, response.text
    assert response.json()["description"] == "Lampu mati total."
    (row,) = stored_complaints(database)
    assert row.description == "Lampu mati total."


def test_a_missing_description_is_rejected_on_its_field(client, database, tenant_in):
    response = client.post(COMPLAINTS, json={}, headers=tenant_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "description")


# Lease requirement


def test_a_tenant_whose_lease_ended_cannot_submit(
    client, database, room, make_verified_tenant, sign_in
):
    stored = make_verified_tenant(room, lease_ended=True)
    response = submit(client, sign_in(stored.user).headers)
    assert_error(response, 403, "NO_ACTIVE_LEASE")


def test_a_tenant_without_any_lease_cannot_submit(client, database, make_user, sign_in):
    session = sign_in(make_user(role=role("tenant")))
    assert_error(submit(client, session.headers), 403, "NO_ACTIVE_LEASE")


def test_a_refused_submission_saves_nothing(
    client, database, room, make_verified_tenant, sign_in, subscribe_owner, owner
):
    subscribe_owner(owner)
    stored = make_verified_tenant(room, lease_ended=True)
    submit(client, sign_in(stored.user).headers)
    assert stored_complaints(database) == []
    assert stored_changes(database) == []


def test_a_refused_submission_does_not_call_the_classifier(
    client,
    database,
    room,
    make_verified_tenant,
    sign_in,
    fake_classifier,
    subscribe_owner,
    owner,
):
    subscribe_owner(owner)
    stored = make_verified_tenant(room, lease_ended=True)
    submit(client, sign_in(stored.user).headers)
    assert fake_classifier.calls == []


# Success


def test_submitting_answers_with_the_saved_complaint(
    client, database, tenant, tenant_in, prop, room
):
    before = datetime.now(UTC)
    response = submit(client, tenant_in.headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == COMPLAINT_FIELDS
    (row,) = stored_complaints(database)
    assert body["id"] == str(row.id)
    assert body["description"] == DESCRIPTION
    assert body["status"] == "new"
    assert body["property"] == {"id": str(prop.id), "name": "Kos Melati"}
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["tenantName"] == "Budi Tenant"
    assert body["hasPhoto"] is False
    assert body["classification"] is None
    assert body["classificationWithheld"] is False
    created = parse_time(body["createdAt"])
    assert before - timedelta(minutes=1) <= created <= datetime.now(UTC)


def test_the_complaint_is_stored_for_the_tenant_and_the_room_of_the_lease(
    client, database, tenant, tenant_in, room
):
    submit(client, tenant_in.headers)
    (row,) = stored_complaints(database)
    assert row.tenant_id == tenant.id
    assert row.room_id == room.id
    assert row.status == "new"
    assert row.ai_category is None
    assert row.ai_urgency is None
    assert row.ai_suggested_action is None


def test_the_first_status_change_is_new_without_a_note(client, database, tenant_in):
    before = datetime.now(UTC)
    response = submit(client, tenant_in.headers)
    (change,) = response.json()["statusChanges"]
    assert change["status"] == "new"
    assert change["handlingNote"] is None
    changed = parse_time(change["changedAt"])
    assert before - timedelta(minutes=1) <= changed <= datetime.now(UTC)


def test_one_status_change_row_is_stored(client, database, tenant_in):
    response = submit(client, tenant_in.headers)
    (row,) = stored_changes(database)
    assert str(row.complaint_id) == response.json()["id"]
    assert row.status == "new"
    assert row.handling_note is None


def test_a_tenant_may_submit_several_complaints(client, database, tenant_in):
    first = submit(client, tenant_in.headers).json()
    second = submit(client, tenant_in.headers, "Another problem here.").json()
    assert first["id"] != second["id"]
    assert len(stored_complaints(database)) == 2
    assert len(stored_changes(database)) == 2


def test_a_submitted_complaint_can_be_read_back(client, database, tenant_in):
    created = submit(client, tenant_in.headers).json()
    response = client.get(f"{COMPLAINTS}/{created['id']}", headers=tenant_in.headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["description"] == DESCRIPTION


def test_the_complaint_belongs_to_the_room_of_the_active_lease_only(
    client, database, prop, make_room, make_verified_tenant, sign_in
):
    first_room = make_room(prop, number="B1")
    old = make_verified_tenant(first_room, lease_ended=True)
    second_room = make_room(prop, number="B2")
    current = make_verified_tenant(second_room)
    submit(client, sign_in(current.user).headers)
    (row,) = stored_complaints(database)
    assert row.room_id == second_room.id
    assert row.tenant_id != old.id


# Classification state at save time


def test_an_owner_on_the_free_plan_leaves_the_complaint_not_classified(
    client, database, tenant_in, fake_classifier
):
    response = submit(client, tenant_in.headers)
    assert response.status_code == 201
    assert response.json()["classificationState"] == "notClassified"
    assert response.json()["classification"] is None
    (row,) = stored_complaints(database)
    assert row.classification_state == "notClassified"


def test_the_classifier_is_not_called_for_an_owner_on_the_free_plan(
    client, database, tenant_in, fake_classifier
):
    submit(client, tenant_in.headers)
    assert fake_classifier.calls == []


def test_an_expired_paid_period_counts_as_no_subscription(
    client,
    database,
    tenant_in,
    fake_classifier,
    owner,
    subscribe_owner,
    expire_subscription,
):
    subscribe_owner(owner, "pro")
    expire_subscription(owner)
    response = submit(client, tenant_in.headers)
    assert response.json()["classificationState"] == "notClassified"
    assert fake_classifier.calls == []
    (row,) = stored_complaints(database)
    assert row.classification_state == "notClassified"


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_the_response_of_a_subscribed_owner_shows_the_interim_state(
    client, database, tenant_in, fake_classifier, owner, subscribe_owner, plan
):
    subscribe_owner(owner, plan)
    response = submit(client, tenant_in.headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["classificationState"] == "classifying"
    assert body["classification"] is None
    assert body["classificationWithheld"] is False
    assert body["status"] == "new"


def test_the_subscription_of_another_owner_does_not_enable_classification(
    client, database, tenant_in, fake_classifier, make_user, subscribe_owner
):
    subscribe_owner(make_user(name="Other Owner"), "pro")
    response = submit(client, tenant_in.headers)
    assert response.json()["classificationState"] == "notClassified"
    assert fake_classifier.calls == []


def test_a_manager_without_a_plan_does_not_stop_the_owner_plan_from_applying(
    client,
    database,
    tenant_in,
    fake_classifier,
    owner,
    make_user,
    prop,
    assign_manager,
    subscribe_owner,
):
    manager = make_user(name="Mira Manager", role=role("manager"))
    assign_manager(manager, prop)
    subscribe_owner(owner, "basic")
    response = submit(client, tenant_in.headers)
    assert response.json()["classificationState"] == "classifying"


# Complaint categories


@pytest.mark.parametrize("name", ["tenant", "owner", "manager", "admin"])
def test_every_role_can_read_the_categories(client, database, make_user, sign_in, name):
    session = sign_in(make_user(role=role(name)))
    response = client.get(CATEGORIES_URL, headers=session.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": CATEGORY_NAMES}


def test_the_categories_come_from_the_configured_constant(
    client, database, make_user, sign_in
):
    from app.config import COMPLAINT_CATEGORIES

    session = sign_in(make_user(role=role("owner")))
    response = client.get(CATEGORIES_URL, headers=session.headers)
    assert response.json()["items"] == list(COMPLAINT_CATEGORIES)


def test_the_response_ids_are_uuids(client, database, tenant_in):
    body = submit(client, tenant_in.headers).json()
    UUID(body["id"])
    UUID(body["property"]["id"])
    UUID(body["room"]["id"])
