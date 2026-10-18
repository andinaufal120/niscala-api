"""The `rooms` table and its model."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError


def new_user(**overrides):
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    fields = {
        "name": "Rina Owner",
        "email": f"{uuid4().hex}@example.com",
        "password_hash": None,
        "role": UserRole.OWNER,
    }
    return UserAccount(**{**fields, **overrides})


def new_property(owner_id, **overrides):
    from app.models import Property

    fields = {"owner_id": owner_id, "name": "Kos Melati", "address": "Jl. Melati 5"}
    return Property(**{**fields, **overrides})


def new_room(property_id, **overrides):
    from app.models import Room

    fields = {"property_id": property_id, "number": "A1", "base_rate": 1500000}
    return Room(**{**fields, **overrides})


def saved_property(db_session, **overrides):
    owner = new_user()
    db_session.add(owner)
    db_session.flush()
    row = new_property(owner.id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def saved_room(db_session, property_id=None, **overrides):
    if property_id is None:
        property_id = saved_property(db_session).id
    row = new_room(property_id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def test_room_is_registered_on_the_metadata():
    from app.models import Base

    assert "rooms" in Base.metadata.tables


def test_room_uses_the_expected_table_name():
    from app.models import Room

    assert Room.__tablename__ == "rooms"


def test_room_gets_defaults_on_insert(db_session):
    prop = saved_property(db_session)
    before = datetime.now(UTC)
    row = saved_room(db_session, prop.id)
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.view_only is False
    assert row.deleted_at is None
    assert row.length_m is None
    assert row.width_m is None
    assert row.facilities == []
    assert row.created_at.tzinfo is not None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_room_ids_are_unique_per_row(db_session):
    prop = saved_property(db_session)
    first = saved_room(db_session, prop.id, number="A1")
    second = saved_room(db_session, prop.id, number="A2")
    assert first.id != second.id


def test_room_round_trips_its_fields(db_session):
    prop = saved_property(db_session)
    deleted = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = new_room(
        prop.id,
        number="B7",
        base_rate=2000000,
        length_m=Decimal("3.50"),
        width_m=Decimal("4.25"),
        facilities=["ac", "wifi"],
        view_only=True,
        deleted_at=deleted,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.property_id == prop.id
    assert stored.number == "B7"
    assert stored.base_rate == 2000000
    assert stored.length_m == Decimal("3.50")
    assert stored.width_m == Decimal("4.25")
    assert stored.facilities == ["ac", "wifi"]
    assert stored.view_only is True
    assert stored.deleted_at == deleted


@pytest.mark.parametrize(
    "facilities",
    [[], ["ac"], ["kamar mandi dalam", "air panas", "ac"], ["b", "a", "b"]],
)
def test_facilities_round_trip_in_order(db_session, facilities):
    prop = saved_property(db_session)
    row = saved_room(db_session, prop.id, facilities=facilities)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(type(row), row.id).facilities == facilities


def test_room_requires_an_existing_property(db_session):
    db_session.add(new_room(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field", ["property_id", "number", "base_rate", "facilities", "view_only"]
)
def test_room_requires_its_mandatory_columns(db_session, field):
    prop = saved_property(db_session)
    db_session.add(new_room(**{"property_id": prop.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("value", [0, -1])
def test_base_rate_must_be_positive(db_session, value):
    prop = saved_property(db_session)
    db_session.add(new_room(prop.id, base_rate=value))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["length_m", "width_m"])
@pytest.mark.parametrize("value", [Decimal(0), Decimal("-1.5")])
def test_dimensions_must_be_positive_when_set(db_session, field, value):
    prop = saved_property(db_session)
    db_session.add(new_room(prop.id, **{field: value}))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["length_m", "width_m"])
@pytest.mark.parametrize("value", [Decimal("0.01"), Decimal("20.00"), None])
def test_dimensions_accept_the_range_limits_and_null(db_session, field, value):
    prop = saved_property(db_session)
    row = saved_room(db_session, prop.id, **{field: value})
    db_session.refresh(row)
    assert getattr(row, field) == value


@pytest.mark.parametrize("field", ["length_m", "width_m"])
def test_dimensions_keep_two_decimals(db_session, field):
    prop = saved_property(db_session)
    row = saved_room(db_session, prop.id, **{field: Decimal("2.5")})
    db_session.refresh(row)
    assert getattr(row, field) == Decimal("2.50")
    assert getattr(row, field).as_tuple().exponent == -2


@pytest.mark.parametrize("field", ["length_m", "width_m"])
def test_dimensions_hold_values_up_to_twenty(db_session, field):
    prop = saved_property(db_session)
    db_session.add(new_room(prop.id, **{field: Decimal("20.00")}))
    db_session.flush()


def test_property_cannot_have_two_rooms_with_the_same_number(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1")
    db_session.add(new_room(prop.id, number="A1"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("first", "second"), [("A1", "a1"), ("a1", "A1"), ("Lt 2", "LT 2")]
)
def test_room_numbers_are_compared_ignoring_case(db_session, first, second):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number=first)
    db_session.add(new_room(prop.id, number=second))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_different_numbers_of_one_property_do_not_conflict(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1")
    saved_room(db_session, prop.id, number="A2")


def test_different_properties_may_reuse_a_number(db_session):
    first, second = saved_property(db_session), saved_property(db_session)
    saved_room(db_session, first.id, number="A1")
    saved_room(db_session, second.id, number="a1")


def test_a_deleted_room_does_not_block_its_number(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1", deleted_at=datetime.now(UTC))
    saved_room(db_session, prop.id, number="a1")


def test_several_deleted_rooms_may_share_a_number(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1", deleted_at=datetime.now(UTC))
    saved_room(db_session, prop.id, number="A1", deleted_at=datetime.now(UTC))


def test_a_view_only_room_still_holds_its_number(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1", view_only=True)
    db_session.add(new_room(prop.id, number="A1"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_restoring_a_deleted_room_onto_a_taken_number_is_refused(db_session):
    prop = saved_property(db_session)
    gone = saved_room(db_session, prop.id, number="A1", deleted_at=datetime.now(UTC))
    saved_room(db_session, prop.id, number="A1")
    gone.deleted_at = None
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_renaming_a_room_to_a_taken_number_is_refused(db_session):
    prop = saved_property(db_session)
    saved_room(db_session, prop.id, number="A1")
    other = saved_room(db_session, prop.id, number="A2")
    other.number = "a1"
    with pytest.raises(IntegrityError):
        db_session.flush()
