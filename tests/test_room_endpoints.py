"""Adding, listing, reading, editing and deleting rooms, and facility suggestions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

PROPERTIES = "/properties"
BODY = {
    "number": "A1",
    "baseRate": 1500000,
    "lengthM": 3.5,
    "widthM": 4,
    "facilities": ["ac", "wifi"],
}
ROOM_FIELDS = {
    "id",
    "propertyId",
    "number",
    "baseRate",
    "occupancy",
    "lengthM",
    "widthM",
    "facilities",
    "lease",
    "editable",
}
SUMMARY_FIELDS = ROOM_FIELDS - {"propertyId"}
FREE_ROOM_LIMIT = 15


def rooms_url(property_id) -> str:
    return f"{PROPERTIES}/{property_id}/rooms"


def suggestions_url(property_id) -> str:
    return f"{PROPERTIES}/{property_id}/facility-suggestions"


def room_url(room_id) -> str:
    return f"/rooms/{room_id}"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def without(body: dict, *keys: str) -> dict:
    return {k: v for k, v in body.items() if k not in keys}


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def stored_room(database, room_id):
    from app.models import Room

    with Session(database, expire_on_commit=False) as db:
        return db.get(Room, UUID(str(room_id)))


def stored_rooms(database, property_id=None) -> list:
    """Every stored room of a property (all properties if omitted), deleted ones too."""
    from app.models import Room

    query = select(Room).order_by(Room.created_at, Room.id)
    if property_id is not None:
        query = query.where(Room.property_id == UUID(str(property_id)))
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(query))


def live_rooms(database, property_id=None) -> list:
    return [r for r in stored_rooms(database, property_id) if r.deleted_at is None]


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


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


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
    return make_property(owner, name="Kos Melati")


@pytest.fixture
def make_room(database):
    """Create and commit a `Room` in a property."""
    from app.models import Room

    def factory(
        property_,
        number: str = "A1",
        base_rate: int = 1000000,
        facilities: list[str] | None = None,
        length_m=None,
        width_m=None,
        view_only: bool = False,
        deleted: bool = False,
    ):
        with Session(database, expire_on_commit=False) as db:
            row = Room(
                property_id=property_.id,
                number=number,
                base_rate=base_rate,
                facilities=facilities or [],
                length_m=length_m,
                width_m=width_m,
                view_only=view_only,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            db.add(row)
            db.commit()
            return row

    return factory


@pytest.fixture
def room(existing, make_room):
    return make_room(existing, number="A1", facilities=["old"])


def create(client, headers, property_id, **overrides):
    return client.post(
        rooms_url(property_id), json={**BODY, **overrides}, headers=headers
    )


def update(client, headers, room_id, **overrides):
    return client.put(room_url(room_id), json={**BODY, **overrides}, headers=headers)


# Authentication and roles


REQUESTS = [
    pytest.param("post", rooms_url(uuid4()), BODY, id="create"),
    pytest.param("get", rooms_url(uuid4()), None, id="list"),
    pytest.param("get", suggestions_url(uuid4()), None, id="suggestions"),
    pytest.param("get", room_url(uuid4()), None, id="get"),
    pytest.param("put", room_url(uuid4()), BODY, id="update"),
    pytest.param("delete", room_url(uuid4()), None, id="delete"),
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


@pytest.mark.parametrize("name", ["tenant", "admin"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_tenants_and_admins_are_forbidden_everywhere(
    client, database, make_user, sign_in, name, method, url, body
):
    session = sign_in(make_user(role=role(name)))
    response = client.request(method, url, json=body, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_forbidden_tenant_changes_nothing(
    client, database, make_user, sign_in, existing, room
):
    headers = sign_in(make_user(role=role("tenant"))).headers
    create(client, headers, existing.id, number="B1")
    update(client, headers, room.id, number="C1")
    client.delete(room_url(room.id), headers=headers)
    rows = live_rooms(database, existing.id)
    assert [r.number for r in rows] == ["A1"]


# POST /properties/{propertyId}/rooms


def test_creating_a_room_answers_with_the_stored_room(
    client, database, existing, signed_in
):
    response = create(client, signed_in.headers, existing.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ROOM_FIELDS
    (row,) = stored_rooms(database, existing.id)
    assert body["id"] == str(row.id)
    assert body["propertyId"] == str(existing.id)
    assert body["number"] == "A1"
    assert body["baseRate"] == 1500000
    assert body["lengthM"] == 3.5
    assert body["widthM"] == 4
    assert body["facilities"] == ["ac", "wifi"]


def test_a_created_room_is_vacant_editable_and_without_a_lease(
    client, database, existing, signed_in
):
    body = create(client, signed_in.headers, existing.id).json()
    assert body["occupancy"] == "vacant"
    assert body["lease"] is None
    assert body["editable"] is True


def test_a_created_room_is_stored_with_its_values(
    client, database, existing, signed_in
):
    create(client, signed_in.headers, existing.id)
    (row,) = stored_rooms(database, existing.id)
    assert row.property_id == existing.id
    assert row.number == "A1"
    assert row.base_rate == 1500000
    assert row.length_m == Decimal("3.50")
    assert row.width_m == Decimal("4.00")
    assert row.facilities == ["ac", "wifi"]
    assert row.view_only is False
    assert row.deleted_at is None


def test_a_room_with_only_the_required_fields_has_empty_optionals(
    client, database, existing, signed_in
):
    response = client.post(
        rooms_url(existing.id),
        json={"number": "A1", "baseRate": 500000},
        headers=signed_in.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["lengthM"] is None
    assert body["widthM"] is None
    assert body["facilities"] == []
    (row,) = stored_rooms(database, existing.id)
    assert row.length_m is None
    assert row.width_m is None
    assert row.facilities == []


def test_the_created_room_can_be_read_back(client, database, existing, signed_in):
    created = create(client, signed_in.headers, existing.id).json()
    response = client.get(room_url(created["id"]), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == created


def test_the_created_room_appears_in_the_list(client, database, existing, signed_in):
    created = create(client, signed_in.headers, existing.id).json()
    items = client.get(rooms_url(existing.id), headers=signed_in.headers).json()
    assert [i["id"] for i in items["items"]] == [created["id"]]


def test_a_second_room_is_added_next_to_the_first(
    client, database, existing, signed_in
):
    create(client, signed_in.headers, existing.id, number="A1")
    response = create(client, signed_in.headers, existing.id, number="A2")
    assert response.status_code == 201
    assert len(live_rooms(database, existing.id)) == 2


def test_the_base_rate_is_stored_as_a_whole_number(
    client, database, existing, signed_in
):
    response = create(client, signed_in.headers, existing.id, baseRate=1)
    assert response.status_code == 201
    assert response.json()["baseRate"] == 1


# POST: property access


def test_an_unknown_property_is_not_found_and_nothing_is_saved(
    client, database, signed_in
):
    response = create(client, signed_in.headers, uuid4())
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored_rooms(database) == []


def test_another_owners_property_is_not_found_and_nothing_is_saved(
    client, database, signed_in, make_user, make_property
):
    theirs = make_property(make_user(), name="Theirs")
    response = create(client, signed_in.headers, theirs.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored_rooms(database) == []


def test_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = create(client, signed_in.headers, gone.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored_rooms(database) == []


def test_a_malformed_property_id_is_a_validation_failure(client, database, signed_in):
    response = client.post(
        rooms_url("not-a-uuid"), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


def test_a_manager_adds_a_room_to_an_assigned_property(
    client, database, manager, manager_in, existing, assign_manager
):
    assign_manager(manager, existing)
    response = create(client, manager_in.headers, existing.id)
    assert response.status_code == 201
    (row,) = live_rooms(database, existing.id)
    assert row.number == "A1"


def test_a_manager_cannot_add_a_room_to_an_unassigned_property(
    client, database, manager_in, existing
):
    response = create(client, manager_in.headers, existing.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert stored_rooms(database) == []


def test_a_manager_loses_the_right_to_add_rooms_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, assign_manager
):
    assign_manager(manager, existing)
    assert create(client, manager_in.headers, existing.id).status_code == 201
    unassign(database, manager, existing)
    response = create(client, manager_in.headers, existing.id, number="A2")
    assert_error(response, 404, "PROPERTY_NOT_FOUND")
    assert len(live_rooms(database, existing.id)) == 1


# POST: view-only property


def test_a_view_only_property_refuses_new_rooms(
    client, database, owner, signed_in, make_property
):
    frozen = make_property(owner, view_only=True)
    response = create(client, signed_in.headers, frozen.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert stored_rooms(database) == []


def test_a_view_only_property_refuses_new_rooms_from_a_manager(
    client, database, owner, manager, manager_in, make_property, assign_manager
):
    frozen = make_property(owner, view_only=True)
    assign_manager(manager, frozen)
    response = create(client, manager_in.headers, frozen.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_not_found_is_reported_before_view_only(
    client, database, signed_in, make_user, make_property
):
    theirs = make_property(make_user(), view_only=True)
    response = create(client, signed_in.headers, theirs.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_view_only_is_reported_before_field_rules(
    client, database, owner, signed_in, make_property
):
    frozen = make_property(owner, view_only=True)
    response = create(client, signed_in.headers, frozen.id, number="  ")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_view_only_is_reported_before_a_taken_number(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    make_room(frozen, number="A1")
    response = create(client, signed_in.headers, frozen.id, number="A1")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


# POST and PUT: field rules


class Write:
    """One way to submit a room body: adding a room or replacing one."""

    def __init__(self, client, headers, property_id, room_id):
        self.client = client
        self.headers = headers
        self.property_id = property_id
        self.room_id = room_id

    def raw(self, body: dict):
        if self.room_id is None:
            return self.client.post(
                rooms_url(self.property_id), json=body, headers=self.headers
            )
        return self.client.put(room_url(self.room_id), json=body, headers=self.headers)

    def __call__(self, **overrides):
        return self.raw({**BODY, **overrides})

    def assert_untouched(self, database) -> None:
        rows = live_rooms(database, self.property_id)
        if self.room_id is None:
            assert rows == []
            return
        (row,) = rows
        assert row.number == "A1"
        assert row.base_rate == 1000000
        assert row.facilities == ["old"]
        assert row.length_m is None
        assert row.width_m is None


@pytest.fixture(params=["create", "update"])
def write(request, client, database, existing, signed_in, make_room):
    room_id = None
    if request.param == "update":
        room_id = make_room(existing, number="A1", facilities=["old"]).id
    return Write(client, signed_in.headers, existing.id, room_id)


def test_the_number_is_trimmed(client, database, existing, write):
    response = write(number="  B 2 \n")
    assert response.status_code in (200, 201), response.text
    assert response.json()["number"] == "B 2"
    (row,) = live_rooms(database, existing.id)
    assert row.number == "B 2"


def test_the_case_of_the_number_is_kept(database, existing, write):
    response = write(number="b2")
    assert response.json()["number"] == "b2"
    (row,) = live_rooms(database, existing.id)
    assert row.number == "b2"


@pytest.mark.parametrize("value", ["", " ", " \t\n "])
def test_a_blank_number_is_a_validation_failure(database, write, value):
    assert_error(write(number=value), 422, "VALIDATION_FAILED", "number")
    write.assert_untouched(database)


def test_a_missing_number_is_a_validation_failure(database, write):
    response = write.raw(without(BODY, "number"))
    assert_error(response, 422, "VALIDATION_FAILED", "number")
    write.assert_untouched(database)


@pytest.mark.parametrize("value", [0, -5])
def test_a_base_rate_that_is_not_positive_is_a_validation_failure(
    database, write, value
):
    assert_error(write(baseRate=value), 422, "VALIDATION_FAILED", "baseRate")
    write.assert_untouched(database)


def test_a_base_rate_with_a_fraction_is_a_validation_failure(database, write):
    assert_error(write(baseRate=1500.5), 422, "VALIDATION_FAILED", "baseRate")
    write.assert_untouched(database)


def test_a_length_without_a_width_is_a_validation_failure_on_the_width(database, write):
    response = write.raw(without(BODY, "widthM"))
    assert_error(response, 422, "VALIDATION_FAILED", "widthM")
    write.assert_untouched(database)


def test_a_width_without_a_length_is_a_validation_failure_on_the_length(
    database, write
):
    response = write.raw(without(BODY, "lengthM"))
    assert_error(response, 422, "VALIDATION_FAILED", "lengthM")
    write.assert_untouched(database)


def test_a_length_with_a_null_width_is_a_validation_failure_on_the_width(
    database, write
):
    assert_error(write(widthM=None), 422, "VALIDATION_FAILED", "widthM")
    write.assert_untouched(database)


def test_a_width_with_a_null_length_is_a_validation_failure_on_the_length(
    database, write
):
    assert_error(write(lengthM=None), 422, "VALIDATION_FAILED", "lengthM")
    write.assert_untouched(database)


def test_omitting_both_dimensions_stores_none(database, existing, write):
    response = write.raw(without(BODY, "lengthM", "widthM"))
    assert response.status_code in (200, 201)
    assert response.json()["lengthM"] is None
    assert response.json()["widthM"] is None
    (row,) = live_rooms(database, existing.id)
    assert row.length_m is None
    assert row.width_m is None


def test_null_dimensions_store_none(database, existing, write):
    response = write(lengthM=None, widthM=None)
    assert response.status_code in (200, 201)
    (row,) = live_rooms(database, existing.id)
    assert row.length_m is None
    assert row.width_m is None


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
@pytest.mark.parametrize("value", [2.555, 1.001, 0.125])
def test_a_dimension_with_three_decimals_is_a_validation_failure(
    database, write, field, value
):
    assert_error(write(**{field: value}), 422, "VALIDATION_FAILED", field)
    write.assert_untouched(database)


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
@pytest.mark.parametrize("value", [2.5, 20, 20.0, 0.01, 3.25, 12])
def test_a_dimension_with_at_most_two_decimals_in_range_is_accepted(
    database, existing, write, field, value
):
    response = write(**{field: value})
    assert response.status_code in (200, 201), response.text
    assert response.json()[field] == value
    (row,) = live_rooms(database, existing.id)
    assert getattr(row, "length_m" if field == "lengthM" else "width_m") == Decimal(
        str(value)
    )


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
@pytest.mark.parametrize("value", [20.01, 0, -1])
def test_a_dimension_outside_the_range_is_a_validation_failure(
    database, write, field, value
):
    assert_error(write(**{field: value}), 422, "VALIDATION_FAILED", field)
    write.assert_untouched(database)


def test_facilities_are_normalized_in_the_response_and_in_storage(
    database, existing, write
):
    response = write(
        facilities=[" AC ", "Wi   Fi", "", "   ", "ac", "WIFI", "wi fi", "Kasur"]
    )
    assert response.status_code in (200, 201), response.text
    expected = ["ac", "wi fi", "wifi", "kasur"]
    assert response.json()["facilities"] == expected
    (row,) = live_rooms(database, existing.id)
    assert row.facilities == expected


def test_duplicate_facilities_keep_the_first_occurrence_order(database, write):
    response = write(facilities=["b", "a", "B", "c", "a"])
    assert response.json()["facilities"] == ["b", "a", "c"]


def test_facilities_with_only_blank_tags_become_empty(database, existing, write):
    response = write(facilities=["", "  ", " "])
    assert response.status_code in (200, 201)
    assert response.json()["facilities"] == []
    (row,) = live_rooms(database, existing.id)
    assert row.facilities == []


def test_omitted_facilities_become_empty(database, existing, write):
    response = write.raw(without(BODY, "facilities"))
    assert response.status_code in (200, 201)
    assert response.json()["facilities"] == []


def test_a_facility_of_thirty_characters_is_accepted(database, write):
    tag = "a" * 30
    response = write(facilities=[tag])
    assert response.status_code in (200, 201)
    assert response.json()["facilities"] == [tag]


def test_a_facility_of_thirty_one_characters_is_a_validation_failure(database, write):
    response = write(facilities=["ok", "a" * 31])
    assert_error(response, 422, "VALIDATION_FAILED", "facilities")
    write.assert_untouched(database)


def test_a_facility_is_measured_after_normalization(database, write):
    tag = "a" * 14 + "     " + "b" * 15
    padded = "   " + "c" * 30 + "   "
    response = write(facilities=[tag, padded])
    assert response.status_code in (200, 201), response.text
    assert response.json()["facilities"] == ["a" * 14 + " " + "b" * 15, "c" * 30]


def test_fifteen_distinct_facilities_are_accepted(database, write):
    tags = [f"tag{n}" for n in range(15)]
    response = write(facilities=tags)
    assert response.status_code in (200, 201)
    assert response.json()["facilities"] == tags


def test_sixteen_distinct_facilities_are_a_validation_failure(database, write):
    tags = [f"tag{n}" for n in range(16)]
    response = write(facilities=tags)
    assert_error(response, 422, "VALIDATION_FAILED", "facilities")
    write.assert_untouched(database)


def test_sixteen_raw_facilities_collapsing_to_fifteen_are_accepted(database, write):
    tags = [f"tag{n}" for n in range(15)] + ["  TAG0 "]
    response = write(facilities=tags)
    assert response.status_code in (200, 201)
    assert response.json()["facilities"] == [f"tag{n}" for n in range(15)]


def test_blank_tags_do_not_count_towards_the_facility_limit(database, write):
    tags = [f"tag{n}" for n in range(15)] + ["", " "]
    response = write(facilities=tags)
    assert response.status_code in (200, 201)


def test_a_non_string_facility_is_a_validation_failure(database, write):
    assert_error(write(facilities=[1]), 422, "VALIDATION_FAILED", "facilities.0")
    write.assert_untouched(database)


# POST: number uniqueness


def test_a_number_already_used_in_the_property_is_refused(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1")
    response = create(client, signed_in.headers, existing.id, number="A1")
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")
    assert len(live_rooms(database, existing.id)) == 1


@pytest.mark.parametrize("number", ["a1", " A1 ", "  a1\t"])
def test_a_taken_number_is_detected_ignoring_case_and_surrounding_spaces(
    client, database, existing, signed_in, make_room, number
):
    make_room(existing, number="A1")
    response = create(client, signed_in.headers, existing.id, number=number)
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")
    assert len(live_rooms(database, existing.id)) == 1


def test_a_view_only_room_still_holds_its_number(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1", view_only=True)
    response = create(client, signed_in.headers, existing.id, number="a1")
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")


def test_another_property_may_use_the_same_number(
    client, database, owner, existing, signed_in, make_property, make_room
):
    other = make_property(owner, name="Other")
    make_room(other, number="A1")
    response = create(client, signed_in.headers, existing.id, number="A1")
    assert response.status_code == 201


def test_the_number_of_a_deleted_room_can_be_used_again(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1", deleted=True)
    response = create(client, signed_in.headers, existing.id, number="a1")
    assert response.status_code == 201


def test_a_number_freed_through_the_api_can_be_used_again(
    client, database, existing, signed_in
):
    first = create(client, signed_in.headers, existing.id).json()
    deleted = client.delete(room_url(first["id"]), headers=signed_in.headers)
    assert deleted.status_code == 204
    response = create(client, signed_in.headers, existing.id)
    assert response.status_code == 201
    assert response.json()["id"] != first["id"]


def test_field_rules_are_reported_before_a_taken_number(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1")
    response = create(client, signed_in.headers, existing.id, facilities=["a" * 31])
    assert_error(response, 422, "VALIDATION_FAILED", "facilities")


# POST: room limit


def fill(property_, make_room, count: int) -> None:
    for n in range(count):
        make_room(property_, number=f"R{n}")


def assert_limit_reached(response) -> None:
    assert_error(response, 403, "ROOM_LIMIT_REACHED")


def test_a_free_owner_may_add_the_last_room_within_the_limit(
    client, database, existing, signed_in, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT - 1)
    assert create(client, signed_in.headers, existing.id).status_code == 201
    assert len(live_rooms(database, existing.id)) == FREE_ROOM_LIMIT


def test_a_free_owner_is_refused_the_sixteenth_room(
    client, database, existing, signed_in, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert_limit_reached(create(client, signed_in.headers, existing.id))
    assert len(live_rooms(database, existing.id)) == FREE_ROOM_LIMIT


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_paid_plans_have_no_room_limit(
    client, database, owner, existing, signed_in, make_room, plan
):
    subscribe(database, owner, plan)
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert create(client, signed_in.headers, existing.id).status_code == 201
    assert len(live_rooms(database, existing.id)) == FREE_ROOM_LIMIT + 1


def test_an_expired_paid_plan_counts_as_free(
    client, database, owner, existing, signed_in, make_room
):
    subscribe(database, owner, "pro")
    expire_subscription(database, owner)
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert_limit_reached(create(client, signed_in.headers, existing.id))


def test_view_only_rooms_count_towards_the_limit(
    client, database, existing, signed_in, make_room
):
    for n in range(FREE_ROOM_LIMIT):
        make_room(existing, number=f"R{n}", view_only=True)
    assert_limit_reached(create(client, signed_in.headers, existing.id))


def test_deleted_rooms_do_not_count_towards_the_limit(
    client, database, existing, signed_in, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT - 1)
    for n in range(5):
        make_room(existing, number=f"Gone{n}", deleted=True)
    assert create(client, signed_in.headers, existing.id).status_code == 201


def test_deleting_a_room_frees_a_place(
    client, database, existing, signed_in, make_room
):
    first = make_room(existing, number="First")
    fill(existing, make_room, FREE_ROOM_LIMIT - 1)
    assert_limit_reached(create(client, signed_in.headers, existing.id, number="New"))
    deleted = client.delete(room_url(first.id), headers=signed_in.headers)
    assert deleted.status_code == 204
    response = create(client, signed_in.headers, existing.id, number="New")
    assert response.status_code == 201


def test_rooms_of_other_properties_do_not_count(
    client, database, owner, existing, signed_in, make_property, make_room
):
    other = make_property(owner, name="Other")
    fill(other, make_room, FREE_ROOM_LIMIT)
    assert create(client, signed_in.headers, existing.id).status_code == 201


def test_a_full_property_does_not_stop_another_property_of_the_owner(
    client, database, owner, existing, signed_in, make_property, make_room
):
    other = make_property(owner, name="Other")
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert create(client, signed_in.headers, other.id).status_code == 201


def test_another_owners_plan_does_not_raise_the_limit(
    client, database, existing, signed_in, make_user, make_room
):
    subscribe(database, make_user(), "pro")
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert_limit_reached(create(client, signed_in.headers, existing.id))


def test_the_owners_free_plan_limits_a_manager(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    assign_manager(manager, existing)
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert_limit_reached(create(client, manager_in.headers, existing.id))
    assert len(live_rooms(database, existing.id)) == FREE_ROOM_LIMIT


def test_the_owners_paid_plan_lifts_the_limit_for_a_manager(
    client, database, owner, manager, manager_in, existing, make_room, assign_manager
):
    subscribe(database, owner, "basic")
    assign_manager(manager, existing)
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert create(client, manager_in.headers, existing.id).status_code == 201


def test_an_expired_owner_plan_limits_a_manager(
    client, database, owner, manager, manager_in, existing, make_room, assign_manager
):
    subscribe(database, owner, "pro")
    expire_subscription(database, owner)
    assign_manager(manager, existing)
    fill(existing, make_room, FREE_ROOM_LIMIT)
    assert_limit_reached(create(client, manager_in.headers, existing.id))


def test_a_taken_number_is_reported_before_the_limit(
    client, database, existing, signed_in, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT)
    response = create(client, signed_in.headers, existing.id, number="R0")
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")


def test_field_rules_are_reported_before_the_limit(
    client, database, existing, signed_in, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT)
    response = create(client, signed_in.headers, existing.id, number=" ")
    assert_error(response, 422, "VALIDATION_FAILED", "number")


def test_a_full_view_only_property_reports_read_only_before_the_limit(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    fill(frozen, make_room, FREE_ROOM_LIMIT)
    assert_error(
        create(client, signed_in.headers, frozen.id), 403, "PROPERTY_READ_ONLY"
    )


# GET /properties/{propertyId}/rooms


def test_a_property_without_rooms_lists_an_empty_array(
    client, database, existing, signed_in
):
    response = client.get(rooms_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_list_shows_rooms_as_summaries(
    client, database, existing, signed_in, make_room
):
    row = make_room(
        existing,
        number="A1",
        base_rate=1250000,
        facilities=["ac", "wifi"],
        length_m=Decimal("3.50"),
        width_m=Decimal("4.00"),
    )
    response = client.get(rooms_url(existing.id), headers=signed_in.headers)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == SUMMARY_FIELDS
    assert item == {
        "id": str(row.id),
        "number": "A1",
        "baseRate": 1250000,
        "occupancy": "vacant",
        "lengthM": 3.5,
        "widthM": 4,
        "facilities": ["ac", "wifi"],
        "lease": None,
        "editable": True,
    }


def test_a_room_without_dimensions_lists_null_dimensions(
    client, database, existing, signed_in, make_room
):
    make_room(existing)
    (item,) = client.get(rooms_url(existing.id), headers=signed_in.headers).json()[
        "items"
    ]
    assert item["lengthM"] is None
    assert item["widthM"] is None
    assert item["facilities"] == []


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        (["10", "2", "1", "21", "3"], ["1", "2", "3", "10", "21"]),
        (["A10", "A2", "A1", "A100", "A9"], ["A1", "A2", "A9", "A10", "A100"]),
        (["a10", "A2", "a1", "B1"], ["a1", "A2", "a10", "B1"]),
        (["b1", "A2", "B0", "a10"], ["A2", "a10", "B0", "b1"]),
    ],
)
def test_rooms_are_listed_in_natural_order_of_their_number(
    client, database, existing, signed_in, make_room, numbers, expected
):
    for number in numbers:
        make_room(existing, number=number)
    items = client.get(rooms_url(existing.id), headers=signed_in.headers).json()
    assert [i["number"] for i in items["items"]] == expected


def test_the_list_leaves_out_deleted_rooms_and_other_properties(
    client, database, owner, existing, signed_in, make_property, make_room
):
    mine = make_room(existing, number="A1")
    view_only = make_room(existing, number="A2", view_only=True)
    make_room(existing, number="A3", deleted=True)
    make_room(make_property(owner, name="Other"), number="A4")
    items = client.get(rooms_url(existing.id), headers=signed_in.headers).json()
    assert [i["id"] for i in items["items"]] == [str(mine.id), str(view_only.id)]


def test_a_view_only_room_is_listed_as_not_editable(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1", view_only=True)
    make_room(existing, number="A2")
    items = client.get(rooms_url(existing.id), headers=signed_in.headers).json()
    assert [(i["number"], i["editable"]) for i in items["items"]] == [
        ("A1", False),
        ("A2", True),
    ]


def test_every_room_of_a_view_only_property_is_listed_as_not_editable(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    make_room(frozen, number="A1")
    make_room(frozen, number="A2")
    items = client.get(rooms_url(frozen.id), headers=signed_in.headers).json()
    assert [i["editable"] for i in items["items"]] == [False, False]


def test_a_manager_lists_the_rooms_of_an_assigned_property(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    row = make_room(existing)
    assign_manager(manager, existing)
    response = client.get(rooms_url(existing.id), headers=manager_in.headers)
    assert response.status_code == 200
    assert [i["id"] for i in response.json()["items"]] == [str(row.id)]


def test_an_unassigned_manager_cannot_list_the_rooms(
    client, database, manager_in, existing, make_room
):
    make_room(existing)
    response = client.get(rooms_url(existing.id), headers=manager_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_a_manager_loses_access_to_the_list_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    make_room(existing)
    assign_manager(manager, existing)
    assert (
        client.get(rooms_url(existing.id), headers=manager_in.headers).status_code
        == 200
    )
    unassign(database, manager, existing)
    response = client.get(rooms_url(existing.id), headers=manager_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_rooms_of_an_unknown_property_is_not_found(
    client, database, signed_in
):
    response = client.get(rooms_url(uuid4()), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_rooms_of_another_owners_property_is_not_found(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_property(make_user(), name="Theirs")
    make_room(theirs)
    response = client.get(rooms_url(theirs.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_the_rooms_of_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = client.get(rooms_url(gone.id), headers=signed_in.headers)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_listing_with_a_malformed_property_id_is_a_validation_failure(
    client, database, signed_in
):
    response = client.get(rooms_url("not-a-uuid"), headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


# GET /properties/{propertyId}/facility-suggestions


def suggestions(client, headers, property_id):
    return client.get(suggestions_url(property_id), headers=headers)


def test_a_property_without_facilities_suggests_nothing(
    client, database, existing, signed_in, make_room
):
    make_room(existing)
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_suggestions_are_the_distinct_tags_sorted_alphabetically(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1", facilities=["wifi", "ac", "kasur"])
    make_room(existing, number="A2", facilities=["ac", "air panas", "wifi"])
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.status_code == 200
    assert response.json() == {"items": ["ac", "air panas", "kasur", "wifi"]}


def test_suggestions_cover_all_properties_of_the_owner(
    client, database, owner, existing, signed_in, make_property, make_room
):
    make_room(existing, number="A1", facilities=["ac"])
    other = make_property(owner, name="Other")
    make_room(other, number="A1", facilities=["wifi"])
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["ac", "wifi"]}


def test_suggestions_include_view_only_properties_and_rooms(
    client, database, owner, existing, signed_in, make_property, make_room
):
    frozen = make_property(owner, name="Frozen", view_only=True)
    make_room(frozen, number="A1", facilities=["kolam"])
    make_room(existing, number="A1", facilities=["dapur"], view_only=True)
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["dapur", "kolam"]}


def test_suggestions_leave_out_other_owners_tags(
    client, database, existing, signed_in, make_user, make_property, make_room
):
    make_room(existing, number="A1", facilities=["ac"])
    theirs = make_property(make_user(), name="Theirs")
    make_room(theirs, number="A1", facilities=["secret"])
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["ac"]}


def test_suggestions_leave_out_deleted_rooms(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1", facilities=["ac"])
    make_room(existing, number="A2", facilities=["gone"], deleted=True)
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["ac"]}


def test_suggestions_leave_out_deleted_properties(
    client, database, owner, existing, signed_in, make_property, make_room
):
    make_room(existing, number="A1", facilities=["ac"])
    gone = make_property(owner, name="Gone", deleted=True)
    make_room(gone, number="A1", facilities=["gone"])
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["ac"]}


def test_deleting_the_only_room_with_a_tag_stops_suggesting_it(
    client, database, existing, signed_in, make_room
):
    only = make_room(existing, number="A1", facilities=["ac"])
    client.delete(room_url(only.id), headers=signed_in.headers)
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": []}


def test_tags_of_rooms_added_through_the_api_are_suggested_normalized(
    client, database, existing, signed_in
):
    create(client, signed_in.headers, existing.id, facilities=[" WiFi ", "AC"])
    response = suggestions(client, signed_in.headers, existing.id)
    assert response.json() == {"items": ["ac", "wifi"]}


def test_a_manager_gets_the_tags_of_all_the_owners_properties(
    client,
    database,
    owner,
    manager,
    manager_in,
    existing,
    make_property,
    make_room,
    assign_manager,
):
    assign_manager(manager, existing)
    make_room(existing, number="A1", facilities=["ac"])
    unassigned = make_property(owner, name="Unassigned")
    make_room(unassigned, number="A1", facilities=["kolam"])
    response = suggestions(client, manager_in.headers, existing.id)
    assert response.status_code == 200
    assert response.json() == {"items": ["ac", "kolam"]}


def test_a_manager_does_not_get_tags_of_other_owners(
    client,
    database,
    manager,
    manager_in,
    existing,
    make_user,
    make_property,
    make_room,
    assign_manager,
):
    assign_manager(manager, existing)
    make_room(existing, number="A1", facilities=["ac"])
    theirs = make_property(make_user(), name="Theirs")
    make_room(theirs, number="A1", facilities=["secret"])
    response = suggestions(client, manager_in.headers, existing.id)
    assert response.json() == {"items": ["ac"]}


def test_an_unassigned_manager_gets_no_suggestions(
    client, database, manager_in, existing, make_room
):
    make_room(existing, facilities=["ac"])
    response = suggestions(client, manager_in.headers, existing.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_suggestions_for_an_unknown_property_are_not_found(client, database, signed_in):
    response = suggestions(client, signed_in.headers, uuid4())
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_suggestions_for_another_owners_property_are_not_found(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_property(make_user(), name="Theirs")
    make_room(theirs, facilities=["ac"])
    response = suggestions(client, signed_in.headers, theirs.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_suggestions_for_a_deleted_property_are_not_found(
    client, database, owner, signed_in, make_property
):
    gone = make_property(owner, name="Gone", deleted=True)
    response = suggestions(client, signed_in.headers, gone.id)
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


def test_suggestions_with_a_malformed_property_id_are_a_validation_failure(
    client, database, signed_in
):
    response = suggestions(client, signed_in.headers, "not-a-uuid")
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


# GET /rooms/{roomId}


def test_an_owner_reads_a_room(client, database, existing, signed_in, make_room):
    row = make_room(
        existing,
        number="A1",
        base_rate=1250000,
        facilities=["ac"],
        length_m=Decimal("3.50"),
        width_m=Decimal("4.00"),
    )
    response = client.get(room_url(row.id), headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(row.id),
        "propertyId": str(existing.id),
        "number": "A1",
        "baseRate": 1250000,
        "occupancy": "vacant",
        "lengthM": 3.5,
        "widthM": 4,
        "facilities": ["ac"],
        "lease": None,
        "editable": True,
    }


def test_a_view_only_room_reads_as_not_editable(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, view_only=True)
    body = client.get(room_url(row.id), headers=signed_in.headers).json()
    assert body["editable"] is False


def test_a_room_of_a_view_only_property_reads_as_not_editable(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    row = make_room(frozen)
    body = client.get(room_url(row.id), headers=signed_in.headers).json()
    assert body["editable"] is False


def test_a_manager_reads_a_room_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    response = client.get(room_url(room.id), headers=manager_in.headers)
    assert response.status_code == 200
    assert set(response.json()) == ROOM_FIELDS
    assert response.json()["id"] == str(room.id)


def test_an_unassigned_manager_gets_room_not_found(client, database, manager_in, room):
    response = client.get(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_a_manager_loses_access_to_a_room_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    assert client.get(room_url(room.id), headers=manager_in.headers).status_code == 200
    unassign(database, manager, existing)
    response = client.get(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_an_unknown_room_is_not_found(client, database, signed_in, method):
    response = client.request(
        method, room_url(uuid4()), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_room_of_another_owners_property_is_not_found_and_untouched(
    client, database, signed_in, make_user, make_property, make_room, method
):
    theirs = make_room(make_property(make_user(), name="Theirs"), number="T1")
    response = client.request(
        method, room_url(theirs.id), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")
    row = stored_room(database, theirs.id)
    assert row.number == "T1"
    assert row.deleted_at is None


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_deleted_room_is_not_found(
    client, database, existing, signed_in, make_room, method
):
    gone = make_room(existing, deleted=True)
    response = client.request(
        method, room_url(gone.id), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_room_of_a_deleted_property_is_not_found(
    client, database, owner, signed_in, make_property, make_room, method
):
    gone = make_property(owner, name="Gone", deleted=True)
    row = make_room(gone)
    response = client.request(
        method, room_url(row.id), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 404, "ROOM_NOT_FOUND")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_a_malformed_room_id_is_a_validation_failure(
    client, database, signed_in, method
):
    response = client.request(
        method, room_url("not-a-uuid"), json=BODY, headers=signed_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "roomId")


# PUT /rooms/{roomId}


def test_an_owner_replaces_a_room(client, database, existing, signed_in, room):
    response = update(
        client,
        signed_in.headers,
        room.id,
        number="B2",
        baseRate=2000000,
        lengthM=5,
        widthM=2.25,
        facilities=["kasur"],
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(room.id),
        "propertyId": str(existing.id),
        "number": "B2",
        "baseRate": 2000000,
        "occupancy": "vacant",
        "lengthM": 5,
        "widthM": 2.25,
        "facilities": ["kasur"],
        "lease": None,
        "editable": True,
    }
    row = stored_room(database, room.id)
    assert (row.number, row.base_rate) == ("B2", 2000000)
    assert (row.length_m, row.width_m) == (Decimal("5.00"), Decimal("2.25"))
    assert row.facilities == ["kasur"]


def test_the_edit_can_be_read_back(client, database, signed_in, room):
    response = update(client, signed_in.headers, room.id, number="B2")
    assert client.get(room_url(room.id), headers=signed_in.headers).json() == (
        response.json()
    )


def test_an_edit_replaces_the_whole_room(
    client, database, existing, signed_in, make_room
):
    row = make_room(
        existing,
        facilities=["ac"],
        length_m=Decimal("3.00"),
        width_m=Decimal("3.00"),
    )
    response = client.put(
        room_url(row.id),
        json={"number": "A1", "baseRate": 900000},
        headers=signed_in.headers,
    )
    assert response.status_code == 200
    assert response.json()["lengthM"] is None
    assert response.json()["widthM"] is None
    assert response.json()["facilities"] == []
    stored = stored_room(database, row.id)
    assert stored.length_m is None
    assert stored.width_m is None
    assert stored.facilities == []


def test_an_edit_keeps_identity_property_and_flags(
    client, database, existing, signed_in, room
):
    update(client, signed_in.headers, room.id, number="B2")
    row = stored_room(database, room.id)
    assert row.id == room.id
    assert row.property_id == existing.id
    assert row.created_at == room.created_at
    assert row.view_only is False
    assert row.deleted_at is None


def test_an_edit_does_not_change_other_rooms(
    client, database, existing, signed_in, room, make_room
):
    other = make_room(existing, number="A2", base_rate=777, facilities=["x"])
    update(client, signed_in.headers, room.id, number="B2")
    row = stored_room(database, other.id)
    assert (row.number, row.base_rate, row.facilities) == ("A2", 777, ["x"])


def test_an_edit_may_keep_the_same_number(client, database, signed_in, room):
    response = update(client, signed_in.headers, room.id, number="A1", baseRate=5)
    assert response.status_code == 200
    assert stored_room(database, room.id).base_rate == 5


def test_an_edit_may_change_only_the_case_of_the_number(
    client, database, signed_in, room
):
    response = update(client, signed_in.headers, room.id, number="a1")
    assert response.status_code == 200
    assert stored_room(database, room.id).number == "a1"


def test_an_edit_may_not_take_the_number_of_another_room(
    client, database, existing, signed_in, room, make_room
):
    make_room(existing, number="A2")
    response = update(client, signed_in.headers, room.id, number=" a2 ")
    assert_error(response, 409, "ROOM_NUMBER_TAKEN", "number")
    assert stored_room(database, room.id).number == "A1"


def test_an_edit_may_take_the_number_of_a_deleted_room(
    client, database, existing, signed_in, room, make_room
):
    make_room(existing, number="A2", deleted=True)
    response = update(client, signed_in.headers, room.id, number="A2")
    assert response.status_code == 200


def test_an_edit_may_take_a_number_used_in_another_property(
    client, database, owner, signed_in, room, make_property, make_room
):
    make_room(make_property(owner, name="Other"), number="A2")
    response = update(client, signed_in.headers, room.id, number="A2")
    assert response.status_code == 200


def test_an_edit_is_not_subject_to_the_room_limit(
    client, database, existing, signed_in, room, make_room
):
    fill(existing, make_room, FREE_ROOM_LIMIT)
    response = update(client, signed_in.headers, room.id, baseRate=5)
    assert response.status_code == 200


def test_a_manager_edits_a_room_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    response = update(client, manager_in.headers, room.id, number="B2")
    assert response.status_code == 200
    assert stored_room(database, room.id).number == "B2"


def test_a_manager_cannot_edit_a_room_of_an_unassigned_property(
    client, database, manager_in, room
):
    response = update(client, manager_in.headers, room.id, number="B2")
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert stored_room(database, room.id).number == "A1"


def test_a_manager_loses_the_right_to_edit_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    assert update(client, manager_in.headers, room.id).status_code == 200
    unassign(database, manager, existing)
    response = update(client, manager_in.headers, room.id, number="B2")
    assert_error(response, 404, "ROOM_NOT_FOUND")


# PUT: view-only


def test_a_view_only_room_cannot_be_edited(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, view_only=True)
    response = update(client, signed_in.headers, row.id, number="B2")
    assert_error(response, 403, "ROOM_READ_ONLY")
    assert stored_room(database, row.id).number == "A1"


def test_a_room_of_a_view_only_property_cannot_be_edited(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    row = make_room(frozen)
    response = update(client, signed_in.headers, row.id, number="B2")
    assert_error(response, 403, "PROPERTY_READ_ONLY")
    assert stored_room(database, row.id).number == "A1"


def test_property_read_only_is_reported_before_room_read_only(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    row = make_room(frozen, view_only=True)
    response = update(client, signed_in.headers, row.id)
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_a_manager_cannot_edit_a_view_only_room(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    assign_manager(manager, existing)
    row = make_room(existing, view_only=True)
    response = update(client, manager_in.headers, row.id)
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_not_found_is_reported_before_read_only(
    client, database, signed_in, make_user, make_property, make_room
):
    theirs = make_room(
        make_property(make_user(), view_only=True), number="T1", view_only=True
    )
    response = update(client, signed_in.headers, theirs.id)
    assert_error(response, 404, "ROOM_NOT_FOUND")


def test_read_only_is_reported_before_field_rules(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, view_only=True)
    response = update(client, signed_in.headers, row.id, number=" ")
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_property_read_only_is_reported_before_field_rules(
    client, database, owner, signed_in, make_property, make_room
):
    row = make_room(make_property(owner, view_only=True))
    response = update(client, signed_in.headers, row.id, number=" ")
    assert_error(response, 403, "PROPERTY_READ_ONLY")


def test_read_only_is_reported_before_a_taken_number(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, number="A1", view_only=True)
    make_room(existing, number="A2")
    response = update(client, signed_in.headers, row.id, number="A2")
    assert_error(response, 403, "ROOM_READ_ONLY")


def test_field_rules_are_reported_before_a_taken_number_on_edit(
    client, database, existing, signed_in, room, make_room
):
    make_room(existing, number="A2")
    response = update(
        client, signed_in.headers, room.id, number="A2", facilities=["a" * 31]
    )
    assert_error(response, 422, "VALIDATION_FAILED", "facilities")


# DELETE /rooms/{roomId}


def test_deleting_a_room_answers_with_an_empty_body(client, database, signed_in, room):
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert response.content == b""


def test_deleting_marks_the_row_instead_of_removing_it(
    client, database, signed_in, room
):
    before = datetime.now(UTC)
    client.delete(room_url(room.id), headers=signed_in.headers)
    after = datetime.now(UTC)
    row = stored_room(database, room.id)
    assert row is not None
    assert before <= row.deleted_at <= after
    assert row.number == "A1"


def test_a_deleted_room_leaves_the_list_and_the_detail(
    client, database, existing, signed_in, room
):
    client.delete(room_url(room.id), headers=signed_in.headers)
    listing = client.get(rooms_url(existing.id), headers=signed_in.headers)
    assert listing.json() == {"items": []}
    assert_error(
        client.get(room_url(room.id), headers=signed_in.headers),
        404,
        "ROOM_NOT_FOUND",
    )


def test_deleting_leaves_other_rooms(
    client, database, existing, signed_in, room, make_room
):
    kept = make_room(existing, number="A2")
    client.delete(room_url(room.id), headers=signed_in.headers)
    assert stored_room(database, kept.id).deleted_at is None
    items = client.get(rooms_url(existing.id), headers=signed_in.headers).json()
    assert [i["id"] for i in items["items"]] == [str(kept.id)]


def test_deleting_a_room_a_second_time_is_not_found(client, database, signed_in, room):
    first = client.delete(room_url(room.id), headers=signed_in.headers)
    assert first.status_code == 204
    stamp = stored_room(database, room.id).deleted_at
    response = client.delete(room_url(room.id), headers=signed_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert stored_room(database, room.id).deleted_at == stamp


def test_a_view_only_room_can_be_deleted(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, view_only=True)
    response = client.delete(room_url(row.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_room(database, row.id).deleted_at is not None


def test_a_room_of_a_view_only_property_can_be_deleted(
    client, database, owner, signed_in, make_property, make_room
):
    row = make_room(make_property(owner, view_only=True))
    response = client.delete(room_url(row.id), headers=signed_in.headers)
    assert response.status_code == 204
    assert stored_room(database, row.id).deleted_at is not None


def test_a_manager_deletes_a_room_of_an_assigned_property(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert response.status_code == 204
    assert stored_room(database, room.id).deleted_at is not None


def test_a_manager_cannot_delete_a_room_of_an_unassigned_property(
    client, database, manager_in, room
):
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert stored_room(database, room.id).deleted_at is None


def test_a_manager_loses_the_right_to_delete_as_soon_as_unassigned(
    client, database, manager, manager_in, existing, room, assign_manager
):
    assign_manager(manager, existing)
    unassign(database, manager, existing)
    response = client.delete(room_url(room.id), headers=manager_in.headers)
    assert_error(response, 404, "ROOM_NOT_FOUND")
    assert stored_room(database, room.id).deleted_at is None


# Room counts on properties


def property_detail(client, headers, property_id):
    return client.get(f"{PROPERTIES}/{property_id}", headers=headers).json()


def property_list(client, headers):
    return client.get(PROPERTIES, headers=headers).json()["items"]


def test_the_detail_counts_the_rooms_of_the_property(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1")
    make_room(existing, number="A2")
    body = property_detail(client, signed_in.headers, existing.id)
    assert body["roomCount"] == 2
    assert body["occupiedRoomCount"] == 0
    assert body["vacantRoomCount"] == 2


def test_the_list_counts_the_rooms_of_each_property(
    client, database, owner, existing, signed_in, make_property, make_room
):
    subscribe(database, owner, "pro")
    other = make_property(owner, name="Other")
    make_room(existing, number="A1")
    make_room(existing, number="A2")
    make_room(existing, number="A3")
    make_room(other, number="B1")
    items = property_list(client, signed_in.headers)
    counts = {i["name"]: (i["roomCount"], i["occupiedRoomCount"]) for i in items}
    assert counts == {"Kos Melati": (3, 0), "Other": (1, 0)}


def test_a_property_without_rooms_counts_zero(client, database, existing, signed_in):
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["vacantRoomCount"]) == (0, 0)
    (item,) = property_list(client, signed_in.headers)
    assert item["roomCount"] == 0


def test_deleted_rooms_are_not_counted(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1")
    make_room(existing, number="A2", deleted=True)
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["vacantRoomCount"]) == (1, 1)
    (item,) = property_list(client, signed_in.headers)
    assert item["roomCount"] == 1


def test_view_only_rooms_are_counted(client, database, existing, signed_in, make_room):
    make_room(existing, number="A1", view_only=True)
    body = property_detail(client, signed_in.headers, existing.id)
    assert body["roomCount"] == 1


def test_the_counts_follow_rooms_added_and_deleted_through_the_api(
    client, database, existing, signed_in
):
    first = create(client, signed_in.headers, existing.id, number="A1").json()
    create(client, signed_in.headers, existing.id, number="A2")
    assert property_detail(client, signed_in.headers, existing.id)["roomCount"] == 2
    client.delete(room_url(first["id"]), headers=signed_in.headers)
    body = property_detail(client, signed_in.headers, existing.id)
    assert (body["roomCount"], body["vacantRoomCount"]) == (1, 1)


def test_a_manager_sees_the_room_counts_of_an_assigned_property(
    client, database, manager, manager_in, existing, make_room, assign_manager
):
    assign_manager(manager, existing)
    make_room(existing, number="A1")
    make_room(existing, number="A2")
    body = property_detail(client, manager_in.headers, existing.id)
    assert (body["roomCount"], body["vacantRoomCount"]) == (2, 2)
    (item,) = property_list(client, manager_in.headers)
    assert item["roomCount"] == 2


def test_editing_a_property_answers_with_its_room_counts(
    client, database, existing, signed_in, make_room
):
    make_room(existing, number="A1")
    make_room(existing, number="A2")
    response = client.put(
        f"{PROPERTIES}/{existing.id}",
        json={"name": "Kos Melati", "address": "Jl. Baru 1"},
        headers=signed_in.headers,
    )
    assert response.status_code == 200
    assert response.json()["roomCount"] == 2
    assert response.json()["vacantRoomCount"] == 2


# DELETE /properties/{propertyId} deletes the rooms


def test_deleting_a_property_deletes_its_rooms(
    client, database, existing, signed_in, make_room
):
    first = make_room(existing, number="A1")
    second = make_room(existing, number="A2", view_only=True)
    before = datetime.now(UTC)
    response = client.delete(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    after = datetime.now(UTC)
    assert response.status_code == 204
    for room_id in (first.id, second.id):
        row = stored_room(database, room_id)
        assert row is not None
        assert before <= row.deleted_at <= after


def test_deleting_a_property_leaves_the_rooms_of_other_properties(
    client, database, owner, existing, signed_in, make_property, make_room
):
    subscribe(database, owner, "pro")
    kept_property = make_property(owner, name="Kept")
    kept = make_room(kept_property, number="A1")
    make_room(existing, number="A1")
    client.delete(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    assert stored_room(database, kept.id).deleted_at is None
    items = client.get(rooms_url(kept_property.id), headers=signed_in.headers).json()
    assert [i["id"] for i in items["items"]] == [str(kept.id)]


def test_deleting_a_property_leaves_other_owners_rooms(
    client, database, existing, signed_in, make_user, make_property, make_room
):
    theirs = make_room(make_property(make_user(), name="Theirs"), number="A1")
    make_room(existing, number="A1")
    client.delete(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    assert stored_room(database, theirs.id).deleted_at is None


def test_the_rooms_of_a_deleted_property_are_no_longer_reachable(
    client, database, existing, signed_in, make_room
):
    row = make_room(existing, number="A1", facilities=["ac"])
    client.delete(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    assert_error(
        client.get(room_url(row.id), headers=signed_in.headers),
        404,
        "ROOM_NOT_FOUND",
    )
    assert_error(
        client.get(rooms_url(existing.id), headers=signed_in.headers),
        404,
        "PROPERTY_NOT_FOUND",
    )


def test_the_tags_of_a_deleted_propertys_rooms_are_no_longer_suggested(
    client, database, owner, existing, signed_in, make_property, make_room
):
    subscribe(database, owner, "pro")
    other = make_property(owner, name="Other")
    make_room(existing, number="A1", facilities=["gone"])
    make_room(other, number="A1", facilities=["kept"])
    client.delete(f"{PROPERTIES}/{existing.id}", headers=signed_in.headers)
    response = suggestions(client, signed_in.headers, other.id)
    assert response.json() == {"items": ["kept"]}


def test_deleting_a_property_deletes_rooms_that_were_view_only(
    client, database, owner, signed_in, make_property, make_room
):
    frozen = make_property(owner, view_only=True)
    row = make_room(frozen, view_only=True)
    client.delete(f"{PROPERTIES}/{frozen.id}", headers=signed_in.headers)
    assert stored_room(database, row.id).deleted_at is not None
