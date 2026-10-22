"""Recording cash payments and changing a payment status manually."""

from datetime import UTC, datetime, timedelta

import pytest
from rent_bill_support import (
    DETAIL_FIELDS,
    assert_error,
    assert_field_error,
    assert_not_found,
    assert_refused,
    assert_validation_error,
    bill_url,
    days_ago,
    days_ahead,
    make_property_view_only,
    png,
    snapshot,
    stored_bill,
    stored_changes,
    today,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def pay_cash(client, headers, bill, received_on=None):
    body = {"receivedOn": (received_on or today()).isoformat()}
    return client.post(bill_url(bill, "/cash-payment"), json=body, headers=headers)


def change(client, headers, bill, **body):
    return client.post(bill_url(bill, "/status-changes"), json=body, headers=headers)


def paid_change(received_on=None, method="cash", reason="Paid in person."):
    return {
        "status": "paid",
        "reason": reason,
        "method": method,
        "receivedOn": (received_on or today()).isoformat(),
    }


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def bill(make_rent_bill, lease):
    return make_rent_bill(lease)


def bill_in(make_rent_bill, lease, status: str):
    """A bill in the given status with consistent payment fields."""
    paid = status == "paid"
    return make_rent_bill(
        lease,
        status=status,
        method="transfer" if paid else None,
        paid_on=days_ago(1) if paid else None,
        rejection_reason="Earlier reason." if status == "rejected" else None,
        receipt=(png(), "image/png", datetime.now(UTC))
        if status == "awaitingVerification"
        else None,
    )


STAFF = ["owner_in", "manager_in"]

# Cash payment: authentication and roles


def test_a_cash_payment_without_a_token_is_rejected(client, database, bill):
    assert_error(pay_cash(client, {}, bill), 401, "ACCESS_TOKEN_INVALID")


def test_a_cash_payment_from_an_unverified_manager_is_rejected(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(role=role("manager"), email_verified=False))
    assert_error(pay_cash(client, session.headers, bill), 403, "EMAIL_NOT_VERIFIED")


def test_tenants_cannot_record_cash_payments(client, database, scene, bill):
    before = snapshot(database, bill)
    response = pay_cash(client, scene.tenant_in.headers, bill)
    assert_error(response, 403, "FORBIDDEN")
    assert snapshot(database, bill) == before


def test_admins_cannot_record_cash_payments(client, database, bill, make_user, sign_in):
    session = sign_in(make_user(role=role("admin")))
    assert_error(pay_cash(client, session.headers, bill), 403, "FORBIDDEN")


def test_an_unassigned_manager_cannot_record_a_cash_payment(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(name="Other Manager", role=role("manager")))
    before = snapshot(database, bill)
    assert_not_found(pay_cash(client, session.headers, bill))
    assert snapshot(database, bill) == before


def test_another_owner_cannot_record_a_cash_payment(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(name="Other Owner"))
    before = snapshot(database, bill)
    assert_not_found(pay_cash(client, session.headers, bill))
    assert snapshot(database, bill) == before


def test_a_cash_payment_for_an_unknown_bill_is_not_found(client, database, scene):
    class Missing:
        id = "00000000-0000-4000-8000-000000000000"

    assert_not_found(pay_cash(client, scene.owner_in.headers, Missing))


# Cash payment: success


@pytest.mark.parametrize("who", STAFF)
@pytest.mark.parametrize("status", ["unpaid", "rejected"])
def test_a_cash_payment_marks_the_bill_paid_by_cash(
    client, database, scene, make_rent_bill, lease, who, status
):
    bill = bill_in(make_rent_bill, lease, status)
    response = pay_cash(client, getattr(scene, who).headers, bill, days_ago(2))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["payment"]["status"] == "paid"
    assert body["payment"]["method"] == "cash"
    assert body["payment"]["paidOn"] == days_ago(2).isoformat()
    assert body["payment"]["rejectionReason"] is None
    assert body["daysOverdue"] == 0


def test_the_cash_payment_is_stored(client, database, scene, bill):
    pay_cash(client, scene.owner_in.headers, bill, days_ago(3))
    row = stored_bill(database, bill)
    assert row.payment_status == "paid"
    assert row.payment_method == "cash"
    assert row.paid_on == days_ago(3)


@pytest.mark.parametrize("received", [today(), days_ago(1), days_ago(400)])
def test_the_date_received_may_be_today_or_earlier(
    client, database, scene, bill, received
):
    response = pay_cash(client, scene.owner_in.headers, bill, received)
    assert response.status_code == 200, response.text
    assert response.json()["payment"]["paidOn"] == received.isoformat()


def test_a_cash_payment_appends_a_history_entry_by_the_actor(
    client, database, scene, bill
):
    pay_cash(client, scene.manager_in.headers, bill)
    created, entry = stored_changes(database, bill)
    assert created.status == "unpaid"
    assert entry.status == "paid"
    assert entry.method == "cash"
    assert entry.reason is None
    assert entry.manual is False
    assert entry.actor_id == scene.manager.id
    assert abs((entry.changed_at - datetime.now(UTC)).total_seconds()) < 60


def test_the_cash_payment_history_is_shown_to_the_tenant(client, database, scene, bill):
    pay_cash(client, scene.owner_in.headers, bill)
    body = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    last = body["statusChanges"][-1]
    assert last["status"] == "paid"
    assert last["method"] == "cash"
    assert last["manual"] is False
    assert last["actorName"] == "Rina Owner"


def test_a_cash_payment_works_on_a_view_only_property(client, database, scene, bill):
    make_property_view_only(database, scene.prop)
    assert pay_cash(client, scene.owner_in.headers, bill).status_code == 200


def test_an_overdue_bill_can_be_paid_in_cash(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, due_date=days_ago(8))
    body = pay_cash(client, scene.owner_in.headers, bill).json()
    assert body["payment"]["status"] == "paid"
    assert body["daysOverdue"] == 0


# Cash payment: validation


@pytest.mark.parametrize("status", ["awaitingVerification", "paid"])
def test_a_bill_that_is_not_unpaid_or_rejected_refuses_a_cash_payment(
    client, database, scene, make_rent_bill, lease, status
):
    bill = bill_in(make_rent_bill, lease, status)
    before = snapshot(database, bill)
    response = pay_cash(client, scene.owner_in.headers, bill)
    assert_refused(response, "RENT_BILL_NOT_PAYABLE")
    assert snapshot(database, bill) == before


def test_a_date_after_today_is_rejected_on_its_field(client, database, scene, bill):
    before = snapshot(database, bill)
    response = pay_cash(client, scene.owner_in.headers, bill, days_ahead(1))
    assert_field_error(response, "RECEIVED_ON_IN_FUTURE", "receivedOn")
    assert snapshot(database, bill) == before


def test_today_in_jakarta_is_not_in_the_future(
    client, database, scene, bill, monkeypatch
):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    ok = pay_cash(client, scene.owner_in.headers, bill, date(2031, 3, 1))
    assert ok.status_code == 200, ok.text
    assert ok.json()["payment"]["paidOn"] == "2031-03-01"


def test_the_day_after_today_in_jakarta_is_in_the_future(
    client, database, scene, bill, monkeypatch
):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    response = pay_cash(client, scene.owner_in.headers, bill, date(2031, 3, 2))
    assert_field_error(response, "RECEIVED_ON_IN_FUTURE", "receivedOn")


def test_a_manual_paid_change_dated_today_in_jakarta_is_not_in_the_future(
    client, database, scene, bill, monkeypatch
):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    headers = scene.owner_in.headers
    tomorrow = change(client, headers, bill, **paid_change(date(2031, 3, 2)))
    assert_field_error(tomorrow, "RECEIVED_ON_IN_FUTURE", "receivedOn")
    same_day = change(client, headers, bill, **paid_change(date(2031, 3, 1)))
    assert same_day.status_code == 201, same_day.text


def test_a_date_far_in_the_future_is_rejected_on_its_field(
    client, database, scene, bill
):
    response = pay_cash(client, scene.owner_in.headers, bill, days_ahead(500))
    assert_field_error(response, "RECEIVED_ON_IN_FUTURE", "receivedOn")


@pytest.mark.parametrize(
    "body",
    [{}, {"receivedOn": None}, {"receivedOn": ""}, {"receivedOn": "2026-13-45"}],
    ids=["missing", "null", "empty", "impossible_date"],
)
def test_a_missing_or_invalid_date_is_rejected_on_its_field(
    client, database, scene, bill, body
):
    before = snapshot(database, bill)
    response = client.post(
        bill_url(bill, "/cash-payment"), json=body, headers=scene.owner_in.headers
    )
    assert_validation_error(response, "receivedOn")
    assert snapshot(database, bill) == before


def test_a_text_date_is_rejected_on_its_field(client, database, scene, bill):
    response = client.post(
        bill_url(bill, "/cash-payment"),
        json={"receivedOn": "yesterday"},
        headers=scene.owner_in.headers,
    )
    assert_validation_error(response, "receivedOn")


# Manual change: authentication and roles


def test_a_manual_change_without_a_token_is_rejected(client, database, bill):
    response = change(client, {}, bill, status="paid", reason="x")
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_manual_change_from_an_unverified_manager_is_rejected(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(role=role("manager"), email_verified=False))
    response = change(client, session.headers, bill, **paid_change())
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_tenants_cannot_change_a_payment_status(client, database, scene, bill):
    before = snapshot(database, bill)
    response = change(client, scene.tenant_in.headers, bill, **paid_change())
    assert_error(response, 403, "FORBIDDEN")
    assert snapshot(database, bill) == before


def test_admins_cannot_change_a_payment_status(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(role=role("admin")))
    response = change(client, session.headers, bill, **paid_change())
    assert_error(response, 403, "FORBIDDEN")


def test_an_unassigned_manager_cannot_change_a_payment_status(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(name="Other Manager", role=role("manager")))
    before = snapshot(database, bill)
    assert_not_found(change(client, session.headers, bill, **paid_change()))
    assert snapshot(database, bill) == before


def test_another_owner_cannot_change_a_payment_status(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(name="Other Owner"))
    before = snapshot(database, bill)
    assert_not_found(change(client, session.headers, bill, **paid_change()))
    assert snapshot(database, bill) == before


# Manual change: success


@pytest.mark.parametrize("who", STAFF)
def test_a_manual_change_answers_created_with_the_bill(
    client, database, scene, bill, who
):
    response = change(
        client,
        getattr(scene, who).headers,
        bill,
        status="rejected",
        reason="Bank statement shows nothing.",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(bill.id)
    assert body["payment"]["status"] == "rejected"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("unpaid", "paid"),
        ("unpaid", "rejected"),
        ("awaitingVerification", "paid"),
        ("awaitingVerification", "unpaid"),
        ("awaitingVerification", "rejected"),
        ("paid", "unpaid"),
        ("paid", "rejected"),
        ("rejected", "unpaid"),
        ("rejected", "paid"),
    ],
)
def test_any_other_status_can_be_set_manually(
    client, database, scene, make_rent_bill, lease, current, target
):
    bill = bill_in(make_rent_bill, lease, current)
    body = (
        paid_change(method="transfer")
        if target == "paid"
        else {"status": target, "reason": "Corrected after checking."}
    )
    response = change(client, scene.owner_in.headers, bill, **body)
    assert response.status_code == 201, response.text
    assert response.json()["payment"]["status"] == target
    assert stored_bill(database, bill).payment_status == target


