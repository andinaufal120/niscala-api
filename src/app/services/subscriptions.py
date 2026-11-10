"""Plans, orders and downgrades of subscriptions, and resolving an owner's current plan."""

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import google_play
from app.errors import ApiError
from app.google_play import (
    GooglePlay,
    GooglePlayUnreachable,
    PlaySubscription,
    PurchaseNotFound,
)
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

logger = logging.getLogger(__name__)

ORDER_LIFETIME = timedelta(days=3)

# Subscriptions ending between these offsets from now are fetched again daily.
RECONCILE_LOOKBACK = timedelta(days=3)
RECONCILE_LOOKAHEAD = timedelta(days=1)


def _running_subscription(
    db: Session, owner_id: UUID, now: datetime | None
) -> SubscriptionRow | None:
    row = db.get(SubscriptionRow, owner_id)
    if row is None or row.ends_at <= (now or datetime.now(UTC)):
        return None
    return row


def _lock_owner(db: Session, owner_id: UUID) -> bool:
    """Lock the owner's account row until the transaction ends.

    Returns whether the account exists.
    """
    return (
        db.scalar(
            select(UserAccount.id).where(UserAccount.id == owner_id).with_for_update()
        )
        is not None
    )


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


def _schedule_view(
    schedule: ScheduleRow, subscription: SubscriptionRow
) -> ScheduledDowngrade:
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
    # Serializes the owner's order requests, so a retried request cannot leave
    # two orders awaiting payment.
    _lock_owner(db, owner.id)
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


def _purchase_outcome(purchase: PlaySubscription, now: datetime) -> OrderStatus:
    """Map Google's state to the status the purchase gives an order.

    SUCCEEDED means a paid period is running, AWAITING_PAYMENT that payment is
    still pending, and FAILED that the purchase ended or never completed.
    """
    if purchase.state in ("ACTIVE", "IN_GRACE_PERIOD") or (
        purchase.state == "CANCELED" and purchase.expiry_time > now
    ):
        return OrderStatus.SUCCEEDED
    if purchase.state == "PENDING":
        return OrderStatus.AWAITING_PAYMENT
    return OrderStatus.FAILED


def _plan_of(
    purchase: PlaySubscription,
) -> tuple[PaidPlanCode, SubscriptionPeriod] | None:
    """Return the plan and billing period of the purchase's product, if it is ours."""
    plans = {product: plan for plan, product in GOOGLE_PLAY_PRODUCT_IDS.items()}
    periods = {base: period for period, base in GOOGLE_PLAY_BASE_PLAN_IDS.items()}
    plan = plans.get(purchase.product_id)
    period = periods.get(purchase.base_plan_id)
    return None if plan is None or period is None else (plan, period)


def _set_subscription(
    db: Session,
    owner_id: UUID,
    plan: PaidPlanCode,
    period: SubscriptionPeriod,
    purchase: PlaySubscription,
    token: str,
) -> None:
    row = db.get(SubscriptionRow, owner_id)
    if row is None:
        row = SubscriptionRow(owner_id=owner_id)
        db.add(row)
    row.plan = plan.value
    row.billing_period = period.value
    row.ends_at = purchase.expiry_time
    row.auto_renew = purchase.auto_renewing
    row.purchase_token = token
    db.flush()


def _token_in_use(db: Session, owner_id: UUID, order_id: UUID, token: str) -> bool:
    """Whether the token is held by another order, or by another owner's subscription."""
    return (
        db.scalar(
            select(OrderRow.id).where(
                OrderRow.purchase_token == token, OrderRow.id != order_id
            )
        )
        is not None
        or db.scalar(
            select(SubscriptionRow.owner_id).where(
                SubscriptionRow.purchase_token == token,
                SubscriptionRow.owner_id != owner_id,
            )
        )
        is not None
    )


