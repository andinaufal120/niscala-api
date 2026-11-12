"""Scenarios of rent bill generation, reminders and overdue notices."""

from datetime import date

import pytest

from e2e.e2e_rent import (
    accept_another_tenancy,
    build_site,
    join,
    notifications_of,
    run_jobs_on,
    types_of,
)

TODAY = date(2026, 10, 23)


def periods(person) -> list[tuple[str, str]]:
    """The (period start, period end) of each bill, newest first."""
    return [(b["periodStart"], b["periodEnd"]) for b in person.rent_bills()]


def test_the_daily_job_bills_the_current_period_at_the_lease_rent(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={
            "startDate": date(2026, 10, 20),
            "gracePeriodDays": 5,
            "rent": 1_350_000,
        },
    )
    budi = world.tenant_activates(token, email="budi@example.com")

    assert owner.rent_bills() == []
    assert budi.rent_bills() == []
    assert types_of(budi) == []

    world.clock.run_daily_jobs()

    (bill,) = budi.rent_bills()
    assert bill["periodStart"] == "2026-10-20"
    assert bill["periodEnd"] == "2026-11-19"
    assert bill["dueDate"] == "2026-10-25"
    assert bill["amount"] == 1_350_000
    assert bill["payment"]["status"] == "unpaid"
    assert bill["daysOverdue"] == 0
    assert bill["isCurrent"] is True
    assert bill["canUploadReceipt"] is True
    assert bill["property"]["name"] == "Kos Melati"
    assert bill["room"]["number"] == "A1"
    detail = budi.rent_bill(bill)
    (entry,) = detail["statusChanges"]
    assert entry["status"] == "unpaid"
    assert entry["actorName"] is None
    assert entry["manual"] is False
    assert entry["reason"] is None
    assert entry["method"] is None
    assert detail["bankAccount"]["bankName"] == "Bank Mandiri"
    assert owner.rent_bills()[0]["id"] == bill["id"]

    world.clock.run_daily_jobs()
    world.clock.run_daily_jobs()

    assert budi.rent_bills() == [bill]
    assert types_of(budi) == ["billIssued"]
    issued = notifications_of(budi, "billIssued")[0]
    assert issued["rentBill"]["rentBillId"] == bill["id"]
    assert issued["rentBill"]["amount"] == 1_350_000
    assert issued["rentBill"]["paymentStatus"] == "unpaid"
    assert issued["read"] is False


def test_a_lease_saved_in_the_past_is_billed_from_its_current_period_only(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 4, 20), "gracePeriodDays": 10},
    )

    world.clock.run_daily_jobs()

    assert periods(budi) == [("2026-10-20", "2026-11-19")]
    assert types_of(budi) == ["billIssued"]


def test_each_period_gets_its_bill_when_the_clock_reaches_it(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 10, 20)},
    )
    world.clock.run_daily_jobs()

    world.clock.set(date(2026, 11, 19))
    world.clock.run_daily_jobs()
    assert len(budi.rent_bills()) == 1

    world.clock.set(date(2026, 11, 20))
    world.clock.run_daily_jobs()
    world.clock.run_daily_jobs()

    assert periods(budi) == [
        ("2026-11-20", "2026-12-19"),
        ("2026-10-20", "2026-11-19"),
    ]
    bills = budi.rent_bills()
    assert [b["isCurrent"] for b in bills] == [True, False]
    assert types_of(budi).count("billIssued") == 2


def test_a_run_that_was_missed_is_made_up_while_the_period_is_current(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 10, 20)},
    )

    world.clock.set(date(2026, 11, 5))
    world.clock.run_daily_jobs()

    assert periods(budi) == [("2026-10-20", "2026-11-19")]


def test_a_tenant_who_has_not_activated_is_billed_too(world):
    world.clock.set(TODAY)
    site = build_site(world)
    token = site.owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 20)},
    )

    world.clock.run_daily_jobs()

    (bill,) = site.owner.rent_bills()
    assert bill["tenant"]["id"] == token.id
    assert bill["payment"]["status"] == "unpaid"
    assert site.owner.tenants(site.melati)[0]["accountStatus"] == "notActivated"