@pytest.mark.parametrize("method", ["cash", "transfer"])
def test_a_manual_paid_change_stores_method_and_date(
    client, database, scene, bill, method
):
    response = change(
        client,
        scene.owner_in.headers,
        bill,
        **paid_change(days_ago(4), method, "Seen in the bank app."),
    )
    assert response.status_code == 201, response.text
    payment = response.json()["payment"]
    assert payment["status"] == "paid"
    assert payment["method"] == method
    assert payment["paidOn"] == days_ago(4).isoformat()
    row = stored_bill(database, bill)
    assert row.payment_method == method
    assert row.paid_on == days_ago(4)


def test_a_manual_paid_change_may_be_dated_today(client, database, scene, bill):
    response = change(client, scene.owner_in.headers, bill, **paid_change(today()))
    assert response.status_code == 201, response.text


def test_a_manual_change_appends_a_manual_history_entry(client, database, scene, bill):
    change(
        client,
        scene.manager_in.headers,
        bill,
        **paid_change(days_ago(1), "transfer", "Seen in the bank app."),
    )
    created, entry = stored_changes(database, bill)
    assert created.status == "unpaid"
    assert entry.status == "paid"
    assert entry.method == "transfer"
    assert entry.reason == "Seen in the bank app."
    assert entry.manual is True
    assert entry.actor_id == scene.manager.id
    assert abs((entry.changed_at - datetime.now(UTC)).total_seconds()) < 60