def verify_purchase(
    db: Session, play: GooglePlay, owner: UserAccount, order_id: UUID, token: str
) -> SubscriptionOrder:
    """Check the purchase token of an order against Google Play and apply the result.

    A paid purchase succeeds the order, acknowledges the purchase if needed and
    sets the subscription; a pending one keeps the order awaiting payment with
    the token stored; any other state fails the order. Repeating a succeeded
    order with its own token returns it unchanged.

    Raises 404 SUBSCRIPTION_ORDER_NOT_FOUND, 409 SUBSCRIPTION_ORDER_CLOSED for an
    order that is not awaiting payment, 409 PURCHASE_TOKEN_IN_USE, 503
    GOOGLE_PLAY_UNREACHABLE (also when the acknowledgement fails; nothing is
    saved), 422 PURCHASE_TOKEN_INVALID for an unknown token or one bought for
    another account, and 422 PURCHASE_PRODUCT_MISMATCH. Flushes, never commits.
    """
    now = datetime.now(UTC)
    _lock_owner(db, owner.id)
    _expire_lapsed_orders(db, owner.id, now)
    row = db.scalars(
        select(OrderRow).where(OrderRow.id == order_id, OrderRow.owner_id == owner.id)
    ).first()
    if row is None:
        raise ApiError(404, "SUBSCRIPTION_ORDER_NOT_FOUND")
    if row.status == OrderStatus.SUCCEEDED and row.purchase_token == token:
        return _order_view(row)
    if row.status != OrderStatus.AWAITING_PAYMENT:
        raise ApiError(409, "SUBSCRIPTION_ORDER_CLOSED")
    if _token_in_use(db, owner.id, row.id, token):
        raise ApiError(409, "PURCHASE_TOKEN_IN_USE")
    try:
        purchase = play.get_subscription(token)
    except PurchaseNotFound:
        raise ApiError(422, "PURCHASE_TOKEN_INVALID", field="purchaseToken") from None
    except GooglePlayUnreachable:
        raise ApiError(503, "GOOGLE_PLAY_UNREACHABLE") from None
    if purchase.obfuscated_account_id != str(owner.id):
        raise ApiError(422, "PURCHASE_TOKEN_INVALID", field="purchaseToken")
    plan = PaidPlanCode(row.plan)
    period = SubscriptionPeriod(row.billing_period)
    if (
        purchase.product_id != GOOGLE_PLAY_PRODUCT_IDS[plan]
        or purchase.base_plan_id != GOOGLE_PLAY_BASE_PLAN_IDS[period]
    ):
        raise ApiError(422, "PURCHASE_PRODUCT_MISMATCH", field="purchaseToken")
    outcome = _purchase_outcome(purchase, now)
    if outcome == OrderStatus.SUCCEEDED:
        try:
            if not purchase.acknowledged:
                play.acknowledge(purchase.product_id, token)
        except PurchaseNotFound:
            raise ApiError(
                422, "PURCHASE_TOKEN_INVALID", field="purchaseToken"
            ) from None
        except GooglePlayUnreachable:
            raise ApiError(503, "GOOGLE_PLAY_UNREACHABLE") from None
        row.status = outcome.value
        row.purchase_token = token
        _set_subscription(db, owner.id, plan, period, purchase, token)
        restore_editability(db, owner.id)
    else:
        row.status = outcome.value
        row.purchase_token = token
    db.flush()
    return _order_view(row)


def _order_for_purchase(
    db: Session,
    owner_id: UUID,
    token: str,
    plan: PaidPlanCode,
    period: SubscriptionPeriod,
    paid: bool,
) -> OrderRow | None:
    """Find the order awaiting payment that a purchase belongs to.

    The order holding the token is the one; without it, a paid purchase belongs
    to the owner's newest order awaiting payment for the same plan and period.
    A closed order holding the token is never reopened.
    """
    holding = db.scalars(
        select(OrderRow).where(OrderRow.purchase_token == token)
    ).first()
    if holding is not None:
        open_ = holding.owner_id == owner_id and (
            holding.status == OrderStatus.AWAITING_PAYMENT
        )
        return holding if open_ else None
    if not paid:
        return None
    return db.scalars(
        select(OrderRow)
        .where(
            OrderRow.owner_id == owner_id,
            OrderRow.status == OrderStatus.AWAITING_PAYMENT,
            OrderRow.purchase_token.is_(None),
            OrderRow.plan == plan.value,
            OrderRow.billing_period == period.value,
        )
        .order_by(OrderRow.created_at.desc())
        .limit(1)
    ).first()


