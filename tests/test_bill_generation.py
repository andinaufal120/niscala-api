"""Creating the missing rent bills of active leases."""

from datetime import date, timedelta
from itertools import count

import pytest
from bill_generation_support import (
    build_site,
    edit_lease,
    freeze_date,
    freeze_instant,
    generate,
    only_bill,
    periods,
    stored_bills,
    utc,
)
from notification_support import of_type, stored_rows
from rent_bill_support import (
    CHANGE_FIELDS,
    DETAIL_FIELDS,
    PAYMENT_FIELDS,
    RENT_BILLS,
    at_noon_jakarta,
    parse_time,
    stored_changes,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

TODAY = date(2026, 3, 15)


@pytest.fixture
def site(database, make_user, make_property, make_room, assign_manager, sign_in):
    return build_site(make_user, make_property, make_room, assign_manager, sign_in)


@pytest.fixture
def add_lease(site, make_room, make_verified_tenant):
    """Add a tenant with an active lease in a new room; lease options are keywords."""
    numbers = count(2)

    def add(**options):
        options.setdefault("start_date", date(2026, 1, 10))
        room = make_room(site.prop, number=f"R{next(numbers)}")
        return make_verified_tenant(room, **options)

    return add


@pytest.fixture
def today_is(monkeypatch):
    """Fix today in Jakarta for one test; call it again to move the date."""

    def set_day(day: date) -> None:
        freeze_date(monkeypatch, day)

    set_day(TODAY)
    return set_day


# Period: which period gets the bill


@pytest.mark.parametrize(
    ("cycle", "start", "today", "expected_start", "expected_end"),
    [
        pytest.param(
            "monthly",
            date(2026, 1, 10),
            date(2026, 3, 10),
            date(2026, 3, 10),
            date(2026, 4, 9),
            id="monthly-today-is-a-period-start",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 10),
            date(2026, 3, 25),
            date(2026, 3, 10),
            date(2026, 4, 9),
            id="monthly-mid-period",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 10),
            date(2026, 4, 9),
            date(2026, 3, 10),
            date(2026, 4, 9),
            id="monthly-last-day-of-the-period",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 10),
            date(2026, 3, 9),
            date(2026, 2, 10),
            date(2026, 3, 9),
            id="monthly-day-before-a-period-start",
        ),
        pytest.param(
            "monthly",
            date(2026, 3, 10),
            date(2026, 3, 10),
            date(2026, 3, 10),
            date(2026, 4, 9),
            id="monthly-lease-starts-today",
        ),
        pytest.param(
            "monthly",
            date(2026, 3, 10),
            date(2026, 3, 14),
            date(2026, 3, 10),
            date(2026, 4, 9),
            id="monthly-lease-started-a-few-days-ago",
        ),
        pytest.param(
            "weekly",
            date(2026, 3, 2),
            date(2026, 3, 16),
            date(2026, 3, 16),
            date(2026, 3, 22),
            id="weekly-today-is-a-period-start",
        ),
        pytest.param(
            "weekly",
            date(2026, 3, 2),
            date(2026, 3, 22),
            date(2026, 3, 16),
            date(2026, 3, 22),
            id="weekly-last-day-of-the-period",
        ),
        pytest.param(
            "weekly",
            date(2026, 3, 2),
            date(2026, 3, 23),
            date(2026, 3, 23),
            date(2026, 3, 29),
            id="weekly-first-day-of-the-next-period",
        ),
        pytest.param(
            "weekly",
            date(2026, 2, 26),
            date(2026, 3, 10),
            date(2026, 3, 5),
            date(2026, 3, 11),
            id="weekly-across-a-month-end",
        ),
        pytest.param(
            "quarterly",
            date(2026, 1, 15),
            date(2026, 5, 1),
            date(2026, 4, 15),
            date(2026, 7, 14),
            id="quarterly-mid-period",
        ),
        pytest.param(
            "quarterly",
            date(2026, 1, 15),
            date(2026, 4, 15),
            date(2026, 4, 15),
            date(2026, 7, 14),
            id="quarterly-today-is-a-period-start",
        ),
        pytest.param(
            "quarterly",
            date(2026, 1, 15),
            date(2026, 4, 14),
            date(2026, 1, 15),
            date(2026, 4, 14),
            id="quarterly-day-before-a-period-start",
        ),
        pytest.param(
            "semiannual",
            date(2025, 12, 1),
            date(2026, 6, 30),
            date(2026, 6, 1),
            date(2026, 11, 30),
            id="semiannual-mid-period",
        ),
        pytest.param(
            "semiannual",
            date(2025, 12, 1),
            date(2026, 5, 31),
            date(2025, 12, 1),
            date(2026, 5, 31),
            id="semiannual-last-day-of-the-period",
        ),
        pytest.param(
            "annual",
            date(2024, 3, 15),
            date(2026, 10, 23),
            date(2026, 3, 15),
            date(2027, 3, 14),
            id="annual-mid-period",
        ),
        pytest.param(
            "annual",
            date(2024, 3, 15),
            date(2026, 3, 15),
            date(2026, 3, 15),
            date(2027, 3, 14),
            id="annual-today-is-a-period-start",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 2, 28),
            date(2026, 3, 30),
            id="monthly-from-the-31st-clamped-in-february",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 31),
            date(2026, 3, 15),
            date(2026, 2, 28),
            date(2026, 3, 30),
            id="monthly-from-the-31st-clamped-period-runs-into-march",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 31),
            date(2026, 3, 31),
            date(2026, 3, 31),
            date(2026, 4, 29),
            id="monthly-from-the-31st-back-to-the-31st",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 31),
            date(2026, 4, 30),
            date(2026, 4, 30),
            date(2026, 5, 30),
            id="monthly-from-the-31st-clamped-in-a-30-day-month",
        ),
        pytest.param(
            "monthly",
            date(2027, 12, 31),
            date(2028, 2, 29),
            date(2028, 2, 29),
            date(2028, 3, 30),
            id="monthly-from-the-31st-in-a-leap-february",
        ),
        pytest.param(
            "monthly",
            date(2027, 12, 31),
            date(2028, 1, 31),
            date(2028, 1, 31),
            date(2028, 2, 28),
            id="monthly-period-before-a-leap-day-start",
        ),
        pytest.param(
            "monthly",
            date(2026, 1, 30),
            date(2026, 2, 28),
            date(2026, 2, 28),
            date(2026, 3, 29),
            id="monthly-from-the-30th-clamped-in-february",
        ),
        pytest.param(
            "quarterly",
            date(2026, 11, 30),
            date(2027, 3, 10),
            date(2027, 2, 28),
            date(2027, 5, 29),
            id="quarterly-clamped-and-counted-from-the-start-date",
        ),
        pytest.param(
            "annual",
            date(2024, 2, 29),
            date(2026, 5, 10),
            date(2026, 2, 28),
            date(2027, 2, 27),
            id="annual-from-a-leap-day-clamped",
        ),
        pytest.param(
            "annual",
            date(2024, 2, 29),
            date(2028, 3, 1),
            date(2028, 2, 29),
            date(2029, 2, 27),
            id="annual-from-a-leap-day-back-on-the-leap-day",
        ),
    ],
)
def test_the_bill_is_for_the_period_containing_today(
    database,
    today_is,
    add_lease,
    cycle,
    start,
    today,
    expected_start,
    expected_end,
):
    today_is(today)
    tenant = add_lease(billing_cycle=cycle, start_date=start)
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(expected_start, expected_end)]


