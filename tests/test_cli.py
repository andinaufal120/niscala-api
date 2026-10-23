"""The `niscala-api` command line."""

import tomllib
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.auth import UserRole
from app.schemas.subscriptions import PlanCode

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_subscription(database, owner_id):
    from app.models import Subscription

    with Session(database, expire_on_commit=False) as session:
        return session.get(Subscription, owner_id)


def count_subscriptions(database) -> int:
    from app.models import Subscription

    with Session(database) as session:
        return session.scalar(select(func.count()).select_from(Subscription))


def test_console_script_runs_the_cli_main():
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)
    assert config["project"]["scripts"]["niscala-api"] == "app.cli:main"


def test_main_is_callable():
    from app.cli import main

    assert callable(main)


def test_grant_creates_a_subscription_and_exits_zero(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    before = datetime.now(UTC)
    assert main(["grant-subscription", "rina@example.com", "pro"]) == 0
    row = read_subscription(database, owner.id)
    assert row.plan == "pro"
    expected = before + timedelta(days=30)
    assert expected <= row.ends_at <= datetime.now(UTC) + timedelta(days=30)
    assert capsys.readouterr().err == ""


def test_grant_prints_one_line_with_email_plan_and_end(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert (
        main(["grant-subscription", "rina@example.com", "basic", "--days", "10"]) == 0
    )
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 1
    row = read_subscription(database, owner.id)
    assert "rina@example.com" in lines[0]
    assert "basic" in lines[0]
    assert row.ends_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M") in lines[0]


def test_printed_end_is_iso_8601_utc(database, make_user, capsys):
    from app.cli import main

    make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "pro"])
    tokens = capsys.readouterr().out.split()
    stamps = []
    for token in tokens:
        try:
            stamps.append(datetime.fromisoformat(token))
        except ValueError:
            continue
    assert len(stamps) == 1
    assert stamps[0].utcoffset() == timedelta(0)


def test_days_option_sets_the_period(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "7"])
    row = read_subscription(database, owner.id)
    remaining = row.ends_at - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


def test_one_day_is_accepted(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert main(["grant-subscription", "rina@example.com", "pro", "--days", "1"]) == 0
    assert read_subscription(database, owner.id) is not None


def test_email_lookup_ignores_case_and_surrounding_spaces(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert main(["grant-subscription", "  Rina@Example.COM ", "pro"]) == 0
    assert read_subscription(database, owner.id).plan == "pro"
    out = capsys.readouterr().out
    assert "rina@example.com" in out
    assert "Rina@Example.COM" not in out


def test_running_twice_replaces_the_subscription(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "90"])
    first_end = read_subscription(database, owner.id).ends_at
    main(["grant-subscription", "rina@example.com", "pro", "--days", "5"])
    row = read_subscription(database, owner.id)
    assert row.plan == "pro"
    assert row.ends_at < first_end
    assert count_subscriptions(database) == 1


def test_grant_makes_the_subscription_active(database, make_user):
    from app.cli import main
    from app.services.subscriptions import current_plan, has_active_subscription

    owner = make_user(email="rina@example.com")
    with Session(database) as session:
        assert has_active_subscription(session, owner.id) is False
    main(["grant-subscription", "rina@example.com", "basic"])
    with Session(database) as session:
        assert has_active_subscription(session, owner.id) is True
        assert current_plan(session, owner.id) is PlanCode.BASIC


def test_unknown_email_fails_without_saving(database, make_user, capsys):
    from app.cli import main

    make_user(email="rina@example.com")
    assert main(["grant-subscription", "nobody@example.com", "pro"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert count_subscriptions(database) == 0


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.TENANT, UserRole.ADMIN])
def test_account_that_is_not_an_owner_fails_without_saving(
    database, make_user, capsys, role
):
    from app.cli import main

    user = make_user(email="someone@example.com", role=role)
    assert main(["grant-subscription", "someone@example.com", "pro"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert read_subscription(database, user.id) is None


def test_failure_leaves_an_existing_subscription_unchanged(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "10"])
    before = read_subscription(database, owner.id)
    main(["grant-subscription", "nobody@example.com", "pro"])
    after = read_subscription(database, owner.id)
    assert (after.plan, after.ends_at) == (before.plan, before.ends_at)


@pytest.mark.parametrize("plan", ["free", "gold", "PRO", ""])
def test_unknown_plan_is_a_usage_error(database, make_user, plan):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    with pytest.raises(SystemExit) as exit_info:
        main(["grant-subscription", "rina@example.com", plan])
    assert exit_info.value.code == 2
    assert read_subscription(database, owner.id) is None


@pytest.mark.parametrize("days", ["0", "-3", "abc", "1.5", ""])
def test_invalid_days_is_a_usage_error(database, make_user, days):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    with pytest.raises(SystemExit) as exit_info:
        main(["grant-subscription", "rina@example.com", "pro", "--days", days])
    assert exit_info.value.code == 2
    assert read_subscription(database, owner.id) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["grant-subscription"],
        ["grant-subscription", "rina@example.com"],
        ["unknown-command", "rina@example.com", "pro"],
        [],
    ],
)
def test_malformed_command_line_is_a_usage_error(database, argv):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


