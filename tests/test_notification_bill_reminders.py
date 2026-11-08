"""Due-date reminders and overdue notices sent by the daily jobs.

"Today" is the real Asia/Jakarta date; every bill is built relative to it.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from notification_support import (
    awaiting_bill,
    dump,
    edit_session,
    items,
    of_type,
    stored_for,
    stored_rows,
    unassign,
)
from rent_bill_support import JAKARTA, at_noon_jakarta
from sqlalchemy import text
from sqlalchemy.orm import Session

REMINDER = "dueDateReminder"
OVERDUE = "billOverdue"


def today() -> date:
    from app.services.rent_bills import today_jakarta

    return today_jakarta()


def day(offset: int) -> date:
    return today() + timedelta(days=offset)


def send_reminders(database) -> int:
    from app.services import notifications

    with Session(database) as db:
        count = notifications.send_due_date_reminders(db)
        db.commit()
    return count


def send_overdue(database) -> int:
    from app.services import notifications

    with Session(database) as db:
        count = notifications.send_overdue_notices(db)
        db.commit()
    return count


@pytest.fixture
def site(
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    assign_manager,
    sign_in,
):
    """An owner, an assigned manager and a tenant with an active lease, all signed in."""
    from app.schemas.auth import UserRole

    owner = make_user(name="Rina Owner")
    manager = make_user(name="Mira Manager", role=UserRole.MANAGER)
    prop = make_property(owner, name="Kos Melati")
    assign_manager(manager, prop)
    room = make_room(prop, number="A1")
    tenant = make_verified_tenant(room, name="Budi Tenant")
    return SimpleNamespace(
        owner=owner,
        manager=manager,
        prop=prop,
        room=room,
        tenant=tenant,
        lease=tenant.lease,
        owner_in=sign_in(owner),
        manager_in=sign_in(manager),
        tenant_in=sign_in(tenant.user),
    )


@pytest.fixture
def lease(site):
    return site.lease


@pytest.fixture
def bill_of(make_rent_bill):
    """Build a bill due `due_in` days from today, issued `issued_before_due` days before."""

    def build(
        lease,
        due_in: int,
        *,
        issued_before_due: int = 10,
        status: str = "unpaid",
        **options,
    ):
        due = day(due_in)
        options = {
            "due_date": due,
            "period_start": due - timedelta(days=20),
            "created_at": at_noon_jakarta(due - timedelta(days=issued_before_due)),
            **options,
        }
        if status == "awaitingVerification":
            return awaiting_bill(make_rent_bill, lease, **options)
        if status == "paid":
            options.update(method="cash", paid_on=today())
        if status == "rejected":
            options.setdefault("rejection_reason", "Wrong amount.")
        return make_rent_bill(lease, status=status, **options)

    return build


def assert_facts(item: dict, bill, status: str, days_overdue: int) -> None:
    shown = item["rentBill"]
    assert shown["rentBillId"] == str(bill.id)
    assert shown["periodStart"] == bill.period_start.isoformat()
    assert shown["periodEnd"] == bill.period_end.isoformat()
    assert shown["dueDate"] == bill.due_date.isoformat()
    assert shown["amount"] == bill.amount
    assert shown["paymentStatus"] == status
    assert shown["paymentMethod"] is None
    assert shown["daysOverdue"] == days_overdue
    assert item["read"] is False


def rows_of(database, type_: str) -> list[dict]:
    return [row for row in stored_rows(database) if str(row["type"]) == type_]


def give_devices(database, site) -> dict[str, str]:
    tokens = {
        "tenant": "tenant-device",
        "owner": "owner-device",
        "manager": "manager-device",
    }
    for who, token in tokens.items():
        edit_session(database, getattr(site, f"{who}_in").session_id, push_token=token)
    return tokens


def save_off(client, signed_in, role_name: str, *categories: str) -> None:
    from notification_support import save_settings

    save_settings(client, signed_in, role_name, off=categories)


# Due-date reminders: when a bill qualifies


@pytest.mark.parametrize("due_in", [3, 2, 1])
def test_a_bill_due_within_three_days_is_reminded(
    client, database, site, lease, bill_of, due_in
):
    bill = bill_of(lease, due_in)
    assert send_reminders(database) == 1
    item = of_type(client, site.tenant_in, REMINDER)
    assert len(item) == 1
    assert item[0]["type"] == REMINDER
    assert_facts(item[0], bill, "unpaid", 0)


@pytest.mark.parametrize("due_in", [4, 5, 30])
def test_a_bill_due_in_more_than_three_days_is_not_yet_reminded(
    client, database, site, lease, bill_of, due_in
):
    bill_of(lease, due_in)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


@pytest.mark.parametrize("due_in", [0, -1, -10])
def test_a_bill_due_today_or_overdue_is_not_reminded(
    client, database, site, lease, bill_of, due_in
):
    bill_of(lease, due_in)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


@pytest.mark.parametrize("status", ["unpaid", "rejected"])
def test_an_unpaid_or_rejected_bill_is_reminded_with_its_status(
    client, database, site, lease, bill_of, status
):
    bill = bill_of(lease, 3, status=status)
    assert send_reminders(database) == 1
    (item,) = of_type(client, site.tenant_in, REMINDER)
    assert_facts(item, bill, status, 0)


@pytest.mark.parametrize("status", ["awaitingVerification", "paid"])
def test_a_bill_awaiting_verification_or_paid_is_never_reminded(
    client, database, site, lease, bill_of, status
):
    bill_of(lease, 3, status=status)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


def test_a_bill_of_an_ended_lease_is_never_reminded(
    client, database, site, make_room, make_verified_tenant, bill_of
):
    ended = make_verified_tenant(
        make_room(site.prop, number="A2"), name="Old Tenant", lease_ended=True
    )
    bill_of(ended.lease, 3)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


def test_a_reminder_is_sent_to_the_tenant_only(client, database, site, lease, bill_of):
    bill_of(lease, 3)
    send_reminders(database)
    assert items(client, site.owner_in) == []
    assert items(client, site.manager_in) == []
    assert len(stored_rows(database)) == 1


def test_a_reminder_is_stored_for_the_tenant_and_the_property_of_the_bill(
    client, database, site, lease, bill_of
):
    bill_of(lease, 2)
    send_reminders(database)
    (row,) = stored_for(database, site.tenant.user)
    assert str(row["type"]) == REMINDER
    assert row["property_id"] == site.prop.id
    assert row["read_at"] is None
    assert row["created_at"] is not None


def test_a_reminder_carries_the_room_and_the_property(
    client, database, site, lease, bill_of
):
    bill_of(lease, 3)
    send_reminders(database)
    (item,) = of_type(client, site.tenant_in, REMINDER)
    assert item["room"] == {"id": str(site.room.id), "number": "A1"}
    assert item["property"] == {"id": str(site.prop.id), "name": "Kos Melati"}
    assert item["complaint"] is None
    assert item["actorName"] is None


# Due-date reminders: bills issued late


def test_a_bill_issued_exactly_three_days_before_its_due_date_is_reminded(
    client, database, site, lease, bill_of
):
    bill_of(lease, 3, issued_before_due=3)
    assert send_reminders(database) == 1


def test_a_bill_issued_two_days_before_its_due_date_is_never_reminded(
    client, database, site, lease, bill_of
):
    bill_of(lease, 2, issued_before_due=2)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


@pytest.mark.parametrize(("due_in", "issued_before_due"), [(1, 2), (1, 1), (2, 0)])
def test_a_bill_issued_fewer_than_three_days_before_its_due_date_is_not_reminded_later(
    client, database, site, lease, bill_of, due_in, issued_before_due
):
    bill_of(lease, due_in, issued_before_due=issued_before_due)
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


@pytest.mark.parametrize(("due_in", "issued_before_due"), [(2, 3), (1, 3), (1, 10)])
def test_a_bill_issued_long_enough_before_is_reminded_by_a_later_run(
    client, database, site, lease, bill_of, due_in, issued_before_due
):
    bill_of(lease, due_in, issued_before_due=issued_before_due)
    assert send_reminders(database) == 1


def test_the_issue_date_is_read_in_the_jakarta_calendar(
    client, database, site, lease, bill_of
):
    due = day(1)
    # 05:00 in Jakarta two days before the due date is still the day before in UTC.
    created = datetime.combine(
        due - timedelta(days=2), datetime.min.time().replace(hour=5), tzinfo=JAKARTA
    ).astimezone(UTC)
    assert created.date() == due - timedelta(days=3)
    bill_of(lease, 1, created_at=created)
    assert send_reminders(database) == 0


def test_a_bill_issued_early_in_the_jakarta_day_three_days_before_is_reminded(
    client, database, site, lease, bill_of
):
    due = day(1)
    created = datetime.combine(
        due - timedelta(days=3), datetime.min.time().replace(minute=30), tzinfo=JAKARTA
    ).astimezone(UTC)
    bill_of(lease, 1, created_at=created)
    assert send_reminders(database) == 1


# Due-date reminders: once per bill


def test_a_second_run_sends_no_further_reminder(client, database, site, lease, bill_of):
    bill_of(lease, 3)
    assert send_reminders(database) == 1
    assert send_reminders(database) == 0
    assert len(rows_of(database, REMINDER)) == 1
    assert len(of_type(client, site.tenant_in, REMINDER)) == 1


def test_a_reminder_sent_three_days_ahead_is_not_repeated_on_the_following_day(
    client, database, site, lease, bill_of, make_rent_bill
):
    bill = bill_of(lease, 3)
    assert send_reminders(database) == 1
    with Session(database) as db:
        from app.models import RentBill

        db.get(RentBill, bill.id).due_date = day(2)
        db.commit()
    assert send_reminders(database) == 0
    assert len(rows_of(database, REMINDER)) == 1


def test_a_rejected_bill_is_reminded_once(client, database, site, lease, bill_of):
    bill_of(lease, 3, status="rejected")
    assert send_reminders(database) == 1
    assert send_reminders(database) == 0


def test_a_stored_reminder_of_the_bill_stops_the_next_one(
    client, database, site, lease, bill_of
):
    from app.schemas.notifications import NotificationRentBill, NotificationType
    from app.schemas.payments import PaymentStatus
    from app.services import notifications

    bill = bill_of(lease, 2)
    with Session(database) as db:
        notifications.notify(
            db,
            [site.tenant.user.id],
            NotificationType.DUE_DATE_REMINDER,
            site.prop.id,
            rent_bill=NotificationRentBill(
                rent_bill_id=bill.id,
                period_start=bill.period_start,
                period_end=bill.period_end,
                due_date=bill.due_date,
                amount=bill.amount,
                payment_status=PaymentStatus.UNPAID,
                payment_method=None,
                reason=None,
                days_overdue=0,
            ),
        )
        db.commit()
    assert send_reminders(database) == 0
    assert len(rows_of(database, REMINDER)) == 1


def test_a_reminder_of_another_bill_does_not_stop_this_one(
    client, database, site, lease, bill_of
):
    first = bill_of(lease, 3)
    assert send_reminders(database) == 1
    second = bill_of(lease, 2, period_start=first.period_end + timedelta(days=1))
    assert send_reminders(database) == 1
    shown = {
        i["rentBill"]["rentBillId"] for i in of_type(client, site.tenant_in, REMINDER)
    }
    assert shown == {str(first.id), str(second.id)}


def test_other_notifications_about_the_bill_do_not_stop_its_reminder(
    client, database, site, lease, bill_of
):
    from app.schemas.notifications import NotificationRentBill, NotificationType
    from app.schemas.payments import PaymentStatus
    from app.services import notifications

    bill = bill_of(lease, 3)
    with Session(database) as db:
        notifications.notify(
            db,
            [site.tenant.user.id],
            NotificationType.PAYMENT_STATUS_CHANGED,
            site.prop.id,
            rent_bill=NotificationRentBill(
                rent_bill_id=bill.id,
                period_start=bill.period_start,
                period_end=bill.period_end,
                due_date=bill.due_date,
                amount=bill.amount,
                payment_status=PaymentStatus.REJECTED,
                payment_method=None,
                reason="Blurry.",
                days_overdue=0,
            ),
        )
        db.commit()
    assert send_reminders(database) == 1


def test_every_qualifying_bill_is_counted_and_reminded(
    client, database, site, lease, bill_of, make_room, make_verified_tenant
):
    other = make_verified_tenant(make_room(site.prop, number="A2"), name="Sari")
    bill_of(lease, 3)
    bill_of(other.lease, 1)
    bill_of(other.lease, 20, period_start=day(-50))
    assert send_reminders(database) == 2
    assert len(rows_of(database, REMINDER)) == 2


def test_a_run_without_qualifying_bills_returns_zero(database, site):
    assert send_reminders(database) == 0
    assert stored_rows(database) == []


def test_the_reminder_job_flushes_but_does_not_commit(
    client, database, site, lease, bill_of
):
    from app.services import notifications

    bill_of(lease, 3)
    with Session(database) as db:
        assert notifications.send_due_date_reminders(db) == 1
        stored = db.execute(text("SELECT count(*) FROM notifications")).scalar_one()
        assert stored == 1
        assert stored_rows(database) == []
        db.rollback()
    assert stored_rows(database) == []
    assert send_reminders(database) == 1


# Overdue notices: when a bill qualifies


@pytest.mark.parametrize("days", [1, 2, 10, 90])
def test_a_bill_past_its_due_date_is_notified_with_the_days_overdue(
    client, database, site, lease, bill_of, days
):
    bill = bill_of(lease, -days)
    assert send_overdue(database) == 1
    (item,) = of_type(client, site.tenant_in, OVERDUE)
    assert_facts(item, bill, "unpaid", days)


@pytest.mark.parametrize("due_in", [0, 1, 3, 4])
def test_a_bill_not_yet_past_its_due_date_is_not_notified_as_overdue(
    client, database, site, lease, bill_of, due_in
):
    bill_of(lease, due_in)
    assert send_overdue(database) == 0
    assert stored_rows(database) == []


@pytest.mark.parametrize("status", ["unpaid", "rejected"])
def test_an_unpaid_or_rejected_overdue_bill_is_notified_with_its_status(
    client, database, site, lease, bill_of, status
):
    bill = bill_of(lease, -3, status=status)
    assert send_overdue(database) == 1
    (item,) = of_type(client, site.tenant_in, OVERDUE)
    assert_facts(item, bill, status, 3)


@pytest.mark.parametrize("status", ["awaitingVerification", "paid"])
def test_an_overdue_bill_awaiting_verification_or_paid_is_never_notified(
    client, database, site, lease, bill_of, status
):
    bill_of(lease, -3, status=status)
    assert send_overdue(database) == 0
    assert stored_rows(database) == []


def test_an_overdue_bill_of_an_ended_lease_is_never_notified(
    client, database, site, make_room, make_verified_tenant, bill_of
):
    ended = make_verified_tenant(
        make_room(site.prop, number="A2"), name="Old Tenant", lease_ended=True
    )
    bill_of(ended.lease, -3)
    assert send_overdue(database) == 0
    assert stored_rows(database) == []


def test_the_overdue_job_does_not_send_reminders_and_the_reminder_job_no_notices(
    client, database, site, lease, bill_of
):
    bill_of(lease, -2)
    bill_of(lease, 2, period_start=day(-100))
    assert send_overdue(database) == 1
    assert len(rows_of(database, OVERDUE)) == 3
    assert rows_of(database, REMINDER) == []
    assert send_reminders(database) == 1
    assert len(rows_of(database, OVERDUE)) == 3
    assert len(rows_of(database, REMINDER)) == 1


# Overdue notices: who is told


def test_an_overdue_notice_goes_to_the_tenant_the_owner_and_the_assigned_manager(
    client, database, site, lease, bill_of
):
    bill = bill_of(lease, -4)
    assert send_overdue(database) == 1
    for who in ("tenant_in", "owner_in", "manager_in"):
        (item,) = of_type(client, getattr(site, who), OVERDUE)
        assert_facts(item, bill, "unpaid", 4)
        assert len(items(client, getattr(site, who))) == 1
    assert len(stored_rows(database)) == 3


def test_the_notice_for_management_names_the_tenant_the_room_and_the_property(
    client, database, site, lease, bill_of
):
    bill_of(lease, -4)
    send_overdue(database)
    for who in ("owner_in", "manager_in"):
        (item,) = of_type(client, getattr(site, who), OVERDUE)
        assert item["tenant"] == {
            "id": str(site.tenant.user.id),
            "name": "Budi Tenant",
        }
        assert item["room"] == {"id": str(site.room.id), "number": "A1"}
        assert item["property"] == {"id": str(site.prop.id), "name": "Kos Melati"}
        assert item["actorName"] is None


def test_the_notice_for_the_tenant_carries_the_room_and_the_property(
    client, database, site, lease, bill_of
):
    bill_of(lease, -4)
    send_overdue(database)
    (item,) = of_type(client, site.tenant_in, OVERDUE)
    assert item["room"] == {"id": str(site.room.id), "number": "A1"}
    assert item["property"] == {"id": str(site.prop.id), "name": "Kos Melati"}


def test_an_overdue_notice_is_stored_with_the_property_of_the_bill(
    client, database, site, lease, bill_of
):
    bill_of(lease, -1)
    send_overdue(database)
    rows = rows_of(database, OVERDUE)
    assert {row["recipient_id"] for row in rows} == {
        site.tenant.user.id,
        site.owner.id,
        site.manager.id,
    }
    assert {row["property_id"] for row in rows} == {site.prop.id}


def test_every_assigned_manager_is_told(
    client, database, site, lease, bill_of, make_user, assign_manager, sign_in
):
    from notification_support import role

    colleague = make_user(name="Colleague", role=role("manager"))
    assign_manager(colleague, site.prop)
    bill_of(lease, -2)
    send_overdue(database)
    assert len(of_type(client, sign_in(colleague), OVERDUE)) == 1
    assert len(stored_rows(database)) == 4


def test_a_manager_no_longer_assigned_is_not_told(
    client, database, site, lease, bill_of
):
    unassign(database, site.manager, site.prop)
    bill_of(lease, -2)
    assert send_overdue(database) == 1
    assert stored_for(database, site.manager) == []
    assert len(stored_for(database, site.owner)) == 1
    assert len(stored_for(database, site.tenant.user)) == 1


def test_a_manager_of_another_property_is_not_told(
    client, database, site, lease, bill_of, make_user, make_property, assign_manager
):
    from notification_support import role

    outsider = make_user(name="Outside Manager", role=role("manager"))
    assign_manager(outsider, make_property(site.owner, name="Kos Kedua"))
    bill_of(lease, -2)
    send_overdue(database)
    assert stored_for(database, outsider) == []


def test_another_owner_is_not_told(client, database, site, lease, bill_of, make_user):
    stranger = make_user(name="Other Owner")
    bill_of(lease, -2)
    send_overdue(database)
    assert stored_for(database, stranger) == []


def test_a_tenant_of_another_room_is_not_told(
    client, database, site, lease, bill_of, make_room, make_verified_tenant
):
    neighbour = make_verified_tenant(make_room(site.prop, number="A2"), name="Sari")
    bill_of(lease, -2)
    send_overdue(database)
    assert stored_for(database, neighbour.user) == []


# Overdue notices: once per bill


def test_a_second_run_sends_no_further_overdue_notice(
    client, database, site, lease, bill_of
):
    bill_of(lease, -1)
    assert send_overdue(database) == 1
    assert send_overdue(database) == 0
    assert len(rows_of(database, OVERDUE)) == 3


def test_the_notice_is_not_repeated_on_later_days(
    client, database, site, lease, bill_of
):
    from app.models import RentBill

    bill = bill_of(lease, -1)
    assert send_overdue(database) == 1
    with Session(database) as db:
        db.get(RentBill, bill.id).due_date = day(-5)
        db.commit()
    assert send_overdue(database) == 0
    (item,) = of_type(client, site.tenant_in, OVERDUE)
    assert item["rentBill"]["daysOverdue"] == 1


def test_another_overdue_bill_of_the_same_tenant_gets_its_own_notice(
    client, database, site, lease, bill_of
):
    first = bill_of(lease, -1)
    assert send_overdue(database) == 1
    second = bill_of(lease, -8, period_start=day(-120))
    assert send_overdue(database) == 1
    shown = {
        i["rentBill"]["rentBillId"]: i["rentBill"]["daysOverdue"]
        for i in of_type(client, site.tenant_in, OVERDUE)
    }
    assert shown == {str(first.id): 1, str(second.id): 8}


def test_two_overdue_bills_are_counted_as_two(client, database, site, lease, bill_of):
    bill_of(lease, -1)
    bill_of(lease, -8, period_start=day(-120))
    assert send_overdue(database) == 2
    assert len(rows_of(database, OVERDUE)) == 6


def test_a_stored_notice_of_the_bill_stops_the_next_one(
    client, database, site, lease, bill_of
):
    from app.schemas.notifications import NotificationRentBill, NotificationType
    from app.schemas.payments import PaymentStatus
    from app.services import notifications

    bill = bill_of(lease, -3)
    with Session(database) as db:
        notifications.notify(
            db,
            [site.tenant.user.id],
            NotificationType.BILL_OVERDUE,
            site.prop.id,
            rent_bill=NotificationRentBill(
                rent_bill_id=bill.id,
                period_start=bill.period_start,
                period_end=bill.period_end,
                due_date=bill.due_date,
                amount=bill.amount,
                payment_status=PaymentStatus.UNPAID,
                payment_method=None,
                reason=None,
                days_overdue=1,
            ),
        )
        db.commit()
    assert send_overdue(database) == 0
    assert len(rows_of(database, OVERDUE)) == 1


def test_a_reminder_of_the_bill_does_not_stop_its_overdue_notice(
    client, database, site, lease, bill_of
):
    from app.models import RentBill

    bill = bill_of(lease, 2)
    assert send_reminders(database) == 1
    with Session(database) as db:
        db.get(RentBill, bill.id).due_date = day(-1)
        db.commit()
    assert send_overdue(database) == 1
    assert len(rows_of(database, REMINDER)) == 1
    assert len(rows_of(database, OVERDUE)) == 3


def test_the_overdue_job_flushes_but_does_not_commit(
    client, database, site, lease, bill_of
):
    from app.services import notifications

    bill_of(lease, -2)
    with Session(database) as db:
        assert notifications.send_overdue_notices(db) == 1
        stored = db.execute(text("SELECT count(*) FROM notifications")).scalar_one()
        assert stored == 3
        assert stored_rows(database) == []
        db.rollback()
    assert stored_rows(database) == []
    assert send_overdue(database) == 1


def test_a_run_without_overdue_bills_returns_zero(database, site):
    assert send_overdue(database) == 0
    assert stored_rows(database) == []


# Push


def test_a_reminder_is_pushed_to_the_tenant_only(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    bill_of(lease, 3)
    send_reminders(database)
    assert pushes.tokens() == [tokens["tenant"]]
    (sent,) = pushes.to(tokens["tenant"])
    (listed,) = of_type(client, site.tenant_in, REMINDER)
    assert dump(sent) == listed


def test_an_overdue_notice_is_pushed_to_the_tenant_the_owner_and_the_manager(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    bill_of(lease, -2)
    send_overdue(database)
    assert sorted(pushes.tokens()) == sorted(tokens.values())
    for who in ("tenant", "owner", "manager"):
        (sent,) = pushes.to(tokens[who])
        (listed,) = of_type(client, getattr(site, f"{who}_in"), OVERDUE)
        assert dump(sent) == listed


def test_a_run_that_sends_nothing_pushes_nothing(
    client, database, site, lease, bill_of, pushes
):
    give_devices(database, site)
    bill_of(lease, 3)
    bill_of(lease, -2, period_start=day(-100))
    send_reminders(database)
    send_overdue(database)
    before = len(pushes.attempts)
    send_reminders(database)
    send_overdue(database)
    assert len(pushes.attempts) == before


def test_a_reminder_with_the_billing_category_off_is_stored_but_not_pushed(
    client, database, site, lease, bill_of, pushes
):
    give_devices(database, site)
    save_off(client, site.tenant_in, "tenant", "billing")
    bill_of(lease, 3)
    assert send_reminders(database) == 1
    assert pushes.attempts == []
    assert len(of_type(client, site.tenant_in, REMINDER)) == 1


def test_the_tenants_overdue_notice_follows_the_billing_category(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    save_off(client, site.tenant_in, "tenant", "billing")
    bill_of(lease, -2)
    send_overdue(database)
    assert sorted(pushes.tokens()) == sorted([tokens["owner"], tokens["manager"]])
    assert len(of_type(client, site.tenant_in, OVERDUE)) == 1


def test_the_management_overdue_notice_follows_the_overdue_bill_category(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    save_off(client, site.owner_in, "owner", "overdueBill")
    bill_of(lease, -2)
    send_overdue(database)
    assert sorted(pushes.tokens()) == sorted([tokens["tenant"], tokens["manager"]])
    assert len(of_type(client, site.owner_in, OVERDUE)) == 1


def test_only_the_overdue_bill_category_gates_the_management_push(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    save_off(
        client,
        site.manager_in,
        "manager",
        "newComplaint",
        "receiptUpload",
        "accountActivity",
    )
    bill_of(lease, -2)
    send_overdue(database)
    assert tokens["manager"] in pushes.tokens()


def test_the_billing_category_does_not_gate_the_management_push(
    client, database, site, lease, bill_of, pushes
):
    tokens = give_devices(database, site)
    save_off(client, site.owner_in, "owner", "receiptUpload")
    bill_of(lease, -2)
    send_overdue(database)
    assert tokens["owner"] in pushes.tokens()


def test_pushes_are_sent_only_after_the_commit(
    client, database, site, lease, bill_of, pushes
):
    from app.services import notifications

    tokens = give_devices(database, site)
    committed: list[set[str]] = []
    pushes.before_send = lambda token, notification: committed.append(
        {str(row["id"]) for row in stored_rows(database)}
    )
    bill_of(lease, 3)
    bill_of(lease, -2, period_start=day(-100))
    with Session(database) as db:
        assert notifications.send_due_date_reminders(db) == 1
        assert notifications.send_overdue_notices(db) == 1
        db.flush()
        assert pushes.attempts == []
        db.commit()
    assert len(pushes.attempts) == 4
    assert tokens["tenant"] in pushes.tokens()
    for ids, (_, notification) in zip(committed, pushes.attempts, strict=True):
        assert str(notification.id) in ids


def test_a_rolled_back_run_pushes_nothing(
    client, database, site, lease, bill_of, pushes
):
    from app.services import notifications

    give_devices(database, site)
    bill_of(lease, -2)
    with Session(database) as db:
        notifications.send_overdue_notices(db)
        db.rollback()
    assert pushes.attempts == []
    assert stored_rows(database) == []


def test_a_failing_sender_does_not_lose_the_notices(
    client, database, site, lease, bill_of, pushes
):
    give_devices(database, site)
    pushes.fail_all = True
    bill_of(lease, -2)
    assert send_overdue(database) == 1
    assert len(pushes.attempts) == 3
    assert len(rows_of(database, OVERDUE)) == 3


# The daily job list


def test_the_notification_jobs_follow_the_session_cleanup_in_the_daily_jobs():
    from app.services import notifications
    from app.services.jobs import DAILY_JOBS
    from app.services.sessions import end_expired_sessions

    names = [job.__name__ for job in DAILY_JOBS]
    assert names.index("send_due_date_reminders") > names.index(
        end_expired_sessions.__name__
    )
    assert (
        names.index("send_overdue_notices")
        == names.index("send_due_date_reminders") + 1
    )
    assert notifications.send_due_date_reminders in DAILY_JOBS
    assert notifications.send_overdue_notices in DAILY_JOBS
    assert len(names) == len(set(names))


def test_running_the_daily_jobs_stores_and_commits_the_notifications(
    client, database, site, lease, bill_of
):
    from app.services.jobs import run_daily_jobs

    due_soon = bill_of(lease, 2)
    overdue = bill_of(lease, -3, period_start=day(-100))
    assert run_daily_jobs() == []
    reminders = of_type(client, site.tenant_in, REMINDER)
    notices = of_type(client, site.tenant_in, OVERDUE)
    assert [i["rentBill"]["rentBillId"] for i in reminders] == [str(due_soon.id)]
    assert [i["rentBill"]["rentBillId"] for i in notices] == [str(overdue.id)]
    assert len(of_type(client, site.owner_in, OVERDUE)) == 1
    assert len(of_type(client, site.manager_in, OVERDUE)) == 1


def test_running_the_daily_jobs_twice_notifies_once(
    client, database, site, lease, bill_of
):
    from app.services.jobs import run_daily_jobs

    bill_of(lease, 2)
    bill_of(lease, -3, period_start=day(-100))
    assert run_daily_jobs() == []
    assert run_daily_jobs() == []
    assert len(rows_of(database, REMINDER)) == 1
    assert len(rows_of(database, OVERDUE)) == 3


def test_running_the_daily_jobs_pushes_after_the_commit(
    client, database, site, lease, bill_of, pushes
):
    from app.services.jobs import run_daily_jobs

    tokens = give_devices(database, site)
    bill_of(lease, -3)
    assert run_daily_jobs() == []
    assert sorted(pushes.tokens()) == sorted(tokens.values())
