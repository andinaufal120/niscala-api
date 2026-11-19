"""The daily purge of the data of an Owner whose account was deleted long ago."""

from datetime import timedelta

import pytest
from account_erasure_support import session_state
from owner_purge_support import (
    KEPT_TABLES,
    build_owner_graph,
    delete_at,
    fixtures,
    purge,
    rows_mentioning,
    table_rows,
    whole_database,
)
from sqlalchemy import event
from sqlalchemy.orm import Session
from user_account_support import rows_of

JOBS_URL = "/internal/jobs/daily"
SECRET = "purge-secret-0123456789abcdef"
PAST = 91
WITHIN = 89


@pytest.fixture(autouse=True)
def store(file_store, monkeypatch):
    """Give the purge the in-memory file store."""
    monkeypatch.setattr("app.services.owner_purge.get_file_store", lambda: file_store)
    return file_store


@pytest.fixture
def graph(
    database,
    file_store,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    make_rent_bill,
    make_complaint,
    sign_in,
    subscribe_owner,
):
    """Build an owner graph; pass `share` to reuse the accounts of another graph."""
    fx = fixtures(
        database=database,
        file_store=file_store,
        make_user=make_user,
        make_property=make_property,
        make_room=make_room,
        make_verified_tenant=make_verified_tenant,
        make_manager=make_manager,
        make_rent_bill=make_rent_bill,
        make_complaint=make_complaint,
        sign_in=sign_in,
        subscribe_owner=subscribe_owner,
    )

    def build(email="rina@example.com", name="Rina Owner", share=None):
        return build_owner_graph(fx, email=email, name=name, share=share)

    return build


@pytest.fixture
def jobs_secret(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("JOBS_SECRET", SECRET)
    get_settings.cache_clear()
    yield {"Authorization": f"Bearer {SECRET}"}
    get_settings.cache_clear()


def leftovers(database, graph):
    return rows_mentioning(database, graph.ids, skip=KEPT_TABLES)


def user_row(database, user):
    from app.models import UserAccount

    return table_rows(database, UserAccount, UserAccount.id == user.id)


def only_purge_job(monkeypatch):
    from app.services.owner_purge import purge_deleted_owners

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [purge_deleted_owners])