def test_a_lease_started_months_ago_gets_only_its_current_period(
    database, today_is, add_lease
):
    today_is(date(2026, 4, 20))
    tenant = add_lease(start_date=date(2025, 8, 15))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 4, 15), date(2026, 5, 14))]


def test_a_weekly_lease_started_long_ago_gets_only_its_current_period(
    database, today_is, add_lease
):
    today_is(date(2026, 3, 15))
    tenant = add_lease(billing_cycle="weekly", start_date=date(2025, 1, 1))
    assert generate(database) == 1
    (only,) = periods(database, tenant.lease)
    assert only[0] <= TODAY <= only[1]
    assert (only[1] - only[0]).days == 6


def test_earlier_periods_never_get_a_bill(database, today_is, add_lease):
    today_is(date(2026, 3, 15))
    tenant = add_lease(start_date=date(2025, 3, 10))
    generate(database)
    assert [start for start, _ in periods(database, tenant.lease)] == [
        date(2026, 3, 10)
    ]


def test_a_lease_whose_start_date_is_in_the_future_gets_no_bill(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=TODAY + timedelta(days=1))
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_lease_starting_far_in_the_future_gets_no_bill(database, today_is, add_lease):
    add_lease(start_date=date(2099, 1, 10))
    assert generate(database) == 0
    assert stored_bills(database) == []


def test_a_lease_gets_its_first_bill_on_the_day_it_starts(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=TODAY + timedelta(days=1))
    assert generate(database) == 0
    today_is(TODAY + timedelta(days=1))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [
        (TODAY + timedelta(days=1), date(2026, 4, 15))
    ]


