"""The `billIssued` notification of generated bills, and how they meet the reminder jobs."""

from datetime import date, timedelta
from itertools import count
from types import SimpleNamespace

import pytest
from bill_generation_support import (
    build_site,
    freeze_date,
    generate,
    only_bill,
    stored_bills,
)
from notification_support import (
    assert_item,
    dump,
    edit_session,
    items,
    of_type,
    only,
    property_ref,
    rent_bill_facts,
    room_ref,
    save_settings,
    stored_for,
    stored_rows,
    types,
)
from sqlalchemy.orm import Session

BILL_ISSUED = "billIssued"
REMINDER = "dueDateReminder"
OVERDUE = "billOverdue"
FIXED_TODAY = date(2026, 3, 15)


def real_today() -> date:
    from app.services.rent_bills import today_jakarta

    return today_jakarta()


def send_reminders(database) -> int:
    from app.services import notifications

    with Session(database) as db:
        sent = notifications.send_due_date_reminders(db)
        db.commit()
    return sent


def send_overdue(database) -> int:
    from app.services import notifications

    with Session(database) as db:
        sent = notifications.send_overdue_notices(db)
        db.commit()
    return sent


def rows_of(database, type_: str) -> list[dict]:
    return [row for row in stored_rows(database) if str(row["type"]) == type_]


@pytest.fixture
def site(database, make_user, make_property, make_room, assign_manager, sign_in):
    return build_site(make_user, make_property, make_room, assign_manager, sign_in)


@pytest.fixture
def add_tenant(site, make_room, make_verified_tenant, sign_in):
    """Add a signed-in tenant with an active lease; lease options are keywords.

    The first tenant takes the room of the site, later ones a new room.
    """
    numbers = count(2)
    first = [True]

    def add(**options):
        options.setdefault("start_date", date(2026, 1, 10))
        if first[0]:
            room = site.room
            first[0] = False
        else:
            room = make_room(site.prop, number=f"R{next(numbers)}")
        stored = make_verified_tenant(room, **options)
        return SimpleNamespace(
            user=stored.user,
            lease=stored.lease,
            id=stored.id,
            room=room,
            signed_in=sign_in(stored.user),
        )

    return add


@pytest.fixture
def fixed_today(monkeypatch):
    freeze_date(monkeypatch, FIXED_TODAY)
    return FIXED_TODAY


def tenant_facts(site, tenant, bill, **options) -> dict:
    """What the tenant's `billIssued` notification of the bill carries."""
    return {
        "rentBill": rent_bill_facts(bill, "unpaid", **options),
        "room": room_ref(tenant.room),
        "property": property_ref(site.prop),
    }


# Who is told, and what they are told