class DeleteFailure:
    """Make the statement deleting properties fail, to break the purge mid-way."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.active = True

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        if self.active and statement.lstrip().upper().startswith(
            "DELETE FROM PROPERTIES"
        ):
            raise RuntimeError("database failure")

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self)


# The retention period and the selector


def test_the_retention_period_is_ninety_days():
    from app.services.owner_purge import OWNER_RETENTION

    assert timedelta(days=90) == OWNER_RETENTION


def test_an_owner_deleted_for_more_than_ninety_days_loses_every_record(database, graph):
    owner = graph()
    delete_at(database, owner.owner, PAST)
    assert leftovers(database, owner)

    purge(database)

    assert leftovers(database, owner) == {}


def test_an_owner_deleted_for_less_than_ninety_days_keeps_everything(
    database, graph, file_store
):
    owner = graph()
    delete_at(database, owner.owner, WITHIN)
    before = whole_database(database)
    keys = set(file_store.keys)

    purge(database)

    assert whole_database(database) == before
    assert file_store.keys == keys
    assert file_store.deleted() == []


def test_the_ninety_days_run_from_the_deletion_time_of_the_account(database, graph):
    owner = graph()
    delete_at(database, owner.owner, WITHIN)
    purge(database)
    assert leftovers(database, owner)

    delete_at(database, owner.owner, PAST)
    purge(database)

    assert leftovers(database, owner) == {}


def test_a_live_owner_is_never_purged(database, graph, file_store):
    graph()
    before = whole_database(database)

    purge(database)

    assert whole_database(database) == before
    assert file_store.deleted() == []


@pytest.mark.parametrize("role", ["tenant", "manager", "admin"])
def test_accounts_of_other_roles_deleted_long_ago_are_never_purged(
    database, make_user, make_property, make_room, role
):
    from app.models import Property, Room
    from app.schemas.auth import UserRole

    user = make_user(role=UserRole(role), email=f"{role}@example.com")
    prop = make_property(user)
    room = make_room(prop)
    delete_at(database, user, 400)

    purge(database)

    assert len(rows_of(database, Property, Property.id == prop.id)) == 1
    assert len(rows_of(database, Room, Room.id == room.id)) == 1


def test_a_deleted_tenant_account_leaves_its_record_at_a_live_owner(database, graph):
    from app.models import Lease, Tenant

    owner = graph()
    delete_at(database, owner.tenant.user, 400)

    purge(database)

    assert len(rows_of(database, Tenant, Tenant.id == owner.tenant.id)) == 1
    assert len(rows_of(database, Lease, Lease.id == owner.tenant.lease.id)) == 1


def test_a_deleted_manager_account_leaves_its_record_at_a_live_owner(database, graph):
    from app.models import Manager

    owner = graph()
    delete_at(database, owner.manager.user, 400)

    purge(database)

    assert len(rows_of(database, Manager, Manager.id == owner.manager.id)) == 1


def test_only_owners_past_the_retention_are_purged_among_several(database, graph):
    old = graph(email="old@example.com")
    recent = graph(email="recent@example.com")
    live = graph(email="live@example.com")
    delete_at(database, old.owner, 120)
    delete_at(database, recent.owner, 30)
    recent_before = rows_mentioning(database, recent.ids)
    live_before = rows_mentioning(database, live.ids)

    purge(database)

    assert leftovers(database, old) == {}
    assert rows_mentioning(database, recent.ids) == recent_before
    assert rows_mentioning(database, live.ids) == live_before


def test_every_owner_past_the_retention_is_purged_in_one_run(database, graph):
    first = graph(email="first@example.com")
    second = graph(email="second@example.com")
    delete_at(database, first.owner, 100)
    delete_at(database, second.owner, 500)

    purge(database)

    assert leftovers(database, first) == {}
    assert leftovers(database, second) == {}


@pytest.mark.parametrize("left", ["property", "manager", "subscription"])
def test_an_owner_with_only_one_kind_of_record_left_is_still_purged(
    database, make_user, make_property, make_manager, subscribe_owner, left
):
    from app.models import Manager, Property, Subscription

    owner = make_user()
    if left == "property":
        stored = make_property(owner)
        model, key = Property, stored.id
    elif left == "manager":
        stored = make_manager(owner, activated=True).record
        model, key = Manager, stored.id
    else:
        subscribe_owner(owner)
        model, key = Subscription, owner.id
    delete_at(database, owner, PAST)
    assert rows_of(database, model, model.__mapper__.primary_key[0] == key)

    purge(database)

    assert rows_of(database, model, model.__mapper__.primary_key[0] == key) == []


def test_an_owner_with_nothing_left_is_a_no_op(
    database, make_user, file_store, make_property
):
    owner = make_user()
    delete_at(database, owner, PAST)
    other = make_user(email="other@example.com")
    make_property(other)
    before = whole_database(database)

    purge(database)

    assert whole_database(database) == before
    assert file_store.calls == []


# What is deleted and what stays


DELETED_MODELS = [
    "Property",
    "Room",
    "Lease",
    "Tenant",
    "EmergencyContact",
    "Invitation",
    "Manager",
    "ManagerAssignment",
    "RentBill",
    "RentBillStatusChange",
    "RentBillReceipt",
    "Complaint",
    "ComplaintStatusChange",
    "ComplaintPhoto",
    "PaymentPatternSummary",
    "Notification",
    "Subscription",
    "ScheduledDowngrade",
    "NotificationSetting",
]


@pytest.mark.parametrize("name", DELETED_MODELS)
def test_the_purge_deletes_every_row_of_a_table_the_owner_owns(database, graph, name):
    from app import models

    table = getattr(models, name).__table__
    owner = graph()
    delete_at(database, owner.owner, PAST)
    assert table.name in leftovers(database, owner)

    purge(database)

    assert table.name not in leftovers(database, owner)


def test_the_purge_deletes_the_archived_and_ended_records_too(database, graph):
    from app.models import Lease, Property, Room, Tenant

    owner = graph()
    delete_at(database, owner.owner, PAST)

    purge(database)

    assert rows_of(database, Property, Property.id == owner.archived_prop.id) == []
    assert rows_of(database, Room, Room.id == owner.archived_room.id) == []
    assert rows_of(database, Tenant, Tenant.id == owner.former_tenant.id) == []
    assert rows_of(database, Lease, Lease.id == owner.former_tenant.lease.id) == []


def test_the_purge_deletes_the_notifications_about_the_properties_of_every_recipient(
    database, graph
):
    from app.models import Notification

    owner = graph()
    delete_at(database, owner.owner, PAST)

    purge(database)

    remaining = {
        row.id for row in rows_of(database, Notification, Notification.id.is_not(None))
    }
    assert remaining.isdisjoint(owner.notification_ids)
    assert remaining == {owner.unrelated_notification_id}


def test_the_purge_keeps_the_account_row_of_the_owner_unchanged(database, graph):
    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = user_row(database, owner.owner)

    purge(database)

    assert user_row(database, owner.owner) == before


def test_the_purge_keeps_the_subscription_orders(database, graph):
    from app.models import SubscriptionOrder

    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = table_rows(database, SubscriptionOrder)
    assert len(before) == 2

    purge(database)

    assert table_rows(database, SubscriptionOrder) == before


def test_the_purge_keeps_the_sessions_of_the_owner(database, graph):
    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = session_state(database, owner.owner.id)
    assert before

    purge(database)

    assert session_state(database, owner.owner.id) == before


def test_the_tenant_and_manager_accounts_of_the_owner_are_kept(database, graph):
    from app.models import Notification, NotificationSetting

    owner = graph()
    delete_at(database, owner.owner, PAST)
    tenant_before = user_row(database, owner.tenant.user)
    manager_before = user_row(database, owner.manager.user)
    tenant_sessions = session_state(database, owner.tenant.user.id)
    manager_sessions = session_state(database, owner.manager.user.id)

    purge(database)

    assert user_row(database, owner.tenant.user) == tenant_before
    assert user_row(database, owner.manager.user) == manager_before
    assert session_state(database, owner.tenant.user.id) == tenant_sessions
    assert session_state(database, owner.manager.user.id) == manager_sessions
    assert all(row[1] is None for row in tenant_sessions + manager_sessions)
    settings = rows_of(
        database,
        NotificationSetting,
        NotificationSetting.user_id == owner.tenant.user.id,
    )
    assert len(settings) == 1
    kept = rows_of(
        database,
        Notification,
        Notification.recipient_id == owner.tenant.user.id,
    )
    assert [row.id for row in kept] == [owner.unrelated_notification_id]


def test_the_records_of_another_owner_are_untouched(database, graph, file_store):
    purged = graph(email="gone@example.com")
    other = graph(email="other@example.com")
    delete_at(database, purged.owner, PAST)
    other_rows = rows_mentioning(database, other.ids)
    assert other_rows

    purge(database)

    assert rows_mentioning(database, other.ids) == other_rows
    assert other.keys <= file_store.keys


def test_accounts_with_records_at_two_owners_keep_the_other_records(
    database, graph, file_store
):
    from app.models import Notification, Tenant

    purged = graph(email="gone@example.com")
    other = graph(email="other@example.com", share=purged)
    assert other.tenant.user.id == purged.tenant.user.id
    assert other.manager.user.id == purged.manager.user.id
    delete_at(database, purged.owner, PAST)
    other_rows = rows_mentioning(database, other.ids)
    tenant_user = user_row(database, purged.tenant.user)
    manager_user = user_row(database, purged.manager.user)
    tenant_sessions = session_state(database, purged.tenant.user.id)
    manager_sessions = session_state(database, purged.manager.user.id)

    purge(database)

    assert leftovers(database, purged) == {}
    assert rows_mentioning(database, other.ids) == other_rows
    assert len(rows_of(database, Tenant, Tenant.id == other.tenant.id)) == 1
    assert user_row(database, purged.tenant.user) == tenant_user
    assert user_row(database, purged.manager.user) == manager_user
    assert session_state(database, purged.tenant.user.id) == tenant_sessions
    assert session_state(database, purged.manager.user.id) == manager_sessions
    about_other = rows_of(
        database,
        Notification,
        Notification.property_id == other.prop.id,
    )
    assert {row.recipient_id for row in about_other} == {
        other.owner.id,
        other.tenant.user.id,
        other.manager.user.id,
    }
    assert other.keys <= file_store.keys


# Stored files


def test_the_stored_files_are_deleted_after_the_commit(database, graph, file_store):
    from app.services.owner_purge import purge_deleted_owners

    owner = graph()
    other = graph(email="other@example.com")
    delete_at(database, owner.owner, PAST)
    file_store.put("unrelated/file", b"x", "text/plain")

    with Session(database) as db:
        purge_deleted_owners(db)
        assert owner.keys <= file_store.keys
        assert file_store.deleted() == []
        db.commit()

    assert owner.keys.isdisjoint(file_store.keys)
    assert sorted(file_store.deleted()) == sorted(owner.keys)
    assert other.keys <= file_store.keys
    assert "unrelated/file" in file_store.keys


def test_the_job_does_not_commit(database, graph):
    from app.services.owner_purge import purge_deleted_owners

    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = rows_mentioning(database, owner.ids)

    with Session(database) as db:
        purge_deleted_owners(db)
        assert rows_mentioning(database, owner.ids) == before
        db.rollback()

    assert rows_mentioning(database, owner.ids) == before


def test_the_stored_files_stay_when_the_job_rolls_back(database, graph, file_store):
    from app.services.owner_purge import purge_deleted_owners

    owner = graph()
    delete_at(database, owner.owner, PAST)

    with Session(database) as db:
        purge_deleted_owners(db)
        db.rollback()

    assert owner.keys <= file_store.keys
    assert file_store.deleted() == []


def test_a_failing_file_deletion_does_not_break_the_purge(database, graph, file_store):
    owner = graph()
    delete_at(database, owner.owner, PAST)
    file_store.fail_on_delete = True

    purge(database)

    assert leftovers(database, owner) == {}
    assert sorted(file_store.deleted()) == sorted(owner.keys)


def test_a_failing_file_deletion_does_not_fail_the_daily_run(
    database, graph, file_store, monkeypatch
):
    from app.services.jobs import run_daily_jobs

    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, PAST)
    file_store.fail_on_delete = True

    assert run_daily_jobs() == []
    assert leftovers(database, owner) == {}


# Failure and repetition


def test_a_failure_in_the_middle_leaves_everything_in_place(
    database, graph, file_store, monkeypatch
):
    from app.db import get_engine
    from app.services.jobs import run_daily_jobs

    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = whole_database(database)
    keys = set(file_store.keys)

    with DeleteFailure(get_engine()):
        failed = run_daily_jobs()

    assert failed == ["purge_deleted_owners"]
    assert whole_database(database) == before
    assert file_store.keys == keys
    assert file_store.deleted() == []


def test_the_purge_is_tried_again_the_next_run_after_a_failure(
    database, graph, monkeypatch
):
    from app.db import get_engine
    from app.services.jobs import run_daily_jobs

    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, PAST)
    with DeleteFailure(get_engine()):
        assert run_daily_jobs() == ["purge_deleted_owners"]

    assert run_daily_jobs() == []

    assert leftovers(database, owner) == {}


def test_a_second_run_changes_nothing(database, graph, file_store):
    owner = graph()
    graph(email="other@example.com")
    delete_at(database, owner.owner, PAST)
    purge(database)
    after_first = whole_database(database)
    calls = list(file_store.calls)

    purge(database)

    assert whole_database(database) == after_first
    assert file_store.calls == calls


# The daily run


def test_the_default_daily_run_purges_the_deleted_owner(database, graph, file_store):
    from app.services.jobs import run_daily_jobs

    owner = graph()
    other = graph(email="other@example.com")
    delete_at(database, owner.owner, PAST)

    assert run_daily_jobs() == []

    assert leftovers(database, owner) == {}
    assert owner.keys.isdisjoint(file_store.keys)
    assert other.keys <= file_store.keys


def test_the_daily_endpoint_purges_the_deleted_owner(
    client, database, graph, jobs_secret, monkeypatch, file_store
):
    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, PAST)

    response = client.post(JOBS_URL, headers=jobs_secret)

    assert response.status_code == 204
    assert leftovers(database, owner) == {}
    assert owner.keys.isdisjoint(file_store.keys)


def test_the_daily_endpoint_answers_500_and_deletes_nothing_when_the_purge_fails(
    client, database, graph, jobs_secret, monkeypatch, file_store
):
    from app.db import get_engine

    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, PAST)
    before = whole_database(database)

    with DeleteFailure(get_engine()):
        response = client.post(JOBS_URL, headers=jobs_secret)

    assert response.status_code == 500
    assert response.json()["code"] == "JOBS_FAILED"
    assert whole_database(database) == before
    assert file_store.deleted() == []


def test_the_daily_endpoint_does_not_purge_an_owner_within_the_retention(
    client, database, graph, jobs_secret, monkeypatch
):
    only_purge_job(monkeypatch)
    owner = graph()
    delete_at(database, owner.owner, WITHIN)
    before = whole_database(database)

    response = client.post(JOBS_URL, headers=jobs_secret)

    assert response.status_code == 204
    assert whole_database(database) == before


def test_an_owner_deleted_just_now_is_not_purged(database, graph):
    owner = graph()
    delete_at(database, owner.owner, 0)
    before = rows_mentioning(database, owner.ids)

    purge(database)

    assert rows_mentioning(database, owner.ids) == before
