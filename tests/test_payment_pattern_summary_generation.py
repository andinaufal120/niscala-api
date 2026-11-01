"""Clearing, scheduling and regenerating the stored payment pattern summaries."""

import time
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from payment_summary_support import (
    SUMMARY_TEXT,
    add_bill,
    all_summaries,
    store_summary,
    stored_summary,
)
from rent_bill_support import (
    GIF_BYTES,
    TODAY,
    at_noon_jakarta,
    bill_url,
    days_ago,
    days_ahead,
    png,
)
from sqlalchemy.orm import Session

ACTIONS = ["receipt", "verification", "rejection", "cash_payment", "status_change"]
RESULTING_STATUS = {
    "receipt": "awaitingVerification",
    "verification": "paid",
    "rejection": "rejected",
    "cash_payment": "paid",
    "status_change": "rejected",
}


def facts_of(**overrides):
    from app.services.payment_patterns import PaymentFacts

    values = {
        "on_time_count": 0,
        "counted_bill_count": 0,
        "average_days_late": 0,
        "arrears": 0,
        "at_risk": False,
    }
    return PaymentFacts(**{**values, **overrides})


def counted(due_date, status, days_late):
    from app.services.payment_patterns import CountedBill

    return CountedBill(due_date, status, days_late)


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def subscribed(scene, subscribe_owner):
    subscribe_owner(scene.owner, "basic")


@pytest.fixture
def other_lease(scene, make_room, make_verified_tenant):
    """The active lease of a second tenant in the same property."""
    return make_verified_tenant(
        make_room(scene.prop, number="A2"), name="Ani Tenant"
    ).lease


def prepare(make_rent_bill, lease, action):
    """Commit a bill, three days overdue, that the action can be applied to."""
    extra = {}
    status = "unpaid"
    if action in ("verification", "rejection"):
        status = "awaitingVerification"
        extra["receipt"] = (png(), "image/png", at_noon_jakarta(days_ago(1)))
    return make_rent_bill(
        lease,
        period_start=days_ago(30),
        period_end=days_ago(1),
        due_date=days_ago(3),
        status=status,
        **extra,
    )


def send(client, scene, bill, action):
    if action == "receipt":
        return client.put(
            bill_url(bill, "/receipt"),
            files={"file": ("receipt.png", png(), "image/png")},
            headers=scene.tenant_in.headers,
        )
    headers = scene.owner_in.headers
    if action == "verification":
        return client.post(bill_url(bill, "/verification"), headers=headers)
    if action == "rejection":
        return client.post(
            bill_url(bill, "/rejection"), json={"reason": "Blurry."}, headers=headers
        )
    if action == "cash_payment":
        return client.post(
            bill_url(bill, "/cash-payment"),
            json={"receivedOn": TODAY.isoformat()},
            headers=headers,
        )
    return client.post(
        bill_url(bill, "/status-changes"),
        json={"status": "rejected", "reason": "Checked by hand."},
        headers=headers,
    )


def send_failing(client, scene, bill, action):
    """Send a request for the action that the API refuses."""
    if action == "receipt":
        return client.put(
            bill_url(bill, "/receipt"),
            files={"file": ("receipt.gif", GIF_BYTES, "image/gif")},
            headers=scene.tenant_in.headers,
        )
    headers = scene.owner_in.headers
    if action == "verification":
        return client.post(bill_url(bill, "/verification"), headers=headers)
    if action == "rejection":
        return client.post(
            bill_url(bill, "/rejection"), json={"reason": "  "}, headers=headers
        )
    if action == "cash_payment":
        return client.post(
            bill_url(bill, "/cash-payment"),
            json={"receivedOn": days_ahead(1).isoformat()},
            headers=headers,
        )
    return client.post(
        bill_url(bill, "/status-changes"),
        json={"status": "unpaid", "reason": "Checked by hand."},
        headers=headers,
    )


def prepare_failing(make_rent_bill, lease, action):
    """A bill for which `send_failing` is refused."""
    if action == "verification":
        return make_rent_bill(lease, status="unpaid")
    if action == "rejection":
        return prepare(make_rent_bill, lease, "rejection")
    return prepare(make_rent_bill, lease, "cash_payment")


# Clearing the stored summary


@pytest.mark.parametrize("action", ACTIONS)
def test_a_payment_status_change_clears_the_stored_summary(
    client, database, scene, lease, make_rent_bill, fake_summarizer, action
):
    from app.ai.summarizer import SummaryUnavailable

    fake_summarizer.error = SummaryUnavailable("down")
    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, lease, "Old summary.")
    response = send(client, scene, bill, action)
    assert response.status_code in (200, 201), response.text
    assert stored_summary(database, lease) is None


