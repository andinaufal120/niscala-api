"""Payment pattern facts computed from the bills of one lease."""

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import count

import pytest

TODAY = date(2026, 10, 23)
_serial = count(1)


@dataclass
class Bill:
    period_start: date
    due_date: date
    amount: int
    payment_status: str
    paid_on: date | None


def facts_of(bills, today: date = TODAY):
    from app.services.payment_patterns import compute_payment_facts

    return compute_payment_facts(bills, today)


def bill(
    due_ago: int,
    status: str = "unpaid",
    *,
    late: int | None = None,
    amount: int = 1000,
    period_start: date | None = None,
) -> Bill:
    """A bill due `due_ago` days before today (negative: in the future).

    A paid bill was paid `late` days after its due date (negative: before it).
    """
    due = TODAY - timedelta(days=due_ago)
    paid_on = None
    if status == "paid":
        paid_on = due + timedelta(days=late or 0)
    return Bill(
        period_start=period_start or due - timedelta(days=25 + next(_serial) % 3),
        due_date=due,
        amount=amount,
        payment_status=status,
        paid_on=paid_on,
    )


def paid(due_ago: int, late: int = 0, **options) -> Bill:
    return bill(due_ago, "paid", late=late, **options)


def paid_series(count_: int, *, first_due_ago: int = 10, late: int = 0) -> list[Bill]:
    """Paid bills due 30 days apart, the latest `first_due_ago` days ago."""
    return [paid(first_due_ago + 30 * i, late) for i in range(count_)]


# Empty and uncounted history


def test_no_bills_gives_all_zero_facts():
    facts = facts_of([])
    assert facts.on_time_count == 0
    assert facts.counted_bill_count == 0
    assert facts.average_days_late == 0
    assert facts.arrears == 0
    assert facts.at_risk is False


def test_the_facts_use_plain_integers_and_a_boolean():
    facts = facts_of([paid(40, 2), paid(10)])
    assert type(facts.on_time_count) is int
    assert type(facts.counted_bill_count) is int
    assert type(facts.average_days_late) is int
    assert type(facts.arrears) is int
    assert type(facts.at_risk) is bool


def test_a_tuple_of_bills_is_accepted():
    assert facts_of(tuple(paid_series(2))).counted_bill_count == 2


def test_an_unpaid_bill_not_yet_due_is_not_counted():
    facts = facts_of([bill(-5)])
    assert facts.counted_bill_count == 0
    assert facts.on_time_count == 0
    assert facts.arrears == 0
    assert facts.at_risk is False


def test_an_unpaid_bill_due_today_is_not_overdue():
    facts = facts_of([bill(0)])
    assert facts.counted_bill_count == 0
    assert facts.arrears == 0
    assert facts.at_risk is False


def test_an_unpaid_bill_due_yesterday_is_overdue_by_one_day():
    facts = facts_of([bill(1, amount=700)])
    assert facts.counted_bill_count == 1
    assert facts.on_time_count == 0
    assert facts.average_days_late == 1
    assert facts.arrears == 700


def test_a_rejected_bill_not_yet_due_is_not_counted():
    facts = facts_of([bill(-3, "rejected")])
    assert facts.counted_bill_count == 0
    assert facts.arrears == 0


def test_a_rejected_bill_due_today_is_not_overdue():
    facts = facts_of([bill(0, "rejected")])
    assert facts.counted_bill_count == 0
    assert facts.arrears == 0


def test_a_paid_bill_is_counted_even_when_its_due_date_is_in_the_future():
    facts = facts_of([paid(-5, late=-6)])
    assert facts.counted_bill_count == 1
    assert facts.on_time_count == 1


def test_uncounted_bills_do_not_change_the_counted_ones():
    bills = [paid(40), paid(10, 3), bill(-20), bill(-50, "rejected")]
    facts = facts_of(bills)
    assert facts.counted_bill_count == 2
    assert facts.on_time_count == 1
    assert facts.average_days_late == 3


# On time and late


def test_a_bill_paid_on_its_due_date_is_on_time():
    facts = facts_of([paid(10, late=0)])
    assert facts.counted_bill_count == 1
    assert facts.on_time_count == 1
    assert facts.average_days_late == 0


def test_a_bill_paid_before_its_due_date_is_on_time():
    facts = facts_of([paid(10, late=-4)])
    assert facts.on_time_count == 1
    assert facts.average_days_late == 0


def test_a_bill_paid_one_day_after_its_due_date_is_late():
    facts = facts_of([paid(10, late=1)])
    assert facts.counted_bill_count == 1
    assert facts.on_time_count == 0
    assert facts.average_days_late == 1


def test_days_late_of_a_paid_bill_come_from_its_payment_date():
    facts = facts_of([paid(60, late=9)])
    assert facts.average_days_late == 9


def test_days_late_of_an_overdue_bill_come_from_today():
    facts = facts_of([bill(12)])
    assert facts.average_days_late == 12


def test_on_time_count_is_counted_minus_late():
    facts = facts_of([paid(90), paid(60, 2), paid(30), bill(5)])
    assert facts.counted_bill_count == 4
    assert facts.on_time_count == 2


