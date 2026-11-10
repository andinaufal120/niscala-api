"""Plans, orders and downgrades of subscriptions, and resolving an owner's current plan."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Lease, UserAccount
from app.models import Property as PropertyRow
from app.models import Room as RoomRow
from app.models import ScheduledDowngrade as ScheduleRow
from app.models import Subscription as SubscriptionRow
from app.models import SubscriptionOrder as OrderRow
from app.plans import (
    GOOGLE_PLAY_BASE_PLAN_IDS,
    GOOGLE_PLAY_PRODUCT_IDS,
    PLAN_LIMITS,
    PLAN_PRICES,
    PLAN_RANK,
    SUBSCRIPTION_PLANS,
    PlanLimits,
)
from app.schemas.subscriptions import (
    OrderStatus,
    PaidPlanCode,
    PlanCode,
    ScheduledDowngrade,
    ScheduledDowngradeInput,
    Subscription,
    SubscriptionOrder,
    SubscriptionOrderInput,
    SubscriptionPeriod,
    SubscriptionPlan,
    SubscriptionPlanList,
    SubscriptionPlanPrice,
    SubscriptionStatus,
)

ORDER_LIFETIME = timedelta(days=3)


def _running_subscription(
    db: Session, owner_id: UUID, now: datetime | None
) -> SubscriptionRow | None:
    row = db.get(SubscriptionRow, owner_id)
    if row is None or row.ends_at <= (now or datetime.now(UTC)):
        return None
    return row


def _jakarta_date(moment: datetime) -> date:
    # Imported here because rent_bills reaches this module through rooms.
    from app.services.rent_bills import TIMEZONE

    return moment.astimezone(TIMEZONE).date()


def grant_subscription(
    db: Session, owner: UserAccount, plan: PaidPlanCode, days: int
) -> SubscriptionRow:
    """Set the owner's subscription to `plan` for `days` days counted from now.

    Replaces any existing subscription, running or ended, with a monthly one that
    does not renew, and makes the owner's properties and rooms editable.
    Flushes, never commits. Raises ValueError when `days` is less than 1.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    ends_at = datetime.now(UTC) + timedelta(days=days)
    row = db.get(SubscriptionRow, owner.id)
    if row is None:
        row = SubscriptionRow(owner_id=owner.id, plan=plan.value, ends_at=ends_at)
        db.add(row)
    else:
        row.plan = plan.value
        row.ends_at = ends_at
        row.billing_period = SubscriptionPeriod.MONTHLY.value
        row.auto_renew = False
    db.flush()
    restore_editability(db, owner.id)
    return row


def current_plan(db: Session, owner_id: UUID, now: datetime | None = None) -> PlanCode:
    """Return the owner's plan at `now`; free without a running subscription.

    A subscription counts only while `ends_at` is strictly after `now`.
    """
    row = _running_subscription(db, owner_id, now)
    return PlanCode.FREE if row is None else PlanCode(row.plan)


def plan_limits(db: Session, owner_id: UUID, now: datetime | None = None) -> PlanLimits:
    """Return the limits of the owner's plan at `now`."""
    return PLAN_LIMITS[current_plan(db, owner_id, now)]


def has_active_subscription(
    db: Session, owner_id: UUID, now: datetime | None = None
) -> bool:
    """Return whether the owner has a paid subscription running at `now`."""
    return _running_subscription(db, owner_id, now) is not None


def _plan(code: PlanCode) -> SubscriptionPlan:
    limits = PLAN_LIMITS[code]
    prices = []
    if code != PlanCode.FREE:
        paid = PaidPlanCode(code)
        prices = [
            SubscriptionPlanPrice(
                billing_period=period,
                amount=amount,
                google_play_product_id=GOOGLE_PLAY_PRODUCT_IDS[paid],
                google_play_base_plan_id=GOOGLE_PLAY_BASE_PLAN_IDS[period],
            )
            for period, amount in PLAN_PRICES[paid].items()
        ]
    return SubscriptionPlan(
        code=code,
        max_properties=limits.max_properties,
        max_rooms_per_property=limits.max_rooms_per_property,
        ai_enabled=limits.ai_enabled,
        prices=prices,
    )


