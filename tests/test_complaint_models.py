"""The `complaints` and `complaint_status_changes` tables and their models."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def seed_room(db_session):
    """Insert an owner, property, room and tenant; return `(tenant_id, room_id)`."""
    from app.models import Property, Room, Tenant, UserAccount
    from app.schemas.auth import UserRole

    owner = UserAccount(
        name="Rina Owner",
        email=f"{uuid4().hex}@example.com",
        password_hash=None,
        role=UserRole.OWNER,
    )
    user = UserAccount(
        name="Budi Tenant",
        email=f"{uuid4().hex}@example.com",
        password_hash=None,
        role=UserRole.TENANT,
    )
    db_session.add_all([owner, user])
    db_session.flush()
    prop = Property(owner_id=owner.id, name="Kos Melati", address="Jl. Melati 5")
    db_session.add_all([prop, Tenant(user_id=user.id, phone="081234567890")])
    db_session.flush()
    room = Room(property_id=prop.id, number="A1", base_rate=1000000)
    db_session.add(room)
    db_session.flush()
    return user.id, room.id


def new_complaint(tenant_id, room_id, **overrides):
    from app.models import Complaint

    fields = {
        "tenant_id": tenant_id,
        "room_id": room_id,
        "description": "The tap in the bathroom leaks badly.",
        "status": "new",
    }
    return Complaint(**{**fields, **overrides})


def saved_complaint(db_session, **overrides):
    tenant_id, room_id = seed_room(db_session)
    row = new_complaint(tenant_id, room_id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def insert_complaint_sql(db_session, **overrides):
    """Insert a complaint with raw SQL, bypassing any ORM-side validation."""
    tenant_id, room_id = seed_room(db_session)
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "room_id": room_id,
        "description": "The tap in the bathroom leaks badly.",
        "status": "new",
        "classification_state": None,
        "ai_category": None,
        "ai_urgency": None,
        "ai_suggested_action": None,
        **overrides,
    }
    db_session.execute(
        text(
            "INSERT INTO complaints (id, tenant_id, room_id, description, status, "
            "classification_state, ai_category, ai_urgency, ai_suggested_action, "
            "created_at) VALUES (:id, :tenant_id, :room_id, :description, :status, "
            ":classification_state, :ai_category, :ai_urgency, "
            ":ai_suggested_action, now())"
        ),
        values,
    )


def insert_status_change_sql(db_session, complaint_id, **overrides):
    values = {
        "id": uuid4(),
        "complaint_id": complaint_id,
        "status": "new",
        "handling_note": None,
        **overrides,
    }
    db_session.execute(
        text(
            "INSERT INTO complaint_status_changes "
            "(id, complaint_id, status, handling_note, changed_at) "
            "VALUES (:id, :complaint_id, :status, :handling_note, now())"
        ),
        values,
    )


def test_tables_are_created_by_the_migrations(database):
    names = inspect(database).get_table_names()
    assert "complaints" in names
    assert "complaint_status_changes" in names


def test_models_are_registered_on_the_metadata():
    from app.models import Base

    assert "complaints" in Base.metadata.tables
    assert "complaint_status_changes" in Base.metadata.tables


def test_models_use_the_expected_table_names():
    from app.models import Complaint, ComplaintStatusChange

    assert Complaint.__tablename__ == "complaints"
    assert ComplaintStatusChange.__tablename__ == "complaint_status_changes"


def test_complaint_gets_defaults_on_insert(db_session):
    before = datetime.now(UTC)
    row = saved_complaint(db_session)
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.classification_state is None
    assert row.ai_category is None
    assert row.ai_urgency is None
    assert row.ai_suggested_action is None
    assert row.created_at.tzinfo is not None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_complaint_ids_are_unique_per_row(db_session):
    tenant_id, room_id = seed_room(db_session)
    first = new_complaint(tenant_id, room_id)
    second = new_complaint(tenant_id, room_id)
    db_session.add_all([first, second])
    db_session.flush()
    assert first.id != second.id


def test_complaint_round_trips_its_fields(db_session):
    tenant_id, room_id = seed_room(db_session)
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = new_complaint(
        tenant_id,
        room_id,
        description="Lampu kamar mati total.",
        status="inProgress",
        classification_state="awaitingClassification",
        ai_category="Listrik",
        ai_urgency="high",
        ai_suggested_action="Call an electrician.",
        created_at=created,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.tenant_id == tenant_id
    assert stored.room_id == room_id
    assert stored.description == "Lampu kamar mati total."
    assert stored.status == "inProgress"
    assert stored.classification_state == "awaitingClassification"
    assert stored.ai_category == "Listrik"
    assert stored.ai_urgency == "high"
    assert stored.ai_suggested_action == "Call an electrician."
    assert stored.created_at == created


def test_tenant_may_have_several_complaints_in_one_room(db_session):
    tenant_id, room_id = seed_room(db_session)
    db_session.add_all(
        [new_complaint(tenant_id, room_id), new_complaint(tenant_id, room_id)]
    )
    db_session.flush()


def test_complaint_requires_an_existing_tenant(db_session):
    _, room_id = seed_room(db_session)
    db_session.add(new_complaint(uuid4(), room_id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_complaint_requires_an_existing_room(db_session):
    tenant_id, _ = seed_room(db_session)
    db_session.add(new_complaint(tenant_id, uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["tenant_id", "room_id", "description", "status"])
def test_complaint_requires_its_mandatory_columns(db_session, field):
    tenant_id, room_id = seed_room(db_session)
    fields = {"tenant_id": tenant_id, "room_id": room_id, field: None}
    db_session.add(new_complaint(**fields))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("status", ["new", "inProgress", "done"])
def test_complaint_accepts_each_status(db_session, status):
    insert_complaint_sql(db_session, status=status)


@pytest.mark.parametrize("status", ["", "closed", "NEW", "in_progress", "new_"])
def test_complaint_refuses_an_unknown_status(db_session, status):
    with pytest.raises(IntegrityError):
        insert_complaint_sql(db_session, status=status)


@pytest.mark.parametrize(
    "state", [None, "classifying", "awaitingClassification", "notClassified"]
)
def test_complaint_accepts_each_classification_state_and_null(db_session, state):
    insert_complaint_sql(db_session, classification_state=state)


@pytest.mark.parametrize("state", ["", "classified", "CLASSIFYING", "not_classified"])
def test_complaint_refuses_an_unknown_classification_state(db_session, state):
    with pytest.raises(IntegrityError):
        insert_complaint_sql(db_session, classification_state=state)


@pytest.mark.parametrize("urgency", [None, "low", "medium", "high"])
def test_complaint_accepts_each_ai_urgency_and_null(db_session, urgency):
    insert_complaint_sql(db_session, ai_urgency=urgency)


@pytest.mark.parametrize("urgency", ["", "critical", "HIGH", "urgent"])
def test_complaint_refuses_an_unknown_ai_urgency(db_session, urgency):
    with pytest.raises(IntegrityError):
        insert_complaint_sql(db_session, ai_urgency=urgency)


# Status changes


def test_status_change_gets_defaults_on_insert(db_session):
    complaint = saved_complaint(db_session)
    before = datetime.now(UTC)
    from app.models import ComplaintStatusChange

    row = ComplaintStatusChange(complaint_id=complaint.id, status="new")
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.handling_note is None
    assert row.changed_at.tzinfo is not None
    assert row.changed_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.changed_at <= datetime.now(UTC)


def test_status_change_round_trips_its_fields(db_session):
    from app.models import ComplaintStatusChange

    complaint = saved_complaint(db_session)
    changed = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    row = ComplaintStatusChange(
        complaint_id=complaint.id,
        status="inProgress",
        handling_note="Technician scheduled.",
        changed_at=changed,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ComplaintStatusChange, row.id)
    assert stored.complaint_id == complaint.id
    assert stored.status == "inProgress"
    assert stored.handling_note == "Technician scheduled."
    assert stored.changed_at == changed


def test_status_change_requires_an_existing_complaint(db_session):
    from app.models import ComplaintStatusChange

    db_session.add(ComplaintStatusChange(complaint_id=uuid4(), status="new"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["complaint_id", "status"])
def test_status_change_requires_its_mandatory_columns(db_session, field):
    from app.models import ComplaintStatusChange

    complaint = saved_complaint(db_session)
    fields = {"complaint_id": complaint.id, "status": "new", field: None}
    db_session.add(ComplaintStatusChange(**fields))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("status", ["new", "inProgress", "done"])
def test_status_change_accepts_each_status(db_session, status):
    complaint = saved_complaint(db_session)
    insert_status_change_sql(db_session, complaint.id, status=status)


@pytest.mark.parametrize("status", ["", "closed", "NEW", "in_progress"])
def test_status_change_refuses_an_unknown_status(db_session, status):
    complaint = saved_complaint(db_session)
    with pytest.raises(IntegrityError):
        insert_status_change_sql(db_session, complaint.id, status=status)


def test_complaint_may_have_several_status_changes(db_session):
    complaint = saved_complaint(db_session)
    insert_status_change_sql(db_session, complaint.id, status="new")
    insert_status_change_sql(db_session, complaint.id, status="inProgress")
    insert_status_change_sql(db_session, complaint.id, status="done")