def test_a_manual_change_without_a_method_records_its_reason_only(
    client, database, scene, bill
):
    change(
        client, scene.owner_in.headers, bill, status="rejected", reason="Not received."
    )
    _, entry = stored_changes(database, bill)
    assert entry.status == "rejected"
    assert entry.method is None
    assert entry.reason == "Not received."
    assert entry.manual is True


def test_the_manual_history_is_shown_in_the_response(client, database, scene, bill):
    body = change(
        client,
        scene.owner_in.headers,
        bill,
        status="rejected",
        reason="Not received.",
    ).json()
    last = body["statusChanges"][-1]
    assert last["status"] == "rejected"
    assert last["reason"] == "Not received."
    assert last["manual"] is True
    assert last["actorName"] == "Rina Owner"
    assert len(body["statusChanges"]) == 2


def test_the_reason_of_a_manual_change_is_trimmed(client, database, scene, bill):
    change(
        client, scene.owner_in.headers, bill, status="rejected", reason="  Late.  \n"
    )
    assert stored_changes(database, bill)[-1].reason == "Late."


def test_moving_a_paid_bill_back_to_unpaid_clears_the_payment_details(
    client, database, scene, make_rent_bill, lease
):
    bill = bill_in(make_rent_bill, lease, "paid")
    body = change(
        client, scene.owner_in.headers, bill, status="unpaid", reason="Bounced."
    ).json()
    assert body["payment"]["status"] == "unpaid"
    assert body["payment"]["method"] is None
    assert body["payment"]["paidOn"] is None
    row = stored_bill(database, bill)
    assert row.payment_method is None
    assert row.paid_on is None