@pytest.mark.parametrize("action", ACTIONS)
def test_a_change_clears_the_summary_without_a_subscription(
    client, database, scene, lease, make_rent_bill, fake_summarizer, action
):
    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, lease, "Old summary.")
    response = send(client, scene, bill, action)
    assert response.status_code in (200, 201), response.text
    assert stored_summary(database, lease) is None
    assert fake_summarizer.calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_a_change_leaves_the_summary_of_another_lease(
    client, database, scene, lease, other_lease, make_rent_bill, fake_summarizer, action
):
    from app.ai.summarizer import SummaryUnavailable

    fake_summarizer.error = SummaryUnavailable("down")
    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, other_lease, "Ani summary.")
    send(client, scene, bill, action)
    kept = stored_summary(database, other_lease)
    assert kept is not None
    assert kept.summary == "Ani summary."


@pytest.mark.parametrize("action", ACTIONS)
def test_a_refused_request_leaves_the_stored_summary(
    client, database, scene, lease, subscribed, make_rent_bill, fake_summarizer, action
):
    bill = prepare_failing(make_rent_bill, lease, action)
    store_summary(database, lease, "Old summary.")
    response = send_failing(client, scene, bill, action)
    assert 400 <= response.status_code < 500, response.text
    kept = stored_summary(database, lease)
    assert kept is not None
    assert kept.summary == "Old summary."


def test_a_forbidden_request_leaves_the_stored_summary(
    client, database, scene, lease, subscribed, make_rent_bill, fake_summarizer
):
    bill = prepare(make_rent_bill, lease, "verification")
    store_summary(database, lease, "Old summary.")
    response = client.post(
        bill_url(bill, "/verification"), headers=scene.tenant_in.headers
    )
    assert response.status_code == 403
    assert stored_summary(database, lease).summary == "Old summary."
    assert fake_summarizer.calls == []


def test_an_unknown_bill_leaves_the_stored_summary(
    client, database, scene, lease, subscribed, fake_summarizer
):
    store_summary(database, lease, "Old summary.")
    response = client.post(
        f"/rent-bills/{uuid4()}/verification", headers=scene.owner_in.headers
    )
    assert response.status_code == 404
    assert stored_summary(database, lease).summary == "Old summary."
    assert fake_summarizer.calls == []


# Scheduling the regeneration


@pytest.mark.parametrize("action", ACTIONS)
def test_a_successful_change_stores_a_new_summary(
    client,
    database,
    scene,
    lease,
    subscribed,
    make_rent_bill,
    fake_summarizer,
    action,
):
    fake_summarizer.result = "Ringkasan baru."
    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, lease, "Old summary.")
    before = datetime.now(UTC)
    response = send(client, scene, bill, action)
    assert response.status_code in (200, 201), response.text
    assert len(fake_summarizer.calls) == 1
    row = stored_summary(database, lease)
    assert row.summary == "Ringkasan baru."
    assert before <= row.generated_at <= datetime.now(UTC)


@pytest.mark.parametrize("action", ACTIONS)
def test_the_summary_is_generated_after_the_change_is_committed(
    client,
    database,
    scene,
    lease,
    subscribed,
    make_rent_bill,
    fake_summarizer,
    action,
):
    from app.models import RentBill

    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, lease, "Old summary.")
    seen = {}

    def observe():
        with Session(database) as db:
            seen["status"] = db.get(RentBill, bill.id).payment_status
        seen["summary"] = stored_summary(database, lease)

    fake_summarizer.on_call = observe
    send(client, scene, bill, action)
    assert seen["status"] == RESULTING_STATUS[action]
    assert seen["summary"] is None


def test_a_verification_summarizes_the_facts_after_the_change(
    client, scene, lease, subscribed, make_rent_bill, fake_summarizer
):
    bill = prepare(make_rent_bill, lease, "verification")
    send(client, scene, bill, "verification")
    ((facts, bills),) = fake_summarizer.calls
    assert facts == facts_of(on_time_count=0, counted_bill_count=1, average_days_late=2)
    assert bills == [counted(days_ago(3), "paid", 2)]


