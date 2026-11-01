"""Notifications created by receipt uploads, reviews, cash payments and status changes."""

import pytest
from notification_support import (
    assert_item,
    awaiting_bill,
    change_status,
    items,
    list_all,
    only,
    pay_cash,
    property_ref,
    reject,
    rent_bill_facts,
    role,
    room_ref,
    stored_for,
    stored_rows,
    tenant_ref,
    types,
    unassign,
    upload_receipt,
    verify,
)
from rent_bill_support import (
    GIF_BYTES,
    clear_bank_account,
    days_ago,
    days_ahead,
    stored_bill,
    stored_changes,
    today,
)
from sqlalchemy.orm import Session


def paid_body(method: str = "cash", reason: str = "Paid in person.") -> dict:
    return {
        "status": "paid",
        "reason": reason,
        "method": method,
        "receivedOn": today().isoformat(),
    }


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def bill(make_rent_bill, lease):
    return make_rent_bill(lease)


@pytest.fixture
def awaiting(make_rent_bill, lease):
    return awaiting_bill(make_rent_bill, lease, period_start=days_ago(60))


def tenant_facts(scene, bill, status, **options) -> dict:
    """What a tenant notification about the bill carries."""
    return {
        "rentBill": rent_bill_facts(bill, status, **options),
        "room": room_ref(scene.room),
        "property": property_ref(scene.prop),
    }


def management_facts(scene, bill, status, **options) -> dict:
    """What a notification to management about the bill carries."""
    return {
        **tenant_facts(scene, bill, status, **options),
        "tenant": tenant_ref(scene.tenant.user),
    }


# The tenant is told about what management decides


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_verifying_a_receipt_notifies_the_tenant_that_it_is_paid(
    client, database, scene, awaiting, who
):
    assert verify(client, getattr(scene, who).headers, awaiting).status_code == 200
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(scene, awaiting, "paid", method="transfer"),
    )


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_rejecting_a_receipt_notifies_the_tenant_with_the_reason(
    client, database, scene, awaiting, who
):
    reject(client, getattr(scene, who).headers, awaiting, "  Wrong amount.  \n")
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(scene, awaiting, "rejected", reason="Wrong amount."),
    )


def test_a_rejection_shows_the_days_overdue_of_the_bill_at_that_moment(
    client, database, scene, make_rent_bill, lease
):
    overdue = awaiting_bill(make_rent_bill, lease, due_date=days_ago(5))
    reject(client, scene.owner_in.headers, overdue)
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert item["rentBill"]["daysOverdue"] == 5
    assert item["rentBill"]["paymentStatus"] == "rejected"


def test_verifying_an_overdue_bill_shows_no_days_overdue(
    client, database, scene, make_rent_bill, lease
):
    overdue = awaiting_bill(make_rent_bill, lease, due_date=days_ago(5))
    verify(client, scene.owner_in.headers, overdue)
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert item["rentBill"]["daysOverdue"] == 0


def test_verifying_does_not_notify_management(client, database, scene, awaiting):
    verify(client, scene.owner_in.headers, awaiting)
    assert items(client, scene.owner_in) == []
    assert items(client, scene.manager_in) == []


def test_rejecting_does_not_notify_management(client, database, scene, awaiting):
    reject(client, scene.manager_in.headers, awaiting)
    assert items(client, scene.owner_in) == []
    assert items(client, scene.manager_in) == []


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
@pytest.mark.parametrize("status", ["unpaid", "rejected"])
def test_a_cash_payment_notifies_the_tenant_that_it_is_paid_in_cash(
    client, database, scene, make_rent_bill, lease, who, status
):
    stored = make_rent_bill(
        lease,
        status=status,
        rejection_reason="Earlier reason." if status == "rejected" else None,
    )
    assert pay_cash(client, getattr(scene, who).headers, stored).status_code == 200
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(scene, stored, "paid", method="cash"),
    )


def test_a_cash_payment_of_an_overdue_bill_shows_no_days_overdue(
    client, database, scene, make_rent_bill, lease
):
    overdue = make_rent_bill(lease, due_date=days_ago(8))
    pay_cash(client, scene.owner_in.headers, overdue)
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert item["rentBill"]["daysOverdue"] == 0


def test_a_manual_change_to_paid_notifies_the_tenant_with_method_and_reason(
    client, database, scene, bill
):
    change_status(client, scene.owner_in.headers, bill, **paid_body("transfer"))
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(
            scene, bill, "paid", method="transfer", reason="Paid in person."
        ),
    )