def test_moving_a_paid_bill_to_rejected_clears_the_payment_details(
    client, database, scene, make_rent_bill, lease
):
    bill = bill_in(make_rent_bill, lease, "paid")
    body = change(
        client, scene.owner_in.headers, bill, status="rejected", reason="Bounced."
    ).json()
    assert body["payment"]["status"] == "rejected"
    assert body["payment"]["method"] is None
    assert body["payment"]["paidOn"] is None


def test_a_manually_unpaid_overdue_bill_counts_days_overdue(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(
        lease,
        status="paid",
        method="cash",
        paid_on=days_ago(1),
        due_date=days_ago(6),
    )
    body = change(
        client, scene.owner_in.headers, bill, status="unpaid", reason="Bounced."
    ).json()
    assert body["daysOverdue"] == 6


def test_a_manual_change_works_on_a_view_only_property(client, database, scene, bill):
    make_property_view_only(database, scene.prop)
    response = change(client, scene.owner_in.headers, bill, **paid_change())
    assert response.status_code == 201, response.text


def test_several_manual_changes_build_the_history_in_order(
    client, database, scene, bill
):
    change(client, scene.owner_in.headers, bill, **paid_change())
    change(client, scene.owner_in.headers, bill, status="unpaid", reason="Bounced.")
    body = change(
        client, scene.manager_in.headers, bill, status="rejected", reason="Gone."
    ).json()
    assert [c["status"] for c in body["statusChanges"]] == [
        "unpaid",
        "paid",
        "unpaid",
        "rejected",
    ]
    assert [c["manual"] for c in body["statusChanges"]] == [False, True, True, True]
    times = [c["changedAt"] for c in body["statusChanges"]]
    assert times == sorted(times)


# Manual change: validation


@pytest.mark.parametrize("current", ["unpaid", "paid", "rejected"])
def test_the_target_must_differ_from_the_current_status(
    client, database, scene, make_rent_bill, lease, current
):
    bill = bill_in(make_rent_bill, lease, current)
    body = (
        paid_change(method="transfer")
        if current == "paid"
        else {"status": current, "reason": "No change."}
    )
    before = snapshot(database, bill)
    response = change(client, scene.owner_in.headers, bill, **body)
    assert_field_error(response, "STATUS_UNCHANGED", "status")
    assert snapshot(database, bill) == before


@pytest.mark.parametrize("status", ["awaitingVerification", "pending", "", "Paid"])
def test_an_unavailable_target_status_is_rejected_on_its_field(
    client, database, scene, bill, status
):
    before = snapshot(database, bill)
    response = change(client, scene.owner_in.headers, bill, status=status, reason="x")
    assert_validation_error(response, "status")
    assert snapshot(database, bill) == before


def test_a_missing_target_status_is_rejected_on_its_field(
    client, database, scene, bill
):
    response = change(client, scene.owner_in.headers, bill, reason="x")
    assert_validation_error(response, "status")


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
@pytest.mark.parametrize("status", ["unpaid", "rejected", "paid"])
def test_a_blank_reason_is_rejected_on_its_field(
    client, database, scene, make_rent_bill, lease, status, reason
):
    bill = bill_in(make_rent_bill, lease, "awaitingVerification")
    body = paid_change() if status == "paid" else {"status": status}
    before = snapshot(database, bill)
    response = change(
        client, scene.owner_in.headers, bill, **{**body, "reason": reason}
    )
    assert_field_error(response, "REASON_REQUIRED", "reason")
    assert snapshot(database, bill) == before


@pytest.mark.parametrize("status", ["unpaid", "rejected", "paid"])
@pytest.mark.parametrize(
    "reason", ["missing", None, 7], ids=["missing", "null", "number"]
)
def test_a_missing_or_malformed_reason_fails_validation_on_its_field(
    client, database, scene, make_rent_bill, lease, status, reason
):
    bill = bill_in(make_rent_bill, lease, "awaitingVerification")
    body = paid_change() if status == "paid" else {"status": status}
    body.pop("reason", None)
    if reason != "missing":
        body["reason"] = reason
    before = snapshot(database, bill)
    response = change(client, scene.owner_in.headers, bill, **body)
    assert_validation_error(response, "reason")
    assert snapshot(database, bill) == before


def test_paid_requires_a_method(client, database, scene, bill):
    before = snapshot(database, bill)
    response = change(
        client,
        scene.owner_in.headers,
        bill,
        status="paid",
        reason="x",
        receivedOn=today().isoformat(),
    )
    assert_validation_error(response, "method")
    assert snapshot(database, bill) == before


def test_paid_requires_a_date_received(client, database, scene, bill):
    before = snapshot(database, bill)
    response = change(
        client, scene.owner_in.headers, bill, status="paid", reason="x", method="cash"
    )
    assert_validation_error(response, "receivedOn")
    assert snapshot(database, bill) == before


def test_paid_without_method_and_date_reports_one_of_them(
    client, database, scene, bill
):
    response = change(client, scene.owner_in.headers, bill, status="paid", reason="x")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["field"] in ("method", "receivedOn")


def test_paid_with_a_null_method_is_rejected_on_its_field(
    client, database, scene, bill
):
    response = change(
        client,
        scene.owner_in.headers,
        bill,
        status="paid",
        reason="x",
        method=None,
        receivedOn=today().isoformat(),
    )
    assert_validation_error(response, "method")


def test_an_unknown_method_is_rejected_on_its_field(client, database, scene, bill):
    before = snapshot(database, bill)
    response = change(
        client, scene.owner_in.headers, bill, **paid_change(method="barter")
    )
    assert_validation_error(response, "method")
    assert snapshot(database, bill) == before


def test_a_date_after_today_is_rejected_for_a_paid_change(
    client, database, scene, bill
):
    before = snapshot(database, bill)
    response = change(
        client, scene.owner_in.headers, bill, **paid_change(days_ahead(1))
    )
    assert_field_error(response, "RECEIVED_ON_IN_FUTURE", "receivedOn")
    assert snapshot(database, bill) == before


def test_an_invalid_date_is_rejected_for_a_paid_change(client, database, scene, bill):
    body = {**paid_change(), "receivedOn": "2026-02-31"}
    response = change(client, scene.owner_in.headers, bill, **body)
    assert_validation_error(response, "receivedOn")


@pytest.mark.parametrize("status", ["unpaid", "rejected"])
@pytest.mark.parametrize("method", ["cash", "transfer"])
def test_a_method_is_not_allowed_unless_the_target_is_paid(
    client, database, scene, make_rent_bill, lease, status, method
):
    bill = bill_in(make_rent_bill, lease, "awaitingVerification")
    before = snapshot(database, bill)
    response = change(
        client, scene.owner_in.headers, bill, status=status, reason="x", method=method
    )
    assert_validation_error(response, "method")
    assert snapshot(database, bill) == before


@pytest.mark.parametrize("status", ["unpaid", "rejected"])
def test_a_date_received_is_not_allowed_unless_the_target_is_paid(
    client, database, scene, make_rent_bill, lease, status
):
    bill = bill_in(make_rent_bill, lease, "awaitingVerification")
    before = snapshot(database, bill)
    response = change(
        client,
        scene.owner_in.headers,
        bill,
        status=status,
        reason="x",
        receivedOn=today().isoformat(),
    )
    assert_validation_error(response, "receivedOn")
    assert snapshot(database, bill) == before


def test_a_refused_manual_change_adds_no_history_entry(client, database, scene, bill):
    change(client, scene.owner_in.headers, bill, status="unpaid", reason="x")
    change(client, scene.owner_in.headers, bill, status="paid", reason="")
    change(client, scene.owner_in.headers, bill, **paid_change(days_ahead(2)))
    assert len(stored_changes(database, bill)) == 1


def test_a_refused_cash_payment_adds_no_history_entry(client, database, scene, bill):
    pay_cash(client, scene.owner_in.headers, bill, days_ahead(1))
    assert len(stored_changes(database, bill)) == 1


def test_a_manual_change_for_an_unknown_bill_is_not_found(client, database, scene):
    class Missing:
        id = "00000000-0000-4000-8000-000000000000"

    response = change(
        client, scene.owner_in.headers, Missing, status="unpaid", reason="x"
    )
    assert_not_found(response)


def test_the_stored_timestamps_of_changes_never_go_backwards(
    client, database, scene, bill
):
    pay_cash(client, scene.owner_in.headers, bill)
    change(client, scene.owner_in.headers, bill, status="unpaid", reason="Bounced.")
    stamps = [c.changed_at for c in stored_changes(database, bill)]
    assert stamps == sorted(stamps)
    assert stamps[-1] - stamps[0] < timedelta(minutes=1)