def list_plans() -> SubscriptionPlanList:
    """List the plans from free to pro with their limits and prices."""
    return SubscriptionPlanList(items=[_plan(code) for code in SUBSCRIPTION_PLANS])


def _order_view(row: OrderRow) -> SubscriptionOrder:
    plan = PaidPlanCode(row.plan)
    period = SubscriptionPeriod(row.billing_period)
    return SubscriptionOrder(
        id=row.id,
        plan_code=plan,
        billing_period=period,
        status=OrderStatus(row.status),
        google_play_product_id=GOOGLE_PLAY_PRODUCT_IDS[plan],
        google_play_base_plan_id=GOOGLE_PLAY_BASE_PLAN_IDS[period],
        obfuscated_account_id=str(row.owner_id),
        created_at=row.created_at,
    )


def _schedule_view(schedule: ScheduleRow, subscription: SubscriptionRow):
    return ScheduledDowngrade(
        plan_code=PlanCode(schedule.plan),
        effective_date=_jakarta_date(subscription.ends_at) + timedelta(days=1),
        kept_property_ids=schedule.kept_property_ids,
        kept_room_ids=schedule.kept_room_ids,
    )


def _expire_lapsed_orders(db: Session, owner_id: UUID, now: datetime) -> None:
    """Save as expired every order awaiting payment that has no token and lapsed."""
    db.execute(
        update(OrderRow)
        .where(
            OrderRow.owner_id == owner_id,
            OrderRow.status == OrderStatus.AWAITING_PAYMENT,
            OrderRow.purchase_token.is_(None),
            OrderRow.expires_at <= now,
        )
        .values(status=OrderStatus.EXPIRED.value)
    )


def get_subscription(db: Session, owner: UserAccount) -> Subscription:
    """Return the owner's current subscription.

    The plan comes from the running paid period, if any. Lapsed orders are saved
    as expired first, so the open order is the newest one still awaiting payment.
    """
    now = datetime.now(UTC)
    _expire_lapsed_orders(db, owner.id, now)
    row = _running_subscription(db, owner.id, now)
    open_order = db.scalars(
        select(OrderRow)
        .where(
            OrderRow.owner_id == owner.id,
            OrderRow.status == OrderStatus.AWAITING_PAYMENT,
        )
        .order_by(OrderRow.created_at.desc())
        .limit(1)
    ).first()
    schedule = None if row is None else db.get(ScheduleRow, owner.id)
    property_count = db.scalar(
        select(func.count())
        .select_from(PropertyRow)
        .where(PropertyRow.owner_id == owner.id, PropertyRow.deleted_at.is_(None))
    )
    return Subscription(
        plan_code=PlanCode.FREE if row is None else PlanCode(row.plan),
        status=SubscriptionStatus.FREE if row is None else SubscriptionStatus.ACTIVE,
        billing_period=None if row is None else SubscriptionPeriod(row.billing_period),
        end_date=None if row is None else _jakarta_date(row.ends_at),
        auto_renew=False if row is None else row.auto_renew,
        property_count=property_count or 0,
        open_order=None if open_order is None else _order_view(open_order),
        scheduled_downgrade=(
            None if schedule is None else _schedule_view(schedule, row)
        ),
    )