def test_a_cash_payment_summarizes_the_facts_after_the_change(
    client, scene, lease, subscribed, make_rent_bill, fake_summarizer
):
    bill = prepare(make_rent_bill, lease, "cash_payment")
    send(client, scene, bill, "cash_payment")
    ((facts, bills),) = fake_summarizer.calls
    assert facts == facts_of(on_time_count=0, counted_bill_count=1, average_days_late=3)
    assert bills == [counted(days_ago(3), "paid", 3)]


def test_a_rejection_summarizes_the_arrears_after_the_change(
    client, scene, lease, subscribed, make_rent_bill, fake_summarizer
):
    bill = prepare(make_rent_bill, lease, "rejection")
    send(client, scene, bill, "rejection")
    ((facts, bills),) = fake_summarizer.calls
    assert facts == facts_of(counted_bill_count=1, average_days_late=3, arrears=1000000)
    assert bills == [counted(days_ago(3), "rejected", 3)]


@pytest.mark.parametrize("action", ACTIONS)
def test_a_change_to_one_lease_regenerates_only_that_lease(
    client,
    database,
    scene,
    lease,
    other_lease,
    subscribed,
    make_rent_bill,
    fake_summarizer,
    action,
):
    bill = prepare(make_rent_bill, lease, action)
    store_summary(database, other_lease, "Ani summary.")
    send(client, scene, bill, action)
    assert len(fake_summarizer.calls) == 1
    assert stored_summary(database, other_lease).summary == "Ani summary."
    assert stored_summary(database, lease).summary == SUMMARY_TEXT


@pytest.mark.parametrize("action", ACTIONS)
def test_a_change_without_a_subscription_stores_no_summary(
    client, database, scene, lease, make_rent_bill, fake_summarizer, action
):
    bill = prepare(make_rent_bill, lease, action)
    send(client, scene, bill, action)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


@pytest.mark.parametrize("action", ACTIONS)
def test_a_change_with_an_expired_subscription_stores_no_summary(
    client,
    database,
    scene,
    lease,
    subscribed,
    expire_subscription,
    make_rent_bill,
    fake_summarizer,
    action,
):
    expire_subscription(scene.owner)
    bill = prepare(make_rent_bill, lease, action)
    send(client, scene, bill, action)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


@pytest.mark.parametrize("action", ACTIONS)
def test_a_refused_request_does_not_schedule_a_summary(
    client, scene, lease, subscribed, make_rent_bill, fake_summarizer, action
):
    bill = prepare_failing(make_rent_bill, lease, action)
    response = send_failing(client, scene, bill, action)
    assert 400 <= response.status_code < 500, response.text
    assert fake_summarizer.calls == []


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("boom"), ValueError("bad"), "unavailable"],
    ids=["runtime_error", "value_error", "summary_unavailable"],
)
def test_a_failing_summarizer_does_not_fail_the_change(
    client,
    database,
    scene,
    lease,
    subscribed,
    make_rent_bill,
    fake_summarizer,
    action,
    failure,
):
    from app.ai.summarizer import SummaryUnavailable

    from app.models import RentBill

    fake_summarizer.error = (
        SummaryUnavailable("down") if failure == "unavailable" else failure
    )
    bill = prepare(make_rent_bill, lease, action)
    response = send(client, scene, bill, action)
    assert response.status_code in (200, 201), response.text
    assert response.json()["payment"]["status"] == RESULTING_STATUS[action]
    with Session(database) as db:
        assert db.get(RentBill, bill.id).payment_status == RESULTING_STATUS[action]
    assert all_summaries(database) == []


def test_the_unavailable_summarizer_leaves_no_summary_after_a_change(
    app, client, database, scene, lease, subscribed, make_rent_bill
):
    from app.ai.summarizer import (
        UnavailablePaymentSummarizer,
        get_payment_pattern_summarizer,
    )

    app.dependency_overrides[get_payment_pattern_summarizer] = lambda: (
        UnavailablePaymentSummarizer()
    )
    try:
        bill = prepare(make_rent_bill, lease, "verification")
        store_summary(database, lease, "Old summary.")
        response = send(client, scene, bill, "verification")
    finally:
        app.dependency_overrides.pop(get_payment_pattern_summarizer, None)
    assert response.status_code == 200, response.text
    assert all_summaries(database) == []


# Clearing a summary directly


def test_clear_summary_removes_the_row_of_the_lease(database, lease, other_lease):
    from app.services.payment_patterns import clear_summary

    store_summary(database, lease, "Budi summary.")
    store_summary(database, other_lease, "Ani summary.")
    with Session(database) as db:
        clear_summary(db, lease.id)
        db.commit()
    assert stored_summary(database, lease) is None
    assert stored_summary(database, other_lease).summary == "Ani summary."


