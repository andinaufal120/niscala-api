"""Helpers shared by the subscription plan, order, downgrade and job tests."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

JAKARTA = ZoneInfo("Asia/Jakarta")


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def jakarta_date(moment: datetime) -> date:
    return moment.astimezone(JAKARTA).date()


def set_subscription(
    database,
    owner,
    *,
    plan: str = "pro",
    ends_at: datetime | None = None,
    billing_period: str = "monthly",
    auto_renew: bool = False,
) -> None:
    """Store the subscription row of an owner with exact values."""
    from app.models import Subscription

    ends = ends_at or datetime.now(UTC) + timedelta(days=30)
    with Session(database) as db:
        row = db.get(Subscription, owner.id)
        if row is None:
            row = Subscription(owner_id=owner.id, plan=plan, ends_at=ends)
            db.add(row)
        row.plan = plan
        row.ends_at = ends
        row.billing_period = billing_period
        row.auto_renew = auto_renew
        db.commit()


def stored_subscription(database, owner):
    from app.models import Subscription

    with Session(database, expire_on_commit=False) as db:
        return db.get(Subscription, owner.id)


def insert_order(
    database,
    owner,
    *,
    plan: str = "basic",
    billing_period: str = "monthly",
    status: str = "awaitingPayment",
    purchase_token: str | None = None,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
):
    """Store a subscription order directly; by default it is open and expires later."""
    from app.models import SubscriptionOrder

    now = datetime.now(UTC)
    with Session(database, expire_on_commit=False) as db:
        row = SubscriptionOrder(
            id=uuid4(),
            owner_id=owner.id,
            plan=plan,
            billing_period=billing_period,
            status=status,
            purchase_token=purchase_token,
            created_at=created_at or now - timedelta(days=1),
            expires_at=expires_at or now + timedelta(days=2),
        )
        db.add(row)
        db.commit()
        return row


def stored_order(database, order_id):
    from app.models import SubscriptionOrder

    with Session(database, expire_on_commit=False) as db:
        return db.get(SubscriptionOrder, UUID(str(order_id)))


def stored_orders(database, owner) -> list:
    from app.models import SubscriptionOrder

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(SubscriptionOrder)
                .where(SubscriptionOrder.owner_id == owner.id)
                .order_by(SubscriptionOrder.created_at)
            )
        )


def schedule_row(database, owner):
    """The stored scheduled downgrade of an owner, or None."""
    from app.models import ScheduledDowngrade

    with Session(database, expire_on_commit=False) as db:
        return db.get(ScheduledDowngrade, owner.id)


def store_schedule(
    database,
    owner,
    plan: str,
    property_ids=(),
    room_ids=(),
) -> None:
    """Store a scheduled downgrade directly."""
    from app.models import ScheduledDowngrade

    with Session(database) as db:
        db.add(
            ScheduledDowngrade(
                owner_id=owner.id,
                plan=plan,
                kept_property_ids=[UUID(str(i)) for i in property_ids],
                kept_room_ids=[UUID(str(i)) for i in room_ids],
            )
        )
        db.commit()


def view_only_properties(database, owner) -> set[UUID]:
    """Ids of the owner's live properties that are view-only."""
    from app.models import Property

    with Session(database) as db:
        return set(
            db.scalars(
                select(Property.id).where(
                    Property.owner_id == owner.id,
                    Property.deleted_at.is_(None),
                    Property.view_only.is_(True),
                )
            )
        )


def view_only_rooms(database, property_) -> set[UUID]:
    """Ids of the live view-only rooms of a property."""
    from app.models import Room

    with Session(database) as db:
        return set(
            db.scalars(
                select(Room.id).where(
                    Room.property_id == property_.id,
                    Room.deleted_at.is_(None),
                    Room.view_only.is_(True),
                )
            )
        )


def is_property_view_only(database, property_) -> bool:
    from app.models import Property

    with Session(database) as db:
        return db.get(Property, property_.id).view_only


def is_room_view_only(database, room) -> bool:
    from app.models import Room

    with Session(database) as db:
        return db.get(Room, room.id).view_only


def ids(rows) -> list[str]:
    return [str(row.id) for row in rows]