def test_no_bill_for_a_lease_without_a_start_date_or_an_ended_lease(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    owner.add_tenant(site.rooms["A1"], "Undated Tenant", "081211111111")
    gone = owner.add_tenant(
        site.rooms["A2"],
        "Gone Tenant",
        "081211111112",
        lease={"startDate": date(2026, 10, 1)},
    )
    kept = owner.add_tenant(
        site.rooms["A3"],
        "Kept Tenant",
        "081211111113",
        lease={"startDate": date(2026, 10, 1)},
    )
    owner.delete(f"/tenants/{gone.id}", expect=204)

    world.clock.run_daily_jobs()

    assert [b["tenant"]["id"] for b in owner.rent_bills()] == [kept.id]


def test_no_bill_for_a_period_that_starts_after_the_lease_end_date(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 9, 1), "endDate": date(2026, 10, 15)},
    )

    world.clock.run_daily_jobs()

    (bill,) = budi.rent_bills()
    assert (bill["periodStart"], bill["periodEnd"]) == ("2026-10-01", "2026-10-31")
    assert bill["amount"] == 1_000_000
    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()
    world.clock.set(date(2026, 12, 15))
    world.clock.run_daily_jobs()
    assert len(budi.rent_bills()) == 1
    assert types_of(budi).count("billIssued") == 1


def test_a_lease_that_ended_before_today_gets_no_bill(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 6, 1), "endDate": date(2026, 8, 31)},
    )

    world.clock.run_daily_jobs()

    assert budi.rent_bills() == []
    assert types_of(budi) == []


@pytest.mark.parametrize(
    ("cycle", "start", "period"),
    [
        ("weekly", date(2026, 10, 20), ("2026-10-20", "2026-10-26")),
        ("monthly", date(2026, 10, 20), ("2026-10-20", "2026-11-19")),
        ("quarterly", date(2026, 8, 15), ("2026-08-15", "2026-11-14")),
        ("semiannual", date(2026, 5, 1), ("2026-05-01", "2026-10-31")),
        ("annual", date(2026, 3, 1), ("2026-03-01", "2027-02-28")),
    ],
)
def test_every_billing_cycle_bills_its_whole_period_at_the_full_rent(
    world, cycle, start, period
):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": start, "billingCycle": cycle, "rent": 777_000},
    )

    world.clock.run_daily_jobs()

    (bill,) = budi.rent_bills()
    assert (bill["periodStart"], bill["periodEnd"]) == period
    assert bill["amount"] == 777_000


def test_weekly_and_quarterly_leases_get_their_next_bill_when_the_next_period_begins(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    weekly = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Wati Tenant",
        lease={
            "startDate": date(2026, 10, 20),
            "billingCycle": "weekly",
            "rent": 300_000,
        },
    )
    quarterly = join(
        world,
        site.owner,
        site.rooms["A2"],
        "Quin Tenant",
        lease={
            "startDate": date(2026, 8, 15),
            "billingCycle": "quarterly",
            "rent": 2_700_000,
        },
    )
    world.clock.run_daily_jobs()

    world.clock.set(date(2026, 10, 26))
    world.clock.run_daily_jobs()
    assert len(weekly.rent_bills()) == 1

    world.clock.set(date(2026, 10, 27))
    world.clock.run_daily_jobs()
    assert periods(weekly) == [
        ("2026-10-27", "2026-11-02"),
        ("2026-10-20", "2026-10-26"),
    ]
    assert len(quarterly.rent_bills()) == 1

    world.clock.set(date(2026, 11, 15))
    world.clock.run_daily_jobs()
    assert periods(quarterly) == [
        ("2026-11-15", "2027-02-14"),
        ("2026-08-15", "2026-11-14"),
    ]
    assert [b["amount"] for b in quarterly.rent_bills()] == [2_700_000, 2_700_000]
    assert len(weekly.rent_bills()) == 3


def test_a_monthly_lease_started_on_the_last_day_keeps_that_day_in_shorter_months(
    world,
):
    world.clock.set(date(2026, 2, 28))
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": date(2026, 1, 31)},
    )
    world.clock.run_daily_jobs()

    world.clock.set(date(2026, 3, 31))
    world.clock.run_daily_jobs()

    assert periods(budi) == [
        ("2026-03-31", "2026-04-29"),
        ("2026-02-28", "2026-03-30"),
    ]