def test_the_average_covers_only_late_bills():
    facts = facts_of([paid(120), paid(90), paid(60), paid(30, 4)])
    assert facts.counted_bill_count == 4
    assert facts.average_days_late == 4


def test_the_average_mixes_late_paid_and_overdue_bills():
    facts = facts_of([paid(60, 3), bill(5)])
    assert facts.average_days_late == 4


def test_a_rejected_overdue_bill_counts_as_late():
    facts = facts_of([bill(4, "rejected", amount=900)])
    assert facts.counted_bill_count == 1
    assert facts.on_time_count == 0
    assert facts.average_days_late == 4
    assert facts.arrears == 900


def test_the_input_order_does_not_matter():
    bills = [paid(100, 2), paid(70), paid(40, 6), bill(8)]
    forward = facts_of(bills)
    backward = facts_of(list(reversed(bills)))
    for name in (
        "on_time_count",
        "counted_bill_count",
        "average_days_late",
        "arrears",
        "at_risk",
    ):
        assert getattr(forward, name) == getattr(backward, name), name
    assert forward.average_days_late == 5
    assert forward.on_time_count == 1


# Rounding of the average


@pytest.mark.parametrize(
    ("lates", "expected"),
    [
        ([2, 3], 3),
        ([1, 2], 2),
        ([4, 5], 5),
        ([1, 1, 2], 1),
        ([1, 1, 1, 2], 1),
        ([2, 2, 3], 2),
        ([2, 3, 3], 3),
        ([1, 1, 1, 1, 1, 2], 1),
        ([1, 2, 2, 2, 2, 2], 2),
        ([3], 3),
        ([10, 20], 15),
    ],
)
def test_the_average_days_late_is_rounded_half_up(lates, expected):
    bills = [paid(10 + 30 * i, late) for i, late in enumerate(lates)]
    assert facts_of(bills).average_days_late == expected


def test_an_exact_half_rounds_up_and_not_to_even():
    assert facts_of([paid(40, 2), paid(10, 3)]).average_days_late == 3
    assert facts_of([paid(40, 1), paid(10, 2)]).average_days_late == 2
    assert facts_of([paid(40, 3), paid(10, 4)]).average_days_late == 4


def test_the_average_is_zero_when_nothing_is_late():
    assert facts_of(paid_series(4)).average_days_late == 0


# The latest six bills


def test_exactly_six_counted_bills_are_all_counted():
    bills = paid_series(5) + [paid(400, late=5)]
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 5
    assert facts.average_days_late == 5


def test_a_seventh_counted_bill_drops_the_oldest_one():
    bills = paid_series(6) + [paid(400, late=5)]
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.average_days_late == 0
    assert facts.at_risk is False


def test_many_more_bills_than_six_still_count_six():
    facts = facts_of(paid_series(15))
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.at_risk is False


def test_the_latest_six_are_chosen_by_due_date_not_by_input_order():
    old_late = [paid(300 + 30 * i, late=9) for i in range(4)]
    recent = paid_series(6)
    facts = facts_of(old_late + recent)
    assert facts.on_time_count == 6
    assert facts.average_days_late == 0
    facts = facts_of(recent + old_late)
    assert facts.on_time_count == 6
    assert facts.average_days_late == 0


def test_late_bills_among_the_latest_six_are_counted():
    bills = paid_series(8)
    bills[2] = paid(10 + 30 * 2, late=6)
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 5
    assert facts.average_days_late == 6


def test_bills_that_are_not_counted_do_not_take_a_place_among_the_six():
    bills = paid_series(6, first_due_ago=40)
    bills += [bill(-5), bill(-35), bill(-65, "rejected")]
    bills += [bill(20, "awaitingVerification")]
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6


def test_an_overdue_bill_takes_a_place_among_the_six_by_its_due_date():
    bills = paid_series(6, first_due_ago=40)
    bills.append(bill(5))
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 5
    assert facts.average_days_late == 5


def test_bills_with_the_same_due_date_are_cut_by_the_earlier_period_start():
    newer = [paid(due_ago) for due_ago in range(1, 6)]
    kept = paid(50, late=0, period_start=TODAY - timedelta(days=90))
    dropped = paid(50, late=7, period_start=TODAY - timedelta(days=200))
    facts = facts_of(newer + [dropped, kept])
    assert facts.counted_bill_count == 6
    assert facts.average_days_late == 0
    assert facts.on_time_count == 6


# Awaiting verification


def test_a_bill_awaiting_verification_is_not_counted():
    facts = facts_of([bill(3, "awaitingVerification")])
    assert facts.counted_bill_count == 0
    assert facts.on_time_count == 0
    assert facts.average_days_late == 0


def test_a_bill_awaiting_verification_is_never_overdue():
    facts = facts_of([bill(40, "awaitingVerification", amount=5000)])
    assert facts.arrears == 0
    assert facts.at_risk is False


def test_a_bill_awaiting_verification_does_not_disturb_the_other_bills():
    facts = facts_of([paid(60), bill(20, "awaitingVerification"), paid(30, 2)])
    assert facts.counted_bill_count == 2
    assert facts.on_time_count == 1
    assert facts.average_days_late == 2
    assert facts.arrears == 0