def test_a_missed_run_is_made_up_while_the_period_is_current(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=date(2026, 1, 10))
    # No run on the 10th; the next run is eight days into the period.
    today_is(date(2026, 3, 18))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_period_that_already_has_a_bill_gets_no_second_one(
    database, today_is, add_lease, make_rent_bill
):
    tenant = add_lease(start_date=date(2026, 1, 10))
    existing = make_rent_bill(
        tenant.lease,
        period_start=date(2026, 3, 10),
        period_end=date(2026, 4, 9),
        due_date=date(2026, 3, 10),
        status="paid",
        method="cash",
        paid_on=date(2026, 3, 11),
    )
    assert generate(database) == 0
    (bill,) = stored_bills(database, tenant.lease)
    assert bill.id == existing.id
    assert bill.payment_status == "paid"


def test_a_bill_of_an_earlier_period_does_not_stop_the_current_one(
    database, today_is, add_lease, make_rent_bill
):
    tenant = add_lease(start_date=date(2026, 1, 10))
    earlier = make_rent_bill(
        tenant.lease,
        period_start=date(2026, 2, 10),
        period_end=date(2026, 3, 9),
        due_date=date(2026, 2, 10),
    )
    assert generate(database) == 1
    assert [b.period_start for b in stored_bills(database, tenant.lease)] == [
        earlier.period_start,
        date(2026, 3, 10),
    ]


def test_the_bill_of_another_lease_does_not_count_for_this_period(
    database, today_is, add_lease, make_rent_bill
):
    first = add_lease(start_date=date(2026, 1, 10))
    second = add_lease(start_date=date(2026, 1, 10))
    make_rent_bill(
        first.lease,
        period_start=date(2026, 3, 10),
        period_end=date(2026, 4, 9),
        due_date=date(2026, 3, 10),
    )
    assert generate(database) == 1
    assert len(stored_bills(database, first.lease)) == 1
    assert periods(database, second.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_skipped_period_is_not_billed_afterwards(database, today_is, add_lease):
    tenant = add_lease(start_date=date(2026, 1, 10))
    assert generate(database) == 1
    today_is(date(2026, 5, 12))
    assert generate(database) == 1
    assert [start for start, _ in periods(database, tenant.lease)] == [
        date(2026, 3, 10),
        date(2026, 5, 10),
    ]


def test_each_new_period_gets_its_own_bill(database, today_is, add_lease):
    tenant = add_lease(start_date=date(2026, 1, 10))
    generate(database)
    first = only_bill(database, tenant.lease)
    today_is(date(2026, 4, 10))
    assert generate(database) == 1
    bills = stored_bills(database, tenant.lease)
    assert [b.period_start for b in bills] == [date(2026, 3, 10), date(2026, 4, 10)]
    assert bills[0].id == first.id


# Period: today in the Asia/Jakarta calendar


def test_today_is_read_in_the_jakarta_calendar_just_after_midnight_there(
    database, monkeypatch, add_lease
):
    # 23:30 UTC on the 9th is already 06:30 on the 10th in Jakarta.
    freeze_instant(monkeypatch, utc(2026, 3, 9, 23, 30))
    tenant = add_lease(start_date=date(2026, 1, 10))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_lease_starting_on_the_jakarta_date_is_billed_at_23_30_utc_the_day_before(
    database, monkeypatch, add_lease
):
    freeze_instant(monkeypatch, utc(2026, 3, 9, 23, 30))
    tenant = add_lease(start_date=date(2026, 3, 10))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_lease_starting_the_next_jakarta_day_is_not_yet_billed_at_16_59_utc(
    database, monkeypatch, add_lease
):
    freeze_instant(monkeypatch, utc(2026, 3, 10, 16, 59))
    tenant = add_lease(start_date=date(2026, 3, 11))
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_lease_starting_the_next_jakarta_day_is_billed_from_17_00_utc(
    database, monkeypatch, add_lease
):
    freeze_instant(monkeypatch, utc(2026, 3, 10, 17, 0))
    tenant = add_lease(start_date=date(2026, 3, 11))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 11), date(2026, 4, 10))]


def test_the_period_before_a_start_is_billed_at_16_59_utc_on_the_day_before(
    database, monkeypatch, add_lease
):
    # 16:59 UTC on the 9th is 23:59 on the 9th in Jakarta.
    freeze_instant(monkeypatch, utc(2026, 3, 9, 16, 59))
    tenant = add_lease(start_date=date(2026, 1, 10))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 2, 10), date(2026, 3, 9))]