def test_clear_summary_does_not_commit(database, lease):
    from app.services.payment_patterns import clear_summary

    store_summary(database, lease, "Budi summary.")
    with Session(database) as db:
        clear_summary(db, lease.id)
        db.rollback()
    assert stored_summary(database, lease).summary == "Budi summary."


def test_clear_summary_without_a_stored_summary_does_nothing(database, lease):
    from app.services.payment_patterns import clear_summary

    with Session(database) as db:
        clear_summary(db, lease.id)
        db.commit()
    assert all_summaries(database) == []


# Regenerating a summary


@pytest.fixture
def history(lease, make_rent_bill):
    """Three counted bills and one that is not counted, as of the fixed date."""
    return SimpleNamespace(
        old=add_bill(make_rent_bill, lease, 3, 80, "awaitingVerification"),
        oldest_paid=add_bill(make_rent_bill, lease, 2, 50, "paid", late=4),
        on_time=add_bill(make_rent_bill, lease, 1, 20, "paid"),
        overdue=add_bill(make_rent_bill, lease, 0, 3, "unpaid"),
    )


def regenerate(lease, summarizer):
    from app.services.payment_patterns import regenerate_summary

    return regenerate_summary(lease.id, summarizer)


def test_a_summary_is_stored_for_a_subscribed_owner(
    database, scene, lease, subscribed, history, fake_summarizer
):
    fake_summarizer.result = "Ringkasan."
    before = datetime.now(UTC)
    regenerate(lease, fake_summarizer)
    row = stored_summary(database, lease)
    assert row.summary == "Ringkasan."
    assert row.generated_at.tzinfo is not None
    assert before <= row.generated_at <= datetime.now(UTC)


def test_a_new_summary_replaces_a_stored_one(
    database, scene, lease, subscribed, history, fake_summarizer
):
    store_summary(database, lease, "Old summary.")
    fake_summarizer.result = "Ringkasan baru."
    regenerate(lease, fake_summarizer)
    assert [text for _, text, _ in all_summaries(database)] == ["Ringkasan baru."]


def test_a_summary_is_stored_only_for_the_given_lease(
    database, scene, lease, other_lease, subscribed, history, fake_summarizer
):
    regenerate(lease, fake_summarizer)
    assert stored_summary(database, other_lease) is None
    assert stored_summary(database, lease) is not None


def test_the_summarizer_gets_the_facts_and_counted_bills_as_of_today(
    scene, lease, subscribed, history, fake_summarizer
):
    regenerate(lease, fake_summarizer)
    ((facts, bills),) = fake_summarizer.calls
    assert facts == facts_of(
        on_time_count=1,
        counted_bill_count=3,
        average_days_late=4,
        arrears=1000000,
        at_risk=True,
    )
    assert bills == [
        counted(days_ago(3), "unpaid", 3),
        counted(days_ago(20), "paid", 0),
        counted(days_ago(50), "paid", 4),
    ]


def test_the_summarizer_gets_the_facts_as_of_the_jakarta_date_at_the_call(
    monkeypatch, scene, lease, subscribed, history, fake_summarizer
):
    later = TODAY + timedelta(days=10)
    monkeypatch.setattr("app.services.rent_bills.today_jakarta", lambda: later)
    regenerate(lease, fake_summarizer)
    ((facts, bills),) = fake_summarizer.calls
    assert bills[0] == counted(days_ago(3), "unpaid", 13)
    assert facts.average_days_late == 9
    assert facts.arrears == 1000000


def test_no_subscription_means_no_summary_and_no_call(
    database, scene, lease, history, fake_summarizer
):
    regenerate(lease, fake_summarizer)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


def test_an_expired_subscription_means_no_summary_and_no_call(
    database,
    scene,
    lease,
    subscribed,
    expire_subscription,
    history,
    fake_summarizer,
):
    expire_subscription(scene.owner)
    regenerate(lease, fake_summarizer)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


def test_the_subscription_is_checked_when_the_task_runs(
    database, scene, lease, subscribed, expire_subscription, history, fake_summarizer
):
    store_summary(database, lease, "Old summary.")
    expire_subscription(scene.owner)
    regenerate(lease, fake_summarizer)
    assert fake_summarizer.calls == []
    assert stored_summary(database, lease).summary == "Old summary."


