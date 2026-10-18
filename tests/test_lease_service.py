"""The next bill date of a lease."""

from datetime import date

import pytest

from app.schemas.tenants import BillingCycle


def next_bill_date(start, end, cycle, today):
    from app.services.leases import next_bill_date as function

    return function(start, end, cycle, today)


# (start, cycle, today, expected) with no end date
CASES = [
    # weekly steps of 7 days
    (date(2026, 1, 1), BillingCycle.WEEKLY, date(2026, 1, 2), date(2026, 1, 8)),
    (date(2026, 1, 1), BillingCycle.WEEKLY, date(2026, 1, 8), date(2026, 1, 15)),
    (date(2026, 1, 1), BillingCycle.WEEKLY, date(2026, 1, 7), date(2026, 1, 8)),
    (date(2026, 1, 1), BillingCycle.WEEKLY, date(2026, 3, 1), date(2026, 3, 5)),
    (date(2026, 12, 28), BillingCycle.WEEKLY, date(2026, 12, 29), date(2027, 1, 4)),
    # monthly
    (date(2026, 1, 10), BillingCycle.MONTHLY, date(2026, 1, 20), date(2026, 2, 10)),
    (date(2026, 1, 10), BillingCycle.MONTHLY, date(2026, 2, 10), date(2026, 3, 10)),
    (date(2026, 1, 10), BillingCycle.MONTHLY, date(2026, 2, 9), date(2026, 2, 10)),
    (date(2026, 1, 10), BillingCycle.MONTHLY, date(2026, 12, 10), date(2027, 1, 10)),
    (date(2026, 1, 10), BillingCycle.MONTHLY, date(2028, 5, 11), date(2028, 6, 10)),
    # quarterly
    (date(2026, 1, 10), BillingCycle.QUARTERLY, date(2026, 1, 11), date(2026, 4, 10)),
    (date(2026, 1, 10), BillingCycle.QUARTERLY, date(2026, 4, 10), date(2026, 7, 10)),
    (date(2026, 1, 10), BillingCycle.QUARTERLY, date(2026, 4, 9), date(2026, 4, 10)),
    (date(2026, 11, 15), BillingCycle.QUARTERLY, date(2026, 11, 16), date(2027, 2, 15)),
    # semiannual
    (date(2026, 1, 10), BillingCycle.SEMIANNUAL, date(2026, 1, 11), date(2026, 7, 10)),
    (date(2026, 1, 10), BillingCycle.SEMIANNUAL, date(2026, 7, 10), date(2027, 1, 10)),
    (date(2026, 8, 20), BillingCycle.SEMIANNUAL, date(2026, 9, 1), date(2027, 2, 20)),
    # annual
    (date(2026, 1, 10), BillingCycle.ANNUAL, date(2026, 6, 1), date(2027, 1, 10)),
    (date(2026, 1, 10), BillingCycle.ANNUAL, date(2027, 1, 10), date(2028, 1, 10)),
    (date(2026, 1, 10), BillingCycle.ANNUAL, date(2027, 1, 9), date(2027, 1, 10)),
    (date(2026, 1, 10), BillingCycle.ANNUAL, date(2030, 2, 1), date(2031, 1, 10)),
    # a start date in the future is the first bill date
    (date(2030, 5, 5), BillingCycle.WEEKLY, date(2026, 1, 1), date(2030, 5, 5)),
    (date(2030, 5, 5), BillingCycle.MONTHLY, date(2026, 1, 1), date(2030, 5, 5)),
    (date(2030, 5, 5), BillingCycle.QUARTERLY, date(2026, 1, 1), date(2030, 5, 5)),
    (date(2030, 5, 5), BillingCycle.SEMIANNUAL, date(2026, 1, 1), date(2030, 5, 5)),
    (date(2030, 5, 5), BillingCycle.ANNUAL, date(2026, 1, 1), date(2030, 5, 5)),
    (date(2030, 5, 5), BillingCycle.MONTHLY, date(2030, 5, 4), date(2030, 5, 5)),
    # today equal to the start date gives one cycle later
    (date(2026, 3, 1), BillingCycle.WEEKLY, date(2026, 3, 1), date(2026, 3, 8)),
    (date(2026, 3, 1), BillingCycle.MONTHLY, date(2026, 3, 1), date(2026, 4, 1)),
    (date(2026, 3, 1), BillingCycle.QUARTERLY, date(2026, 3, 1), date(2026, 6, 1)),
    (date(2026, 3, 1), BillingCycle.SEMIANNUAL, date(2026, 3, 1), date(2026, 9, 1)),
    (date(2026, 3, 1), BillingCycle.ANNUAL, date(2026, 3, 1), date(2027, 3, 1)),
]