# Amount


@pytest.mark.parametrize(
    ("cycle", "rent"),
    [
        ("weekly", 250000),
        ("monthly", 1250000),
        ("quarterly", 3600000),
        ("semiannual", 7000000),
        ("annual", 13000000),
    ],
)
def test_the_bill_amount_is_the_rent_of_one_billing_cycle(
    database, today_is, add_lease, cycle, rent
):
    tenant = add_lease(billing_cycle=cycle, rent=rent)
    generate(database)
    assert only_bill(database, tenant.lease).amount == rent


def test_a_period_cut_short_by_the_lease_end_date_is_billed_in_full(
    database, today_is, add_lease
):
    tenant = add_lease(
        start_date=date(2026, 1, 10), end_date=date(2026, 3, 20), rent=1500000
    )
    assert generate(database) == 1
    bill = only_bill(database, tenant.lease)
    assert bill.amount == 1500000
    assert bill.period_start == date(2026, 3, 10)
    assert bill.period_end == date(2026, 4, 9)


def test_a_bill_keeps_its_amount_when_the_rent_changes_later(
    database, today_is, add_lease
):
    tenant = add_lease(rent=1000000)
    generate(database)
    edit_lease(database, tenant.lease, rent=1800000)
    assert generate(database) == 0
    assert only_bill(database, tenant.lease).amount == 1000000


def test_a_rent_change_applies_to_the_next_bill(database, today_is, add_lease):
    tenant = add_lease(rent=1000000)
    generate(database)
    edit_lease(database, tenant.lease, rent=1800000)
    today_is(date(2026, 4, 10))
    assert generate(database) == 1
    amounts = [b.amount for b in stored_bills(database, tenant.lease)]
    assert amounts == [1000000, 1800000]


def test_a_rent_changed_before_the_run_is_the_amount_of_the_bill(
    database, today_is, add_lease
):
    tenant = add_lease(rent=1000000)
    edit_lease(database, tenant.lease, rent=900000)
    generate(database)
    assert only_bill(database, tenant.lease).amount == 900000


# No bill


def test_a_lease_without_a_start_date_gets_no_bill(database, today_is, add_lease):
    tenant = add_lease(start_date=None)
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_an_ended_lease_gets_no_bill(database, today_is, add_lease):
    tenant = add_lease(lease_ended=True)
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_lease_ended_after_its_first_bill_gets_no_further_bill(
    database, today_is, add_lease
):
    from datetime import UTC, datetime

    tenant = add_lease()
    generate(database)
    edit_lease(database, tenant.lease, ended_at=datetime.now(UTC))
    today_is(date(2026, 4, 10))
    assert generate(database) == 0
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_lease_of_a_tenant_deleted_through_the_api_gets_no_bill(
    client, database, today_is, site, add_lease
):
    tenant = add_lease()
    response = client.delete(f"/tenants/{tenant.id}", headers=site.owner_in.headers)
    assert response.status_code == 204
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_lease_of_a_deleted_tenant_record_gets_no_bill(database, today_is, add_lease):
    tenant = add_lease(deleted=True)
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_lease_of_a_deleted_tenant_with_an_ended_lease_gets_no_bill(
    database, today_is, add_lease
):
    tenant = add_lease(deleted=True, lease_ended=True)
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_period_starting_after_the_lease_end_date_gets_no_bill(
    database, today_is, add_lease
):
    # The lease ended on March 5 but was never marked ended; the period that
    # contains today starts on March 10.
    tenant = add_lease(start_date=date(2026, 1, 10), end_date=date(2026, 3, 5))
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_period_starting_the_day_after_the_lease_end_date_gets_no_bill(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=date(2026, 1, 10), end_date=date(2026, 3, 9))
    assert generate(database) == 0
    assert stored_bills(database, tenant.lease) == []


def test_a_period_starting_on_the_lease_end_date_gets_a_bill(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=date(2026, 1, 10), end_date=date(2026, 3, 10))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_period_that_started_before_a_passed_end_date_is_still_billed(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=date(2026, 1, 10), end_date=date(2026, 3, 12))
    assert generate(database) == 1
    assert periods(database, tenant.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]


def test_a_lease_ending_exactly_today_is_billed_when_its_period_started(
    database, today_is, add_lease
):
    tenant = add_lease(start_date=date(2026, 1, 10), end_date=TODAY)
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