def test_a_manual_change_to_rejected_notifies_the_tenant_with_the_reason(
    client, database, scene, make_rent_bill, lease
):
    overdue = make_rent_bill(lease, due_date=days_ago(3))
    change_status(
        client,
        scene.manager_in.headers,
        overdue,
        status="rejected",
        reason="Not received.",
    )
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(
            scene, overdue, "rejected", reason="Not received.", days_overdue=3
        ),
    )


def test_a_manual_change_to_unpaid_notifies_the_tenant_without_method(
    client, database, scene, make_rent_bill, lease
):
    stored = make_rent_bill(
        lease,
        status="paid",
        method="cash",
        paid_on=days_ago(1),
        due_date=days_ago(6),
    )
    change_status(
        client, scene.owner_in.headers, stored, status="unpaid", reason="Bounced."
    )
    item = only(client, scene.tenant_in, "paymentStatusChanged")
    assert_item(
        item,
        "paymentStatusChanged",
        **tenant_facts(scene, stored, "unpaid", reason="Bounced.", days_overdue=6),
    )


def test_a_manual_change_is_notified_to_the_tenant_only(client, database, scene, bill):
    change_status(client, scene.manager_in.headers, bill, **paid_body("cash"))
    assert types(client, scene.tenant_in) == ["paymentStatusChanged"]
    assert items(client, scene.owner_in) == []
    assert items(client, scene.manager_in) == []


def test_every_manual_change_makes_its_own_notification(client, database, scene, bill):
    change_status(client, scene.owner_in.headers, bill, **paid_body("cash"))
    change_status(
        client, scene.owner_in.headers, bill, status="unpaid", reason="Bounced."
    )
    change_status(
        client, scene.manager_in.headers, bill, status="rejected", reason="Gone."
    )
    shown = [i["rentBill"]["paymentStatus"] for i in items(client, scene.tenant_in)]
    assert shown == ["rejected", "unpaid", "paid"]


# Management hears about cash recorded by a manager


def test_a_cash_payment_by_a_manager_notifies_the_owner(client, database, scene, bill):
    pay_cash(client, scene.manager_in.headers, bill)
    item = only(client, scene.owner_in, "cashPaymentRecorded")
    assert_item(
        item,
        "cashPaymentRecorded",
        **management_facts(scene, bill, "paid", method="cash"),
        actorName="Mira Manager",
    )
    assert types(client, scene.owner_in) == ["cashPaymentRecorded"]


def test_a_cash_payment_by_a_manager_also_notifies_the_tenant(
    client, database, scene, bill
):
    pay_cash(client, scene.manager_in.headers, bill)
    assert types(client, scene.tenant_in) == ["paymentStatusChanged"]


def test_a_cash_payment_by_a_manager_does_not_notify_the_manager(
    client, database, scene, bill
):
    pay_cash(client, scene.manager_in.headers, bill)
    assert items(client, scene.manager_in) == []


def test_a_cash_payment_by_a_manager_does_not_notify_other_managers(
    client, database, scene, bill, make_user, assign_manager, sign_in
):
    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(colleague, scene.prop)
    pay_cash(client, scene.manager_in.headers, bill)
    assert items(client, sign_in(colleague)) == []


def test_a_cash_payment_by_the_owner_creates_no_cash_notification(
    client, database, scene, bill
):
    pay_cash(client, scene.owner_in.headers, bill)
    assert items(client, scene.owner_in) == []
    assert items(client, scene.manager_in) == []
    assert types(client, scene.tenant_in) == ["paymentStatusChanged"]


def test_a_manual_paid_change_by_a_manager_does_not_notify_the_owner(
    client, database, scene, bill
):
    change_status(client, scene.manager_in.headers, bill, **paid_body("cash"))
    assert items(client, scene.owner_in) == []


# Management hears about uploaded receipts


@pytest.mark.parametrize("who", ["owner", "manager"])
def test_uploading_a_receipt_notifies_the_owner_and_the_assigned_manager(
    client, database, scene, bill, who
):
    assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200
    recipient = getattr(scene, f"{who}_in")
    item = only(client, recipient, "receiptUploaded")
    assert_item(
        item,
        "receiptUploaded",
        **management_facts(scene, bill, "awaitingVerification"),
    )
    assert types(client, recipient) == ["receiptUploaded"]


def test_uploading_a_receipt_does_not_notify_the_tenant(client, database, scene, bill):
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert items(client, scene.tenant_in) == []


