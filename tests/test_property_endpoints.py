"""Adding, listing, reading, editing and deleting properties."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

URL = "/properties"
BANK = {
    "bankName": "BCA",
    "accountNumber": "1234567890",
    "accountHolderName": "Budi Santoso",
}
BODY = {"name": "Kos Melati", "address": "Jl. Melati 5", "bankAccount": BANK}
BODY_WITHOUT_BANK = {"name": "Kos Melati", "address": "Jl. Melati 5"}
DETAIL_FIELDS = {
    "id",
    "name",
    "address",
    "bankAccount",
    "roomCount",
    "occupiedRoomCount",
    "vacantRoomCount",
    "managers",
    "editable",
}
SUMMARY_FIELDS = {
    "id",
    "name",
    "address",
    "roomCount",
    "occupiedRoomCount",
    "managers",
    "editable",
}
WINDOW = timedelta(minutes=5)


def detail_url(property_id) -> str:
    return f"{URL}/{property_id}"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def stored(database, property_id):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        return db.get(Property, UUID(str(property_id)))


def stored_for(database, owner):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(Property)
                .where(Property.owner_id == owner.id)
                .order_by(Property.created_at, Property.id)
            )
        )


def all_stored(database):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(Property)))


def assignments(database, property_id) -> list:
    from app.models import ManagerAssignment

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(ManagerAssignment).where(
                    ManagerAssignment.property_id == UUID(str(property_id))
                )
            )
        )


def set_bank(database, property_id, bank: dict | None) -> None:
    from app.models import Property

    with Session(database) as db:
        row = db.get(Property, UUID(str(property_id)))
        row.bank_name = bank and bank["bankName"]
        row.bank_account_number = bank and bank["accountNumber"]
        row.bank_account_holder_name = bank and bank["accountHolderName"]
        db.commit()


def set_reauthenticated_at(database, session_id, value) -> None:
    from app.models import UserSession

    with Session(database) as db:
        db.get(UserSession, session_id).reauthenticated_at = value
        db.commit()


def reauthenticated_minutes_ago(database, signed_in, minutes: float) -> None:
    set_reauthenticated_at(
        database, signed_in.session_id, datetime.now(UTC) - timedelta(minutes=minutes)
    )


def subscribe(database, owner, plan: str, days: int = 30) -> None:
    from app.schemas.subscriptions import PaidPlanCode
    from app.services.subscriptions import grant_subscription

    with Session(database) as db:
        grant_subscription(db, owner, PaidPlanCode(plan), days)
        db.commit()


def expire_subscription(database, owner) -> None:
    from app.models import Subscription

    with Session(database) as db:
        db.get(Subscription, owner.id).ends_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()


def create(client, headers, **overrides):
    return client.post(URL, json={**BODY, **overrides}, headers=headers)


def update(client, headers, property_id, **overrides):
    return client.put(
        detail_url(property_id), json={**BODY, **overrides}, headers=headers
    )


def update_plain(client, headers, property_id, **overrides):
    """Edit without a bank account, which leaves a property without one unchanged."""
    return client.put(
        detail_url(property_id),
        json={**BODY_WITHOUT_BANK, **overrides},
        headers=headers,
    )


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def manager(make_user):
    return make_user(name="Mira Manager", role=role("manager"))


@pytest.fixture
def manager_in(manager, sign_in):
    return sign_in(manager)


@pytest.fixture
def existing(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


# Authentication and roles


REQUESTS = [
    pytest.param("post", URL, BODY, id="create"),
    pytest.param("get", URL, None, id="list"),
    pytest.param("get", f"{URL}/{uuid4()}", None, id="get"),
    pytest.param("put", f"{URL}/{uuid4()}", BODY, id="update"),
    pytest.param("delete", f"{URL}/{uuid4()}", None, id="delete"),
]
OWNER_ONLY = [REQUESTS[0], REQUESTS[3], REQUESTS[4]]
READS = [REQUESTS[1], REQUESTS[2]]


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


@pytest.mark.parametrize("name", ["tenant", "admin"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_tenants_and_admins_are_forbidden_everywhere(
    client, database, make_user, sign_in, name, method, url, body
):
    session = sign_in(make_user(role=role(name)))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize(("method", "url", "body"), OWNER_ONLY)
def test_managers_are_forbidden_on_write_endpoints(
    client, database, manager_in, method, url, body
):
    response = client.request(method, url, json=body, headers=manager_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_manager_is_forbidden_to_write_even_an_assigned_property(
    client, database, manager, manager_in, existing, assign_manager
):
    assign_manager(manager, existing)
    for response in (
        update(client, manager_in.headers, existing.id, name="Renamed"),
        client.delete(detail_url(existing.id), headers=manager_in.headers),
    ):
        assert_error(response, 403, "FORBIDDEN")
    assert stored(database, existing.id).name == "Kos Melati"
    assert stored(database, existing.id).deleted_at is None


def test_a_manager_is_forbidden_to_create_before_the_body_is_validated(
    client, database, manager_in
):
    response = client.post(URL, json={}, headers=manager_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_manager_creating_a_property_saves_nothing(client, database, manager_in):
    create(client, manager_in.headers)
    assert all_stored(database) == []


# POST /properties


def test_creating_a_property_answers_with_the_stored_property(
    client, database, owner, signed_in
):
    response = create(client, signed_in.headers)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["name"] == "Kos Melati"
    assert body["address"] == "Jl. Melati 5"
    assert body["bankAccount"] == BANK
    assert body["roomCount"] == 0
    assert body["occupiedRoomCount"] == 0
    assert body["vacantRoomCount"] == 0
    assert body["managers"] == []
    assert body["editable"] is True
    (row,) = stored_for(database, owner)
    assert body["id"] == str(row.id)


def test_a_created_property_belongs_to_the_caller_and_is_not_view_only(
    client, database, owner, signed_in
):
    create(client, signed_in.headers)
    (row,) = stored_for(database, owner)
    assert row.owner_id == owner.id
    assert row.view_only is False
    assert row.deleted_at is None
    assert row.name == "Kos Melati"
    assert row.address == "Jl. Melati 5"
    assert row.bank_name == "BCA"
    assert row.bank_account_number == "1234567890"
    assert row.bank_account_holder_name == "Budi Santoso"


@pytest.mark.parametrize("omit", [True, False])
def test_a_property_without_a_bank_account_has_a_null_bank_account(
    client, database, owner, signed_in, omit
):
    body = BODY_WITHOUT_BANK if omit else {**BODY_WITHOUT_BANK, "bankAccount": None}
    response = client.post(URL, json=body, headers=signed_in.headers)
    assert response.status_code == 201
    assert response.json()["bankAccount"] is None
    (row,) = stored_for(database, owner)
    assert row.bank_name is None
    assert row.bank_account_number is None
    assert row.bank_account_holder_name is None


def test_name_and_address_are_trimmed(client, database, owner, signed_in):
    response = create(
        client, signed_in.headers, name="  Kos Melati \n", address="\t Jl. Melati 5  "
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Kos Melati"
    assert response.json()["address"] == "Jl. Melati 5"
    (row,) = stored_for(database, owner)
    assert row.name == "Kos Melati"
    assert row.address == "Jl. Melati 5"


def test_the_created_property_can_be_read_back(client, database, signed_in):
    created = create(client, signed_in.headers).json()
    response = client.get(detail_url(created["id"]), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("field", ["name", "address"])
@pytest.mark.parametrize("value", ["", " ", " \t\n "])
def test_a_blank_name_or_address_is_a_validation_failure(
    client, database, owner, signed_in, field, value
):
    response = create(client, signed_in.headers, **{field: value})
    assert_error(response, 422, "VALIDATION_FAILED", field)
    assert stored_for(database, owner) == []


@pytest.mark.parametrize("field", ["name", "address"])
def test_a_missing_name_or_address_is_a_validation_failure(
    client, database, owner, signed_in, field
):
    body = {k: v for k, v in BODY.items() if k != field}
    response = client.post(URL, json=body, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", field)


@pytest.mark.parametrize("missing", ["bankName", "accountNumber", "accountHolderName"])
def test_a_partial_bank_account_is_a_validation_failure(
    client, database, owner, signed_in, missing
):
    bank = {k: v for k, v in BANK.items() if k != missing}
    response = create(client, signed_in.headers, bankAccount=bank)
    assert_error(response, 422, "VALIDATION_FAILED", f"bankAccount.{missing}")
    assert stored_for(database, owner) == []


def test_a_duplicate_name_is_refused_and_nothing_is_saved(
    client, database, owner, signed_in
):
    subscribe(database, owner, "pro")
    assert create(client, signed_in.headers).status_code == 201
    response = create(client, signed_in.headers, address="Elsewhere")
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")
    assert len(stored_for(database, owner)) == 1


@pytest.mark.parametrize("name", ["kos melati", "KOS MELATI", "  Kos Melati  "])
def test_a_duplicate_name_is_detected_ignoring_case_and_surrounding_spaces(
    client, database, owner, signed_in, make_property, name
):
    subscribe(database, owner, "pro")
    make_property(owner, name="Kos Melati")
    response = create(client, signed_in.headers, name=name)
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")
    assert len(stored_for(database, owner)) == 1


def test_a_view_only_property_still_holds_its_name(
    client, database, owner, signed_in, make_property
):
    subscribe(database, owner, "pro")
    make_property(owner, name="Kos Melati", view_only=True)
    response = create(client, signed_in.headers)
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")


def test_another_owner_may_use_the_same_name(
    client, database, owner, signed_in, make_user, make_property
):
    make_property(make_user(), name="Kos Melati")
    assert create(client, signed_in.headers).status_code == 201


def test_the_name_of_a_deleted_property_can_be_used_again(
    client, database, owner, signed_in, make_property
):
    make_property(owner, name="Kos Melati", deleted=True)
    assert create(client, signed_in.headers).status_code == 201


def test_a_name_freed_through_the_api_can_be_used_again(
    client, database, owner, signed_in
):
    first = create(client, signed_in.headers).json()
    deleted = client.delete(detail_url(first["id"]), headers=signed_in.headers)
    assert deleted.status_code == 204
    response = create(client, signed_in.headers)
    assert response.status_code == 201
    assert response.json()["id"] != first["id"]


# POST /properties: plan limits


def fill(owner, make_property, count: int, **kwargs):
    return [make_property(owner, name=f"Kos {n}", **kwargs) for n in range(count)]


def assert_limit_reached(response) -> None:
    assert_error(response, 403, "PROPERTY_LIMIT_REACHED")


def test_a_free_owner_may_add_the_first_property(client, database, owner, signed_in):
    assert create(client, signed_in.headers).status_code == 201


def test_a_free_owner_is_refused_a_second_property(
    client, database, owner, signed_in, make_property
):
    fill(owner, make_property, 1)
    assert_limit_reached(create(client, signed_in.headers))
    assert len(stored_for(database, owner)) == 1


def test_an_owner_without_a_subscription_row_counts_as_free(
    client, database, owner, signed_in
):
    assert create(client, signed_in.headers, name="One").status_code == 201
    assert_limit_reached(create(client, signed_in.headers, name="Two"))


@pytest.mark.parametrize(("existing_count", "allowed"), [(2, True), (3, False)])
def test_a_basic_owner_may_hold_three_properties(
    client, database, owner, signed_in, make_property, existing_count, allowed
):
    subscribe(database, owner, "basic")
    fill(owner, make_property, existing_count)
    response = create(client, signed_in.headers)
    if allowed:
        assert response.status_code == 201
        assert len(stored_for(database, owner)) == existing_count + 1
    else:
        assert_limit_reached(response)
        assert len(stored_for(database, owner)) == existing_count


def test_a_pro_owner_has_no_limit(client, database, owner, signed_in, make_property):
    subscribe(database, owner, "pro")
    fill(owner, make_property, 12)
    assert create(client, signed_in.headers).status_code == 201
    assert len(stored_for(database, owner)) == 13


def test_an_expired_paid_subscription_counts_as_free(
    client, database, owner, signed_in, make_property
):
    subscribe(database, owner, "pro")
    expire_subscription(database, owner)
    fill(owner, make_property, 1)
    assert_limit_reached(create(client, signed_in.headers))


def test_an_expired_paid_subscription_still_allows_the_first_property(
    client, database, owner, signed_in
):
    subscribe(database, owner, "basic")
    expire_subscription(database, owner)
    assert create(client, signed_in.headers).status_code == 201


def test_view_only_properties_count_towards_the_limit(
    client, database, owner, signed_in, make_property
):
    make_property(owner, name="Old", view_only=True)
    assert_limit_reached(create(client, signed_in.headers))


def test_deleted_properties_do_not_count_towards_the_limit(
    client, database, owner, signed_in, make_property
):
    make_property(owner, name="Gone", deleted=True)
    assert create(client, signed_in.headers).status_code == 201


def test_deleting_a_property_frees_a_place(client, database, owner, signed_in):
    first = create(client, signed_in.headers, name="One").json()
    assert_limit_reached(create(client, signed_in.headers, name="Two"))
    deleted = client.delete(detail_url(first["id"]), headers=signed_in.headers)
    assert deleted.status_code == 204
    assert create(client, signed_in.headers, name="Two").status_code == 201


def test_other_owners_properties_do_not_count_towards_the_limit(
    client, database, owner, signed_in, make_user, make_property
):
    fill(make_user(), make_property, 5)
    assert create(client, signed_in.headers).status_code == 201


def test_another_owners_plan_does_not_raise_the_limit(
    client, database, owner, signed_in, make_user, make_property
):
    subscribe(database, make_user(), "pro")
    fill(owner, make_property, 1)
    assert_limit_reached(create(client, signed_in.headers))


def test_a_taken_name_is_reported_before_the_limit(
    client, database, owner, signed_in, make_property
):
    make_property(owner, name="Kos Melati")
    response = create(client, signed_in.headers)
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")


def test_validation_is_reported_before_the_limit(
    client, database, owner, signed_in, make_property
):
    fill(owner, make_property, 1)
    response = create(client, signed_in.headers, name=" ")
    assert_error(response, 422, "VALIDATION_FAILED", "name")


# GET /properties


def test_an_owner_without_properties_gets_an_empty_list(client, database, signed_in):
    response = client.get(URL, headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_an_owner_lists_their_own_properties_as_summaries(
    client, database, owner, signed_in, existing
):
    response = client.get(URL, headers=signed_in.headers)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == SUMMARY_FIELDS
    assert item == {
        "id": str(existing.id),
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
        "roomCount": 0,
        "occupiedRoomCount": 0,
        "managers": [],
        "editable": True,
    }


def test_the_list_is_ordered_by_name(client, database, owner, signed_in, make_property):
    subscribe(database, owner, "pro")
    for name in ["Kos Cempaka", "Kos Anggrek", "Kos Bakung"]:
        make_property(owner, name=name)
    items = client.get(URL, headers=signed_in.headers).json()["items"]
    assert [i["name"] for i in items] == ["Kos Anggrek", "Kos Bakung", "Kos Cempaka"]


def test_the_list_leaves_out_other_owners_deleted_and_nothing_else(
    client, database, owner, signed_in, make_user, make_property
):
    subscribe(database, owner, "pro")
    mine = make_property(owner, name="Mine")
    view_only = make_property(owner, name="View only", view_only=True)
    make_property(owner, name="Gone", deleted=True)
    make_property(make_user(), name="Theirs")
    items = client.get(URL, headers=signed_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(mine.id), str(view_only.id)]


def test_a_view_only_property_is_listed_as_not_editable(
    client, database, owner, signed_in, make_property
):
    subscribe(database, owner, "pro")
    make_property(owner, name="A", view_only=True)
    make_property(owner, name="B")
    items = client.get(URL, headers=signed_in.headers).json()["items"]
    assert [(i["name"], i["editable"]) for i in items] == [("A", False), ("B", True)]


def test_listed_managers_are_ordered_by_name_then_id(
    client, database, owner, signed_in, existing, make_user, assign_manager
):
    zed = make_user(name="Zed", role=role("manager"))
    adi = make_user(name="Adi", role=role("manager"))
    twins = [make_user(name="Budi", role=role("manager")) for _ in range(2)]
    for person in [zed, adi, *twins]:
        assign_manager(person, existing)
    (item,) = client.get(URL, headers=signed_in.headers).json()["items"]
    twin_ids = sorted(str(t.id) for t in twins)
    assert item["managers"] == [
        {"id": str(adi.id), "name": "Adi"},
        {"id": twin_ids[0], "name": "Budi"},
        {"id": twin_ids[1], "name": "Budi"},
        {"id": str(zed.id), "name": "Zed"},
    ]


def test_listed_managers_belong_to_their_own_property(
    client, database, owner, signed_in, make_property, make_user, assign_manager
):
    subscribe(database, owner, "pro")
    first = make_property(owner, name="First")
    second = make_property(owner, name="Second")
    make_property(owner, name="Third")
    one = make_user(name="One", role=role("manager"))
    two = make_user(name="Two", role=role("manager"))
    assign_manager(one, first)
    assign_manager(two, second)
    assign_manager(one, second)
    items = client.get(URL, headers=signed_in.headers).json()["items"]
    assert [[m["name"] for m in i["managers"]] for i in items] == [
        ["One"],
        ["One", "Two"],
        [],
    ]


def test_a_manager_lists_only_assigned_properties_across_owners(
    client, database, manager, manager_in, make_user, make_property, assign_manager
):
    first = make_property(make_user(), name="B second")
    second = make_property(make_user(), name="A first")
    make_property(make_user(), name="Unassigned")
    gone = make_property(make_user(), name="Gone", deleted=True)
    for row in (first, second, gone):
        assign_manager(manager, row)
    items = client.get(URL, headers=manager_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(second.id), str(first.id)]


def test_a_manager_sees_all_managers_of_an_assigned_property(
    client, database, manager, manager_in, existing, make_user, assign_manager
):
    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(manager, existing)
    assign_manager(colleague, existing)
    (item,) = client.get(URL, headers=manager_in.headers).json()["items"]
    assert item["managers"] == [
        {"id": str(colleague.id), "name": "Colleague"},
        {"id": str(manager.id), "name": "Mira Manager"},
    ]


def test_a_manager_without_assignments_gets_an_empty_list(
    client, database, manager_in, existing
):
    response = client.get(URL, headers=manager_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_managers_of_other_owners_properties_are_not_revealed(
    client,
    database,
    owner,
    signed_in,
    existing,
    make_user,
    make_property,
    assign_manager,
):
    stranger = make_property(make_user(), name="Stranger")
    assign_manager(make_user(name="Hidden", role=role("manager")), stranger)
    (item,) = client.get(URL, headers=signed_in.headers).json()["items"]
    assert item["managers"] == []
    assert "Hidden" not in client.get(URL, headers=signed_in.headers).text


# GET /properties/{propertyId}


def test_an_owner_reads_a_property_with_its_bank_account(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    response = client.get(detail_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(existing.id),
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
        "bankAccount": BANK,
        "roomCount": 0,
        "occupiedRoomCount": 0,
        "vacantRoomCount": 0,
        "managers": [],
        "editable": True,
    }


def test_a_property_without_a_bank_account_reads_null(
    client, database, signed_in, existing
):
    body = client.get(detail_url(existing.id), headers=signed_in.headers).json()
    assert body["bankAccount"] is None


def test_the_detail_lists_managers_by_name_then_id(
    client, database, signed_in, existing, make_user, assign_manager
):
    for name in ["Zed", "Adi"]:
        assign_manager(make_user(name=name, role=role("manager")), existing)
    body = client.get(detail_url(existing.id), headers=signed_in.headers).json()
    assert [m["name"] for m in body["managers"]] == ["Adi", "Zed"]
    assert all(set(m) == {"id", "name"} for m in body["managers"])


def test_a_view_only_property_reads_as_not_editable(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, view_only=True)
    body = client.get(detail_url(row.id), headers=signed_in.headers).json()
    assert body["editable"] is False


def test_a_manager_reads_an_assigned_property(
    client, database, manager, manager_in, existing, assign_manager
):
    assign_manager(manager, existing)
    response = client.get(detail_url(existing.id), headers=manager_in.headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(existing.id)
    assert body["managers"] == [{"id": str(manager.id), "name": "Mira Manager"}]


def test_a_manager_loses_access_as_soon_as_the_assignment_is_removed(
    client, database, manager, manager_in, existing, assign_manager
):
    from app.models import ManagerAssignment

    assign_manager(manager, existing)
    first = client.get(detail_url(existing.id), headers=manager_in.headers)
    assert first.status_code == 200
    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, existing.id)))
        db.commit()
    response = client.get(detail_url(existing.id), headers=manager_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    listing = client.get(URL, headers=manager_in.headers).json()
    assert listing == {"items": []}


def test_an_unassigned_manager_gets_not_found(client, database, manager_in, existing):
    response = client.get(detail_url(existing.id), headers=manager_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_an_unknown_property_is_not_found(client, database, signed_in, method):
    response = client.request(
        method, detail_url(uuid4()), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_another_owners_property_is_not_found_and_untouched(
    client, database, signed_in, make_user, make_property, method
):
    theirs = make_property(make_user(), name="Theirs")
    response = client.request(
        method, detail_url(theirs.id), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    row = stored(database, theirs.id)
    assert row.name == "Theirs"
    assert row.deleted_at is None


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property, method
):
    row = make_property(owner, deleted=True)
    response = client.request(
        method, detail_url(row.id), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_malformed_property_id_is_a_validation_failure(
    client, database, signed_in, method
):
    response = client.request(
        method, detail_url("not-a-uuid"), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


# PUT /properties/{propertyId}


def test_an_owner_replaces_name_and_address(
    client, database, owner, signed_in, existing
):
    response = update_plain(
        client, signed_in.headers, existing.id, name="Kos Mawar", address="Jl. Mawar 1"
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Kos Mawar"
    assert response.json()["address"] == "Jl. Mawar 1"
    row = stored(database, existing.id)
    assert (row.name, row.address) == ("Kos Mawar", "Jl. Mawar 1")


def test_the_edit_answers_with_the_whole_property(
    client, database, owner, signed_in, existing, make_user, assign_manager
):
    set_bank(database, existing.id, BANK)
    helper = make_user(name="Mira", role=role("manager"))
    assign_manager(helper, existing)
    response = update(client, signed_in.headers, existing.id, name="Kos Mawar")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(existing.id),
        "name": "Kos Mawar",
        "address": "Jl. Melati 5",
        "bankAccount": BANK,
        "roomCount": 0,
        "occupiedRoomCount": 0,
        "vacantRoomCount": 0,
        "managers": [{"id": str(helper.id), "name": "Mira"}],
        "editable": True,
    }
    assert client.get(detail_url(existing.id), headers=signed_in.headers).json() == (
        response.json()
    )


def test_the_edit_trims_name_and_address(client, database, signed_in, existing):
    response = update_plain(
        client, signed_in.headers, existing.id, name=" Kos Mawar ", address=" Jl. 1 "
    )
    assert response.status_code == 200
    row = stored(database, existing.id)
    assert (row.name, row.address) == ("Kos Mawar", "Jl. 1")


@pytest.mark.parametrize("field", ["name", "address"])
@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_edit_is_a_validation_failure_and_saves_nothing(
    client, database, signed_in, existing, field, value
):
    response = update(client, signed_in.headers, existing.id, **{field: value})
    assert_error(response, 422, "VALIDATION_FAILED", field)
    assert stored(database, existing.id).name == "Kos Melati"


def test_an_edit_may_keep_the_same_name(client, database, signed_in, existing):
    response = update_plain(
        client, signed_in.headers, existing.id, address="New address"
    )
    assert response.status_code == 200
    assert stored(database, existing.id).address == "New address"


def test_an_edit_may_change_only_the_case_of_the_name(
    client, database, signed_in, existing
):
    response = update_plain(client, signed_in.headers, existing.id, name="KOS MELATI")
    assert response.status_code == 200
    assert stored(database, existing.id).name == "KOS MELATI"


def test_an_edit_may_not_take_the_name_of_another_property(
    client, database, owner, signed_in, existing, make_property
):
    subscribe(database, owner, "pro")
    make_property(owner, name="Kos Mawar")
    response = update_plain(client, signed_in.headers, existing.id, name=" kos MAWAR ")
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")
    assert stored(database, existing.id).name == "Kos Melati"


def test_an_edit_may_take_the_name_of_a_deleted_property(
    client, database, owner, signed_in, existing, make_property
):
    make_property(owner, name="Kos Mawar", deleted=True)
    response = update_plain(client, signed_in.headers, existing.id, name="Kos Mawar")
    assert response.status_code == 200


def test_an_edit_may_take_a_name_used_by_another_owner(
    client, database, signed_in, existing, make_user, make_property
):
    make_property(make_user(), name="Kos Mawar")
    response = update_plain(client, signed_in.headers, existing.id, name="Kos Mawar")
    assert response.status_code == 200


def test_an_edit_does_not_change_other_properties(
    client, database, owner, signed_in, existing, make_property
):
    subscribe(database, owner, "pro")
    other = make_property(owner, name="Other", address="Other address")
    update(client, signed_in.headers, existing.id, name="Renamed")
    row = stored(database, other.id)
    assert (row.name, row.address) == ("Other", "Other address")


def test_an_edit_does_not_change_the_owner_or_the_view_only_state(
    client, database, owner, signed_in, existing
):
    update(client, signed_in.headers, existing.id, name="Renamed")
    row = stored(database, existing.id)
    assert row.owner_id == owner.id
    assert row.view_only is False
    assert row.deleted_at is None


def test_a_partial_bank_account_in_an_edit_is_a_validation_failure(
    client, database, signed_in, existing
):
    bank = {k: v for k, v in BANK.items() if k != "accountNumber"}
    response = update(client, signed_in.headers, existing.id, bankAccount=bank)
    assert_error(response, 422, "VALIDATION_FAILED", "bankAccount.accountNumber")


# PUT: view-only


def test_a_view_only_property_cannot_be_edited(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, view_only=True)
    response = update(client, signed_in.headers, row.id, name="Renamed")
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert stored(database, row.id).name == "Kos Melati"


def test_a_view_only_property_is_refused_even_when_only_the_name_changes(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, view_only=True)
    set_bank(database, row.id, BANK)
    response = update(client, signed_in.headers, row.id, name="Renamed")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_is_reported_before_re_authentication_is_asked_for(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, view_only=True)
    response = update(client, signed_in.headers, row.id, bankAccount=BANK)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_is_reported_before_a_taken_name(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, name="Old", view_only=True)
    make_property(owner, name="Taken")
    response = update(client, signed_in.headers, row.id, name="Taken")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_not_found_is_reported_before_view_only(
    client, database, signed_in, make_user, make_property
):
    row = make_property(make_user(), view_only=True)
    response = update(client, signed_in.headers, row.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_forbidden_is_reported_before_not_found_for_a_manager(
    client, database, manager_in
):
    response = update(client, manager_in.headers, uuid4())
    assert_error(response, 403, "FORBIDDEN")


# PUT: bank account changes need a recent re-authentication


def test_adding_a_bank_account_needs_re_authentication(
    client, database, signed_in, existing
):
    response = update(client, signed_in.headers, existing.id, name="Renamed")
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    row = stored(database, existing.id)
    assert row.name == "Kos Melati"
    assert row.bank_name is None


def test_removing_the_bank_account_needs_re_authentication(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    response = update(client, signed_in.headers, existing.id, bankAccount=None)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    assert stored(database, existing.id).bank_name == "BCA"


@pytest.mark.parametrize("field", ["bankName", "accountNumber", "accountHolderName"])
def test_changing_any_bank_account_field_needs_re_authentication(
    client, database, signed_in, existing, field
):
    set_bank(database, existing.id, BANK)
    changed = {**BANK, field: "Different"}
    response = update(
        client, signed_in.headers, existing.id, name="Renamed", bankAccount=changed
    )
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    row = stored(database, existing.id)
    assert row.name == "Kos Melati"
    assert (row.bank_name, row.bank_account_number) == ("BCA", "1234567890")
    assert row.bank_account_holder_name == "Budi Santoso"


def test_a_refused_edit_changes_neither_name_nor_address(
    client, database, signed_in, existing
):
    update(client, signed_in.headers, existing.id, name="Renamed", address="Moved")
    row = stored(database, existing.id)
    assert (row.name, row.address) == ("Kos Melati", "Jl. Melati 5")


def test_a_bank_account_change_succeeds_after_a_recent_re_authentication(
    client, database, signed_in, existing
):
    reauthenticated_minutes_ago(database, signed_in, 4)
    response = update(client, signed_in.headers, existing.id, name="Renamed")
    assert response.status_code == 200
    assert response.json()["bankAccount"] == BANK
    row = stored(database, existing.id)
    assert row.name == "Renamed"
    assert row.bank_name == "BCA"
    assert row.bank_account_number == "1234567890"
    assert row.bank_account_holder_name == "Budi Santoso"


def test_replacing_a_bank_account_stores_the_new_one(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    reauthenticated_minutes_ago(database, signed_in, 1)
    new_bank = {
        "bankName": "Mandiri",
        "accountNumber": "999",
        "accountHolderName": "Siti",
    }
    response = update(client, signed_in.headers, existing.id, bankAccount=new_bank)
    assert response.status_code == 200
    assert response.json()["bankAccount"] == new_bank
    row = stored(database, existing.id)
    assert (row.bank_name, row.bank_account_number) == ("Mandiri", "999")
    assert row.bank_account_holder_name == "Siti"


def test_removing_the_bank_account_clears_every_column(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    reauthenticated_minutes_ago(database, signed_in, 1)
    response = update(client, signed_in.headers, existing.id, bankAccount=None)
    assert response.status_code == 200
    assert response.json()["bankAccount"] is None
    row = stored(database, existing.id)
    assert row.bank_name is None
    assert row.bank_account_number is None
    assert row.bank_account_holder_name is None


def test_omitting_the_bank_account_removes_a_stored_one(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    reauthenticated_minutes_ago(database, signed_in, 1)
    response = client.put(
        detail_url(existing.id), json=BODY_WITHOUT_BANK, headers=signed_in.headers
    )
    assert response.status_code == 200
    assert response.json()["bankAccount"] is None


def test_a_bank_account_change_is_refused_after_the_window(
    client, database, signed_in, existing
):
    reauthenticated_minutes_ago(database, signed_in, 6)
    response = update(client, signed_in.headers, existing.id)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    assert stored(database, existing.id).bank_name is None


def test_a_re_authentication_of_another_session_does_not_count(
    client, database, owner, signed_in, existing, sign_in
):
    other = sign_in(owner, device_name="Galaxy")
    reauthenticated_minutes_ago(database, other, 1)
    response = update(client, signed_in.headers, existing.id)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    assert update(client, other.headers, existing.id).status_code == 200


def test_re_authenticating_through_the_api_opens_the_window(
    client, database, owner, existing
):
    from app.services.passwords import hash_password

    password = "correct horse battery"
    from app.models import UserAccount

    with Session(database) as db:
        db.get(UserAccount, owner.id).password_hash = hash_password(password)
        db.commit()
    headers = client.post(
        "/auth/login",
        json={
            "email": owner.email,
            "password": password,
            "device": {"name": "Pixel 8", "platform": "Android 14"},
        },
    ).json()
    token = {"Authorization": f"Bearer {headers['accessToken']}"}
    assert_error(update(client, token, existing.id), 403, "REAUTHENTICATION_REQUIRED")
    reply = client.post(
        "/me/reauthentication/password", json={"password": password}, headers=token
    )
    assert reply.status_code == 200
    assert update(client, token, existing.id).status_code == 200


def test_editing_only_name_and_address_needs_no_re_authentication(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    response = update(client, signed_in.headers, existing.id, name="Renamed")
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_resending_the_identical_bank_account_needs_no_re_authentication(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    response = update(client, signed_in.headers, existing.id, address="Moved")
    assert response.status_code == 200
    assert response.json()["bankAccount"] == BANK


def test_sending_null_when_none_is_stored_needs_no_re_authentication(
    client, database, signed_in, existing
):
    response = update(
        client, signed_in.headers, existing.id, name="Renamed", bankAccount=None
    )
    assert response.status_code == 200
    assert response.json()["bankAccount"] is None


def test_omitting_the_bank_account_when_none_is_stored_needs_no_re_authentication(
    client, database, signed_in, existing
):
    response = client.put(
        detail_url(existing.id), json=BODY_WITHOUT_BANK, headers=signed_in.headers
    )
    assert response.status_code == 200


def test_re_authentication_is_asked_for_before_a_taken_name_is_reported(
    client, database, owner, signed_in, existing, make_property
):
    subscribe(database, owner, "pro")
    make_property(owner, name="Taken")
    response = update(client, signed_in.headers, existing.id, name="Taken")
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")


def test_a_taken_name_is_reported_when_re_authentication_is_recent(
    client, database, owner, signed_in, existing, make_property
):
    subscribe(database, owner, "pro")
    make_property(owner, name="Taken")
    reauthenticated_minutes_ago(database, signed_in, 1)
    response = update(client, signed_in.headers, existing.id, name="Taken")
    assert_error(response, 409, "PROPERTY_NAME_TAKEN", "name")
    assert stored(database, existing.id).bank_name is None


# DELETE /properties/{propertyId}


def test_deleting_a_property_answers_with_an_empty_body(
    client, database, signed_in, existing
):
    response = client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert response.content == b""


def test_deleting_marks_the_row_instead_of_removing_it(
    client, database, signed_in, existing
):
    before = datetime.now(UTC)
    client.delete(detail_url(existing.id), headers=signed_in.headers)
    after = datetime.now(UTC)
    row = stored(database, existing.id)
    assert row is not None
    assert before <= row.deleted_at <= after
    assert row.name == "Kos Melati"


def test_a_deleted_property_leaves_the_list_and_the_detail(
    client, database, signed_in, existing
):
    client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert client.get(URL, headers=signed_in.headers).json() == {"items": []}
    response = client.get(detail_url(existing.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_deleting_removes_every_manager_assignment_of_the_property(
    client,
    database,
    signed_in,
    manager,
    manager_in,
    existing,
    make_user,
    assign_manager,
):
    assign_manager(manager, existing)
    assign_manager(make_user(role=role("manager")), existing)
    assert len(assignments(database, existing.id)) == 2
    client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert assignments(database, existing.id) == []
    response = client.get(detail_url(existing.id), headers=manager_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert client.get(URL, headers=manager_in.headers).json() == {"items": []}


def test_deleting_leaves_other_properties_and_their_assignments(
    client,
    database,
    owner,
    signed_in,
    manager,
    manager_in,
    existing,
    make_property,
    assign_manager,
):
    subscribe(database, owner, "pro")
    kept = make_property(owner, name="Kept")
    assign_manager(manager, existing)
    assign_manager(manager, kept)
    client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert stored(database, kept.id).deleted_at is None
    assert len(assignments(database, kept.id)) == 1
    items = client.get(URL, headers=manager_in.headers).json()["items"]
    assert [i["id"] for i in items] == [str(kept.id)]


def test_a_view_only_property_can_be_deleted(
    client, database, owner, signed_in, make_property
):
    row = make_property(owner, view_only=True)
    response = client.delete(detail_url(row.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored(database, row.id).deleted_at is not None


def test_deleting_a_property_a_second_time_is_not_found(
    client, database, signed_in, existing
):
    first = client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert first.status_code == 204
    stamp = stored(database, existing.id).deleted_at
    response = client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored(database, existing.id).deleted_at == stamp


def test_deleting_needs_no_re_authentication_even_with_a_bank_account(
    client, database, signed_in, existing
):
    set_bank(database, existing.id, BANK)
    response = client.delete(detail_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 204
