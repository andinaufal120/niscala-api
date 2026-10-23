"""Verifying and rejecting an uploaded transfer receipt."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from rent_bill_support import (
    DETAIL_FIELDS,
    JAKARTA,
    assert_error,
    assert_field_error,
    assert_not_found,
    assert_refused,
    assert_validation_error,
    at_noon_jakarta,
    bill_url,
    days_ago,
    make_property_view_only,
    png,
    snapshot,
    stored_bill,
    stored_changes,
    stored_receipts,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def verify(client, headers, bill):
    return client.post(bill_url(bill, "/verification"), headers=headers)


def reject(client, headers, bill, reason="The receipt is unreadable."):
    return client.post(
        bill_url(bill, "/rejection"), json={"reason": reason}, headers=headers
    )


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def awaiting(make_rent_bill, lease):
    """A bill whose receipt was uploaded two days ago."""
    uploaded = at_noon_jakarta(days_ago(2))
    return make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", uploaded),
        changes=[
            ("unpaid", None, None, False, None, uploaded - timedelta(days=1)),
            ("awaitingVerification", None, None, False, lease.tenant_id, uploaded),
        ],
    )


REVIEWERS = ["owner_in", "manager_in"]


# Authentication and roles


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_a_review_without_a_token_is_rejected(client, database, awaiting, action):
    assert_error(action(client, {}, awaiting), 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_a_review_from_an_unverified_manager_is_rejected(
    client, database, awaiting, make_user, sign_in, action
):
    session = sign_in(make_user(role=role("manager"), email_verified=False))
    assert_error(action(client, session.headers, awaiting), 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_tenants_cannot_review_receipts(client, database, scene, awaiting, action):
    response = action(client, scene.tenant_in.headers, awaiting)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_admins_cannot_review_receipts(
    client, database, awaiting, make_user, sign_in, action
):
    session = sign_in(make_user(role=role("admin")))
    assert_error(action(client, session.headers, awaiting), 403, "FORBIDDEN")


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_a_forbidden_review_saves_nothing(client, database, scene, awaiting, action):
    before = snapshot(database, awaiting)
    action(client, scene.tenant_in.headers, awaiting)
    assert snapshot(database, awaiting) == before


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_an_unassigned_manager_cannot_review_a_receipt(
    client, database, scene, awaiting, make_user, sign_in, action
):
    session = sign_in(make_user(name="Other Manager", role=role("manager")))
    before = snapshot(database, awaiting)
    assert_not_found(action(client, session.headers, awaiting))
    assert snapshot(database, awaiting) == before


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_an_owner_cannot_review_the_receipt_of_another_owner(
    client, database, awaiting, make_user, sign_in, action
):
    session = sign_in(make_user(name="Other Owner"))
    before = snapshot(database, awaiting)
    assert_not_found(action(client, session.headers, awaiting))
    assert snapshot(database, awaiting) == before


@pytest.mark.parametrize("action", [verify, reject], ids=["verify", "reject"])
def test_reviewing_an_unknown_bill_is_not_found(client, database, scene, action):
    class Missing:
        id = uuid4()

    assert_not_found(action(client, scene.owner_in.headers, Missing))


# Verify


@pytest.mark.parametrize("who", REVIEWERS)
def test_verifying_marks_the_bill_paid_by_transfer(
    client, database, scene, awaiting, who
):
    response = verify(client, getattr(scene, who).headers, awaiting)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(awaiting.id)
    assert body["payment"]["status"] == "paid"
    assert body["payment"]["method"] == "transfer"
    assert body["payment"]["hasReceipt"] is True
    assert body["payment"]["rejectionReason"] is None
    assert body["daysOverdue"] == 0


def test_the_payment_date_is_the_day_the_receipt_was_uploaded(
    client, database, scene, awaiting
):
    body = verify(client, scene.owner_in.headers, awaiting).json()
    assert body["payment"]["paidOn"] == days_ago(2).isoformat()
    row = stored_bill(database, awaiting)
    assert row.paid_on == days_ago(2)
    assert row.payment_status == "paid"
    assert row.payment_method == "transfer"


def test_a_receipt_uploaded_through_the_api_is_dated_by_its_upload_time_in_jakarta(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease)
    uploaded = client.put(
        bill_url(bill, "/receipt"),
        files={"file": ("a.png", png(), "image/png")},
        headers=scene.tenant_in.headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    (receipt,) = stored_receipts(database)
    body = verify(client, scene.owner_in.headers, bill).json()
    expected = receipt.uploaded_at.astimezone(JAKARTA).date()
    assert body["payment"]["paidOn"] == expected.isoformat()


@pytest.mark.parametrize(
    ("uploaded_at", "paid_on"),
    [
        (datetime(2026, 10, 19, 18, 0, tzinfo=UTC), "2026-10-20"),
        (datetime(2026, 10, 19, 17, 0, tzinfo=UTC), "2026-10-20"),
        (datetime(2026, 10, 19, 16, 59, tzinfo=UTC), "2026-10-19"),
        (datetime(2026, 10, 20, 16, 59, tzinfo=UTC), "2026-10-20"),
        (datetime(2026, 10, 20, 17, 0, tzinfo=UTC), "2026-10-21"),
    ],
    ids=[
        "one_am_jakarta",
        "midnight_jakarta",
        "just_before_midnight_jakarta",
        "late_evening_jakarta",
        "next_midnight_jakarta",
    ],
)
def test_the_payment_date_is_the_jakarta_date_of_the_upload(
    client, database, scene, make_rent_bill, lease, uploaded_at, paid_on
):
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", uploaded_at),
    )
    body = verify(client, scene.owner_in.headers, bill).json()
    assert body["payment"]["paidOn"] == paid_on
    assert stored_bill(database, bill).paid_on.isoformat() == paid_on


def test_the_payment_date_does_not_move_with_the_verification_day(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", at_noon_jakarta(days_ago(9))),
    )
    body = verify(client, scene.owner_in.headers, bill).json()
    assert body["payment"]["paidOn"] == days_ago(9).isoformat()


def test_verifying_appends_a_history_entry_by_the_reviewer(
    client, database, scene, awaiting
):
    verify(client, scene.manager_in.headers, awaiting)
    *_, change = stored_changes(database, awaiting)
    assert change.status == "paid"
    assert change.method == "transfer"
    assert change.reason is None
    assert change.manual is False
    assert change.actor_id == scene.manager.id
    assert abs((change.changed_at - datetime.now(UTC)).total_seconds()) < 60
    assert len(stored_changes(database, awaiting)) == 3


def test_the_verified_history_is_shown_in_the_response(
    client, database, scene, awaiting
):
    body = verify(client, scene.owner_in.headers, awaiting).json()
    assert [c["status"] for c in body["statusChanges"]] == [
        "unpaid",
        "awaitingVerification",
        "paid",
    ]
    last = body["statusChanges"][-1]
    assert last["method"] == "transfer"
    assert last["actorName"] == "Rina Owner"
    assert last["manual"] is False


def test_the_receipt_is_kept_after_verifying(client, database, scene, awaiting):
    verify(client, scene.owner_in.headers, awaiting)
    assert len(stored_receipts(database)) == 1
    response = client.get(
        bill_url(awaiting, "/receipt"), headers=scene.tenant_in.headers
    )
    assert response.status_code == 200


def test_the_tenant_sees_the_bill_as_paid(client, database, scene, awaiting):
    verify(client, scene.owner_in.headers, awaiting)
    body = client.get(bill_url(awaiting), headers=scene.tenant_in.headers).json()
    assert body["payment"]["status"] == "paid"


def test_verifying_works_on_a_view_only_property(client, database, scene, awaiting):
    make_property_view_only(database, scene.prop)
    response = verify(client, scene.owner_in.headers, awaiting)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("status", ["unpaid", "paid", "rejected"])
def test_only_a_bill_awaiting_verification_can_be_verified(
    client, database, scene, make_rent_bill, lease, status
):
    paid = status == "paid"
    bill = make_rent_bill(
        lease,
        status=status,
        method="cash" if paid else None,
        paid_on=days_ago(1) if paid else None,
    )
    before = snapshot(database, bill)
    response = verify(client, scene.owner_in.headers, bill)
    assert_refused(response, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert snapshot(database, bill) == before


def test_verifying_twice_is_refused_the_second_time(client, database, scene, awaiting):
    assert verify(client, scene.owner_in.headers, awaiting).status_code == 200
    before = snapshot(database, awaiting)
    response = verify(client, scene.owner_in.headers, awaiting)
    assert_refused(response, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert snapshot(database, awaiting) == before


# Reject


@pytest.mark.parametrize("who", REVIEWERS)
def test_rejecting_marks_the_bill_rejected_with_the_reason(
    client, database, scene, awaiting, who
):
    response = reject(client, getattr(scene, who).headers, awaiting, "Wrong amount.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["payment"]["status"] == "rejected"
    assert body["payment"]["rejectionReason"] == "Wrong amount."
    assert body["payment"]["method"] is None
    assert body["payment"]["paidOn"] is None


def test_the_rejection_is_stored(client, database, scene, awaiting):
    reject(client, scene.owner_in.headers, awaiting, "Wrong amount.")
    row = stored_bill(database, awaiting)
    assert row.payment_status == "rejected"
    assert row.rejection_reason == "Wrong amount."
    assert row.payment_method is None
    assert row.paid_on is None


def test_the_reason_is_trimmed(client, database, scene, awaiting):
    body = reject(
        client, scene.owner_in.headers, awaiting, "  Wrong amount.  \n"
    ).json()
    assert body["payment"]["rejectionReason"] == "Wrong amount."
    assert stored_bill(database, awaiting).rejection_reason == "Wrong amount."


def test_rejecting_appends_a_history_entry_with_the_reason(
    client, database, scene, awaiting
):
    reject(client, scene.manager_in.headers, awaiting, "Wrong amount.")
    *_, change = stored_changes(database, awaiting)
    assert change.status == "rejected"
    assert change.reason == "Wrong amount."
    assert change.method is None
    assert change.manual is False
    assert change.actor_id == scene.manager.id
    assert len(stored_changes(database, awaiting)) == 3


def test_the_tenant_sees_the_rejection_reason(client, database, scene, awaiting):
    reject(client, scene.owner_in.headers, awaiting, "Wrong amount.")
    body = client.get(bill_url(awaiting), headers=scene.tenant_in.headers).json()
    assert body["payment"]["status"] == "rejected"
    assert body["payment"]["rejectionReason"] == "Wrong amount."
    assert body["statusChanges"][-1]["reason"] == "Wrong amount."


def test_a_rejected_bill_that_is_overdue_counts_days_overdue_again(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        due_date=days_ago(5),
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    body = reject(client, scene.owner_in.headers, bill).json()
    assert body["daysOverdue"] == 5


def test_a_rejected_bill_can_be_paid_again_by_receipt(
    client, database, scene, awaiting
):
    reject(client, scene.owner_in.headers, awaiting)
    response = client.put(
        bill_url(awaiting, "/receipt"),
        files={"file": ("again.png", png(64), "image/png")},
        headers=scene.tenant_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["payment"]["status"] == "awaitingVerification"
    (receipt,) = stored_receipts(database)
    verified = verify(client, scene.owner_in.headers, awaiting)
    assert verified.json()["payment"]["status"] == "paid"
    expected = receipt.uploaded_at.astimezone(JAKARTA).date()
    assert verified.json()["payment"]["paidOn"] == expected.isoformat()


def test_rejecting_works_on_a_view_only_property(client, database, scene, awaiting):
    make_property_view_only(database, scene.prop)
    assert reject(client, scene.owner_in.headers, awaiting).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{"reason": ""}, {"reason": "   "}, {"reason": "\n\t "}],
    ids=["empty", "spaces", "whitespace"],
)
def test_a_blank_reason_is_rejected_on_its_field(
    client, database, scene, awaiting, body
):
    before = snapshot(database, awaiting)
    response = client.post(
        bill_url(awaiting, "/rejection"), json=body, headers=scene.owner_in.headers
    )
    assert_field_error(response, "REASON_REQUIRED", "reason")
    assert snapshot(database, awaiting) == before


@pytest.mark.parametrize(
    "body", [{}, {"reason": None}, {"reason": 5}], ids=["missing", "null", "number"]
)
def test_a_missing_or_malformed_reason_fails_validation_on_its_field(
    client, database, scene, awaiting, body
):
    before = snapshot(database, awaiting)
    response = client.post(
        bill_url(awaiting, "/rejection"), json=body, headers=scene.owner_in.headers
    )
    assert_validation_error(response, "reason")
    assert snapshot(database, awaiting) == before


@pytest.mark.parametrize("status", ["unpaid", "paid", "rejected"])
def test_only_a_bill_awaiting_verification_can_be_rejected(
    client, database, scene, make_rent_bill, lease, status
):
    paid = status == "paid"
    bill = make_rent_bill(
        lease,
        status=status,
        method="cash" if paid else None,
        paid_on=days_ago(1) if paid else None,
        rejection_reason="Earlier reason." if status == "rejected" else None,
    )
    before = snapshot(database, bill)
    response = reject(client, scene.owner_in.headers, bill)
    assert_refused(response, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert snapshot(database, bill) == before


def test_rejecting_twice_is_refused_the_second_time(client, database, scene, awaiting):
    assert reject(client, scene.owner_in.headers, awaiting).status_code == 200
    before = snapshot(database, awaiting)
    response = reject(client, scene.owner_in.headers, awaiting, "Other reason.")
    assert_refused(response, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert snapshot(database, awaiting) == before