def test_uploading_for_an_overdue_bill_shows_no_days_overdue(
    client, database, scene, make_rent_bill, lease
):
    overdue = make_rent_bill(lease, due_date=days_ago(4))
    upload_receipt(client, scene.tenant_in.headers, overdue)
    item = only(client, scene.owner_in, "receiptUploaded")
    assert item["rentBill"]["daysOverdue"] == 0


def test_a_manager_of_another_property_is_not_notified(
    client, database, scene, bill, make_user, make_site, sign_in
):
    outsider = make_user(name="Outside Manager", role=role("manager"))
    make_site(scene.owner, name="Kos Kedua", number="B1", managers=[outsider])
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert items(client, sign_in(outsider)) == []
    assert stored_for(database, outsider) == []


def test_another_owner_is_not_notified(
    client, database, scene, bill, make_user, sign_in
):
    stranger = make_user(name="Other Owner")
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert items(client, sign_in(stranger)) == []


def test_every_assigned_manager_is_notified(
    client, database, scene, bill, make_user, assign_manager, sign_in
):
    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(colleague, scene.prop)
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert types(client, sign_in(colleague)) == ["receiptUploaded"]
    assert len(stored_rows(database)) == 3


def test_a_manager_unassigned_before_the_upload_is_not_notified(
    client, database, scene, bill
):
    unassign(database, scene.manager, scene.prop)
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert stored_for(database, scene.manager) == []
    assert len(stored_for(database, scene.owner)) == 1


def test_each_upload_after_a_rejection_notifies_again(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, period_start=days_ago(60))
    upload_receipt(client, scene.tenant_in.headers, bill)
    reject(client, scene.owner_in.headers, bill)
    upload_receipt(client, scene.tenant_in.headers, bill)
    assert types(client, scene.owner_in) == ["receiptUploaded", "receiptUploaded"]
    assert types(client, scene.manager_in) == ["receiptUploaded", "receiptUploaded"]


# Stored rows


def test_a_notification_is_stored_for_its_recipient_and_property(
    client, database, scene, bill
):
    upload_receipt(client, scene.tenant_in.headers, bill)
    (row,) = stored_for(database, scene.owner)
    assert str(row["type"]) == "receiptUploaded"
    assert row["property_id"] == scene.prop.id
    assert row["read_at"] is None
    assert row["created_at"] is not None


def test_a_tenant_notification_is_tied_to_the_property_too(
    client, database, scene, awaiting
):
    verify(client, scene.owner_in.headers, awaiting)
    (row,) = stored_for(database, scene.tenant.user)
    assert str(row["type"]) == "paymentStatusChanged"
    assert row["property_id"] == scene.prop.id


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("owner_in", 1), ("manager_in", 2)],
)
def test_a_cash_payment_creates_one_notification_per_recipient(
    client, database, scene, bill, actor, expected
):
    pay_cash(client, getattr(scene, actor).headers, bill)
    assert len(stored_rows(database)) == expected


# Snapshots


def test_a_notification_keeps_the_facts_of_its_moment(
    client, database, scene, make_rent_bill, lease
):
    stored = make_rent_bill(lease, due_date=days_ago(2))
    pay_cash(client, scene.owner_in.headers, stored)
    (first,) = items(client, scene.tenant_in)
    change_status(
        client, scene.owner_in.headers, stored, status="unpaid", reason="Bounced."
    )
    change_status(
        client,
        scene.owner_in.headers,
        stored,
        status="rejected",
        reason="Still nothing.",
    )
    by_id = {i["id"]: i for i in items(client, scene.tenant_in)}
    assert len(by_id) == 3
    assert by_id[first["id"]] == first
    assert first["rentBill"]["paymentStatus"] == "paid"
    assert first["rentBill"]["daysOverdue"] == 0


def test_the_same_bill_has_a_notification_for_each_status_it_reached(
    client, database, scene, make_rent_bill, lease
):
    stored = awaiting_bill(make_rent_bill, lease, due_date=days_ago(4))
    reject(client, scene.owner_in.headers, stored, "Wrong amount.")
    upload_receipt(client, scene.tenant_in.headers, stored)
    verify(client, scene.manager_in.headers, stored)
    newest, oldest = items(client, scene.tenant_in)
    assert newest["rentBill"] == rent_bill_facts(stored, "paid", method="transfer")
    assert oldest["rentBill"] == rent_bill_facts(
        stored, "rejected", reason="Wrong amount.", days_overdue=4
    )


