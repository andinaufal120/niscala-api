"""Rent bill tables and the structural rules the database enforces."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from rent_bill_support import png
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


def new_bill(lease, **overrides):
    from app.models import RentBill

    fields = {
        "lease_id": lease.id,
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 31),
        "due_date": date(2026, 10, 5),
        "amount": 1000000,
        "payment_status": "unpaid",
    }
    return RentBill(**{**fields, **overrides})


def test_the_models_are_exported_from_the_models_package():
    from app import models

    for name in ("RentBill", "RentBillStatusChange", "RentBillReceipt"):
        assert hasattr(models, name)


def test_the_tables_exist_with_their_columns(database):
    tables = inspect(database).get_table_names()
    assert {"rent_bills", "rent_bill_status_changes", "rent_bill_receipts"} <= set(
        tables
    )

    def columns(name: str) -> set[str]:
        return {c["name"] for c in inspect(database).get_columns(name)}

    assert columns("rent_bills") >= {
        "id",
        "lease_id",
        "period_start",
        "period_end",
        "due_date",
        "amount",
        "payment_status",
        "payment_method",
        "paid_on",
        "rejection_reason",
        "created_at",
    }
    assert columns("rent_bill_status_changes") >= {
        "id",
        "rent_bill_id",
        "status",
        "method",
        "reason",
        "manual",
        "actor_id",
        "changed_at",
    }
    assert columns("rent_bill_receipts") >= {
        "rent_bill_id",
        "content",
        "content_type",
        "uploaded_at",
    }


def test_a_bill_is_stored_with_generated_id_and_creation_time(db_session, lease):
    row = new_bill(lease)
    db_session.add(row)
    db_session.commit()
    stored = db_session.get(type(row), row.id)
    assert stored.id is not None
    assert stored.created_at is not None
    assert stored.created_at.tzinfo is not None
    assert stored.payment_method is None
    assert stored.paid_on is None
    assert stored.rejection_reason is None


@pytest.mark.parametrize(
    "status", ["unpaid", "awaitingVerification", "paid", "rejected"]
)
def test_every_payment_status_is_accepted(db_session, lease, status):
    db_session.add(new_bill(lease, payment_status=status))
    db_session.commit()


@pytest.mark.parametrize("status", ["", "pending", "Paid", "awaiting_verification"])
def test_an_unknown_payment_status_is_rejected(db_session, lease, status):
    db_session.add(new_bill(lease, payment_status=status))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_missing_payment_status_is_rejected(db_session, lease):
    db_session.add(new_bill(lease, payment_status=None))
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("method", ["transfer", "cash", None])
def test_known_payment_methods_and_none_are_accepted(db_session, lease, method):
    db_session.add(new_bill(lease, payment_method=method))
    db_session.commit()


@pytest.mark.parametrize("method", ["", "card", "Cash"])
def test_an_unknown_payment_method_is_rejected(db_session, lease, method):
    db_session.add(new_bill(lease, payment_method=method))
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("amount", [0, -1, -1000000])
def test_an_amount_that_is_not_positive_is_rejected(db_session, lease, amount):
    db_session.add(new_bill(lease, amount=amount))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_an_amount_of_one_is_accepted(db_session, lease):
    db_session.add(new_bill(lease, amount=1))
    db_session.commit()


@pytest.mark.parametrize(
    "column", ["period_start", "period_end", "due_date", "amount", "lease_id"]
)
def test_required_bill_columns_reject_null(db_session, lease, column):
    db_session.add(new_bill(lease, **{column: None}))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_lease_cannot_have_two_bills_for_the_same_period_start(db_session, lease):
    db_session.add(new_bill(lease))
    db_session.commit()
    db_session.add(new_bill(lease, period_end=date(2026, 11, 5)))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_lease_may_have_bills_for_different_period_starts(db_session, lease):
    db_session.add(new_bill(lease))
    db_session.add(
        new_bill(
            lease,
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            due_date=date(2026, 11, 5),
        )
    )
    db_session.commit()


def test_two_leases_may_have_bills_for_the_same_period_start(
    db_session, scene, make_room, make_verified_tenant
):
    other_room = make_room(scene.prop, number="B1")
    other = make_verified_tenant(other_room, name="Sari Tenant")
    db_session.add(new_bill(scene.tenant.lease))
    db_session.add(new_bill(other.lease))
    db_session.commit()


def test_a_bill_needs_an_existing_lease(db_session, lease):
    db_session.add(new_bill(lease, lease_id=uuid4()))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_status_change_is_stored_with_and_without_an_actor(db_session, lease, scene):
    from app.models import RentBillStatusChange

    bill = new_bill(lease)
    db_session.add(bill)
    db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            RentBillStatusChange(
                rent_bill_id=bill.id,
                status="unpaid",
                method=None,
                reason=None,
                manual=False,
                actor_id=None,
                changed_at=now,
            ),
            RentBillStatusChange(
                rent_bill_id=bill.id,
                status="paid",
                method="cash",
                reason="Paid at the door.",
                manual=True,
                actor_id=scene.owner.id,
                changed_at=now,
            ),
        ]
    )
    db_session.commit()
    rows = list(db_session.scalars(select(RentBillStatusChange)))
    assert len(rows) == 2
    assert {r.actor_id for r in rows} == {None, scene.owner.id}


def test_a_status_change_needs_an_existing_bill(db_session):
    from app.models import RentBillStatusChange

    db_session.add(
        RentBillStatusChange(
            rent_bill_id=uuid4(),
            status="unpaid",
            method=None,
            reason=None,
            manual=False,
            actor_id=None,
            changed_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_status_change_actor_must_be_an_existing_account(db_session, lease):
    from app.models import RentBillStatusChange

    bill = new_bill(lease)
    db_session.add(bill)
    db_session.flush()
    db_session.add(
        RentBillStatusChange(
            rent_bill_id=bill.id,
            status="unpaid",
            method=None,
            reason=None,
            manual=False,
            actor_id=uuid4(),
            changed_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_receipt_keeps_its_bytes_and_type(db_session, lease):
    from app.models import RentBillReceipt

    bill = new_bill(lease)
    db_session.add(bill)
    db_session.flush()
    content = png(2048)
    db_session.add(
        RentBillReceipt(
            rent_bill_id=bill.id,
            content=content,
            content_type="image/png",
            uploaded_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    stored = db_session.get(RentBillReceipt, bill.id)
    assert bytes(stored.content) == content
    assert stored.content_type == "image/png"
    assert stored.uploaded_at.tzinfo is not None


def test_a_bill_has_at_most_one_receipt(db_session, lease):
    from app.models import RentBillReceipt

    bill = new_bill(lease)
    db_session.add(bill)
    db_session.flush()
    db_session.add(
        RentBillReceipt(
            rent_bill_id=bill.id,
            content=png(),
            content_type="image/png",
            uploaded_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    with Session(db_session.get_bind()) as other:
        other.add(
            RentBillReceipt(
                rent_bill_id=bill.id,
                content=png(),
                content_type="image/png",
                uploaded_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            other.commit()


def test_a_receipt_needs_an_existing_bill(db_session):
    from app.models import RentBillReceipt

    db_session.add(
        RentBillReceipt(
            rent_bill_id=uuid4(),
            content=png(),
            content_type="image/png",
            uploaded_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
