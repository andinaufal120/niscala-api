"""The `properties` and `manager_assignments` tables and their models."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


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


def saved_user(db_session, **overrides):
    user = new_user(**overrides)
    db_session.add(user)
    db_session.flush()
    return user


def saved_property(db_session, **overrides):
    owner = saved_user(db_session)
    row = new_property(owner.id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def test_models_are_registered_on_the_metadata():
    from app.models import Base

    assert {"properties", "manager_assignments"} <= set(Base.metadata.tables)


def test_models_use_the_expected_table_names():
    from app.models import ManagerAssignment, Property

    assert Property.__tablename__ == "properties"
    assert ManagerAssignment.__tablename__ == "manager_assignments"


def test_property_gets_defaults_on_insert(db_session):
    owner = saved_user(db_session)
    before = datetime.now(UTC)
    row = new_property(owner.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.view_only is False
    assert row.deleted_at is None
    assert row.created_at.tzinfo is not None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_property_ids_are_unique_per_row(db_session):
    owner = saved_user(db_session)
    first = new_property(owner.id, name="Kos Melati")
    second = new_property(owner.id, name="Kos Mawar")
    db_session.add_all([first, second])
    db_session.flush()
    assert first.id != second.id


def test_property_round_trips_its_fields(db_session):
    owner = saved_user(db_session)
    deleted = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = new_property(
        owner.id,
        name="Kos Mawar",
        address="Jl. Mawar 1",
        view_only=True,
        deleted_at=deleted,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.owner_id == owner.id
    assert stored.name == "Kos Mawar"
    assert stored.address == "Jl. Mawar 1"
    assert stored.view_only is True
    assert stored.deleted_at == deleted


def test_property_requires_an_existing_owner(db_session):
    db_session.add(new_property(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["owner_id", "name", "address", "view_only"])
def test_property_requires_its_mandatory_columns(db_session, field):
    owner = saved_user(db_session)
    db_session.add(new_property(**{"owner_id": owner.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bank_account_columns_default_to_null(db_session):
    row = saved_property(db_session)
    db_session.refresh(row)
    assert row.bank_name is None
    assert row.bank_account_number is None
    assert row.bank_account_holder_name is None


def test_bank_account_columns_round_trip(db_session):
    owner = saved_user(db_session)
    row = new_property(
        owner.id,
        bank_name="BCA",
        bank_account_number="1234567890",
        bank_account_holder_name="Budi Santoso",
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.bank_name == "BCA"
    assert stored.bank_account_number == "1234567890"
    assert stored.bank_account_holder_name == "Budi Santoso"


def test_owner_cannot_have_two_properties_with_the_same_name(db_session):
    owner = saved_user(db_session)
    db_session.add(new_property(owner.id, name="Kos Melati"))
    db_session.flush()
    db_session.add(new_property(owner.id, name="Kos Melati"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Kos Melati", "kos melati"),
        ("kos melati", "KOS MELATI"),
        ("KOS MELATI", "Kos Melati"),
    ],
)
def test_property_names_are_compared_ignoring_case(db_session, first, second):
    owner = saved_user(db_session)
    db_session.add(new_property(owner.id, name=first))
    db_session.flush()
    db_session.add(new_property(owner.id, name=second))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_different_names_of_one_owner_do_not_conflict(db_session):
    owner = saved_user(db_session)
    db_session.add_all(
        [
            new_property(owner.id, name="Kos Melati"),
            new_property(owner.id, name="Kos 2"),
        ]
    )
    db_session.flush()


def test_different_owners_may_use_the_same_name(db_session):
    first, second = saved_user(db_session), saved_user(db_session)
    db_session.add_all(
        [
            new_property(first.id, name="Kos Melati"),
            new_property(second.id, name="kos melati"),
        ]
    )
    db_session.flush()


def test_a_deleted_property_does_not_block_its_name(db_session):
    owner = saved_user(db_session)
    db_session.add(
        new_property(owner.id, name="Kos Melati", deleted_at=datetime.now(UTC))
    )
    db_session.flush()
    db_session.add(new_property(owner.id, name="kos melati"))
    db_session.flush()


def test_several_deleted_properties_may_share_a_name(db_session):
    owner = saved_user(db_session)
    db_session.add_all(
        [
            new_property(owner.id, name="Kos Melati", deleted_at=datetime.now(UTC)),
            new_property(owner.id, name="Kos Melati", deleted_at=datetime.now(UTC)),
        ]
    )
    db_session.flush()


def test_a_live_property_still_blocks_the_name_of_a_deleted_one_being_restored(
    db_session,
):
    owner = saved_user(db_session)
    gone = new_property(owner.id, name="Kos Melati", deleted_at=datetime.now(UTC))
    db_session.add_all([gone, new_property(owner.id, name="Kos Melati")])
    db_session.flush()
    gone.deleted_at = None
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_renaming_a_property_to_a_taken_name_is_refused(db_session):
    owner = saved_user(db_session)
    db_session.add(new_property(owner.id, name="Kos Melati"))
    other = new_property(owner.id, name="Kos Mawar")
    db_session.add(other)
    db_session.flush()
    other.name = "KOS MELATI"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manager_assignment_round_trips_with_a_creation_time(db_session):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    row = saved_property(db_session)
    manager = saved_user(db_session, role=UserRole.MANAGER)
    before = datetime.now(UTC)
    db_session.add(ManagerAssignment(manager_id=manager.id, property_id=row.id))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ManagerAssignment, (manager.id, row.id))
    assert stored.manager_id == manager.id
    assert stored.property_id == row.id
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= stored.created_at <= datetime.now(UTC)


def test_manager_cannot_be_assigned_twice_to_the_same_property(db_session):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    row = saved_property(db_session)
    manager = saved_user(db_session, role=UserRole.MANAGER)
    db_session.add(ManagerAssignment(manager_id=manager.id, property_id=row.id))
    db_session.flush()
    db_session.expunge_all()
    db_session.add(ManagerAssignment(manager_id=manager.id, property_id=row.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manager_can_be_assigned_to_several_properties(db_session):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    first, second = saved_property(db_session), saved_property(db_session)
    manager = saved_user(db_session, role=UserRole.MANAGER)
    db_session.add_all(
        [
            ManagerAssignment(manager_id=manager.id, property_id=first.id),
            ManagerAssignment(manager_id=manager.id, property_id=second.id),
        ]
    )
    db_session.flush()
    count = len(db_session.scalars(select(ManagerAssignment)).all())
    assert count == 2


def test_property_can_have_several_managers(db_session):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    row = saved_property(db_session)
    one = saved_user(db_session, role=UserRole.MANAGER)
    two = saved_user(db_session, role=UserRole.MANAGER)
    db_session.add_all(
        [
            ManagerAssignment(manager_id=one.id, property_id=row.id),
            ManagerAssignment(manager_id=two.id, property_id=row.id),
        ]
    )
    db_session.flush()


def test_manager_assignment_requires_an_existing_manager(db_session):
    from app.models import ManagerAssignment

    row = saved_property(db_session)
    db_session.add(ManagerAssignment(manager_id=uuid4(), property_id=row.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manager_assignment_requires_an_existing_property(db_session):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    manager = saved_user(db_session, role=UserRole.MANAGER)
    db_session.add(ManagerAssignment(manager_id=manager.id, property_id=uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["manager_id", "property_id"])
def test_manager_assignment_requires_both_keys(db_session, field):
    from app.models import ManagerAssignment
    from app.schemas.auth import UserRole

    row = saved_property(db_session)
    manager = saved_user(db_session, role=UserRole.MANAGER)
    keys = {"manager_id": manager.id, "property_id": row.id, field: None}
    db_session.add(ManagerAssignment(**keys))
    with pytest.raises(SQLAlchemyError):
        db_session.flush()