def test_an_upload_notification_does_not_change_when_the_bill_is_reviewed(
    client, database, scene, bill
):
    upload_receipt(client, scene.tenant_in.headers, bill)
    (before,) = items(client, scene.owner_in)
    verify(client, scene.owner_in.headers, bill)
    (after,) = items(client, scene.owner_in)
    assert after == before
    assert after["rentBill"]["paymentStatus"] == "awaitingVerification"


# Events that fail create nothing


def attempt_upload_gif(client, scene, bill, awaiting):
    return upload_receipt(client, scene.tenant_in.headers, bill, GIF_BYTES)


def attempt_verify_unpaid_bill(client, scene, bill, awaiting):
    return verify(client, scene.owner_in.headers, bill)


def attempt_reject_with_blank_reason(client, scene, bill, awaiting):
    return reject(client, scene.owner_in.headers, awaiting, "  ")


def attempt_reject_unpaid_bill(client, scene, bill, awaiting):
    return reject(client, scene.owner_in.headers, bill)


def attempt_cash_in_the_future(client, scene, bill, awaiting):
    return pay_cash(client, scene.owner_in.headers, bill, days_ahead(1))


def attempt_cash_for_awaiting_bill(client, scene, bill, awaiting):
    return pay_cash(client, scene.owner_in.headers, awaiting)


def attempt_unchanged_status(client, scene, bill, awaiting):
    return change_status(
        client, scene.owner_in.headers, bill, status="unpaid", reason="Same."
    )


def attempt_blank_reason(client, scene, bill, awaiting):
    return change_status(
        client, scene.owner_in.headers, bill, status="rejected", reason=" "
    )


def attempt_tenant_verifies(client, scene, bill, awaiting):
    return verify(client, scene.tenant_in.headers, awaiting)


def attempt_management_uploads(client, scene, bill, awaiting):
    return upload_receipt(client, scene.owner_in.headers, bill)


FAILING = [
    pytest.param(attempt_upload_gif, id="receipt_of_the_wrong_type"),
    pytest.param(attempt_verify_unpaid_bill, id="verify_an_unpaid_bill"),
    pytest.param(attempt_reject_with_blank_reason, id="reject_without_reason"),
    pytest.param(attempt_reject_unpaid_bill, id="reject_an_unpaid_bill"),
    pytest.param(attempt_cash_in_the_future, id="cash_dated_in_the_future"),
    pytest.param(attempt_cash_for_awaiting_bill, id="cash_for_an_awaiting_bill"),
    pytest.param(attempt_unchanged_status, id="status_unchanged"),
    pytest.param(attempt_blank_reason, id="manual_change_without_reason"),
    pytest.param(attempt_tenant_verifies, id="tenant_verifies"),
    pytest.param(attempt_management_uploads, id="management_uploads"),
]


@pytest.mark.parametrize("attempt", FAILING)
def test_a_refused_request_creates_no_notification(
    client, database, scene, bill, awaiting, attempt
):
    response = attempt(client, scene, bill, awaiting)
    assert response.status_code >= 400
    assert stored_rows(database) == []


def test_a_receipt_for_a_paid_bill_creates_no_further_notification(
    client, database, scene, bill
):
    pay_cash(client, scene.owner_in.headers, bill)
    assert len(stored_rows(database)) == 1
    response = upload_receipt(client, scene.tenant_in.headers, bill)
    assert response.status_code == 409
    assert len(stored_rows(database)) == 1


def test_a_receipt_for_a_property_without_a_bank_account_creates_no_notification(
    client, database, scene, bill
):
    clear_bank_account(database, scene.prop)
    response = upload_receipt(client, scene.tenant_in.headers, bill)
    assert response.status_code == 409
    assert stored_rows(database) == []


def test_a_review_by_an_unassigned_manager_creates_no_notification(
    client, database, scene, awaiting
):
    unassign(database, scene.manager, scene.prop)
    response = verify(client, scene.manager_in.headers, awaiting)
    assert response.status_code == 404
    assert stored_rows(database) == []


def test_a_refused_request_leaves_the_lists_empty(client, database, scene, bill):
    pay_cash(client, scene.owner_in.headers, bill, days_ahead(3))
    for who in ("tenant_in", "owner_in", "manager_in"):
        assert list_all(client, getattr(scene, who)) == {"items": [], "unreadCount": 0}


# The hook that creates the notifications