def test_an_ended_lease_gets_no_summary_and_no_call(
    database, scene, lease, subscribed, history, fake_summarizer
):
    from app.models import Lease

    with Session(database) as db:
        db.get(Lease, lease.id).ended_at = datetime.now(UTC)
        db.commit()
    regenerate(lease, fake_summarizer)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


def test_an_unknown_lease_does_not_raise(database, subscribed, fake_summarizer):
    from app.services.payment_patterns import regenerate_summary

    regenerate_summary(uuid4(), fake_summarizer)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("unavailable", id="summary_unavailable"),
        pytest.param(RuntimeError("boom"), id="runtime_error"),
        pytest.param(ValueError("bad"), id="value_error"),
        pytest.param(KeyError("x"), id="key_error"),
    ],
)
def test_a_failing_summarizer_stores_nothing_and_does_not_raise(
    database, scene, lease, subscribed, history, fake_summarizer, failure
):
    from app.ai.summarizer import SummaryUnavailable

    fake_summarizer.error = (
        SummaryUnavailable("down") if failure == "unavailable" else failure
    )
    regenerate(lease, fake_summarizer)
    assert len(fake_summarizer.calls) == 1
    assert all_summaries(database) == []


def test_a_slow_summarizer_is_given_up_on(
    monkeypatch, database, scene, lease, subscribed, history, fake_summarizer
):
    from app.services import payment_patterns

    monkeypatch.setattr(payment_patterns, "SUMMARY_TIMEOUT_SECONDS", 0.2)
    fake_summarizer.delay = 1.0
    started = time.monotonic()
    regenerate(lease, fake_summarizer)
    assert time.monotonic() - started < 0.9
    assert all_summaries(database) == []
    time.sleep(1.0)
    assert all_summaries(database) == []


def test_a_summarizer_within_the_timeout_is_used(
    monkeypatch, database, scene, lease, subscribed, history, fake_summarizer
):
    from app.services import payment_patterns

    monkeypatch.setattr(payment_patterns, "SUMMARY_TIMEOUT_SECONDS", 2.0)
    fake_summarizer.delay = 0.1
    regenerate(lease, fake_summarizer)
    assert stored_summary(database, lease) is not None


@pytest.mark.parametrize(
    "result",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n\t", id="whitespace"),
        pytest.param("a" * 501, id="over_five_hundred_characters"),
    ],
)
def test_an_unusable_result_is_not_stored(
    database, scene, lease, subscribed, history, fake_summarizer, result
):
    fake_summarizer.result = result
    regenerate(lease, fake_summarizer)
    assert all_summaries(database) == []


def test_a_result_of_five_hundred_characters_is_stored(
    database, scene, lease, subscribed, history, fake_summarizer
):
    fake_summarizer.result = "a" * 500
    regenerate(lease, fake_summarizer)
    assert stored_summary(database, lease).summary == "a" * 500


def test_a_result_computed_from_facts_that_changed_meanwhile_is_discarded(
    database, scene, lease, subscribed, history, fake_summarizer
):
    from app.models import RentBill

    def pay_the_overdue_bill_meanwhile():
        with Session(database) as db:
            row = db.get(RentBill, history.overdue.id)
            row.payment_status = "paid"
            row.payment_method = "cash"
            row.paid_on = row.due_date
            db.commit()

    fake_summarizer.on_call = pay_the_overdue_bill_meanwhile
    regenerate(lease, fake_summarizer)
    assert len(fake_summarizer.calls) == 1
    assert all_summaries(database) == []


def test_a_result_is_kept_when_the_facts_did_not_change(
    database, scene, lease, subscribed, history, fake_summarizer
):
    from app.models import RentBill

    def touch_a_bill_without_changing_the_facts():
        with Session(database) as db:
            db.get(RentBill, history.old.id).created_at = datetime.now(UTC)
            db.commit()

    fake_summarizer.on_call = touch_a_bill_without_changing_the_facts
    regenerate(lease, fake_summarizer)
    assert stored_summary(database, lease) is not None


# The counted bills


def bill(due_date, status="paid", *, paid_on=None, period_start=None, amount=100):
    return SimpleNamespace(
        id=uuid4(),
        due_date=due_date,
        payment_status=status,
        paid_on=paid_on,
        period_start=period_start or due_date - timedelta(days=25),
        amount=amount,
    )


NOW = date(2026, 10, 23)


def test_counted_bills_are_newest_first():
    from app.services.payment_patterns import counted_bills

    bills = [
        bill(date(2026, 8, 5), paid_on=date(2026, 8, 5)),
        bill(date(2026, 10, 5), paid_on=date(2026, 10, 5)),
        bill(date(2026, 9, 5), paid_on=date(2026, 9, 5)),
    ]
    assert [c.due_date for c in counted_bills(bills, NOW)] == [
        date(2026, 10, 5),
        date(2026, 9, 5),
        date(2026, 8, 5),
    ]


