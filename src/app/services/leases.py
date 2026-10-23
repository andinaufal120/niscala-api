"""Bill dates of a lease."""

import calendar
from datetime import date, timedelta

from app.schemas.tenants import BillingCycle

CYCLE_MONTHS = {
    BillingCycle.MONTHLY: 1,
    BillingCycle.QUARTERLY: 3,
    BillingCycle.SEMIANNUAL: 6,
    BillingCycle.ANNUAL: 12,
}


def _add_months(start: date, months: int) -> date:
    """Move `start` forward by whole months, clamping the day to the month length."""
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def period_start(start_date: date, cycle: BillingCycle, period: int) -> date:
    """Return the start of the zero-based `period` counted from `start_date`."""
    if cycle == BillingCycle.WEEKLY:
        return start_date + timedelta(weeks=period)
    return _add_months(start_date, CYCLE_MONTHS[cycle] * period)


def next_bill_date(
    start_date: date | None,
    end_date: date | None,
    billing_cycle: BillingCycle,
    today: date,
) -> date | None:
    """Return the first period start after `today`, counted from `start_date`.

    Periods are whole weeks or months from the start date, so the day of month
    is kept and clamped to short months. Returns None without a start date or
    when the result falls after the end date.
    """
    if start_date is None:
        return None
    period = 0
    while (result := period_start(start_date, billing_cycle, period)) <= today:
        period += 1
    if end_date is not None and result > end_date:
        return None
    return result