def test_the_tenant_is_reminded_three_days_before_the_due_date_and_told_when_overdue(
    world, database
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner, manager = site.owner, site.manager
    budi = join(
        world,
        owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 10},
    )
    run_jobs_on(world, database, TODAY)
    assert types_of(budi) == ["billIssued"]

    run_jobs_on(world, database, date(2026, 10, 29))
    assert types_of(budi) == ["billIssued"]

    run_jobs_on(world, database, date(2026, 10, 30))
    run_jobs_on(world, database, date(2026, 10, 30))
    reminders = notifications_of(budi, "dueDateReminder")
    assert len(reminders) == 1
    assert reminders[0]["rentBill"]["dueDate"] == "2026-11-02"
    assert reminders[0]["rentBill"]["paymentStatus"] == "unpaid"
    assert notifications_of(owner, "dueDateReminder") == []

    run_jobs_on(world, database, date(2026, 11, 2))
    assert notifications_of(budi, "billOverdue") == []
    assert notifications_of(owner, "billOverdue") == []

    run_jobs_on(world, database, date(2026, 11, 3))
    run_jobs_on(world, database, date(2026, 11, 3))
    for person in (budi, owner, manager):
        (overdue,) = notifications_of(person, "billOverdue")
        assert overdue["rentBill"]["daysOverdue"] == 1
        assert overdue["rentBill"]["dueDate"] == "2026-11-02"
    assert types_of(budi).count("dueDateReminder") == 1

    run_jobs_on(world, database, date(2026, 11, 4))
    assert len(notifications_of(budi, "billOverdue")) == 1
    assert len(notifications_of(owner, "billOverdue")) == 1


def test_days_overdue_grow_as_the_clock_moves(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 2},
    )
    world.clock.run_daily_jobs()
    bill = budi.rent_bills()[0]
    assert bill["dueDate"] == "2026-10-25"

    seen = []
    for day in (date(2026, 10, 25), date(2026, 10, 26), date(2026, 11, 4)):
        world.clock.set(day)
        seen.append(budi.rent_bill(bill)["daysOverdue"])
        assert budi.rent_bills()[0]["daysOverdue"] == seen[-1]

    assert seen == [0, 1, 10]


def test_a_bill_issued_less_than_three_days_before_its_due_date_gets_no_reminder(
    world, database
):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 2},
    )

    for day in (TODAY, date(2026, 10, 24), date(2026, 10, 25)):
        run_jobs_on(world, database, day)

    assert types_of(budi) == ["billIssued"]
    run_jobs_on(world, database, date(2026, 10, 26))
    assert types_of(budi) == ["billOverdue", "billIssued"]


def test_a_bill_issued_exactly_three_days_before_its_due_date_is_reminded_at_once(
    world, database
):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 3},
    )

    run_jobs_on(world, database, TODAY)

    assert sorted(types_of(budi)) == ["billIssued", "dueDateReminder"]


def test_a_missed_run_still_sends_the_reminder_before_the_due_date(world, database):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 10},
    )
    run_jobs_on(world, database, TODAY)

    run_jobs_on(world, database, date(2026, 11, 1))

    assert len(notifications_of(budi, "dueDateReminder")) == 1


def test_a_missed_run_still_sends_the_overdue_notice_while_the_bill_is_unpaid(
    world, database
):
    world.clock.set(TODAY)
    site = build_site(world)
    budi = join(
        world,
        site.owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 2},
    )
    run_jobs_on(world, database, TODAY)

    run_jobs_on(world, database, date(2026, 10, 30))

    assert len(notifications_of(budi, "billOverdue")) == 1
    assert len(notifications_of(site.owner, "billOverdue")) == 1