def test_a_new_bill_notifies_its_tenant_with_the_bill_facts(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant(rent=1250000, grace_period_days=4, start_date=FIXED_TODAY)
    generate(database)
    bill = only_bill(database, tenant.lease)
    item = only(client, tenant.signed_in, BILL_ISSUED)
    assert_item(item, BILL_ISSUED, **tenant_facts(site, tenant, bill))
    assert item["rentBill"] == {
        "rentBillId": str(bill.id),
        "periodStart": "2026-03-15",
        "periodEnd": "2026-04-14",
        "dueDate": "2026-03-19",
        "amount": 1250000,
        "paymentStatus": "unpaid",
        "paymentMethod": None,
        "reason": None,
        "daysOverdue": 0,
    }
    assert item["room"] == {"id": str(tenant.room.id), "number": "A1"}
    assert item["property"] == {"id": str(site.prop.id), "name": "Kos Melati"}
    assert types(client, tenant.signed_in) == [BILL_ISSUED]


def test_a_new_bill_does_not_notify_the_owner_or_the_manager(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant()
    generate(database)
    assert items(client, site.owner_in) == []
    assert items(client, site.manager_in) == []
    assert stored_for(database, site.owner) == []
    assert stored_for(database, site.manager) == []
    assert len(stored_rows(database)) == 1
    assert len(stored_for(database, tenant.user)) == 1


def test_the_notification_is_stored_for_the_tenant_and_the_property(
    database, fixed_today, site, add_tenant
):
    tenant = add_tenant()
    generate(database)
    (row,) = stored_for(database, tenant.user)
    assert str(row["type"]) == BILL_ISSUED
    assert row["recipient_id"] == tenant.user.id
    assert row["property_id"] == site.prop.id
    assert row["read_at"] is None
    assert row["created_at"] is not None


def test_the_notification_is_unread(client, database, fixed_today, site, add_tenant):
    tenant = add_tenant()
    generate(database)
    assert only(client, tenant.signed_in, BILL_ISSUED)["read"] is False


def test_the_notification_of_a_bill_with_a_grace_period_carries_its_due_date(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant(
        grace_period_days=9,
        billing_cycle="quarterly",
        rent=3000000,
        start_date=FIXED_TODAY,
    )
    generate(database)
    item = only(client, tenant.signed_in, BILL_ISSUED)
    assert item["rentBill"]["periodEnd"] == "2026-06-14"
    assert item["rentBill"]["dueDate"] == "2026-03-24"
    assert item["rentBill"]["amount"] == 3000000
    assert item["rentBill"]["daysOverdue"] == 0


def test_a_bill_made_up_late_in_its_period_still_notifies_the_tenant(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant(start_date=date(2026, 3, 1))
    generate(database)
    bill = only_bill(database, tenant.lease)
    item = only(client, tenant.signed_in, BILL_ISSUED)
    assert item["rentBill"]["rentBillId"] == str(bill.id)


def test_a_notification_keeps_the_facts_of_the_moment_the_bill_was_created(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant()
    generate(database)
    (before,) = of_type(client, tenant.signed_in, BILL_ISSUED)
    bill = only_bill(database, tenant.lease)
    with Session(database) as db:
        from app.models import RentBill

        row = db.get(RentBill, bill.id)
        row.payment_status = "rejected"
        row.rejection_reason = "Changed later."
        row.amount = 5
        db.commit()
    (after,) = of_type(client, tenant.signed_in, BILL_ISSUED)
    assert after == before
    assert after["rentBill"]["paymentStatus"] == "unpaid"


def test_each_new_bill_makes_one_notification(
    client, database, fixed_today, site, add_tenant
):
    first = add_tenant()
    second = add_tenant(billing_cycle="weekly", start_date=date(2026, 3, 2))
    third = add_tenant(start_date=date(2099, 1, 1))
    assert generate(database) == 2
    assert len(rows_of(database, BILL_ISSUED)) == 2
    assert len(of_type(client, first.signed_in, BILL_ISSUED)) == 1
    assert len(of_type(client, second.signed_in, BILL_ISSUED)) == 1
    assert items(client, third.signed_in) == []
    first_item = only(client, first.signed_in, BILL_ISSUED)
    assert first_item["rentBill"]["rentBillId"] == str(
        only_bill(database, first.lease).id
    )
    assert first_item["room"]["id"] == str(first.room.id)
    second_item = only(client, second.signed_in, BILL_ISSUED)
    assert second_item["rentBill"]["rentBillId"] == str(
        only_bill(database, second.lease).id
    )
    assert second_item["room"]["id"] == str(second.room.id)


def test_a_tenant_with_two_leases_gets_a_notification_for_each_bill(
    client, database, fixed_today, site, add_tenant, make_room, make_verified_tenant
):
    first = add_tenant()
    other_room = make_room(site.prop, number="Z9")
    second = make_verified_tenant(
        other_room, user=first.user, start_date=date(2026, 2, 20)
    )
    assert generate(database) == 2
    shown = of_type(client, first.signed_in, BILL_ISSUED)
    assert {i["rentBill"]["rentBillId"] for i in shown} == {
        str(only_bill(database, first.lease).id),
        str(only_bill(database, second.lease).id),
    }
    assert {i["room"]["id"] for i in shown} == {str(first.room.id), str(other_room.id)}
    assert len(stored_for(database, first.user)) == 2


def test_a_tenant_is_not_told_about_the_bill_of_another_tenant(
    client, database, fixed_today, site, add_tenant
):
    first = add_tenant()
    second = add_tenant(start_date=date(2099, 1, 1))
    generate(database)
    assert len(of_type(client, first.signed_in, BILL_ISSUED)) == 1
    assert stored_for(database, second.user) == []


def test_a_tenant_who_has_not_activated_the_account_is_notified_too(
    database, fixed_today, site, make_room, make_tenant
):
    tenant = make_tenant(
        make_room(site.prop, number="N1"), start_date=date(2026, 1, 10)
    )
    generate(database)
    (row,) = stored_for(database, tenant.user)
    assert str(row["type"]) == BILL_ISSUED


# No new bill, no notification


def test_a_second_run_creates_no_further_notification(
    client, database, fixed_today, site, add_tenant
):
    tenant = add_tenant()
    generate(database)
    assert generate(database) == 0
    assert len(rows_of(database, BILL_ISSUED)) == 1
    assert len(of_type(client, tenant.signed_in, BILL_ISSUED)) == 1


def test_a_lease_without_a_bill_creates_no_notification(
    database, fixed_today, site, add_tenant
):
    add_tenant(start_date=None)
    add_tenant(lease_ended=True)
    add_tenant(start_date=date(2026, 1, 10), end_date=date(2026, 3, 5))
    add_tenant(start_date=date(2099, 1, 1))
    assert generate(database) == 0
    assert stored_rows(database) == []


def test_a_period_that_already_has_a_bill_creates_no_notification(
    database, fixed_today, site, add_tenant, make_rent_bill
):
    tenant = add_tenant()
    make_rent_bill(
        tenant.lease,
        period_start=date(2026, 3, 10),
        period_end=date(2026, 4, 9),
        due_date=date(2026, 3, 10),
    )
    assert generate(database) == 0
    assert stored_rows(database) == []


def test_the_next_period_notifies_again(
    client, database, monkeypatch, fixed_today, site, add_tenant
):
    tenant = add_tenant()
    generate(database)
    freeze_date(monkeypatch, date(2026, 4, 10))
    assert generate(database) == 1
    shown = of_type(client, tenant.signed_in, BILL_ISSUED)
    assert len(shown) == 2
    assert {i["rentBill"]["periodStart"] for i in shown} == {"2026-03-10", "2026-04-10"}


def test_the_generator_does_not_commit_its_notifications(
    database, fixed_today, site, add_tenant
):
    from app.services import rent_bills

    add_tenant()
    with Session(database) as db:
        assert rent_bills.generate_rent_bills(db) == 1
        db.flush()
        assert stored_rows(database) == []
        db.rollback()
    assert stored_rows(database) == []
    assert stored_bills(database) == []


# Push


def give_devices(database, site, tenant) -> dict[str, str]:
    tokens = {
        "tenant": "tenant-device",
        "owner": "owner-device",
        "manager": "manager-device",
    }
    edit_session(database, tenant.signed_in.session_id, push_token=tokens["tenant"])
    edit_session(database, site.owner_in.session_id, push_token=tokens["owner"])
    edit_session(database, site.manager_in.session_id, push_token=tokens["manager"])
    return tokens


def test_a_new_bill_is_pushed_to_the_tenant_only(
    client, database, fixed_today, site, add_tenant, pushes
):
    tenant = add_tenant()
    tokens = give_devices(database, site, tenant)
    generate(database)
    assert pushes.tokens() == [tokens["tenant"]]
    (sent,) = pushes.to(tokens["tenant"])
    (listed,) = of_type(client, tenant.signed_in, BILL_ISSUED)
    assert dump(sent) == listed


def test_nothing_is_pushed_when_no_bill_is_created(
    database, fixed_today, site, add_tenant, pushes
):
    tenant = add_tenant()
    give_devices(database, site, tenant)
    generate(database)
    before = len(pushes.attempts)
    generate(database)
    assert len(pushes.attempts) == before


def test_a_new_bill_is_stored_but_not_pushed_with_the_billing_category_off(
    client, database, fixed_today, site, add_tenant, pushes
):
    tenant = add_tenant()
    give_devices(database, site, tenant)
    save_settings(client, tenant.signed_in, "tenant", off=("billing",))
    assert generate(database) == 1
    assert pushes.attempts == []
    assert len(of_type(client, tenant.signed_in, BILL_ISSUED)) == 1


def test_only_the_billing_category_gates_the_push_of_a_new_bill(
    client, database, fixed_today, site, add_tenant, pushes
):
    tenant = add_tenant()
    tokens = give_devices(database, site, tenant)
    save_settings(
        client,
        tenant.signed_in,
        "tenant",
        off=("paymentStatus", "complaintProgress"),
    )
    generate(database)
    assert pushes.tokens() == [tokens["tenant"]]


def test_the_push_is_sent_only_after_the_commit(
    database, fixed_today, site, add_tenant, pushes
):
    from app.services import rent_bills

    tenant = add_tenant()
    give_devices(database, site, tenant)
    with Session(database) as db:
        assert rent_bills.generate_rent_bills(db) == 1
        db.flush()
        assert pushes.attempts == []
        db.commit()
    assert len(pushes.attempts) == 1


def test_a_rolled_back_run_pushes_nothing(
    database, fixed_today, site, add_tenant, pushes
):
    from app.services import rent_bills

    tenant = add_tenant()
    give_devices(database, site, tenant)
    with Session(database) as db:
        rent_bills.generate_rent_bills(db)
        db.rollback()
    assert pushes.attempts == []


def test_a_failing_push_keeps_the_bill_and_the_notification(
    client, database, fixed_today, site, add_tenant, pushes
):
    tenant = add_tenant()
    give_devices(database, site, tenant)
    pushes.fail_all = True
    assert generate(database) == 1
    assert len(pushes.attempts) == 1
    assert len(stored_bills(database, tenant.lease)) == 1
    assert len(of_type(client, tenant.signed_in, BILL_ISSUED)) == 1


# A failing notification never undoes the bill


def test_a_failure_to_notify_does_not_undo_the_bill(
    client, database, monkeypatch, fixed_today, site, add_tenant
):
    def broken(*args, **kwargs):
        raise RuntimeError("notification down")

    tenant = add_tenant()
    monkeypatch.setattr("app.services.notifications.notify", broken)
    assert generate(database) == 1
    (bill,) = stored_bills(database, tenant.lease)
    assert bill.payment_status == "unpaid"
    assert stored_rows(database) == []
    assert items(client, tenant.signed_in) == []


def test_a_failure_to_notify_keeps_every_bill_of_the_run(
    database, monkeypatch, fixed_today, site, add_tenant
):
    def broken(*args, **kwargs):
        raise RuntimeError("notification down")

    leases = [add_tenant().lease for _ in range(3)]
    monkeypatch.setattr("app.services.notifications.notify", broken)
    assert generate(database) == 3
    assert [len(stored_bills(database, lease)) for lease in leases] == [1, 1, 1]


def test_a_failure_to_notify_one_tenant_does_not_stop_the_others(
    client, database, monkeypatch, fixed_today, site, add_tenant
):
    from app.services import notifications

    real = notifications.notify
    calls: list[int] = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("notification down")
        return real(*args, **kwargs)

    first = add_tenant()
    second = add_tenant()
    monkeypatch.setattr("app.services.notifications.notify", flaky)
    assert generate(database) == 2
    assert len(stored_bills(database, first.lease)) == 1
    assert len(stored_bills(database, second.lease)) == 1
    assert len(rows_of(database, BILL_ISSUED)) == 1


def test_a_failure_to_notify_leaves_the_history_of_the_bill_intact(
    database, monkeypatch, fixed_today, site, add_tenant
):
    from rent_bill_support import stored_changes

    def broken(*args, **kwargs):
        raise RuntimeError("notification down")

    tenant = add_tenant()
    monkeypatch.setattr("app.services.notifications.notify", broken)
    generate(database)
    bill = only_bill(database, tenant.lease)
    (change,) = stored_changes(database, bill)
    assert change.status == "unpaid"


def test_the_notification_is_made_after_the_bill_is_saved(
    database, monkeypatch, fixed_today, site, add_tenant
):
    from sqlalchemy import func, select

    from app.models import RentBill
    from app.services import notifications

    real = notifications.notify
    seen: list[int] = []

    def spy(*args, **kwargs):
        db = args[0] if args else kwargs["db"]
        seen.append(db.scalar(select(func.count()).select_from(RentBill)))
        return real(*args, **kwargs)

    add_tenant()
    monkeypatch.setattr("app.services.notifications.notify", spy)
    assert generate(database) == 1
    assert seen == [1]


# Meeting the reminder and overdue jobs


def weekly_today(add_tenant, **options):
    """A weekly lease whose period starts today, so its bill is issued today."""
    return add_tenant(billing_cycle="weekly", start_date=real_today(), **options)


def test_a_bill_due_on_the_day_it_is_issued_is_not_reminded_or_overdue_that_day(
    client, database, site, add_tenant
):
    tenant = weekly_today(add_tenant, grace_period_days=0)
    assert generate(database) == 1
    assert send_reminders(database) == 0
    assert send_overdue(database) == 0
    assert rows_of(database, REMINDER) == []
    assert rows_of(database, OVERDUE) == []
    assert types(client, tenant.signed_in) == [BILL_ISSUED]


def test_a_bill_due_on_the_day_it_is_issued_becomes_overdue_the_next_day(
    client, database, monkeypatch, site, add_tenant
):
    tenant = weekly_today(add_tenant, grace_period_days=0)
    generate(database)
    freeze_date(monkeypatch, real_today() + timedelta(days=1))
    assert send_overdue(database) == 1
    for who in (tenant.signed_in, site.owner_in, site.manager_in):
        (item,) = of_type(client, who, OVERDUE)
        assert item["rentBill"]["daysOverdue"] == 1
        assert item["rentBill"]["paymentStatus"] == "unpaid"


@pytest.mark.parametrize("grace", [1, 2])
def test_a_bill_issued_fewer_than_three_days_before_its_due_date_is_never_reminded(
    database, monkeypatch, site, add_tenant, grace
):
    weekly_today(add_tenant, grace_period_days=grace)
    generate(database)
    for offset in range(grace + 2):
        freeze_date(monkeypatch, real_today() + timedelta(days=offset))
        assert send_reminders(database) == 0
    assert rows_of(database, REMINDER) == []


def test_a_bill_issued_exactly_three_days_before_its_due_date_is_reminded_the_same_day(
    client, database, site, add_tenant
):
    tenant = weekly_today(add_tenant, grace_period_days=3)
    generate(database)
    bill = only_bill(database, tenant.lease)
    assert send_reminders(database) == 1
    (item,) = of_type(client, tenant.signed_in, REMINDER)
    assert item["rentBill"]["rentBillId"] == str(bill.id)
    assert item["rentBill"]["paymentStatus"] == "unpaid"
    assert item["rentBill"]["daysOverdue"] == 0
    assert types(client, tenant.signed_in).count(BILL_ISSUED) == 1


def test_a_bill_with_a_week_of_grace_is_reminded_three_days_before_its_due_date_only(
    client, database, monkeypatch, site, add_tenant
):
    tenant = weekly_today(add_tenant, grace_period_days=7)
    generate(database)
    today = real_today()
    sent = {}
    for offset in range(8):
        freeze_date(monkeypatch, today + timedelta(days=offset))
        sent[offset] = send_reminders(database)
    assert sent == {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 0, 6: 0, 7: 0}
    (item,) = of_type(client, tenant.signed_in, REMINDER)
    assert item["rentBill"]["dueDate"] == (today + timedelta(days=7)).isoformat()


def test_a_bill_with_a_week_of_grace_becomes_overdue_the_day_after_its_due_date(
    client, database, monkeypatch, site, add_tenant
):
    tenant = weekly_today(add_tenant, grace_period_days=7)
    generate(database)
    today = real_today()
    freeze_date(monkeypatch, today + timedelta(days=7))
    assert send_overdue(database) == 0
    freeze_date(monkeypatch, today + timedelta(days=8))
    assert send_overdue(database) == 1
    (item,) = of_type(client, tenant.signed_in, OVERDUE)
    assert item["rentBill"]["daysOverdue"] == 1
    assert len(of_type(client, site.owner_in, OVERDUE)) == 1
    assert len(of_type(client, site.manager_in, OVERDUE)) == 1


def test_a_bill_made_up_late_is_not_reminded_when_its_due_date_is_near(
    database, monkeypatch, site, add_tenant
):
    # The period started two days ago; with four days of grace the bill is
    # created today and due in two days, which is fewer than three.
    add_tenant(
        billing_cycle="weekly",
        start_date=real_today() - timedelta(days=2),
        grace_period_days=4,
    )
    assert generate(database) == 1
    for offset in (0, 1):
        freeze_date(monkeypatch, real_today() + timedelta(days=offset))
        assert send_reminders(database) == 0
    assert rows_of(database, REMINDER) == []


def test_a_bill_made_up_after_its_due_date_is_announced_as_overdue(
    client, database, site, add_tenant
):
    tenant = add_tenant(
        billing_cycle="weekly",
        start_date=real_today() - timedelta(days=2),
        grace_period_days=0,
    )
    assert generate(database) == 1
    assert send_reminders(database) == 0
    assert send_overdue(database) == 1
    (item,) = of_type(client, tenant.signed_in, OVERDUE)
    assert item["rentBill"]["daysOverdue"] == 2
    assert types(client, tenant.signed_in).count(BILL_ISSUED) == 1