def test_only_the_leases_that_qualify_are_billed_in_a_mixed_run(
    database, today_is, add_lease
):
    good = add_lease()
    add_lease(start_date=None)
    add_lease(lease_ended=True)
    add_lease(start_date=date(2099, 1, 1))
    add_lease(deleted=True)
    add_lease(start_date=date(2026, 1, 10), end_date=date(2026, 3, 5))
    assert generate(database) == 1
    assert [b.lease_id for b in stored_bills(database)] == [good.lease.id]


# Content of the bill


@pytest.mark.parametrize("grace", [0, 1, 5, 30])
def test_the_due_date_is_the_period_start_plus_the_grace_period(
    database, today_is, add_lease, grace
):
    tenant = add_lease(grace_period_days=grace)
    generate(database)
    bill = only_bill(database, tenant.lease)
    assert bill.period_start == date(2026, 3, 10)
    assert bill.due_date == date(2026, 3, 10) + timedelta(days=grace)


def test_a_bill_without_a_grace_period_is_due_on_its_period_start(
    database, today_is, add_lease
):
    tenant = add_lease(grace_period_days=0)
    generate(database)
    bill = only_bill(database, tenant.lease)
    assert bill.due_date == bill.period_start


def test_a_bill_starts_unpaid_without_payment_details(database, today_is, add_lease):
    tenant = add_lease()
    generate(database)
    bill = only_bill(database, tenant.lease)
    assert bill.payment_status == "unpaid"
    assert bill.payment_method is None
    assert bill.paid_on is None
    assert bill.rejection_reason is None
    assert bill.lease_id == tenant.lease.id


def test_a_bill_has_a_single_status_history_entry_made_by_the_system(
    database, today_is, add_lease
):
    tenant = add_lease()
    generate(database)
    bill = only_bill(database, tenant.lease)
    (change,) = stored_changes(database, bill)
    assert change.status == "unpaid"
    assert change.method is None
    assert change.reason is None
    assert change.manual is False
    assert change.actor_id is None
    assert change.changed_at is not None


def test_the_tenant_sees_the_new_bill_in_the_list(
    client, database, today_is, add_lease, sign_in
):
    tenant = add_lease(rent=1250000, grace_period_days=4, start_date=TODAY)
    generate(database)
    bill = only_bill(database, tenant.lease)
    response = client.get(RENT_BILLS, headers=sign_in(tenant.user).headers)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert item["id"] == str(bill.id)
    assert item["periodStart"] == "2026-03-15"
    assert item["periodEnd"] == "2026-04-14"
    assert item["dueDate"] == "2026-03-19"
    assert item["amount"] == 1250000
    assert item["daysOverdue"] == 0
    assert item["isCurrent"] is True
    assert item["payment"] == {
        "status": "unpaid",
        "method": None,
        "paidOn": None,
        "hasReceipt": False,
        "rejectionReason": None,
    }