def test_no_reminder_or_overdue_notice_for_a_bill_that_is_paid_or_awaiting_verification(
    world, database
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    lease = {"startDate": TODAY, "gracePeriodDays": 5}
    paying = join(world, owner, site.rooms["A1"], "Pay Tenant", lease=lease)
    waiting = join(world, owner, site.rooms["A2"], "Wait Tenant", lease=lease)
    late = join(world, owner, site.rooms["A3"], "Late Tenant", lease=lease)
    run_jobs_on(world, database, TODAY)
    paid_bill = paying.upload_receipt(paying.rent_bills()[0])
    owner.post(f"/rent-bills/{paid_bill['id']}/verification", expect=200)
    waiting.upload_receipt(waiting.rent_bills()[0])

    for day in (date(2026, 10, 26), date(2026, 10, 29), date(2026, 11, 5)):
        run_jobs_on(world, database, day)

    assert types_of(paying) == ["paymentStatusChanged", "billIssued"]
    assert types_of(waiting) == ["billIssued"]
    assert waiting.rent_bills()[0]["daysOverdue"] == 0
    assert types_of(late) == ["billOverdue", "dueDateReminder", "billIssued"]
    assert late.rent_bills()[0]["daysOverdue"] == 8
    assert [n["tenant"]["name"] for n in notifications_of(owner, "billOverdue")] == [
        "Late Tenant"
    ]


def test_a_rejected_bill_is_reminded_and_overdue_like_an_unpaid_one(world, database):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi = join(
        world,
        owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 5},
    )
    run_jobs_on(world, database, TODAY)
    bill = budi.upload_receipt(budi.rent_bills()[0])
    owner.post(
        f"/rent-bills/{bill['id']}/rejection", json={"reason": "Blurry"}, expect=200
    )

    run_jobs_on(world, database, date(2026, 10, 25))
    run_jobs_on(world, database, date(2026, 10, 29))

    assert len(notifications_of(budi, "dueDateReminder")) == 1
    (overdue,) = notifications_of(budi, "billOverdue")
    assert overdue["rentBill"]["paymentStatus"] == "rejected"
    assert budi.rent_bills()[0]["daysOverdue"] == 1


def test_the_overdue_notice_goes_to_the_managers_of_that_property_only(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    join(world, owner, site.rooms["A1"], "Melati Tenant", lease={"startDate": TODAY})
    join(world, owner, site.rooms["B1"], "Anggrek Tenant", lease={"startDate": TODAY})
    world.clock.run_daily_jobs()

    world.clock.set(date(2026, 10, 24))
    world.clock.run_daily_jobs()

    assert len(notifications_of(owner, "billOverdue")) == 2
    names = [n["tenant"]["name"] for n in notifications_of(site.manager, "billOverdue")]
    assert names == ["Melati Tenant"]


def test_a_tenant_with_two_tenancies_gets_the_notifications_of_both(world, database):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi = join(
        world,
        owner,
        site.rooms["A1"],
        "Budi Tenant",
        lease={"startDate": TODAY, "gracePeriodDays": 5},
    )
    accept_another_tenancy(
        owner,
        site.rooms["B1"],
        budi,
        lease={"startDate": TODAY, "gracePeriodDays": 5, "rent": 800_000},
    )

    run_jobs_on(world, database, TODAY)

    bills = {b["property"]["name"]: b for b in budi.rent_bills()}
    assert sorted(bills) == ["Kos Anggrek", "Kos Melati"]
    assert bills["Kos Anggrek"]["amount"] == 800_000
    assert bills["Kos Melati"]["amount"] == 1_000_000
    ids = sorted(b["id"] for b in bills.values())
    issued = notifications_of(budi, "billIssued")
    assert sorted(n["rentBill"]["rentBillId"] for n in issued) == ids
    assert sorted(n["property"]["name"] for n in issued) == [
        "Kos Anggrek",
        "Kos Melati",
    ]

    run_jobs_on(world, database, date(2026, 10, 26))
    reminders = notifications_of(budi, "dueDateReminder")
    assert sorted(n["rentBill"]["rentBillId"] for n in reminders) == ids

    run_jobs_on(world, database, date(2026, 10, 29))
    overdue = notifications_of(budi, "billOverdue")
    assert sorted(n["rentBill"]["rentBillId"] for n in overdue) == ids
    assert sorted(n["property"]["name"] for n in overdue) == [
        "Kos Anggrek",
        "Kos Melati",
    ]
