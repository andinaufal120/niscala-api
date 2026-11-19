"""Helpers for the tests of the purge of a deleted Owner's data."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from account_erasure_support import add_payment_summary, ago, seed_history
from sqlalchemy import select
from sqlalchemy.orm import Session
from user_account_support import rows_of, set_columns

# Tables the purge keeps for the Owner: the erased account row, the purchase
# records and the sessions.
KEPT_TABLES = frozenset(
    {"user_accounts", "subscription_orders", "sessions", "used_refresh_tokens"}
)


@dataclass
class Graph:
    """Everything one Owner account owns, with the accounts around it.

    `ids` holds the ids of the records and rows the purge must delete. The
    tenant and manager accounts are listed apart because an account can
    belong to the graphs of two Owners.
    """

    owner: Any
    owner_in: Any
    prop: Any
    room: Any
    vacant_room: Any
    archived_prop: Any
    archived_room: Any
    tenant: Any
    former_tenant: Any
    tenant_in: Any
    manager: Any
    manager_in: Any
    history: Any
    receipt_key: str
    notification_ids: list[UUID]
    unrelated_notification_id: UUID
    order_ids: list[UUID]
    ids: list[UUID] = field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return {self.receipt_key, self.history.photo_key}


def fixtures(**named) -> SimpleNamespace:
    return SimpleNamespace(**named)


def add_notification(database, recipient_id, property_id) -> UUID:
    from app.models import Notification

    with Session(database) as db:
        row = Notification(
            recipient_id=recipient_id,
            type="billIssued",
            property_id=property_id,
            payload={},
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.commit()
        return row.id


def build_owner_graph(fx, *, email: str, name: str = "Rina Owner", share=None) -> Graph:
    """Store an Owner with a full set of records and the accounts around them.

    The Owner has a live property with two rooms, an archived property with a
    room, a Tenant with an active lease, emergency contacts and an invitation,
    a former Tenant record with an ended lease, a Manager with an assignment
    and an invitation, a paid bill with a receipt and status history, a
    complaint with a photo and status history, a payment-pattern summary,
    notifications about the properties for the Owner, the Tenant and the
    Manager, a subscription, a scheduled downgrade, notification settings and
    two subscription orders. Every file is in the file store.

    With `share`, the Tenant and the Manager are further records of the
    accounts of that graph; without it they are new accounts.
    """
    from app.models import (
        NotificationSetting,
        ScheduledDowngrade,
        SubscriptionOrder,
    )

    database = fx.database
    owner = fx.make_user(name=name, email=email)
    owner_in = fx.sign_in(owner)
    prop = fx.make_property(owner, name=f"Kos of {email}")
    room = fx.make_room(prop, number="A1")
    vacant_room = fx.make_room(prop, number="A2")
    archived_prop = fx.make_property(owner, name="Kos Lama", deleted=True)
    archived_room = fx.make_room(archived_prop, number="L1", deleted=True)

    contacts = [("Siti", "Ibu", "081111111111"), ("Agus", "Ayah", "082222222222")]
    if share is None:
        tenant = fx.make_verified_tenant(
            room,
            distinct_id=True,
            name="Budi Tenant",
            email=f"tenant.{email}",
            phone="081234567890",
            contacts=contacts,
            invitation=True,
        )
        tenant_in = fx.sign_in(tenant.user)
        manager = fx.make_manager(
            owner,
            [prop],
            activated=True,
            email=f"manager.{email}",
            nickname="Mimi",
            phone="081234567890",
        )
        manager_in = fx.sign_in(manager.user)
    else:
        tenant = fx.make_verified_tenant(
            room, user=share.tenant.user, contacts=contacts, invitation=True
        )
        tenant_in = share.tenant_in
        manager = fx.make_manager(
            owner,
            [prop],
            activated=True,
            user=share.manager.user,
            nickname="Mira",
            phone="085555555555",
        )
        manager_in = share.manager_in
    former_tenant = fx.make_verified_tenant(
        room, name="Former Tenant", deleted=True, lease_ended=True, invitation=False
    )

    history = seed_history(
        database,
        fx.file_store,
        fx.make_rent_bill,
        fx.make_complaint,
        tenant,
        room,
        actor_id=owner.id,
    )
    receipt = rows_of(
        database,
        _model("RentBillReceipt"),
        _model("RentBillReceipt").rent_bill_id == history.bill.id,
    )[0]
    add_payment_summary(database, tenant.lease)

    notification_ids = [
        add_notification(database, owner.id, prop.id),
        add_notification(database, owner.id, archived_prop.id),
        add_notification(database, tenant.user.id, prop.id),
        add_notification(database, manager.user.id, prop.id),
    ]
    unrelated = add_notification(database, tenant.user.id, None)

    fx.subscribe_owner(owner)
    now = datetime.now(UTC)
    with Session(database) as db:
        orders = [
            SubscriptionOrder(
                owner_id=owner.id,
                plan="basic",
                billing_period="monthly",
                status="succeeded",
                purchase_token=f"token-{uuid4()}",
                expires_at=now + timedelta(days=30),
            ),
            SubscriptionOrder(
                owner_id=owner.id,
                plan="pro",
                billing_period="yearly",
                status="awaitingPayment",
                expires_at=now + timedelta(days=1),
            ),
        ]
        db.add_all(orders)
        db.add(
            ScheduledDowngrade(
                owner_id=owner.id,
                plan="free",
                kept_property_ids=[prop.id],
                kept_room_ids=[room.id],
            )
        )
        db.add(
            NotificationSetting(
                user_id=owner.id, category="billing", push_enabled=False
            )
        )
        if share is None:
            db.add(
                NotificationSetting(
                    user_id=tenant.user.id, category="billing", push_enabled=False
                )
            )
        db.commit()
        order_ids = [order.id for order in orders]

    ids = [
        owner.id,
        prop.id,
        room.id,
        vacant_room.id,
        archived_prop.id,
        archived_room.id,
        tenant.id,
        tenant.lease.id,
        former_tenant.id,
        former_tenant.lease.id,
        manager.id,
        history.bill.id,
        history.complaint.id,
        *notification_ids,
    ]
    ids += [row.id for row in _invitations_of(database, tenant.id, manager.id)]
    return Graph(
        owner=owner,
        owner_in=owner_in,
        prop=prop,
        room=room,
        vacant_room=vacant_room,
        archived_prop=archived_prop,
        archived_room=archived_room,
        tenant=tenant,
        former_tenant=former_tenant,
        tenant_in=tenant_in,
        manager=manager,
        manager_in=manager_in,
        history=history,
        receipt_key=receipt.storage_key,
        notification_ids=notification_ids,
        unrelated_notification_id=unrelated,
        order_ids=order_ids,
        ids=ids,
    )


def _model(name: str):
    from app import models

    return getattr(models, name)


def _invitations_of(database, tenant_id, manager_id) -> list:
    from app.models import Invitation

    return rows_of(
        database,
        Invitation,
        (Invitation.tenant_id == tenant_id) | (Invitation.manager_id == manager_id),
    )


def delete_at(database, user, days: float) -> None:
    """Mark an account as deleted a number of days ago."""
    from app.models import UserAccount

    set_columns(database, UserAccount, user.id, deleted_at=ago(days=days))


def purge(database) -> None:
    """Run the purge in its own session and commit, as the daily runner does."""
    from app.services.owner_purge import purge_deleted_owners

    with Session(database) as db:
        purge_deleted_owners(db)
        db.commit()


def _mentions(value: Any, wanted: set[str]) -> bool:
    if isinstance(value, UUID):
        return str(value) in wanted
    if isinstance(value, list | tuple):
        return any(_mentions(item, wanted) for item in value)
    return False


def rows_mentioning(database, ids, skip=frozenset()) -> dict[str, list]:
    """The rows of every table, by table name, that hold one of the ids in a column."""
    from app import models

    wanted = {str(item) for item in ids}
    found: dict[str, list] = {}
    with Session(database) as db:
        for table in models.Base.metadata.sorted_tables:
            if table.name in skip:
                continue
            rows = [
                tuple(row)
                for row in db.execute(select(table))
                if any(_mentions(value, wanted) for value in row)
            ]
            if rows:
                found[table.name] = sorted(rows, key=repr)
    return found


def table_rows(database, model, *conditions) -> list[tuple]:
    with Session(database) as db:
        rows = db.execute(select(model.__table__).where(*conditions))
        return sorted((tuple(row) for row in rows), key=repr)


def whole_database(database) -> dict[str, list]:
    """Every row of every table."""
    from app import models

    with Session(database) as db:
        return {
            table.name: sorted(
                (tuple(row) for row in db.execute(select(table))), key=repr
            )
            for table in models.Base.metadata.sorted_tables
        }