SEED = "seed-rent-bills"


def stored_bills(database) -> list:
    """All rent bills, oldest period first."""
    from app.models import RentBill

    with Session(database, expire_on_commit=False) as session:
        return list(session.scalars(select(RentBill).order_by(RentBill.period_start)))


def stored_bill_changes(database, bill) -> list:
    from app.models import RentBillStatusChange

    query = (
        select(RentBillStatusChange)
        .where(RentBillStatusChange.rent_bill_id == bill.id)
        .order_by(RentBillStatusChange.changed_at, RentBillStatusChange.status)
    )
    with Session(database, expire_on_commit=False) as session:
        return list(session.scalars(query))


@pytest.fixture
def seeded_tenant(
    frozen_today, database, make_user, make_property, make_room, make_tenant
):
    """A tenant with a monthly lease that started on 2026-01-10."""
    owner = make_user(email="owner@example.com")
    room = make_room(make_property(owner))
    return make_tenant(
        room,
        email="budi@example.com",
        start_date=date(2026, 1, 10),
        billing_cycle="monthly",
        rent=1250000,
        grace_period_days=3,
        invitation=False,
        activated=True,
    )


def test_seeding_creates_one_bill_per_period_through_the_current_one(
    database, seeded_tenant, capsys
):
    from app.cli import main

    assert main([SEED, "budi@example.com"]) == 0
    bills = stored_bills(database)
    assert [b.period_start for b in bills] == [date(2026, m, 10) for m in range(1, 11)]
    assert all(b.lease_id == seeded_tenant.lease.id for b in bills)
    assert capsys.readouterr().err == ""


def test_periods_are_contiguous_and_the_last_one_contains_today(
    database, seeded_tenant, frozen_today
):
    from app.cli import main

    main([SEED, "budi@example.com"])
    bills = stored_bills(database)
    for earlier, later in pairwise(bills):
        assert earlier.period_end == later.period_start - timedelta(days=1)
    assert bills[-1].period_start <= frozen_today <= bills[-1].period_end


def test_each_bill_has_the_lease_rent_and_a_due_date_after_the_grace_period(
    database, seeded_tenant
):
    from app.cli import main

    main([SEED, "budi@example.com"])
    for bill in stored_bills(database):
        assert bill.amount == 1250000
        assert bill.due_date == bill.period_start + timedelta(days=3)


def test_past_periods_are_paid_by_transfer_and_the_current_one_is_unpaid(
    database, seeded_tenant
):
    from app.cli import main

    main([SEED, "budi@example.com"])
    *past, current = stored_bills(database)
    assert len(past) == 9
    for bill in past:
        assert bill.payment_status == "paid"
        assert bill.payment_method == "transfer"
        assert bill.paid_on is not None
        assert bill.rejection_reason is None
    assert current.payment_status == "unpaid"
    assert current.payment_method is None
    assert current.paid_on is None


def test_every_fourth_bill_is_paid_ten_days_late(database, seeded_tenant):
    from app.cli import main

    main([SEED, "budi@example.com"])
    bills = stored_bills(database)
    late = [
        i
        for i, b in enumerate(bills[:-1], start=1)
        if b.paid_on == b.due_date + timedelta(days=10)
    ]
    assert late == [4, 8]
    for index, bill in enumerate(bills[:-1], start=1):
        if index not in late:
            assert bill.paid_on <= bill.due_date


