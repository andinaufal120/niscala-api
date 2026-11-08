"""The `complaint_photos` table and its model."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def complaint(
    make_user, make_property, make_room, make_verified_tenant, make_complaint
):
    room = make_room(make_property(make_user()))
    return make_complaint(make_verified_tenant(room), room)


def new_photo(complaint_id, **overrides):
    from app.models.complaints import ComplaintPhoto

    fields = {
        "complaint_id": complaint_id,
        "storage_key": f"complaint-photos/{complaint_id}/{uuid4()}",
        "content_type": "image/png",
        "uploaded_at": datetime.now(UTC),
    }
    return ComplaintPhoto(**{**fields, **overrides})


def test_the_model_uses_the_expected_table_name():
    from app.models.complaints import ComplaintPhoto

    assert ComplaintPhoto.__tablename__ == "complaint_photos"


def test_the_model_is_registered_on_the_metadata():
    from app.models import Base
    from app.models.complaints import ComplaintPhoto

    assert Base.metadata.tables["complaint_photos"] is ComplaintPhoto.__table__


def test_the_model_is_exported_from_the_models_package():
    from app import models
    from app.models.complaints import ComplaintPhoto

    assert models.ComplaintPhoto is ComplaintPhoto


def test_the_table_is_created_by_the_migrations(database):
    assert "complaint_photos" in inspect(database).get_table_names()


def test_the_table_has_its_columns(database):
    columns = {c["name"]: c for c in inspect(database).get_columns("complaint_photos")}
    assert set(columns) == {
        "complaint_id",
        "storage_key",
        "content_type",
        "uploaded_at",
    }
    assert all(not c["nullable"] for c in columns.values())


def test_the_model_has_no_content_attribute():
    from app.models.complaints import ComplaintPhoto

    assert not hasattr(ComplaintPhoto, "content")
    assert "content" not in ComplaintPhoto.__table__.c


def test_the_storage_key_is_unique(
    db_session,
    complaint,
    make_complaint,
    make_verified_tenant,
    make_room,
    make_property,
    make_user,
):
    room = make_room(make_property(make_user(name="Other Owner")), number="Z1")
    other = make_complaint(make_verified_tenant(room), room)
    db_session.add(new_photo(complaint.id, storage_key="complaint-photos/shared"))
    db_session.commit()
    db_session.add(new_photo(other.id, storage_key="complaint-photos/shared"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_the_complaint_id_is_the_primary_key(database):
    keys = inspect(database).get_pk_constraint("complaint_photos")
    assert keys["constrained_columns"] == ["complaint_id"]


def test_the_complaint_id_references_complaints(database):
    (key,) = inspect(database).get_foreign_keys("complaint_photos")
    assert key["constrained_columns"] == ["complaint_id"]
    assert key["referred_table"] == "complaints"
    assert key["referred_columns"] == ["id"]


def test_a_photo_keeps_its_storage_key_and_type(db_session, complaint):
    from app.models.complaints import ComplaintPhoto

    key = f"complaint-photos/{complaint.id}/{uuid4()}"
    db_session.add(new_photo(complaint.id, storage_key=key, content_type="image/jpeg"))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ComplaintPhoto, complaint.id)
    assert stored.storage_key == key
    assert stored.content_type == "image/jpeg"


def test_the_upload_time_is_timezone_aware(db_session, complaint):
    from app.models.complaints import ComplaintPhoto

    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    db_session.add(new_photo(complaint.id, uploaded_at=moment))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(ComplaintPhoto, complaint.id)
    assert stored.uploaded_at.tzinfo is not None
    assert stored.uploaded_at == moment


def test_a_complaint_has_at_most_one_photo(db_session, complaint):
    from app.models.complaints import ComplaintPhoto

    db_session.add(new_photo(complaint.id))
    db_session.commit()
    db_session.add(new_photo(complaint.id, content_type="image/jpeg"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert len(list(db_session.scalars(select(ComplaintPhoto)))) == 1


def test_a_photo_needs_an_existing_complaint(db_session):
    db_session.add(new_photo(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("column", ["storage_key", "content_type", "uploaded_at"])
def test_required_photo_columns_reject_null(db_session, complaint, column):
    db_session.add(new_photo(complaint.id, **{column: None}))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_different_complaints_may_each_have_a_photo(
    db_session,
    complaint,
    make_complaint,
    make_verified_tenant,
    make_room,
    make_property,
    make_user,
):
    from app.models.complaints import ComplaintPhoto

    room = make_room(make_property(make_user(name="Other Owner")), number="Z1")
    other = make_complaint(make_verified_tenant(room), room)
    db_session.add_all([new_photo(complaint.id), new_photo(other.id)])
    db_session.commit()
    assert len(list(db_session.scalars(select(ComplaintPhoto)))) == 2