@pytest.mark.parametrize(("start", "cycle", "today", "expected"), CASES)
def test_the_next_bill_date_is_the_first_period_start_after_today(
    start, cycle, today, expected
):
    assert next_bill_date(start, None, cycle, today) == expected


# Month-end clamping: periods are counted from the start date


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 1, 31), date(2026, 2, 28)),
        (date(2026, 2, 28), date(2026, 3, 31)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 4, 30), date(2026, 5, 31)),
        (date(2026, 5, 31), date(2026, 6, 30)),
        (date(2026, 11, 30), date(2026, 12, 31)),
        (date(2026, 12, 31), date(2027, 1, 31)),
    ],
)
def test_a_monthly_lease_from_the_31st_keeps_the_day_and_clamps_short_months(
    today, expected
):
    assert next_bill_date(date(2026, 1, 31), None, BillingCycle.MONTHLY, today) == (
        expected
    )


def test_clamping_does_not_drift_after_a_short_month():
    result = next_bill_date(
        date(2026, 1, 31), None, BillingCycle.MONTHLY, date(2026, 3, 1)
    )
    assert result == date(2026, 3, 31)


def test_a_monthly_lease_from_the_31st_between_two_clamped_dates():
    result = next_bill_date(
        date(2026, 1, 31), None, BillingCycle.MONTHLY, date(2026, 2, 1)
    )
    assert result == date(2026, 2, 28)


def test_a_leap_year_february_has_a_29th():
    result = next_bill_date(
        date(2028, 1, 31), None, BillingCycle.MONTHLY, date(2028, 1, 31)
    )
    assert result == date(2028, 2, 29)


def test_a_leap_day_after_a_leap_february_goes_back_to_the_31st():
    result = next_bill_date(
        date(2028, 1, 31), None, BillingCycle.MONTHLY, date(2028, 2, 29)
    )
    assert result == date(2028, 3, 31)


def test_a_non_leap_february_clamps_to_the_28th():
    result = next_bill_date(
        date(2027, 1, 31), None, BillingCycle.MONTHLY, date(2027, 1, 31)
    )
    assert result == date(2027, 2, 28)


@pytest.mark.parametrize(
    ("start", "today", "expected"),
    [
        (date(2026, 1, 30), date(2026, 1, 30), date(2026, 2, 28)),
        (date(2026, 1, 29), date(2026, 1, 29), date(2026, 2, 28)),
        (date(2028, 1, 30), date(2028, 1, 30), date(2028, 2, 29)),
        (date(2028, 1, 29), date(2028, 1, 29), date(2028, 2, 29)),
    ],
)
def test_a_start_on_the_29th_to_31st_clamps_to_february_length(start, today, expected):
    assert next_bill_date(start, None, BillingCycle.MONTHLY, today) == expected


def test_a_leap_day_start_clamps_every_non_leap_year_for_an_annual_lease():
    start = date(2028, 2, 29)
    assert next_bill_date(start, None, BillingCycle.ANNUAL, start) == date(2029, 2, 28)
    assert next_bill_date(start, None, BillingCycle.ANNUAL, date(2029, 2, 28)) == date(
        2030, 2, 28
    )
    assert next_bill_date(start, None, BillingCycle.ANNUAL, date(2031, 12, 1)) == date(
        2032, 2, 29
    )


@pytest.mark.parametrize(
    ("start", "cycle", "expected"),
    [
        (date(2026, 1, 30), BillingCycle.QUARTERLY, date(2026, 4, 30)),
        (date(2026, 8, 31), BillingCycle.QUARTERLY, date(2026, 11, 30)),
        (date(2026, 1, 31), BillingCycle.SEMIANNUAL, date(2026, 7, 31)),
        (date(2026, 8, 31), BillingCycle.SEMIANNUAL, date(2027, 2, 28)),
        (date(2027, 8, 31), BillingCycle.ANNUAL, date(2028, 8, 31)),
        (date(2027, 1, 31), BillingCycle.ANNUAL, date(2028, 1, 31)),
    ],
)
def test_longer_cycles_clamp_to_the_length_of_the_target_month(start, cycle, expected):
    assert next_bill_date(start, None, cycle, start) == expected