def test_counted_bills_keep_the_latest_six():
    from app.services.payment_patterns import counted_bills

    bills = [
        bill(date(2026, 1, 1) + timedelta(days=30 * n), paid_on=date(2026, 1, 1))
        for n in range(8)
    ]
    result = counted_bills(bills, NOW)
    assert len(result) == 6
    assert result[0].due_date == date(2026, 1, 1) + timedelta(days=30 * 7)
    assert result[-1].due_date == date(2026, 1, 1) + timedelta(days=30 * 2)


def test_counted_bills_skip_bills_that_are_not_paid_or_overdue():
    from app.services.payment_patterns import counted_bills

    bills = [
        bill(date(2026, 10, 30), "unpaid"),
        bill(date(2026, 10, 1), "awaitingVerification"),
        bill(date(2026, 10, 23), "unpaid"),
        bill(date(2026, 10, 2), "paid", paid_on=date(2026, 10, 2)),
    ]
    assert [c.due_date for c in counted_bills(bills, NOW)] == [date(2026, 10, 2)]


def test_counted_bills_of_an_empty_history_are_empty():
    from app.services.payment_patterns import counted_bills

    assert counted_bills([], NOW) == []


def test_days_late_of_an_overdue_bill_is_the_days_overdue():
    from app.services.payment_patterns import counted_bills

    (result,) = counted_bills([bill(date(2026, 10, 13), "unpaid")], NOW)
    assert result.status == "unpaid"
    assert result.days_late == 10


def test_days_late_of_a_rejected_overdue_bill_is_the_days_overdue():
    from app.services.payment_patterns import counted_bills

    (result,) = counted_bills([bill(date(2026, 10, 20), "rejected")], NOW)
    assert result.status == "rejected"
    assert result.days_late == 3


def test_days_late_of_a_bill_paid_late_is_the_days_between_due_and_payment():
    from app.services.payment_patterns import counted_bills

    (result,) = counted_bills([bill(date(2026, 10, 1), paid_on=date(2026, 10, 8))], NOW)
    assert result.status == "paid"
    assert result.days_late == 7


@pytest.mark.parametrize("paid_on", [date(2026, 10, 1), date(2026, 9, 25)])
def test_days_late_of_a_bill_paid_on_or_before_its_due_date_is_zero(paid_on):
    from app.services.payment_patterns import counted_bills

    (result,) = counted_bills([bill(date(2026, 10, 1), paid_on=paid_on)], NOW)
    assert result.days_late == 0


def test_counted_bills_agree_with_the_facts():
    from app.services.payment_patterns import compute_payment_facts, counted_bills

    bills = [
        bill(date(2026, 10, 1), "unpaid"),
        bill(date(2026, 9, 1), "paid", paid_on=date(2026, 9, 6)),
        bill(date(2026, 8, 1), "paid", paid_on=date(2026, 8, 1)),
        bill(date(2026, 7, 1), "rejected"),
        bill(date(2026, 6, 1), "paid", paid_on=date(2026, 6, 1)),
        bill(date(2026, 5, 1), "paid", paid_on=date(2026, 5, 3)),
        bill(date(2026, 4, 1), "paid", paid_on=date(2026, 4, 1)),
        bill(date(2026, 3, 1), "paid", paid_on=date(2026, 3, 1)),
        bill(date(2026, 11, 1), "unpaid"),
    ]
    facts = compute_payment_facts(bills, NOW)
    result = counted_bills(bills, NOW)
    late = [c.days_late for c in result if c.days_late > 0]
    assert len(result) == facts.counted_bill_count
    assert len(result) - len(late) == facts.on_time_count
    assert facts.average_days_late == (2 * sum(late) + len(late)) // (2 * len(late))


def test_a_counted_bill_is_immutable():
    from dataclasses import FrozenInstanceError

    result = counted(date(2026, 10, 1), "paid", 0)
    with pytest.raises(FrozenInstanceError):
        result.days_late = 5


def test_counted_bills_compare_by_value():
    assert counted(date(2026, 10, 1), "paid", 2) == counted(
        date(2026, 10, 1), "paid", 2
    )
    assert counted(date(2026, 10, 1), "paid", 2) != counted(
        date(2026, 10, 1), "paid", 3
    )