def test_every_bill_has_status_history_rows_made_by_the_system(database, seeded_tenant):
    from app.cli import main

    main([SEED, "budi@example.com"])
    *past, current = stored_bills(database)
    for bill in [*past, current]:
        changes = stored_bill_changes(database, bill)
        assert changes[0].status == "unpaid"
        assert all(c.actor_id is None and c.manual is False for c in changes)
    for bill in past:
        last = stored_bill_changes(database, bill)[-1]
        assert last.status == "paid"
        assert last.method == "transfer"
    assert [c.status for c in stored_bill_changes(database, current)] == ["unpaid"]


def test_the_printed_line_states_the_created_count(database, seeded_tenant, capsys):
    from app.cli import main

    main([SEED, "budi@example.com"])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "10" in lines[0].split()


def test_running_twice_creates_nothing_the_second_time(database, seeded_tenant, capsys):
    from app.cli import main

    main([SEED, "budi@example.com"])
    capsys.readouterr()
    before = stored_bills(database)
    changes_before = sum(len(stored_bill_changes(database, b)) for b in before)
    assert main([SEED, "budi@example.com"]) == 0
    after = stored_bills(database)
    assert [b.id for b in after] == [b.id for b in before]
    assert sum(len(stored_bill_changes(database, b)) for b in after) == changes_before
    out = capsys.readouterr()
    assert "0" in out.out.split()
    assert out.err == ""


def test_months_limits_the_seed_to_the_latest_periods(database, seeded_tenant):
    from app.cli import main

    assert main([SEED, "budi@example.com", "--months", "3"]) == 0
    bills = stored_bills(database)
    assert [b.period_start for b in bills] == [
        date(2026, 8, 10),
        date(2026, 9, 10),
        date(2026, 10, 10),
    ]
    assert [b.payment_status for b in bills] == ["paid", "paid", "unpaid"]


def test_a_larger_months_value_adds_only_the_missing_older_periods(
    database, seeded_tenant, capsys
):
    from app.cli import main

    main([SEED, "budi@example.com", "--months", "3"])
    first = {b.period_start: b.id for b in stored_bills(database)}
    capsys.readouterr()
    main([SEED, "budi@example.com", "--months", "5"])
    bills = stored_bills(database)
    assert len(bills) == 5
    for bill in bills:
        if bill.period_start in first:
            assert bill.id == first[bill.period_start]
    assert "2" in capsys.readouterr().out.split()


def test_months_larger_than_the_lease_history_creates_all_periods(
    database, seeded_tenant
):
    from app.cli import main

    assert main([SEED, "budi@example.com", "--months", "60"]) == 0
    assert len(stored_bills(database)) == 10


def test_the_default_is_the_latest_twelve_periods(
    frozen_today, database, make_user, make_property, make_room, make_tenant
):
    from app.cli import main

    room = make_room(make_property(make_user(email="owner@example.com")))
    make_tenant(
        room,
        email="old@example.com",
        start_date=date(2024, 1, 10),
        invitation=False,
        activated=True,
    )
    assert main([SEED, "old@example.com"]) == 0
    bills = stored_bills(database)
    assert len(bills) == 12
    assert bills[0].period_start == date(2025, 11, 10)
    assert bills[-1].period_start == date(2026, 10, 10)


def test_weekly_leases_get_one_bill_per_week(
    frozen_today, database, make_user, make_property, make_room, make_tenant
):
    from app.cli import main

    room = make_room(make_property(make_user(email="owner@example.com")))
    make_tenant(
        room,
        email="weekly@example.com",
        start_date=date(2026, 9, 25),
        billing_cycle="weekly",
        invitation=False,
        activated=True,
    )
    main([SEED, "weekly@example.com"])
    starts = [b.period_start for b in stored_bills(database)]
    assert starts == [date(2026, 9, 25) + timedelta(days=7 * n) for n in range(5)]
    assert [b.period_end - b.period_start for b in stored_bills(database)] == [
        timedelta(days=6)
    ] * 5


