"""Adding managers, listing and reading them, and renewing their invitation."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from manager_support import (
    INVITATION_FIELDS,
    MANAGER_FIELDS,
    MANAGERS,
    PROPERTIES,
    PROPERTY_FIELDS,
    SUMMARY_FIELDS,
    assert_error,
    assert_error_code,
    assert_just_now,
    assigned_property_ids,
    create_manager,
    fetch_all,
    get_manager,
    invitation_base,
    invitation_rows,
    invitation_url,
    link_for,
    list_managers,
    manager_url,
    manager_users,
    new_body,
    parse_time,
    regenerate,
    role,
    state,
    token_of,
    without,
)
from sqlalchemy.orm import Session


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def melati(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def anggrek(owner, make_property):
    return make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")


@pytest.fixture
def other_owner(make_user):
    return make_user(name="Dewi Owner")


# Authentication and roles

REQUESTS = [
    pytest.param(
        "post",
        MANAGERS,
        {"name": "Budi", "phone": "081234567890", "propertyIds": [str(uuid4())]},
        id="create",
    ),
    pytest.param("get", MANAGERS, None, id="list"),
    pytest.param("get", manager_url(uuid4()), None, id="get"),
    pytest.param(
        "put",
        manager_url(uuid4()),
        {"name": "Budi", "phone": "081234567890", "propertyIds": [str(uuid4())]},
        id="edit",
    ),
    pytest.param("delete", manager_url(uuid4()), None, id="delete"),
    pytest.param("post", invitation_url(uuid4()), None, id="regenerate_invitation"),
]


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_without_a_token_is_rejected(client, database, method, url, body):
    response = client.request(method, url, json=body)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_with_a_garbage_token_is_rejected(
    client, database, method, url, body
):
    response = client.request(
        method, url, json=body, headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_from_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, method, url, body
):
    session = sign_in(make_user(email_verified=False))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["tenant", "manager", "admin"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_every_role_but_the_owner_is_forbidden_everywhere(
    client, database, make_user, sign_in, name, method, url, body
):
    session = sign_in(make_user(role=role(name)))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_forbidden_account_adds_nothing(
    client, database, owner, melati, make_user, sign_in
):
    headers = sign_in(make_user(role=role("manager"))).headers
    before = state(database)
    create_manager(client, headers, melati)
    assert state(database) == before


def test_a_manager_cannot_read_a_manager_record_of_their_owner(
    client, database, owner, melati, make_manager, sign_in
):
    stored = make_manager(owner, [melati])
    headers = sign_in(stored.user).headers
    assert_error(get_manager(client, headers, stored.id), 403, "FORBIDDEN")
    assert_error(list_managers(client, headers), 403, "FORBIDDEN")


def test_a_forbidden_role_is_reported_before_lookups(
    client, database, make_user, sign_in
):
    headers = sign_in(make_user(role=role("tenant"))).headers
    assert_error(get_manager(client, headers, uuid4()), 403, "FORBIDDEN")
    response = list_managers(client, headers, propertyId=str(uuid4()))
    assert_error(response, 403, "FORBIDDEN")


# POST: success


def test_adding_a_manager_answers_with_the_stored_manager(
    client, database, melati, signed_in
):
    response = create_manager(client, signed_in.headers, melati, nickname="Pak Budi")
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == MANAGER_FIELDS
    assert body["name"] == "Budi Santoso"
    assert body["nickname"] == "Pak Budi"
    assert body["phone"] == "081234567890"
    assert body["email"] is None
    assert body["accountStatus"] == "notActivated"


def test_the_manager_id_is_the_record_id_and_not_the_account_id(
    client, database, melati, signed_in
):
    from app.models import Manager

    body = create_manager(client, signed_in.headers, melati).json()
    (record,) = fetch_all(database, Manager)
    (user,) = manager_users(database)
    assert body["id"] == str(record.id)
    assert record.id != user.id
    assert record.user_id == user.id
    assert_error(
        get_manager(client, signed_in.headers, user.id), 404, "MANAGER_NOT_FOUND"
    )


def test_the_account_is_stored_as_a_manager_without_email_or_password(
    client, database, melati, signed_in
):
    create_manager(client, signed_in.headers, melati)
    (user,) = manager_users(database)
    assert user.name == "Budi Santoso"
    assert user.email is None
    assert user.password_hash is None
    assert user.role == role("manager")


def test_the_record_is_stored_not_activated_under_the_owner(
    client, database, owner, melati, signed_in
):
    from app.models import Manager

    before = datetime.now(UTC)
    create_manager(client, signed_in.headers, melati, nickname="Pak Budi")
    (user,) = manager_users(database)
    (record,) = fetch_all(database, Manager)
    assert record.owner_id == owner.id
    assert record.user_id == user.id
    assert record.nickname == "Pak Budi"
    assert record.phone == "081234567890"
    assert record.activated_at is None
    assert record.deleted_at is None
    assert before - timedelta(minutes=1) <= record.created_at <= datetime.now(UTC)


def test_the_assignments_grant_the_account_the_submitted_properties(
    client, database, melati, anggrek, signed_in
):
    create_manager(client, signed_in.headers, melati, anggrek)
    (user,) = manager_users(database)
    assert assigned_property_ids(database, user.id) == {melati.id, anggrek.id}


def test_the_response_lists_the_assigned_properties_ordered_by_name(
    client, database, melati, anggrek, owner, make_property, signed_in
):
    cempaka = make_property(owner, name="Kos Cempaka", address="Jl. Cempaka 1")
    body = create_manager(client, signed_in.headers, melati, cempaka, anggrek).json()
    assert body["properties"] == [
        {"id": str(anggrek.id), "name": "Kos Anggrek", "address": "Jl. Anggrek 7"},
        {"id": str(cempaka.id), "name": "Kos Cempaka", "address": "Jl. Cempaka 1"},
        {"id": str(melati.id), "name": "Kos Melati", "address": "Jl. Melati 5"},
    ]
    for item in body["properties"]:
        assert set(item) == PROPERTY_FIELDS


def test_a_view_only_property_may_be_assigned(
    client, database, owner, make_property, signed_in
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    response = create_manager(client, signed_in.headers, frozen)
    assert response.status_code == 201, response.text
    assert [p["id"] for p in response.json()["properties"]] == [str(frozen.id)]


def test_an_invitation_valid_for_seven_days_is_stored_for_the_record(
    client, database, melati, signed_in
):
    from app.models import Invitation, Manager

    create_manager(client, signed_in.headers, melati)
    (record,) = fetch_all(database, Manager)
    (invitation,) = fetch_all(database, Invitation)
    assert invitation.manager_id == record.id
    assert invitation.tenant_id is None
    assert invitation.expires_at - invitation.created_at == timedelta(days=7)
    assert invitation.used_at is None
    assert invitation.invalidated_at is None


def test_the_response_invitation_is_a_fresh_link(client, database, melati, signed_in):
    from app.models import Invitation

    body = create_manager(client, signed_in.headers, melati).json()
    (stored,) = fetch_all(database, Invitation)
    invitation = body["invitation"]
    assert set(invitation) == INVITATION_FIELDS
    assert invitation["expired"] is False
    assert parse_time(invitation["createdAt"]) == stored.created_at
    assert parse_time(invitation["expiresAt"]) == stored.expires_at
    assert parse_time(invitation["expiresAt"]) - parse_time(
        invitation["createdAt"]
    ) == timedelta(days=7)


def test_the_invitation_link_carries_the_raw_token_that_hashes_to_the_stored_hash(
    client, database, melati, signed_in
):
    from app.models import Invitation

    body = create_manager(client, signed_in.headers, melati).json()
    (stored,) = fetch_all(database, Invitation)
    url = body["invitation"]["url"]
    assert url.startswith(f"{invitation_base()}/invitations/")
    token = token_of(url)
    assert token
    assert hashlib.sha256(token.encode()).hexdigest() == stored.token_hash
    assert token not in stored.token_encrypted


def test_the_invitation_link_uses_the_configured_base_url(
    client, database, melati, signed_in, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setenv("INVITATION_BASE_URL", "https://example.test/")
    get_settings.cache_clear()
    try:
        body = create_manager(client, signed_in.headers, melati).json()
    finally:
        get_settings.cache_clear()
    assert body["invitation"]["url"].startswith("https://example.test/invitations/")
    assert "//invitations" not in body["invitation"]["url"]


def test_the_added_manager_can_be_read_back_unchanged(
    client, database, melati, anggrek, signed_in
):
    created = create_manager(
        client, signed_in.headers, melati, anggrek, nickname="Pak Budi"
    ).json()
    response = get_manager(client, signed_in.headers, created["id"])
    assert response.status_code == 200
    assert response.json() == created


def test_the_added_manager_appears_in_the_list(client, database, melati, signed_in):
    created = create_manager(client, signed_in.headers, melati).json()
    items = list_managers(client, signed_in.headers).json()["items"]
    assert [i["id"] for i in items] == [created["id"]]


def test_the_added_manager_reaches_the_assigned_property(
    client, database, melati, anggrek, signed_in, sign_in
):
    from app.models import UserAccount

    create_manager(client, signed_in.headers, melati)
    (user,) = manager_users(database)
    with Session(database) as db:
        db.get(UserAccount, user.id).email_verified = True
        db.commit()
    headers = sign_in(user).headers
    listed = client.get(PROPERTIES, headers=headers).json()["items"]
    assert [p["id"] for p in listed] == [str(melati.id)]
    assert client.get(f"{PROPERTIES}/{melati.id}", headers=headers).status_code == 200
    other = client.get(f"{PROPERTIES}/{anggrek.id}", headers=headers)
    assert_error(other, 404, "PROPERTY_NOT_FOUND")


def test_a_manager_with_only_the_required_fields_gets_a_null_nickname(
    client, database, melati, signed_in
):
    body = create_manager(client, signed_in.headers, melati).json()
    assert body["nickname"] is None


def test_the_same_phone_and_name_may_be_used_for_two_managers(
    client, database, melati, signed_in
):
    first = create_manager(client, signed_in.headers, melati).json()
    second = create_manager(client, signed_in.headers, melati).json()
    assert first["id"] != second["id"]
    assert len(manager_users(database)) == 2


def test_each_added_manager_has_their_own_account_and_link(
    client, database, melati, signed_in
):
    first = create_manager(client, signed_in.headers, melati).json()
    second = create_manager(client, signed_in.headers, melati).json()
    assert first["invitation"]["url"] != second["invitation"]["url"]
    assert len({u.id for u in manager_users(database)}) == 2


# POST: field rules


def test_the_name_is_trimmed(client, database, melati, signed_in):
    body = create_manager(client, signed_in.headers, melati, name="  Budi \n").json()
    assert body["name"] == "Budi"
    (user,) = manager_users(database)
    assert user.name == "Budi"


@pytest.mark.parametrize("value", ["", " ", " \t\n "])
def test_a_blank_name_is_a_validation_failure(
    client, database, melati, signed_in, value
):
    before = state(database)
    response = create_manager(client, signed_in.headers, melati, name=value)
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert state(database) == before


@pytest.mark.parametrize("change", ["missing", "null"])
def test_an_absent_name_is_a_validation_failure(
    client, database, melati, signed_in, change
):
    body = without(new_body(melati), "name")
    if change == "null":
        body["name"] = None
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "name")


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("  Pak Budi ", "Pak Budi"),
        ("Budi", "Budi"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_the_nickname_is_trimmed_and_blank_means_none(
    client, database, melati, signed_in, submitted, expected
):
    from app.models import Manager

    response = create_manager(client, signed_in.headers, melati, nickname=submitted)
    assert response.status_code == 201, response.text
    assert response.json()["nickname"] == expected
    (record,) = fetch_all(database, Manager)
    assert record.nickname == expected


def test_an_omitted_nickname_is_stored_as_none(client, database, melati, signed_in):
    from app.models import Manager

    create_manager(client, signed_in.headers, melati)
    (record,) = fetch_all(database, Manager)
    assert record.nickname is None


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("08123456789", "08123456789"),
        ("628123456789", "08123456789"),
        ("0812-3456-789", "08123456789"),
        ("0812 3456 789", "08123456789"),
        ("62 812-3456 789", "08123456789"),
        (" 08123456789 ", "08123456789"),
        ("0812345678", "0812345678"),
        ("08" + "1" * 11, "08" + "1" * 11),
        ("628" + "1" * 8, "08" + "1" * 8),
        ("628" + "1" * 11, "08" + "1" * 11),
    ],
)
def test_a_phone_is_normalized_to_digits_starting_with_08(
    client, database, melati, signed_in, submitted, expected
):
    from app.models import Manager

    response = create_manager(client, signed_in.headers, melati, phone=submitted)
    assert response.status_code == 201, response.text
    assert response.json()["phone"] == expected
    (record,) = fetch_all(database, Manager)
    assert record.phone == expected


@pytest.mark.parametrize(
    "submitted",
    [
        "+628123456789",
        "+62 812 3456 789",
        "0812345678a",
        "abcdefghijk",
        "0712345678",
        "8123456789",
        "081234567",
        "08123456789012",
        "08" + "1" * 12,
        "628" + "1" * 7,
        "628" + "1" * 12,
        "0812.3456.789",
        "(0812)3456789",
        "08",
        "628",
        "",
        "   ",
    ],
)
def test_an_invalid_phone_is_a_validation_failure(
    client, database, melati, signed_in, submitted
):
    before = state(database)
    response = create_manager(client, signed_in.headers, melati, phone=submitted)
    assert_error(response, 422, "VALIDATION_FAILED", "phone")
    assert state(database) == before


@pytest.mark.parametrize("change", ["missing", "null"])
def test_an_absent_phone_is_a_validation_failure(
    client, database, melati, signed_in, change
):
    body = without(new_body(melati), "phone")
    if change == "null":
        body["phone"] = None
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "phone")


@pytest.mark.parametrize("change", ["missing", "null", "empty", "string"])
def test_missing_or_empty_property_ids_are_a_validation_failure(
    client, database, melati, signed_in, change
):
    body = new_body(melati)
    if change == "missing":
        body = without(body, "propertyIds")
    else:
        body["propertyIds"] = {"null": None, "empty": [], "string": str(melati.id)}[
            change
        ]
    before = state(database)
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyIds")
    assert state(database) == before


def test_a_property_id_that_is_not_a_uuid_is_a_validation_failure(
    client, database, melati, signed_in
):
    body = new_body(melati)
    body["propertyIds"].append("not-a-uuid")
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyIds.1")


def test_a_duplicate_property_id_is_a_validation_failure(
    client, database, melati, signed_in
):
    before = state(database)
    response = create_manager(client, signed_in.headers, melati, melati)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyIds")
    assert state(database) == before


def test_an_unknown_property_is_not_found_and_nothing_is_saved(
    client, database, signed_in
):
    before = state(database)
    body = {**new_body(), "propertyIds": [str(uuid4())]}
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert state(database) == before


def test_another_owners_property_is_not_found_and_nothing_is_saved(
    client, database, melati, other_owner, make_property, signed_in
):
    theirs = make_property(other_owner, name="Theirs")
    before = state(database)
    response = create_manager(client, signed_in.headers, theirs)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert state(database) == before


def test_a_deleted_property_is_not_found_and_nothing_is_saved(
    client, database, owner, melati, make_property, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    before = state(database)
    response = create_manager(client, signed_in.headers, gone)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.0")
    assert state(database) == before


@pytest.mark.parametrize("kind", ["unknown", "other_owner", "deleted"])
def test_the_not_found_error_names_the_index_of_the_first_bad_property(
    client, database, owner, melati, other_owner, make_property, signed_in, kind
):
    if kind == "unknown":
        bad = str(uuid4())
    elif kind == "other_owner":
        bad = str(make_property(other_owner, name="Theirs").id)
    else:
        bad = str(make_property(owner, name="Gone", deleted=True).id)
    body = {**new_body(melati), "propertyIds": [str(melati.id), bad]}
    response = client.post(MANAGERS, json=body, headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.1")


def test_a_bad_property_among_good_ones_saves_nothing(
    client, database, melati, anggrek, other_owner, make_property, signed_in
):
    theirs = make_property(other_owner, name="Theirs")
    before = state(database)
    response = create_manager(client, signed_in.headers, melati, anggrek, theirs)
    assert_error(response, 404, "PROPERTY_NOT_FOUND", "propertyIds.2")
    assert state(database) == before


# POST: invitation failure and atomicity


def test_the_manager_is_saved_when_the_invitation_cannot_be_created(
    client, database, owner, melati, anggrek, signed_in, monkeypatch
):
    from app.models import Invitation, Manager

    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    monkeypatch.setattr("app.services.invitations.create_invitation", fail)
    response = create_manager(client, signed_in.headers, melati, anggrek)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invitation"] is None
    assert body["accountStatus"] == "notActivated"
    assert len(body["properties"]) == 2
    (user,) = manager_users(database)
    (record,) = fetch_all(database, Manager)
    assert record.user_id == user.id
    assert record.owner_id == owner.id
    assert assigned_property_ids(database, user.id) == {melati.id, anggrek.id}
    assert fetch_all(database, Invitation) == []


def test_a_manager_saved_without_an_invitation_reads_back_without_one(
    client, database, melati, signed_in, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", fail)
        created = create_manager(client, signed_in.headers, melati).json()
    response = get_manager(client, signed_in.headers, created["id"])
    assert response.status_code == 200
    assert response.json() == created


def test_the_link_of_a_manager_saved_without_one_can_be_regenerated(
    client, database, melati, signed_in, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", fail)
        created = create_manager(client, signed_in.headers, melati).json()
    response = regenerate(client, signed_in.headers, created["id"])
    assert response.status_code == 201, response.text
    detail = get_manager(client, signed_in.headers, created["id"]).json()
    assert detail["invitation"]["url"] == response.json()["url"]


def test_any_other_failure_saves_nothing(
    app, database, owner, melati, sign_in, monkeypatch
):
    from sqlalchemy.orm import Session as OrmSession

    from app.models import ManagerAssignment

    headers = sign_in(owner).headers
    original = OrmSession.flush

    def failing_flush(self, *args, **kwargs):
        if any(isinstance(obj, ManagerAssignment) for obj in self.new):
            raise RuntimeError("storage failure")
        return original(self, *args, **kwargs)

    before = state(database)
    monkeypatch.setattr(OrmSession, "flush", failing_flush)
    client = TestClient(app, raise_server_exceptions=False)
    response = create_manager(client, headers, melati)
    monkeypatch.setattr(OrmSession, "flush", original)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert state(database) == before


# GET /managers


def test_an_owner_without_managers_lists_an_empty_array(client, database, signed_in):
    response = list_managers(client, signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_list_shows_managers_as_summaries(
    client, database, owner, melati, anggrek, make_manager, signed_in
):
    stored = make_manager(
        owner,
        [melati, anggrek],
        name="Budi Santoso",
        nickname="Pak Budi",
        phone="08123456789",
    )
    response = list_managers(client, signed_in.headers)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == SUMMARY_FIELDS
    assert item["id"] == str(stored.id)
    assert item["name"] == "Budi Santoso"
    assert item["nickname"] == "Pak Budi"
    assert item["phone"] == "08123456789"
    assert item["email"] is None
    assert item["accountStatus"] == "notActivated"
    assert [p["name"] for p in item["properties"]] == ["Kos Anggrek", "Kos Melati"]
    assert "invitation" not in item


def test_an_activated_manager_is_listed_active_with_the_account_email(
    client, database, owner, melati, make_manager, signed_in
):
    make_manager(owner, [melati], activated=True, email="budi@example.com")
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert item["accountStatus"] == "active"
    assert item["email"] == "budi@example.com"


def test_a_manager_without_a_nickname_lists_a_null_nickname(
    client, database, owner, melati, make_manager, signed_in
):
    make_manager(owner, [melati], nickname=None)
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert item["nickname"] is None


def test_the_list_is_ordered_by_nickname_else_name_ignoring_case(
    client, database, owner, melati, make_manager, signed_in
):
    make_manager(owner, [melati], name="Zaki Zulkarnain")
    make_manager(owner, [melati], name="Andi Wijaya", nickname="yanto")
    make_manager(owner, [melati], name="Citra Dewi")
    make_manager(owner, [melati], name="Xavier Hidayat", nickname="Bambang")
    make_manager(owner, [melati], name="budi hartono")
    items = list_managers(client, signed_in.headers).json()["items"]
    assert [i["name"] for i in items] == [
        "Xavier Hidayat",
        "budi hartono",
        "Citra Dewi",
        "Andi Wijaya",
        "Zaki Zulkarnain",
    ]


def test_managers_with_the_same_sort_key_are_ordered_by_id(
    client, database, owner, melati, make_manager, signed_in
):
    from uuid import UUID

    by_name = [
        make_manager(owner, [melati], name="Sam"),
        make_manager(owner, [melati], name="SAM"),
        make_manager(owner, [melati], name="sam", nickname=None),
    ]
    by_nickname = [
        make_manager(owner, [melati], name="Zed", nickname="Same"),
        make_manager(owner, [melati], name="Yan", nickname="same"),
    ]
    items = list_managers(client, signed_in.headers).json()["items"]
    expected = sorted(s.id for s in by_name) + sorted(s.id for s in by_nickname)
    assert [UUID(i["id"]) for i in items] == expected


def test_the_list_leaves_out_deleted_managers(
    client, database, owner, melati, make_manager, signed_in
):
    kept = make_manager(owner, [melati], name="Kept")
    make_manager(owner, [melati], name="Gone", deleted=True)
    items = list_managers(client, signed_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(kept.id)]


def test_the_list_never_shows_the_managers_of_another_owner(
    client, database, owner, melati, other_owner, make_property, make_manager, signed_in
):
    mine = make_manager(owner, [melati], name="Mine")
    theirs = make_property(other_owner, name="Theirs")
    make_manager(other_owner, [theirs], name="Theirs")
    items = list_managers(client, signed_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(mine.id)]


def test_the_list_shows_only_the_properties_of_this_owner(
    client, database, owner, melati, other_owner, make_property, make_manager, signed_in
):
    stored = make_manager(owner, [melati], name="Shared", activated=True)
    elsewhere = make_property(other_owner, name="Theirs")
    make_manager(other_owner, [elsewhere], user=stored.user)
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert [p["id"] for p in item["properties"]] == [str(melati.id)]


def test_the_list_leaves_out_deleted_properties(
    client, database, owner, melati, make_property, make_manager, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    make_manager(owner, [melati, gone])
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert [p["id"] for p in item["properties"]] == [str(melati.id)]


def test_a_manager_whose_properties_were_all_deleted_is_still_listed(
    client, database, owner, make_property, make_manager, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_manager(owner, [gone])
    (item,) = list_managers(client, signed_in.headers).json()["items"]
    assert item["id"] == str(stored.id)
    assert item["properties"] == []


def test_the_list_can_be_limited_to_one_property(
    client, database, owner, melati, anggrek, make_manager, signed_in
):
    both = make_manager(owner, [melati, anggrek], name="Both")
    only_melati = make_manager(owner, [melati], name="Only Melati")
    only_anggrek = make_manager(owner, [anggrek], name="Only Anggrek")
    for prop, expected in (
        (melati, {both.id, only_melati.id}),
        (anggrek, {both.id, only_anggrek.id}),
    ):
        response = list_managers(client, signed_in.headers, propertyId=str(prop.id))
        assert response.status_code == 200, response.text
        assert {i["id"] for i in response.json()["items"]} == {str(i) for i in expected}


def test_a_property_without_managers_lists_an_empty_array(
    client, database, owner, melati, anggrek, make_manager, signed_in
):
    make_manager(owner, [melati])
    response = list_managers(client, signed_in.headers, propertyId=str(anggrek.id))
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_filtered_list_keeps_the_order_and_leaves_out_deleted_managers(
    client, database, owner, melati, make_manager, signed_in
):
    make_manager(owner, [melati], name="Zed")
    make_manager(owner, [melati], name="Abe")
    make_manager(owner, [melati], name="Gone", deleted=True)
    response = list_managers(client, signed_in.headers, propertyId=str(melati.id))
    assert [i["name"] for i in response.json()["items"]] == ["Abe", "Zed"]


def test_a_view_only_property_may_be_used_as_the_filter(
    client, database, owner, make_property, make_manager, signed_in
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    stored = make_manager(owner, [frozen])
    response = list_managers(client, signed_in.headers, propertyId=str(frozen.id))
    assert [i["id"] for i in response.json()["items"]] == [str(stored.id)]


def test_filtering_by_an_unknown_property_is_not_found(client, database, signed_in):
    response = list_managers(client, signed_in.headers, propertyId=str(uuid4()))
    assert_error_code(response, 404, "PROPERTY_NOT_FOUND")


def test_filtering_by_another_owners_property_is_not_found(
    client, database, other_owner, make_property, signed_in
):
    theirs = make_property(other_owner, name="Theirs")
    response = list_managers(client, signed_in.headers, propertyId=str(theirs.id))
    assert_error_code(response, 404, "PROPERTY_NOT_FOUND")


def test_filtering_by_a_deleted_property_is_not_found(
    client, database, owner, make_property, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = list_managers(client, signed_in.headers, propertyId=str(gone.id))
    assert_error_code(response, 404, "PROPERTY_NOT_FOUND")


def test_filtering_by_a_malformed_property_id_is_a_validation_failure(
    client, database, signed_in
):
    response = list_managers(client, signed_in.headers, propertyId="not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


# GET /managers/{managerId}


def test_an_owner_reads_a_manager_with_the_unused_invitation(
    client, database, owner, melati, anggrek, make_manager, signed_in
):
    stored = make_manager(
        owner, [melati, anggrek], name="Budi", nickname="Pak Budi", phone="08123456789"
    )
    response = get_manager(client, signed_in.headers, stored.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == MANAGER_FIELDS
    assert body["id"] == str(stored.id)
    assert body["name"] == "Budi"
    assert body["nickname"] == "Pak Budi"
    assert body["phone"] == "08123456789"
    assert body["email"] is None
    assert body["accountStatus"] == "notActivated"
    assert [p["name"] for p in body["properties"]] == ["Kos Anggrek", "Kos Melati"]
    invitation = body["invitation"]
    assert set(invitation) == INVITATION_FIELDS
    assert invitation["url"] == link_for(stored.token)
    assert invitation["expired"] is False
    assert parse_time(invitation["createdAt"]) == stored.invitation.created_at
    assert parse_time(invitation["expiresAt"]) == stored.invitation.expires_at


def test_an_expired_invitation_has_no_link(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], expired=True)
    invitation = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] is None
    assert invitation["expired"] is True
    assert parse_time(invitation["expiresAt"]) < datetime.now(UTC)
    assert parse_time(invitation["createdAt"]) == stored.invitation.created_at


def test_a_used_invitation_has_no_link_and_is_not_expired(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], used=True)
    invitation = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] is None
    assert invitation["expired"] is False


def test_a_replaced_invitation_is_not_shown_but_the_new_one_is(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], invalidated=True)
    renewed = regenerate(client, signed_in.headers, stored.id).json()
    invitation = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation["url"] == renewed["url"]
    assert invitation["url"] != link_for(stored.token)


def test_the_invitation_of_an_unused_link_is_not_expired_before_its_expiry(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    invitation = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert parse_time(invitation["expiresAt"]) > datetime.now(UTC) + timedelta(days=6)
    assert invitation["expired"] is False


def test_an_active_manager_has_no_invitation(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(
        owner, [melati], activated=True, email="budi@example.com", used=True
    )
    body = get_manager(client, signed_in.headers, stored.id).json()
    assert body["accountStatus"] == "active"
    assert body["email"] == "budi@example.com"
    assert body["invitation"] is None


def test_a_manager_shows_only_the_properties_of_this_owner(
    client, database, owner, melati, other_owner, make_property, make_manager, signed_in
):
    stored = make_manager(owner, [melati], activated=True)
    elsewhere = make_property(other_owner, name="Theirs")
    make_manager(other_owner, [elsewhere], user=stored.user)
    body = get_manager(client, signed_in.headers, stored.id).json()
    assert [p["id"] for p in body["properties"]] == [str(melati.id)]


def test_a_manager_hides_deleted_properties(
    client, database, owner, melati, make_property, make_manager, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_manager(owner, [melati, gone])
    body = get_manager(client, signed_in.headers, stored.id).json()
    assert [p["id"] for p in body["properties"]] == [str(melati.id)]


def test_a_manager_without_live_properties_reads_an_empty_list(
    client, database, owner, make_property, make_manager, signed_in
):
    gone = make_property(owner, name="Gone", deleted=True)
    stored = make_manager(owner, [gone])
    body = get_manager(client, signed_in.headers, stored.id).json()
    assert body["properties"] == []


def test_an_unknown_manager_is_not_found(client, database, signed_in):
    response = get_manager(client, signed_in.headers, uuid4())
    assert_error(response, 404, "MANAGER_NOT_FOUND")


def test_the_id_of_the_manager_account_is_not_a_manager_id(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    response = get_manager(client, signed_in.headers, stored.user_id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")


def test_a_deleted_manager_is_not_found(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], deleted=True)
    response = get_manager(client, signed_in.headers, stored.id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")


def test_the_manager_of_another_owner_is_not_found(
    client, database, other_owner, make_property, make_manager, signed_in
):
    stored = make_manager(other_owner, [make_property(other_owner, name="Theirs")])
    response = get_manager(client, signed_in.headers, stored.id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")


def test_a_malformed_manager_id_is_a_validation_failure(client, database, signed_in):
    response = get_manager(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "managerId")


# POST /managers/{managerId}/invitation


def test_regenerating_answers_with_a_new_invitation(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    before = datetime.now(UTC)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == INVITATION_FIELDS
    assert body["expired"] is False
    assert body["url"].startswith(f"{invitation_base()}/invitations/")
    assert body["url"] != link_for(stored.token)
    created = parse_time(body["createdAt"])
    assert before - timedelta(minutes=1) <= created <= datetime.now(UTC)
    assert parse_time(body["expiresAt"]) - created == timedelta(days=7)


def test_the_new_invitation_is_stored_for_the_record_with_a_hashed_token(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    body = regenerate(client, signed_in.headers, stored.id).json()
    token = token_of(body["url"])
    rows = invitation_rows(database, stored.id)
    assert len(rows) == 2
    newest = rows[-1]
    assert newest.manager_id == stored.id
    assert newest.tenant_id is None
    assert newest.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert newest.used_at is None
    assert newest.invalidated_at is None
    assert newest.expires_at - newest.created_at == timedelta(days=7)


def test_the_old_invitation_is_invalidated(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    regenerate(client, signed_in.headers, stored.id)
    old, _ = invitation_rows(database, stored.id)
    assert old.id == stored.invitation.id
    assert_just_now(old.invalidated_at)
    assert old.used_at is None


def test_the_detail_shows_the_new_link(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    body = regenerate(client, signed_in.headers, stored.id).json()
    invitation = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert invitation == body
    assert invitation["url"] != link_for(stored.token)


def test_an_expired_invitation_is_renewed(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], expired=True)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["expired"] is False
    assert parse_time(body["expiresAt"]) > datetime.now(UTC) + timedelta(days=6)
    detail = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert detail["expired"] is False
    assert detail["url"] == body["url"]
    old, _ = invitation_rows(database, stored.id)
    assert_just_now(old.invalidated_at)


def test_a_manager_without_an_invitation_gets_one(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], invitation=False)
    response = regenerate(client, signed_in.headers, stored.id)
    assert response.status_code == 201, response.text
    (row,) = invitation_rows(database, stored.id)
    assert (
        row.token_hash
        == hashlib.sha256(token_of(response.json()["url"]).encode()).hexdigest()
    )


def test_regenerating_twice_leaves_only_the_latest_invitation_unreplaced(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    first = regenerate(client, signed_in.headers, stored.id).json()
    second = regenerate(client, signed_in.headers, stored.id).json()
    assert first["url"] != second["url"]
    rows = invitation_rows(database, stored.id)
    assert len(rows) == 3
    assert [r.invalidated_at is not None for r in rows] == [True, True, False]
    detail = get_manager(client, signed_in.headers, stored.id).json()["invitation"]
    assert detail["url"] == second["url"]


def test_regenerating_does_not_change_the_manager_data(
    client, database, owner, melati, anggrek, make_manager, signed_in
):
    stored = make_manager(owner, [melati, anggrek], nickname="Pak Budi")
    before = state(database)
    regenerate(client, signed_in.headers, stored.id)
    after = state(database)
    for table in ("users", "managers", "assignments", "sessions"):
        assert after[table] == before[table]
    body = get_manager(client, signed_in.headers, stored.id).json()
    assert body["accountStatus"] == "notActivated"
    assert body["nickname"] == "Pak Budi"


def test_regenerating_leaves_other_managers_invitations_alone(
    client, database, owner, melati, make_manager, signed_in
):
    mine = make_manager(owner, [melati], name="Mine")
    other = make_manager(owner, [melati], name="Other")
    regenerate(client, signed_in.headers, mine.id)
    (row,) = invitation_rows(database, other.id)
    assert row.invalidated_at is None
    detail = get_manager(client, signed_in.headers, other.id).json()["invitation"]
    assert detail["url"] == link_for(other.token)


def test_an_active_manager_cannot_get_a_new_invitation(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(
        owner, [melati], activated=True, email="budi@example.com", used=True
    )
    before = state(database)
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 409, "MANAGER_ALREADY_ACTIVE")
    assert state(database) == before


def test_an_active_manager_without_an_invitation_row_gets_none_created(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(
        owner, [melati], activated=True, email="budi@example.com", invitation=False
    )
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 409, "MANAGER_ALREADY_ACTIVE")
    assert invitation_rows(database, stored.id) == []


def test_an_unknown_manager_is_not_found_on_regenerate(client, database, signed_in):
    response = regenerate(client, signed_in.headers, uuid4())
    assert_error(response, 404, "MANAGER_NOT_FOUND")


def test_the_id_of_the_manager_account_is_not_found_on_regenerate(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati])
    before = state(database)
    response = regenerate(client, signed_in.headers, stored.user_id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == before


def test_a_deleted_manager_is_not_found_on_regenerate(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], deleted=True)
    before = state(database)
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == before


def test_the_manager_of_another_owner_is_not_found_on_regenerate(
    client, database, other_owner, make_property, make_manager, signed_in
):
    stored = make_manager(other_owner, [make_property(other_owner, name="Theirs")])
    before = state(database)
    response = regenerate(client, signed_in.headers, stored.id)
    assert_error(response, 404, "MANAGER_NOT_FOUND")
    assert state(database) == before


def test_a_malformed_manager_id_is_a_validation_failure_on_regenerate(
    client, database, signed_in
):
    response = regenerate(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "managerId")


def test_the_old_link_stays_valid_when_the_new_invitation_cannot_be_created(
    app, database, owner, melati, make_manager, sign_in, monkeypatch
):
    stored = make_manager(owner, [melati])
    headers = sign_in(owner).headers

    def fail(*args, **kwargs):
        raise RuntimeError("no invitation")

    before = state(database)
    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", fail)
        response = regenerate(client, headers, stored.id)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert state(database) == before
    detail = get_manager(client, headers, stored.id).json()["invitation"]
    assert detail["url"] == link_for(stored.token)


def test_the_old_link_stays_valid_when_creation_fails_after_replacing_it(
    app, database, owner, melati, make_manager, sign_in, monkeypatch
):
    from app.services import invitations

    stored = make_manager(owner, [melati])
    headers = sign_in(owner).headers
    create_invitation = invitations.create_invitation

    def create_then_fail(*args, **kwargs):
        create_invitation(*args, **kwargs)
        raise RuntimeError("failure after the new invitation was created")

    before = state(database)
    client = TestClient(app, raise_server_exceptions=False)
    with monkeypatch.context() as patch:
        patch.setattr("app.services.invitations.create_invitation", create_then_fail)
        response = regenerate(client, headers, stored.id)
    assert response.status_code == 500
    assert state(database) == before
