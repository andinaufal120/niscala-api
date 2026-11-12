"""Tests of the steps shared by the rent scenarios."""

from datetime import date

from e2e.e2e_rent import build_site, join, notifications_of, real_today, run_jobs_on


def test_run_jobs_on_moves_the_clock_and_dates_new_bills_to_that_day(world, database):
    world.clock.set(date(2026, 10, 23))
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 10, 23), "gracePeriodDays": 3},
    )

    run_jobs_on(world, database, date(2026, 10, 23))

    assert world.clock.today == date(2026, 10, 23)
    assert len(notifications_of(budi, "billIssued")) == 1
    assert len(notifications_of(budi, "dueDateReminder")) == 1


def test_run_jobs_on_leaves_a_bill_issued_too_late_for_a_reminder_without_one(
    world, database
):
    world.clock.set(date(2026, 10, 23))
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 10, 23), "gracePeriodDays": 2},
    )

    run_jobs_on(world, database, date(2026, 10, 23))

    assert len(notifications_of(budi, "billIssued")) == 1
    assert notifications_of(budi, "dueDateReminder") == []


def test_real_today_is_a_date_that_the_test_clock_does_not_follow(world):
    world.clock.set(date(2026, 1, 1))

    assert isinstance(real_today(), date)
    assert real_today() != world.clock.today