def sync_purchase(db: Session, play: GooglePlay, token: str) -> None:
    """Bring the purchase's owner in line with what Google Play reports for the token.

    The owner is found by the purchase's obfuscated account id; a purchase of no
    known owner or of a product that is not ours changes nothing, and neither
    does a pending one. A paid purchase is adopted when it is the owner's current
    one, replaces it (its linked token is the current one), belongs to an order
    awaiting payment, or the owner has no running subscription. An ended
    purchase updates the owner's subscription only when it is the current one or
    replaces it. The matching order awaiting payment follows the purchase.
    Editability is restored when the plan goes up.

    Raises PurchaseNotFound and GooglePlayUnreachable from the Google Play calls,
    before anything is changed. Flushes, never commits.
    """
    purchase = play.get_subscription(token)
    try:
        owner_id = UUID(purchase.obfuscated_account_id or "")
    except ValueError:
        return
    plan_period = _plan_of(purchase)
    if plan_period is None or not _lock_owner(db, owner_id):
        return
    plan, period = plan_period
    now = datetime.now(UTC)
    outcome = _purchase_outcome(purchase, now)
    if outcome == OrderStatus.AWAITING_PAYMENT:
        return
    paid = outcome == OrderStatus.SUCCEEDED
    order = _order_for_purchase(db, owner_id, token, plan, period, paid)
    row = db.get(SubscriptionRow, owner_id)
    current = row is not None and (
        row.purchase_token == token
        or (
            purchase.linked_purchase_token is not None
            and purchase.linked_purchase_token == row.purchase_token
        )
    )
    adopt = current or (
        paid and (order is not None or row is None or row.ends_at <= now)
    )
    if adopt:
        if paid and not purchase.acknowledged:
            play.acknowledge(purchase.product_id, token)
        previous = current_plan(db, owner_id, now)
        _set_subscription(db, owner_id, plan, period, purchase, token)
        if PLAN_RANK[PlanCode(plan)] > PLAN_RANK[previous]:
            restore_editability(db, owner_id)
    if order is not None:
        order.status = outcome.value
        order.purchase_token = token
    db.flush()


def reconcile_google_play_subscriptions(db: Session) -> None:
    """Fetch again every subscription ending from three days ago to a day ahead.

    Recovers notifications that never arrived. A purchase that cannot be fetched
    is logged and skipped, so the job itself does not fail. Flushes, never
    commits.
    """
    now = datetime.now(UTC)
    tokens = db.scalars(
        select(SubscriptionRow.purchase_token).where(
            SubscriptionRow.purchase_token.is_not(None),
            SubscriptionRow.ends_at >= now - RECONCILE_LOOKBACK,
            SubscriptionRow.ends_at <= now + RECONCILE_LOOKAHEAD,
        )
    ).all()
    if not tokens:
        return
    play = google_play.get_google_play()
    for token in tokens:
        try:
            sync_purchase(db, play, token)
        except (PurchaseNotFound, GooglePlayUnreachable) as error:
            logger.warning("Could not reconcile a Google Play purchase: %r", error)


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
    if confirmed is not None and prop.id in confirmed.kept_property_ids:
        confirmed_rooms = set(confirmed.kept_room_ids)
        ranked.sort(key=lambda r: r.id not in confirmed_rooms)
    kept = {room.id for room in ranked[:limit]}
    for room in rooms:
        room.view_only = room.id not in kept
    return True


def _limit_owner(db: Session, owner_id: UUID, now: datetime) -> None:
    plan = current_plan(db, owner_id, now)
    limits = PLAN_LIMITS[plan]
    if limits.max_properties is None and limits.max_rooms_per_property is None:
        return
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
        ranked = editable
        if confirmed is not None:
            confirmed_properties = set(confirmed.kept_property_ids)
            ranked = sorted(editable, key=lambda p: p.id not in confirmed_properties)
        kept = ranked[: limits.max_properties]
        kept_ids = {prop.id for prop in kept}
        for prop in editable:
            prop.view_only = prop.id not in kept_ids
    trimmed = len(kept) < len(editable)
    if limits.max_rooms_per_property is not None:
        for prop in kept:
            if _limit_rooms(db, prop, limits.max_rooms_per_property, confirmed):
                trimmed = True
    if schedule is not None and (confirmed is not None or trimmed):
        db.delete(schedule)


def apply_plan_limits(db: Session) -> None:
    """Set view-only on the properties and rooms beyond each owner's current plan.

    Without a confirmed downgrade for the plan now in effect, keeps the
    earliest-created properties and, on the free plan, occupied rooms first and
    then the lowest room numbers. With one, keeps the confirmed properties and
    rooms that are still live and editable, and tops up any places they leave
    free: the earliest-created other properties, and in a confirmed property the
    other rooms by the default rule. A property that was not confirmed gets the
    default rooms. Never keeps more than the plan allows. The confirmation is
    deleted once it has been applied or the owner had to be limited. Safe to run
    repeatedly. Flushes, never commits.
    """
    now = datetime.now(UTC)
    owner_ids = db.scalars(
        select(PropertyRow.owner_id).where(PropertyRow.deleted_at.is_(None)).distinct()
    ).all()
    for owner_id in owner_ids:
        _limit_owner(db, owner_id, now)
    db.flush()
