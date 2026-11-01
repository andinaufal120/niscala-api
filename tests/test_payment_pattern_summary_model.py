"""The payment pattern summary table and the structural rules the database enforces."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


def new_summary(lease_id, **overrides):
    from app.models import PaymentPatternSummary

    fields = {
        "lease_id": lease_id,
        "summary": "Penyewa membayar tepat waktu.",
        "generated_at": datetime(2026, 10, 23, 5, 0, tzinfo=UTC),
    }
    return PaymentPatternSummary(**{**fields, **overrides})


def test_the_model_is_exported_from_the_models_package():
    from app import models

    assert hasattr(models, "PaymentPatternSummary")


def test_the_table_exists_with_its_columns(database):
    assert "payment_pattern_summaries" in inspect(database).get_table_names()
    columns = {
        c["name"] for c in inspect(database).get_columns("payment_pattern_summaries")
    }
    assert columns == {"lease_id", "summary", "generated_at"}


def test_the_lease_id_is_the_primary_key(database):
    key = inspect(database).get_pk_constraint("payment_pattern_summaries")
    assert key["constrained_columns"] == ["lease_id"]


def test_the_lease_id_references_leases(database):
    keys = inspect(database).get_foreign_keys("payment_pattern_summaries")
    assert [
        (k["constrained_columns"], k["referred_table"], k["referred_columns"])
        for k in keys
    ] == [(["lease_id"], "leases", ["id"])]


def test_the_generation_time_is_stored_with_its_time_zone(db_session, lease):
    moment = datetime(2026, 10, 23, 5, 0, tzinfo=UTC)
    db_session.add(new_summary(lease.id, generated_at=moment))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(new_summary(lease.id)), lease.id)
    assert stored.generated_at.tzinfo is not None
    assert stored.generated_at == moment


def test_a_summary_is_stored_and_read_back(db_session, lease):
    db_session.add(new_summary(lease.id, summary="Sering terlambat."))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(new_summary(lease.id)), lease.id)
    assert stored.summary == "Sering terlambat."
    assert stored.lease_id == lease.id


def test_a_missing_summary_text_is_rejected(db_session, lease):
    db_session.add(new_summary(lease.id, summary=None))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_lease_holds_one_summary_only(database, lease):
    with Session(database) as db:
        db.add(new_summary(lease.id))
        db.commit()
    with Session(database) as db:
        db.add(new_summary(lease.id, summary="Another."))
        with pytest.raises(IntegrityError):
            db.commit()


def test_a_summary_of_an_unknown_lease_is_rejected(db_session):
    db_session.add(new_summary(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_summary_may_be_removed(db_session, lease):
    db_session.add(new_summary(lease.id))
    db_session.commit()
    db_session.delete(db_session.get(type(new_summary(lease.id)), lease.id))
    db_session.commit()
    assert db_session.get(type(new_summary(lease.id)), lease.id) is None