def test_the_bill_detail_shows_one_unpaid_entry_by_the_system(
    client, database, today_is, add_lease, sign_in
):
    tenant = add_lease(start_date=TODAY)
    generate(database)
    bill = only_bill(database, tenant.lease)
    response = client.get(
        f"{RENT_BILLS}/{bill.id}", headers=sign_in(tenant.user).headers
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert set(body["payment"]) == PAYMENT_FIELDS
    assert body["daysOverdue"] == 0
    (change,) = body["statusChanges"]
    assert set(change) == CHANGE_FIELDS
    assert change["status"] == "unpaid"
    assert change["method"] is None
    assert change["reason"] is None
    assert change["manual"] is False
    assert change["actorName"] is None
    assert parse_time(change["changedAt"]).tzinfo is not None


def test_management_sees_the_new_bill(client, database, today_is, site, add_lease):
    tenant = add_lease()
    generate(database)
    bill = only_bill(database, tenant.lease)
    for who in ("owner_in", "manager_in"):
        response = client.get(RENT_BILLS, headers=getattr(site, who).headers)
        assert [i["id"] for i in response.json()["items"]] == [str(bill.id)]


def test_a_new_bill_can_receive_a_receipt_when_the_property_has_a_bank_account(
    client, database, today_is, site, add_lease, sign_in
):
    from app.models import Property

    with Session(database) as db:
        row = db.get(Property, site.prop.id)
        row.bank_name = "Bank Mandiri"
        row.bank_account_number = "1234567890"
        row.bank_account_holder_name = "Rina Owner"
        db.commit()
    tenant = add_lease()
    generate(database)
    (item,) = client.get(RENT_BILLS, headers=sign_in(tenant.user).headers).json()[
        "items"
    ]
    assert item["canUploadReceipt"] is True


# Scope: which leases are looked at


def test_a_lease_in_a_view_only_property_is_billed(
    database, today_is, site, make_property, make_room, make_verified_tenant
):
    prop = make_property(site.owner, name="Kos Lama", view_only=True)
    tenant = make_verified_tenant(
        make_room(prop, number="V1"), start_date=date(2026, 1, 10)
    )
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_lease_in_a_view_only_room_is_billed(
    database, today_is, site, make_room, make_verified_tenant
):
    room = make_room(site.prop, number="V2", view_only=True)
    tenant = make_verified_tenant(room, start_date=date(2026, 1, 10))
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_tenant_who_has_not_activated_the_account_is_billed(
    database, today_is, site, make_room, make_tenant
):
    tenant = make_tenant(
        make_room(site.prop, number="N1"), start_date=date(2026, 1, 10)
    )
    assert tenant.tenant.activated_at is None
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


@pytest.mark.parametrize("state", ["free", "active", "expired"])
def test_bills_are_created_whatever_the_subscription_of_the_owner(
    database, today_is, site, add_lease, subscribe_owner, expire_subscription, state
):
    if state != "free":
        subscribe_owner(site.owner)
    if state == "expired":
        expire_subscription(site.owner)
    tenant = add_lease()
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


def test_every_lease_of_the_run_is_billed_for_its_own_cycle(
    database, today_is, add_lease
):
    monthly = add_lease(billing_cycle="monthly", start_date=date(2026, 1, 10))
    weekly = add_lease(billing_cycle="weekly", start_date=date(2026, 3, 2))
    quarterly = add_lease(billing_cycle="quarterly", start_date=date(2026, 1, 15))
    annual = add_lease(billing_cycle="annual", start_date=date(2025, 6, 1))
    assert generate(database) == 4
    assert periods(database, monthly.lease) == [(date(2026, 3, 10), date(2026, 4, 9))]
    assert periods(database, weekly.lease) == [(date(2026, 3, 9), date(2026, 3, 15))]
    assert periods(database, quarterly.lease) == [
        (date(2026, 1, 15), date(2026, 4, 14))
    ]
    assert periods(database, annual.lease) == [(date(2025, 6, 1), date(2026, 5, 31))]


def test_leases_of_several_owners_and_properties_are_billed_in_one_run(
    database,
    today_is,
    site,
    add_lease,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    first = add_lease()
    other_owner = make_user(name="Other Owner")
    second_prop = make_property(site.owner, name="Kos Kedua")
    other_prop = make_property(other_owner, name="Kos Mawar")
    second = make_verified_tenant(
        make_room(second_prop, number="B1"), start_date=date(2026, 1, 10)
    )
    third = make_verified_tenant(
        make_room(other_prop, number="C1"), start_date=date(2026, 1, 10)
    )
    assert generate(database) == 3
    for tenant in (first, second, third):
        assert len(stored_bills(database, tenant.lease)) == 1


def test_a_tenant_with_leases_in_two_places_gets_a_bill_for_each(
    client,
    database,
    today_is,
    site,
    add_lease,
    make_room,
    make_verified_tenant,
    sign_in,
):
    first = add_lease(rent=1000000)
    second = make_verified_tenant(
        make_room(site.prop, number="Z9"),
        user=first.user,
        start_date=date(2026, 2, 20),
        rent=2000000,
    )
    assert generate(database) == 2
    assert only_bill(database, first.lease).amount == 1000000
    assert only_bill(database, second.lease).amount == 2000000
    assert only_bill(database, second.lease).period_start == date(2026, 2, 20)
    response = client.get(RENT_BILLS, headers=sign_in(first.user).headers)
    assert len(response.json()["items"]) == 2


def test_a_run_without_leases_creates_nothing(database, today_is, site):
    assert generate(database) == 0
    assert stored_bills(database) == []


def test_a_lease_saved_today_gets_its_first_bill_at_the_next_run(
    client, database, today_is, site, make_room
):
    room = make_room(site.prop, number="N9")
    body = {
        "name": "Budi Santoso",
        "phone": "081234567890",
        "roomId": str(room.id),
        "lease": {
            "startDate": TODAY.isoformat(),
            "billingCycle": "monthly",
            "rent": 1200000,
            "gracePeriodDays": 0,
        },
    }
    response = client.post(
        f"/properties/{site.prop.id}/tenants", json=body, headers=site.owner_in.headers
    )
    assert response.status_code == 201, response.text
    assert stored_bills(database) == []
    assert generate(database) == 1
    (bill,) = stored_bills(database)
    assert bill.period_start == TODAY
    assert bill.amount == 1200000


# Repeat runs


def test_a_second_run_creates_nothing(database, today_is, add_lease):
    tenant = add_lease()
    assert generate(database) == 1
    assert generate(database) == 0
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_second_run_leaves_the_first_bill_unchanged(database, today_is, add_lease):
    tenant = add_lease(rent=1100000, grace_period_days=2)
    generate(database)
    before = only_bill(database, tenant.lease)
    changes_before = [c.id for c in stored_changes(database, before)]
    generate(database)
    after = only_bill(database, tenant.lease)
    assert after.id == before.id
    assert after.created_at == before.created_at
    assert (after.period_start, after.period_end, after.due_date, after.amount) == (
        before.period_start,
        before.period_end,
        before.due_date,
        before.amount,
    )
    assert after.payment_status == before.payment_status
    assert [c.id for c in stored_changes(database, after)] == changes_before


def test_many_runs_in_one_period_create_one_bill(database, today_is, add_lease):
    tenant = add_lease()
    for day in (15, 16, 20, 31):
        today_is(date(2026, 3, day))
        generate(database)
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_run_after_the_bill_was_paid_creates_nothing(
    database, today_is, add_lease, make_rent_bill
):
    tenant = add_lease()
    generate(database)
    bill = only_bill(database, tenant.lease)
    with Session(database) as db:
        from app.models import RentBill

        row = db.get(RentBill, bill.id)
        row.payment_status = "paid"
        row.payment_method = "cash"
        row.paid_on = TODAY
        db.commit()
    assert generate(database) == 0
    (after,) = stored_bills(database, tenant.lease)
    assert after.payment_status == "paid"


def test_runs_over_several_periods_never_repeat_a_period(database, today_is, add_lease):
    tenant = add_lease(billing_cycle="weekly", start_date=date(2026, 3, 1))
    created = 0
    day = date(2026, 3, 1)
    while day <= date(2026, 4, 5):
        today_is(day)
        created += generate(database)
        created += generate(database)
        day += timedelta(days=1)
    starts = [start for start, _ in periods(database, tenant.lease)]
    assert created == len(starts) == 6
    assert len(starts) == len(set(starts))


# Return value and transaction


def test_the_result_counts_only_the_bills_created(database, today_is, add_lease):
    add_lease()
    add_lease()
    add_lease(lease_ended=True)
    assert generate(database) == 2
    add_lease()
    assert generate(database) == 1
    assert generate(database) == 0


def test_the_generator_flushes_but_does_not_commit(database, today_is, add_lease):
    from app.services import rent_bills

    tenant = add_lease()
    with Session(database) as db:
        assert rent_bills.generate_rent_bills(db) == 1
        assert db.execute(text("SELECT count(*) FROM rent_bills")).scalar_one() == 1
        assert (
            db.execute(
                text("SELECT count(*) FROM rent_bill_status_changes")
            ).scalar_one()
            == 1
        )
        assert stored_bills(database) == []
        db.rollback()
    assert stored_bills(database) == []
    assert generate(database) == 1
    assert len(stored_bills(database, tenant.lease)) == 1


# The daily job

JOBS_URL = "/internal/jobs/daily"
JOBS_SECRET = "jobs-secret-0123456789abcdef"


@pytest.fixture
def jobs_secret(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("JOBS_SECRET", JOBS_SECRET)
    get_settings.cache_clear()
    yield JOBS_SECRET
    get_settings.cache_clear()


def real_today() -> date:
    from app.services.rent_bills import today_jakarta

    return today_jakarta()


def job_names() -> list[str]:
    from app.services.jobs import DAILY_JOBS

    return [job.__name__ for job in DAILY_JOBS]


def test_the_daily_jobs_include_the_bill_generator():
    from app.services import rent_bills
    from app.services.jobs import DAILY_JOBS

    assert rent_bills.generate_rent_bills in DAILY_JOBS
    assert job_names().count("generate_rent_bills") == 1


def test_the_bill_generator_runs_before_the_reminders_and_the_overdue_notices():
    names = job_names()
    generator = names.index("generate_rent_bills")
    assert generator < names.index("send_due_date_reminders")
    assert generator < names.index("send_overdue_notices")


def test_the_daily_jobs_still_have_distinct_names():
    names = job_names()
    assert len(names) == len(set(names))


def test_running_the_daily_jobs_creates_and_commits_the_bills(
    client, database, site, add_lease, sign_in
):
    from app.services.jobs import run_daily_jobs

    due = add_lease(billing_cycle="weekly", start_date=real_today(), rent=900000)
    waiting = add_lease(start_date=None)
    assert run_daily_jobs() == []
    (bill,) = stored_bills(database, due.lease)
    assert bill.amount == 900000
    assert bill.period_start == real_today()
    assert stored_bills(database, waiting.lease) == []
    response = client.get(RENT_BILLS, headers=sign_in(due.user).headers)
    assert [i["id"] for i in response.json()["items"]] == [str(bill.id)]


def test_running_the_daily_jobs_twice_creates_each_bill_once(database, site, add_lease):
    from app.services.jobs import run_daily_jobs

    tenant = add_lease(billing_cycle="weekly", start_date=real_today())
    assert run_daily_jobs() == []
    assert run_daily_jobs() == []
    assert len(stored_bills(database, tenant.lease)) == 1


def test_a_bill_issued_three_days_before_its_due_date_is_reminded_in_the_same_run(
    client, database, site, add_lease, sign_in
):
    from app.services.jobs import run_daily_jobs

    tenant = add_lease(
        billing_cycle="weekly", start_date=real_today(), grace_period_days=3
    )
    assert run_daily_jobs() == []
    signed_in = sign_in(tenant.user)
    assert len(of_type(client, signed_in, "billIssued")) == 1
    assert len(of_type(client, signed_in, "dueDateReminder")) == 1


def test_the_endpoint_creates_the_bills(
    client, database, jobs_secret, site, add_lease, sign_in
):
    tenant = add_lease(billing_cycle="weekly", start_date=real_today())
    response = client.post(JOBS_URL, headers={"Authorization": f"Bearer {jobs_secret}"})
    assert response.status_code == 204
    (bill,) = stored_bills(database, tenant.lease)
    assert bill.period_start == real_today()
    listed = client.get(RENT_BILLS, headers=sign_in(tenant.user).headers)
    assert [i["id"] for i in listed.json()["items"]] == [str(bill.id)]


def test_calling_the_endpoint_twice_creates_each_bill_once(
    client, database, jobs_secret, site, add_lease
):
    tenant = add_lease(billing_cycle="weekly", start_date=real_today())
    headers = {"Authorization": f"Bearer {jobs_secret}"}
    assert client.post(JOBS_URL, headers=headers).status_code == 204
    assert client.post(JOBS_URL, headers=headers).status_code == 204
    assert len(stored_bills(database, tenant.lease)) == 1


def failing_generator():
    """The real generator, whose run fails after it has created its bills."""
    from app.services import rent_bills

    def generate_rent_bills(db):
        rent_bills.generate_rent_bills(db)
        raise RuntimeError("boom")

    return generate_rent_bills


def test_a_failing_generator_does_not_stop_the_other_jobs(
    database, site, add_lease, make_rent_bill
):
    from app.services.jobs import DAILY_JOBS, run_daily_jobs

    today = real_today()
    new = add_lease(billing_cycle="weekly", start_date=today)
    old = add_lease(start_date=None)
    make_rent_bill(
        old.lease,
        period_start=today - timedelta(days=30),
        period_end=today - timedelta(days=1),
        due_date=today + timedelta(days=2),
        created_at=at_noon_jakarta(today - timedelta(days=10)),
    )
    make_rent_bill(
        old.lease,
        period_start=today - timedelta(days=100),
        period_end=today - timedelta(days=71),
        due_date=today - timedelta(days=3),
        created_at=at_noon_jakarta(today - timedelta(days=110)),
    )
    jobs = [
        failing_generator() if job.__name__ == "generate_rent_bills" else job
        for job in DAILY_JOBS
    ]
    assert run_daily_jobs(jobs) == ["generate_rent_bills"]
    assert stored_bills(database, new.lease) == []
    types = [str(row["type"]) for row in stored_rows(database)]
    assert types.count("dueDateReminder") == 1
    assert types.count("billOverdue") == 3
    assert "billIssued" not in types


def test_a_failing_generator_makes_the_endpoint_answer_500_after_the_other_jobs(
    client, database, monkeypatch, jobs_secret, site, add_lease
):
    from app.services.jobs import DAILY_JOBS

    ran: list[str] = []

    def spy(db):
        ran.append("ran")

    monkeypatch.setattr(
        "app.services.jobs.DAILY_JOBS",
        [
            failing_generator() if job.__name__ == "generate_rent_bills" else job
            for job in DAILY_JOBS
        ]
        + [spy],
    )
    add_lease(billing_cycle="weekly", start_date=real_today())
    response = client.post(JOBS_URL, headers={"Authorization": f"Bearer {jobs_secret}"})
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert ran == ["ran"]
    assert stored_bills(database) == []
