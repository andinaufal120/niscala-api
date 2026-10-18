"""Granting subscriptions and resolving an owner's current plan."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Subscription, UserAccount
from app.plans import PLAN_LIMITS, PlanLimits
from app.schemas.subscriptions import PaidPlanCode, PlanCode


def _running_subscription(
    db: Session, owner_id: UUID, now: datetime | None
) -> Subscription | None:
    row = db.get(Subscription, owner_id)
    if row is None or row.ends_at <= (now or datetime.now(UTC)):
        return None
    return row


def grant_subscription(
    db: Session, owner: UserAccount, plan: PaidPlanCode, days: int
) -> Subscription:
    """Set the owner's subscription to `plan` for `days` days counted from now.

    Replaces any existing subscription, running or ended. Flushes, never commits.
    Raises ValueError when `days` is less than 1.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    ends_at = datetime.now(UTC) + timedelta(days=days)
    row = db.get(Subscription, owner.id)
    if row is None:
        row = Subscription(owner_id=owner.id, plan=plan.value, ends_at=ends_at)
        db.add(row)
    else:
        row.plan = plan.value
        row.ends_at = ends_at
    db.flush()
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
