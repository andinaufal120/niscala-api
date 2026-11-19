"""Scenarios of the data of a deleted Owner, kept for a while and then purged."""

import pytest
from owner_purge_support import delete_at, whole_database
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from e2e.e2e_subscription import last_token, notify_play
from e2e.e2e_world import JOBS_PATH

OTHER_EMAIL = "other.owner@example.com"
PAST = 91
WITHIN = 89


@pytest.fixture(autouse=True)
def stored_files(stubs, monkeypatch):
    """Give the purge the stub file store the scenario's uploads go to."""
    monkeypatch.setattr("app.services.owner_purge.get_file_store", lambda: stubs.files)


def count(database, model, *conditions) -> int:
    with Session(database) as db:
        return db.scalar(select(func.count()).select_from(model).where(*conditions))


def delete_owner(world, seeded_world) -> None:
    """End every lease, stop the renewal and delete the Owner through an Admin."""
    owner = seeded_world.owner
    for prop in (seeded_world.melati, seeded_world.anggrek):
        for tenant in owner.tenants(prop):
            owner.delete(f"/tenants/{tenant['id']}", expect=204)
    token = last_token(world)
    world.stubs.play.change(token, state="CANCELED", auto_renewing=False)
    assert notify_play(world, token).status_code == 204
    world.admin().delete(f"/user-accounts/{owner.user_id}", expect=204)


def test_a_deleted_owner_keeps_its_history_until_ninety_days_and_then_loses_it(
    seeded_world, world, database, rtdn
):
    from app.models import (
        Complaint,
        Manager,
        Property,
        RentBill,
        RentBillReceipt,
        Room,
        Subscription,
        SubscriptionOrder,
        Tenant,
        UserAccount,
        UserSession,
    )

    owner = seeded_world.owner
    budi = seeded_world.budi
    budi.upload_receipt(budi.rent_bills()[0])
    other = world.owner_signs_up(email=OTHER_EMAIL, name="Other Owner")
    other_property = other.add_property("Kos Other", address="Jl. Lain 1")
    other.add_room(other_property, "Z1")
    world.stubs.assert_files_stored(1)
    delete_owner(world, seeded_world)
    orders = count(
        database, SubscriptionOrder, SubscriptionOrder.owner_id == owner.user_id
    )
    assert orders >= 1

    world.clock.run_daily_jobs()
    delete_at(database, owner.namespace, WITHIN)
    world.clock.run_daily_jobs()

    owned = Property.owner_id == owner.user_id
    assert count(database, Property, owned) == 2
    assert count(database, RentBillReceipt) == 1
    assert count(database, Subscription, Subscription.owner_id == owner.user_id) == 1
    world.stubs.assert_files_stored(1)

    delete_at(database, owner.namespace, PAST)
    world.clock.run_daily_jobs()

    assert count(database, Property, owned) == 0
    assert count(database, Manager, Manager.owner_id == owner.user_id) == 0
    assert count(database, Subscription, Subscription.owner_id == owner.user_id) == 0
    assert count(database, RentBillReceipt) == 0
    assert count(database, Complaint) == 0
    assert count(database, Tenant) == 0
    assert count(database, RentBill) == 0
    assert count(database, Room) == 1
    assert count(database, Property) == 1
    world.stubs.assert_files_stored(0)
    assert (
        count(database, SubscriptionOrder, SubscriptionOrder.owner_id == owner.user_id)
        == orders
    )
    assert count(database, UserAccount, UserAccount.id == owner.user_id) == 1
    assert count(database, UserSession, UserSession.user_id == owner.user_id) >= 1
    assert [p["name"] for p in other.properties()] == ["Kos Other"]
    assert [r["number"] for r in other.rooms(other_property)] == ["Z1"]


def test_the_manager_account_survives_the_purge_of_its_owner(
    seeded_world, world, database, rtdn
):
    from app.models import Manager, UserAccount

    manager = seeded_world.manager
    delete_owner(world, seeded_world)
    delete_at(database, seeded_world.owner.namespace, PAST)

    world.clock.run_daily_jobs()

    assert count(database, Manager, Manager.user_id == manager.user_id) == 0
    assert count(database, UserAccount, UserAccount.id == manager.user_id) == 1
    back = world.login(manager.email)
    assert back.properties() == []


def test_running_the_jobs_again_after_the_purge_is_harmless(
    seeded_world, world, database, rtdn
):
    delete_owner(world, seeded_world)
    delete_at(database, seeded_world.owner.namespace, PAST)
    world.clock.run_daily_jobs()
    after_first = whole_database(database)

    world.clock.run_daily_jobs()

    assert whole_database(database) == after_first


def test_a_failed_purge_changes_nothing_and_is_retried_by_the_next_run(
    seeded_world, world, database, client, jobs_secret, rtdn
):
    from app.db import get_engine
    from app.models import Property

    owner = seeded_world.owner
    delete_owner(world, seeded_world)
    delete_at(database, owner.namespace, PAST)
    before = whole_database(database)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE FROM PROPERTIES"):
            raise RuntimeError("database failure")

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = client.post(
            JOBS_PATH, headers={"Authorization": f"Bearer {jobs_secret}"}
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert response.json()["code"] == "JOBS_FAILED"
    assert whole_database(database) == before
    assert count(database, Property, Property.owner_id == owner.user_id) == 2

    world.clock.run_daily_jobs()

    assert count(database, Property, Property.owner_id == owner.user_id) == 0