def test_a_quarterly_lease_from_november_30_steps_into_february():
    result = next_bill_date(
        date(2026, 11, 30), None, BillingCycle.QUARTERLY, date(2026, 11, 30)
    )
    assert result == date(2027, 2, 28)


# Year boundaries


def test_the_next_bill_date_may_fall_in_the_following_year():
    result = next_bill_date(
        date(2026, 12, 15), None, BillingCycle.MONTHLY, date(2026, 12, 15)
    )
    assert result == date(2027, 1, 15)


def test_many_periods_after_the_start_are_counted_from_the_start_date():
    result = next_bill_date(
        date(2020, 1, 31), None, BillingCycle.MONTHLY, date(2026, 6, 15)
    )
    assert result == date(2026, 6, 30)


def test_a_weekly_lease_stays_on_its_weekday():
    result = next_bill_date(
        date(2020, 2, 29), None, BillingCycle.WEEKLY, date(2026, 10, 18)
    )
    assert result.weekday() == date(2020, 2, 29).weekday()
    assert date(2026, 10, 18) < result <= date(2026, 10, 25)


# No start date and the end date


def test_there_is_no_next_bill_date_without_a_start_date():
    assert next_bill_date(None, None, BillingCycle.MONTHLY, date(2026, 1, 1)) is None


@pytest.mark.parametrize("cycle", list(BillingCycle))
def test_there_is_no_next_bill_date_without_a_start_date_for_any_cycle(cycle):
    assert next_bill_date(None, date(2030, 1, 1), cycle, date(2026, 1, 1)) is None


def test_a_result_equal_to_the_end_date_is_still_returned():
    result = next_bill_date(
        date(2026, 1, 10), date(2026, 2, 10), BillingCycle.MONTHLY, date(2026, 1, 20)
    )
    assert result == date(2026, 2, 10)


def test_a_result_one_day_after_the_end_date_is_empty():
    result = next_bill_date(
        date(2026, 1, 10), date(2026, 2, 9), BillingCycle.MONTHLY, date(2026, 1, 20)
    )
    assert result is None


def test_today_far_after_the_end_date_gives_no_next_bill_date():
    result = next_bill_date(
        date(2024, 1, 10), date(2025, 1, 9), BillingCycle.MONTHLY, date(2026, 6, 1)
    )
    assert result is None


def test_a_future_start_after_the_end_date_gives_no_next_bill_date():
    result = next_bill_date(
        date(2030, 5, 5), date(2030, 5, 4), BillingCycle.MONTHLY, date(2026, 1, 1)
    )
    assert result is None


def test_a_future_start_equal_to_the_end_date_is_returned():
    result = next_bill_date(
        date(2030, 5, 5), date(2030, 5, 5), BillingCycle.MONTHLY, date(2026, 1, 1)
    )
    assert result == date(2030, 5, 5)


def test_a_weekly_result_equal_to_the_end_date_is_returned():
    result = next_bill_date(
        date(2026, 1, 1), date(2026, 1, 8), BillingCycle.WEEKLY, date(2026, 1, 3)
    )
    assert result == date(2026, 1, 8)


def test_a_weekly_result_one_day_after_the_end_date_is_empty():
    result = next_bill_date(
        date(2026, 1, 1), date(2026, 1, 7), BillingCycle.WEEKLY, date(2026, 1, 3)
    )
    assert result is None


def test_an_annual_result_one_day_after_the_end_date_is_empty():
    result = next_bill_date(
        date(2026, 1, 10), date(2027, 1, 9), BillingCycle.ANNUAL, date(2026, 6, 1)
    )
    assert result is None


def test_an_end_date_after_the_result_does_not_change_it():
    result = next_bill_date(
        date(2026, 1, 10), date(2030, 1, 1), BillingCycle.MONTHLY, date(2026, 1, 20)
    )
    assert result == date(2026, 2, 10)