class StatusHook:
    """Stands in for the notification hook of rent bills."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bool, object, str]] = []
        self.error = error

    def __call__(self, db, bill, change) -> None:
        self.calls.append((isinstance(db, Session), bill.id, str(change.status)))
        if self.error is not None:
            raise self.error


@pytest.fixture
def hook(monkeypatch):
    stub = StatusHook()
    monkeypatch.setattr("app.services.rent_bills.notify_status_change", stub)
    return stub


def test_the_hook_receives_the_session_the_bill_and_the_change(
    client, database, scene, awaiting, hook
):
    assert verify(client, scene.owner_in.headers, awaiting).status_code == 200
    assert hook.calls == [(True, awaiting.id, "paid")]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param(
            lambda c, s, b, a: verify(c, s.owner_in.headers, a), "paid", id="verify"
        ),
        pytest.param(
            lambda c, s, b, a: reject(c, s.owner_in.headers, a),
            "rejected",
            id="reject",
        ),
        pytest.param(
            lambda c, s, b, a: pay_cash(c, s.manager_in.headers, b), "paid", id="cash"
        ),
        pytest.param(
            lambda c, s, b, a: change_status(
                c, s.owner_in.headers, b, status="rejected", reason="No."
            ),
            "rejected",
            id="manual",
        ),
        pytest.param(
            lambda c, s, b, a: upload_receipt(c, s.tenant_in.headers, b),
            "awaitingVerification",
            id="upload",
        ),
    ],
)
def test_the_hook_is_called_once_for_each_kind_of_change(
    client, database, scene, bill, awaiting, hook, action, expected
):
    response = action(client, scene, bill, awaiting)
    assert response.status_code in (200, 201), response.text
    ((is_session, _, status),) = hook.calls
    assert is_session is True
    assert status == expected


@pytest.mark.parametrize("attempt", FAILING)
def test_the_hook_is_not_called_for_a_refused_request(
    client, database, scene, bill, awaiting, hook, attempt
):
    response = attempt(client, scene, bill, awaiting)
    assert response.status_code >= 400
    assert hook.calls == []


@pytest.mark.parametrize(
    ("action", "target", "expected"),
    [
        pytest.param(
            lambda c, s, b: verify(c, s.owner_in.headers, b),
            "awaiting",
            "paid",
            id="verify",
        ),
        pytest.param(
            lambda c, s, b: reject(c, s.owner_in.headers, b, "Blurry."),
            "awaiting",
            "rejected",
            id="reject",
        ),
        pytest.param(
            lambda c, s, b: pay_cash(c, s.manager_in.headers, b),
            "bill",
            "paid",
            id="cash",
        ),
        pytest.param(
            lambda c, s, b: change_status(
                c, s.owner_in.headers, b, status="rejected", reason="No."
            ),
            "bill",
            "rejected",
            id="manual",
        ),
        pytest.param(
            lambda c, s, b: upload_receipt(c, s.tenant_in.headers, b),
            "bill",
            "awaitingVerification",
            id="upload",
        ),
    ],
)
def test_a_failing_notification_does_not_undo_the_change(
    client, database, scene, bill, awaiting, monkeypatch, action, target, expected
):
    failing = StatusHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.rent_bills.notify_status_change", failing)
    stored = {"bill": bill, "awaiting": awaiting}[target]
    response = action(client, scene, stored)
    assert response.status_code in (200, 201), response.text
    assert response.json()["payment"]["status"] == expected
    assert len(failing.calls) == 1
    assert stored_bill(database, stored).payment_status == expected
    assert [c.status for c in stored_changes(database, stored)][-1] == expected


def test_a_failing_notification_leaves_the_bill_in_its_new_status(
    client, database, scene, awaiting, monkeypatch
):
    failing = StatusHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.rent_bills.notify_status_change", failing)
    assert verify(client, scene.owner_in.headers, awaiting).status_code == 200
    row = stored_bill(database, awaiting)
    assert row.payment_status == "paid"
    assert row.payment_method == "transfer"
    assert [c.status for c in stored_changes(database, awaiting)][-1] == "paid"


def test_a_failing_notification_is_not_shown_to_the_caller(
    client, database, scene, bill, monkeypatch
):
    failing = StatusHook(error=RuntimeError("notification down"))
    monkeypatch.setattr("app.services.rent_bills.notify_status_change", failing)
    response = upload_receipt(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200
    assert "notification down" not in response.text


def test_the_bill_can_be_changed_again_after_a_failing_notification(
    client, database, scene, bill, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(
            "app.services.rent_bills.notify_status_change",
            StatusHook(error=RuntimeError("notification down")),
        )
        assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200
    assert verify(client, scene.owner_in.headers, bill).status_code == 200
    assert types(client, scene.tenant_in) == ["paymentStatusChanged"]