# Arrears


def test_arrears_is_the_sum_of_the_amounts_of_the_overdue_bills():
    bills = [
        bill(5, amount=1000),
        bill(35, "rejected", amount=2500),
        paid(65, amount=4000),
    ]
    assert facts_of(bills).arrears == 3500


def test_arrears_ignore_paid_awaiting_and_not_yet_due_bills():
    bills = [
        paid(40, 3, amount=100),
        bill(10, "awaitingVerification", amount=200),
        bill(-10, amount=300),
        bill(-40, "rejected", amount=400),
        bill(0, amount=500),
    ]
    assert facts_of(bills).arrears == 0


def test_arrears_include_overdue_bills_outside_the_latest_six():
    bills = paid_series(6, first_due_ago=10)
    bills.append(bill(400, amount=7000))
    bills.append(bill(430, "rejected", amount=800))
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.arrears == 7800


def test_arrears_count_each_overdue_bill_once_inside_the_six():
    bills = [bill(8, amount=1500), bill(38, amount=1500), bill(68, amount=1500)]
    assert facts_of(bills).arrears == 4500


# Risk


def test_no_risk_without_late_bills():
    assert facts_of(paid_series(6)).at_risk is False


def test_one_late_bill_is_not_a_risk():
    bills = paid_series(5, first_due_ago=40) + [paid(10, 3)]
    assert facts_of(bills).at_risk is False


def test_two_late_bills_are_a_risk():
    bills = paid_series(4, first_due_ago=70) + [paid(40, 1), paid(10, 1)]
    assert facts_of(bills).at_risk is True


def test_two_late_bills_are_a_risk_wherever_they_are_among_the_six():
    bills = paid_series(6)
    bills[0] = paid(10, 1)
    bills[5] = paid(10 + 150, 2)
    assert facts_of(bills).at_risk is True


def test_late_bills_outside_the_latest_six_do_not_count_toward_the_risk():
    bills = paid_series(6, first_due_ago=40)
    bills += [paid(400, 5), paid(430, 5), paid(460, 5)]
    assert facts_of(bills).at_risk is False


def test_one_paid_late_and_one_overdue_bill_are_a_risk():
    assert facts_of([paid(60, 1), bill(2)]).at_risk is True


def test_two_overdue_bills_are_a_risk_even_when_just_overdue():
    assert facts_of([bill(1), bill(31)]).at_risk is True


def test_an_overdue_bill_of_seven_days_is_not_a_risk_by_itself():
    facts = facts_of([bill(7)])
    assert facts.at_risk is False
    assert facts.arrears == 1000


def test_an_overdue_bill_of_eight_days_is_a_risk_by_itself():
    facts = facts_of([bill(8)])
    assert facts.counted_bill_count == 1
    assert facts.at_risk is True


def test_a_rejected_bill_of_eight_days_is_a_risk():
    assert facts_of([bill(8, "rejected")]).at_risk is True


def test_a_rejected_bill_of_seven_days_is_not_a_risk():
    assert facts_of([bill(7, "rejected")]).at_risk is False


def test_one_late_bill_and_one_overdue_by_eight_days_are_a_risk():
    assert facts_of([paid(60), bill(8)]).at_risk is True


def test_one_late_bill_and_one_overdue_by_seven_days_are_a_risk_by_count():
    assert facts_of([paid(60, 1), bill(7)]).at_risk is True


def test_a_long_overdue_bill_outside_the_latest_six_is_a_risk():
    bills = paid_series(6, first_due_ago=10)
    bills.append(bill(300))
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.at_risk is True


def test_an_old_overdue_bill_of_seven_days_outside_the_six_is_not_a_risk():
    bills = [paid(due_ago, late=-1) for due_ago in range(6)] + [bill(7)]
    facts = facts_of(bills)
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.arrears == 1000
    assert facts.at_risk is False


def test_a_bill_paid_many_days_late_is_not_overdue():
    facts = facts_of([paid(60, 30)])
    assert facts.arrears == 0
    assert facts.at_risk is False
    assert facts.average_days_late == 30


def test_a_bill_awaiting_verification_beyond_seven_days_is_not_a_risk():
    assert facts_of([bill(30, "awaitingVerification")]).at_risk is False


def test_a_tenant_with_many_on_time_bills_is_not_at_risk():
    facts = facts_of(paid_series(12, late=0))
    assert facts.counted_bill_count == 6
    assert facts.on_time_count == 6
    assert facts.average_days_late == 0
    assert facts.arrears == 0
    assert facts.at_risk is False


def test_the_risk_follows_the_given_today():
    bills = [bill(7)]
    assert facts_of(bills, TODAY).at_risk is False
    assert facts_of(bills, TODAY + timedelta(days=1)).at_risk is True


def test_overdue_follows_the_given_today():
    bills = [bill(-2, amount=600)]
    assert facts_of(bills, TODAY).arrears == 0
    later = facts_of(bills, TODAY + timedelta(days=3))
    assert later.arrears == 600
    assert later.counted_bill_count == 1
    assert later.average_days_late == 1