def test_seeding_never_dates_a_late_payment_after_today(
    frozen_today, database, make_user, make_property, make_room, make_tenant
):
    from zoneinfo import ZoneInfo

    from app.cli import main

    room = make_room(make_property(make_user(email="owner@example.com")))
    make_tenant(
        room,
        email="weekly@example.com",
        start_date=date(2026, 9, 25),
        billing_cycle="weekly",
        invitation=False,
        activated=True,
    )
    main([SEED, "weekly@example.com"])
    bills = stored_bills(database)
    # The fourth bill is due 2026-10-16, so due date + 10 days would be after today.
    assert bills[3].due_date + timedelta(days=10) > frozen_today
    end_of_today = datetime(
        frozen_today.year,
        frozen_today.month,
        frozen_today.day,
        tzinfo=ZoneInfo("Asia/Jakarta"),
    ) + timedelta(days=1)
    for bill in bills[:-1]:
        assert bill.paid_on <= frozen_today
        paid = [c for c in stored_bill_changes(database, bill) if c.status == "paid"]
        assert paid
        assert all(c.changed_at <= end_of_today for c in paid)


def test_quarterly_leases_get_one_bill_per_quarter(
    frozen_today, database, make_user, make_property, make_room, make_tenant
):
    from app.cli import main

    room = make_room(make_property(make_user(email="owner@example.com")))
    make_tenant(
        room,
        email="quarter@example.com",
        start_date=date(2026, 1, 10),
        billing_cycle="quarterly",
        invitation=False,
        activated=True,
    )
    main([SEED, "quarter@example.com"])
    assert [b.period_start for b in stored_bills(database)] == [
        date(2026, 1, 10),
        date(2026, 4, 10),
        date(2026, 7, 10),
        date(2026, 10, 10),
    ]


def test_seeding_ignores_case_and_spaces_in_the_email(database, seeded_tenant):
    from app.cli import main

    assert main([SEED, "  Budi@Example.COM "]) == 0
    assert len(stored_bills(database)) == 10


def test_seeding_one_tenant_leaves_other_tenants_without_bills(
    database, seeded_tenant, make_user, make_property, make_room, make_tenant
):
    from app.cli import main

    other_owner = make_user(email="other-owner@example.com")
    other_room = make_room(make_property(other_owner, name="Kos Mawar"))
    other = make_tenant(
        other_room,
        email="sari@example.com",
        start_date=date(2026, 1, 10),
        invitation=False,
        activated=True,
    )
    main([SEED, "budi@example.com"])
    assert all(b.lease_id != other.lease.id for b in stored_bills(database))


def test_an_unknown_email_fails_without_saving(database, seeded_tenant, capsys):
    from app.cli import main

    assert main([SEED, "nobody@example.com"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert stored_bills(database) == []


def test_a_tenant_whose_lease_ended_fails_without_saving(
    frozen_today, database, make_user, make_property, make_room, make_tenant, capsys
):
    from app.cli import main

    room = make_room(make_property(make_user(email="owner@example.com")))
    make_tenant(
        room,
        email="gone@example.com",
        start_date=date(2026, 1, 10),
        lease_ended=True,
        invitation=False,
        activated=True,
    )
    assert main([SEED, "gone@example.com"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert stored_bills(database) == []


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.MANAGER, UserRole.ADMIN])
def test_an_account_without_a_lease_fails_without_saving(
    frozen_today, database, make_user, capsys, role
):
    from app.cli import main

    make_user(email="someone@example.com", role=role)
    assert main([SEED, "someone@example.com"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert stored_bills(database) == []


@pytest.mark.parametrize("months", ["0", "-2", "abc", "1.5", ""])
def test_invalid_months_is_a_usage_error(database, seeded_tenant, months):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([SEED, "budi@example.com", "--months", months])
    assert exit_info.value.code == 2
    assert stored_bills(database) == []


def test_seeding_without_an_email_is_a_usage_error(database):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([SEED])
    assert exit_info.value.code == 2


def test_usage_error_prints_nothing_to_stdout(database, capsys):
    from app.cli import main

    with pytest.raises(SystemExit):
        main(["grant-subscription", "rina@example.com", "gold"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