def create_order(
    db: Session, owner: UserAccount, data: SubscriptionOrderInput
) -> SubscriptionOrder:
    """Start a purchase of a plan higher than the owner's current one.

    Raises 409 SUBSCRIPTION_NOT_AN_UPGRADE otherwise. Every earlier order still
    awaiting payment is expired. The new order lapses three days after creation.
    """
    now = datetime.now(UTC)
    if (
        PLAN_RANK[PlanCode(data.plan_code)]
        <= PLAN_RANK[current_plan(db, owner.id, now)]
    ):
        raise ApiError(409, "SUBSCRIPTION_NOT_AN_UPGRADE")
    db.execute(
        update(OrderRow)
        .where(
            OrderRow.owner_id == owner.id,
            OrderRow.status == OrderStatus.AWAITING_PAYMENT,
        )
        .values(status=OrderStatus.EXPIRED.value)
    )
    row = OrderRow(
        owner_id=owner.id,
        plan=data.plan_code.value,
        billing_period=data.billing_period.value,
        status=OrderStatus.AWAITING_PAYMENT.value,
        created_at=now,
        expires_at=now + ORDER_LIFETIME,
    )
    db.add(row)
    db.flush()
    return _order_view(row)


def get_order(db: Session, owner: UserAccount, order_id: UUID) -> SubscriptionOrder:
    """Return an order of the owner.

    Raises 404 SUBSCRIPTION_ORDER_NOT_FOUND for an unknown order or another
    owner's. A lapsed order is saved as expired first.
    """
    _expire_lapsed_orders(db, owner.id, datetime.now(UTC))
    row = db.scalars(
        select(OrderRow).where(OrderRow.id == order_id, OrderRow.owner_id == owner.id)
    ).first()
    if row is None:
        raise ApiError(404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    return _order_view(row)


def _check_kept_properties(
    db: Session, owner_id: UUID, target: PlanCode, kept: list[UUID]
) -> None:
    live = set(
        db.scalars(
            select(PropertyRow.id).where(
                PropertyRow.owner_id == owner_id, PropertyRow.deleted_at.is_(None)
            )
        )
    )
    limit = PLAN_LIMITS[target].max_properties
    expected = len(live) if limit is None else min(limit, len(live))
    if len(set(kept)) != len(kept) or not set(kept) <= live or len(kept) != expected:
        raise ApiError(422, "KEPT_PROPERTIES_INVALID", field="keptPropertyIds")


def _check_kept_rooms(
    db: Session, target: PlanCode, kept_properties: list[UUID], kept: list[UUID]
) -> None:
    live: set[UUID] = set()
    expected = 0
    limit = PLAN_LIMITS[target].max_rooms_per_property
    if target == PlanCode.FREE and kept_properties and limit is not None:
        live = set(
            db.scalars(
                select(RoomRow.id).where(
                    RoomRow.property_id == kept_properties[0],
                    RoomRow.deleted_at.is_(None),
                )
            )
        )
        expected = min(limit, len(live))
    if len(set(kept)) != len(kept) or not set(kept) <= live or len(kept) != expected:
        raise ApiError(422, "KEPT_ROOMS_INVALID", field="keptRoomIds")


def schedule_downgrade(
    db: Session, owner: UserAccount, data: ScheduledDowngradeInput
) -> ScheduledDowngrade:
    """Store the owner's confirmation of a downgrade at the end of the paid period.

    Checks in order: the plan is lower than the running paid plan (422
    SUBSCRIPTION_NOT_A_DOWNGRADE), the kept properties (422
    KEPT_PROPERTIES_INVALID), the kept rooms (422 KEPT_ROOMS_INVALID).
    Replaces an earlier confirmation.
    """
    subscription = _running_subscription(db, owner.id, None)
    if (
        subscription is None
        or PLAN_RANK[data.plan_code] >= PLAN_RANK[PlanCode(subscription.plan)]
    ):
        raise ApiError(422, "SUBSCRIPTION_NOT_A_DOWNGRADE", field="planCode")
    _check_kept_properties(db, owner.id, data.plan_code, data.kept_property_ids)
    _check_kept_rooms(db, data.plan_code, data.kept_property_ids, data.kept_room_ids)
    schedule = db.get(ScheduleRow, owner.id)
    if schedule is None:
        schedule = ScheduleRow(owner_id=owner.id)
        db.add(schedule)
    schedule.plan = data.plan_code.value
    schedule.kept_property_ids = data.kept_property_ids
    schedule.kept_room_ids = data.kept_room_ids
    db.flush()
    return _schedule_view(schedule, subscription)


def cancel_downgrade(db: Session, owner: UserAccount) -> None:
    """Remove the owner's scheduled downgrade; succeeds when there is none."""
    db.execute(delete(ScheduleRow).where(ScheduleRow.owner_id == owner.id))


def restore_editability(db: Session, owner_id: UUID) -> None:
    """Make every property and room of the owner editable and drop the scheduled downgrade.

    Flushes, never commits.
    """
    db.execute(
        update(RoomRow)
        .where(
            RoomRow.property_id.in_(
                select(PropertyRow.id).where(PropertyRow.owner_id == owner_id)
            )
        )
        .values(view_only=False)
    )
    db.execute(
        update(PropertyRow)
        .where(PropertyRow.owner_id == owner_id)
        .values(view_only=False)
    )
    db.execute(delete(ScheduleRow).where(ScheduleRow.owner_id == owner_id))
    db.flush()


def _limit_rooms(
    db: Session, prop: PropertyRow, limit: int, confirmed: ScheduleRow | None
) -> bool:
    """Set view-only on the rooms of `prop` beyond `limit`; return whether any were."""
    # Imported here because rooms imports this module.
    from app.services.rooms import natural_number_key

    rooms = list(
        db.scalars(
            select(RoomRow).where(
                RoomRow.property_id == prop.id,
                RoomRow.deleted_at.is_(None),
                RoomRow.view_only.is_(False),
            )
        )
    )
    if len(rooms) <= limit:
        return False
    if confirmed is not None and prop.id in confirmed.kept_property_ids:
        kept = set(confirmed.kept_room_ids)
    else:
        occupied = set(
            db.scalars(
                select(Lease.room_id).where(
                    Lease.room_id.in_([room.id for room in rooms]),
                    Lease.ended_at.is_(None),
                )
            )
        )
        ranked = sorted(
            rooms,
            key=lambda r: (r.id not in occupied, natural_number_key(r.number), r.id),
        )
        kept = {room.id for room in ranked[:limit]}
    for room in rooms:
        room.view_only = room.id not in kept
    return True


def _limit_owner(db: Session, owner_id: UUID, now: datetime) -> None:
    plan = current_plan(db, owner_id, now)
    limits = PLAN_LIMITS[plan]
    schedule = db.get(ScheduleRow, owner_id)
    confirmed = schedule if schedule is not None and schedule.plan == plan else None
    editable = list(
        db.scalars(
            select(PropertyRow)
            .where(
                PropertyRow.owner_id == owner_id,
                PropertyRow.deleted_at.is_(None),
                PropertyRow.view_only.is_(False),
            )
            .order_by(PropertyRow.created_at, PropertyRow.id)
        )
    )
    kept = editable
    if limits.max_properties is not None and len(editable) > limits.max_properties:
        if confirmed is not None:
            kept = [p for p in editable if p.id in confirmed.kept_property_ids]
        else:
            kept = editable[: limits.max_properties]
        for prop in editable:
            prop.view_only = prop not in kept
    trimmed = len(kept) < len(editable)
    if limits.max_rooms_per_property is not None:
        for prop in kept:
            if _limit_rooms(db, prop, limits.max_rooms_per_property, confirmed):
                trimmed = True
    if schedule is not None and (confirmed is not None or trimmed):
        db.delete(schedule)


def apply_plan_limits(db: Session) -> None:
    """Set view-only on the properties and rooms beyond each owner's current plan.

    Uses the owner's confirmed downgrade when its plan is the plan now in effect,
    otherwise keeps the earliest-created properties and, on the free plan,
    occupied rooms first and then the lowest room numbers. The confirmation is
    deleted once it no longer applies. Safe to run repeatedly. Flushes, never commits.
    """
    now = datetime.now(UTC)
    owner_ids = db.scalars(
        select(PropertyRow.owner_id).where(PropertyRow.deleted_at.is_(None)).distinct()
    ).all()
    for owner_id in owner_ids:
        _limit_owner(db, owner_id, now)
    db.flush()
