"""Granting subscriptions and resolving an owner's current plan."""

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.subscriptions import PaidPlanCode, PlanCode

NOW = datetime(2030, 6, 1, 12, 0, 0, tzinfo=UTC)


class PlanLimitsByPlan:
    """Looks up `app.plans.PLAN_LIMITS` lazily so a missing module fails per test."""

    def __getitem__(self, plan):
        from app.plans import PLAN_LIMITS

        return PLAN_LIMITS[plan]


PLAN_LIMITS = PlanLimitsByPlan()


@pytest.fixture
def owner(make_user):
    return make_user()


def store(db, owner, plan: str, ends_at: datetime):
    from app.models import Subscription

    row = db.get(Subscription, owner.id)
    if row is None:
        row = Subscription(owner_id=owner.id, plan=plan, ends_at=ends_at)
        db.add(row)
    else:
        row.plan = plan
        row.ends_at = ends_at
    db.flush()
    return row


def test_owner_without_a_subscription_is_on_the_free_plan(db_session, owner):
    from app.services.subscriptions import current_plan

    assert current_plan(db_session, owner.id) is PlanCode.FREE


@pytest.mark.parametrize("plan", [PlanCode.BASIC, PlanCode.PRO])
def test_running_subscription_gives_its_plan(db_session, owner, plan):
    from app.services.subscriptions import current_plan

    store(db_session, owner, plan.value, NOW + timedelta(days=1))
    assert current_plan(db_session, owner.id, NOW) is plan


def test_expired_subscription_falls_back_to_free(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "basic", NOW - timedelta(days=1))
    assert current_plan(db_session, owner.id, NOW) is PlanCode.FREE


def test_subscription_ending_exactly_now_counts_as_ended(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "pro", NOW)
    assert current_plan(db_session, owner.id, NOW) is PlanCode.FREE


def test_subscription_ending_one_second_after_now_is_running(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "pro", NOW + timedelta(seconds=1))
    assert current_plan(db_session, owner.id, NOW) is PlanCode.PRO


def test_subscription_that_ended_one_second_ago_is_ended(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "pro", NOW - timedelta(seconds=1))
    assert current_plan(db_session, owner.id, NOW) is PlanCode.FREE


def test_now_defaults_to_the_current_time(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "pro", datetime.now(UTC) + timedelta(hours=1))
    assert current_plan(db_session, owner.id) is PlanCode.PRO
    store(db_session, owner, "pro", datetime.now(UTC) - timedelta(hours=1))
    assert current_plan(db_session, owner.id) is PlanCode.FREE


def test_explicit_now_decides_whether_a_period_is_running(db_session, owner):
    from app.services.subscriptions import current_plan

    store(db_session, owner, "basic", NOW)
    assert current_plan(db_session, owner.id, NOW - timedelta(days=1)) is PlanCode.BASIC
    assert current_plan(db_session, owner.id, NOW + timedelta(days=1)) is PlanCode.FREE


def test_owners_are_independent(db_session, owner, make_user):
    from app.services.subscriptions import current_plan

    other = make_user()
    store(db_session, owner, "pro", NOW + timedelta(days=5))
    assert current_plan(db_session, owner.id, NOW) is PlanCode.PRO
    assert current_plan(db_session, other.id, NOW) is PlanCode.FREE


def test_plan_limits_without_a_subscription_are_the_free_limits(db_session, owner):
    from app.services.subscriptions import plan_limits

    assert plan_limits(db_session, owner.id, NOW) == PLAN_LIMITS[PlanCode.FREE]


@pytest.mark.parametrize("plan", [PlanCode.BASIC, PlanCode.PRO])
def test_plan_limits_of_a_running_subscription(db_session, owner, plan):
    from app.services.subscriptions import plan_limits

    store(db_session, owner, plan.value, NOW + timedelta(days=1))
    assert plan_limits(db_session, owner.id, NOW) == PLAN_LIMITS[plan]


def test_plan_limits_of_an_expired_subscription_are_the_free_limits(db_session, owner):
    from app.services.subscriptions import plan_limits

    store(db_session, owner, "pro", NOW - timedelta(seconds=1))
    assert plan_limits(db_session, owner.id, NOW) == PLAN_LIMITS[PlanCode.FREE]


def test_plan_limits_of_a_subscription_ending_now_are_the_free_limits(
    db_session, owner
):
    from app.services.subscriptions import plan_limits

    store(db_session, owner, "pro", NOW)
    assert plan_limits(db_session, owner.id, NOW) == PLAN_LIMITS[PlanCode.FREE]


def test_plan_limits_default_now_is_the_current_time(db_session, owner):
    from app.services.subscriptions import plan_limits

    store(db_session, owner, "basic", datetime.now(UTC) + timedelta(hours=1))
    assert plan_limits(db_session, owner.id) == PLAN_LIMITS[PlanCode.BASIC]


def test_no_active_subscription_without_a_row(db_session, owner):
    from app.services.subscriptions import has_active_subscription

    assert has_active_subscription(db_session, owner.id, NOW) is False


@pytest.mark.parametrize("plan", ["basic", "pro"])
def test_running_paid_plan_is_an_active_subscription(db_session, owner, plan):
    from app.services.subscriptions import has_active_subscription

    store(db_session, owner, plan, NOW + timedelta(days=1))
    assert has_active_subscription(db_session, owner.id, NOW) is True


def test_expired_plan_is_not_an_active_subscription(db_session, owner):
    from app.services.subscriptions import has_active_subscription

    store(db_session, owner, "pro", NOW - timedelta(days=1))
    assert has_active_subscription(db_session, owner.id, NOW) is False


def test_plan_ending_exactly_now_is_not_an_active_subscription(db_session, owner):
    from app.services.subscriptions import has_active_subscription

    store(db_session, owner, "basic", NOW)
    assert has_active_subscription(db_session, owner.id, NOW) is False


def test_active_subscription_default_now_is_the_current_time(db_session, owner):
    from app.services.subscriptions import has_active_subscription

    store(db_session, owner, "basic", datetime.now(UTC) + timedelta(hours=1))
    assert has_active_subscription(db_session, owner.id) is True


def test_grant_creates_a_subscription_for_the_period(db_session, owner):
    from app.models import Subscription
    from app.services.subscriptions import grant_subscription

    before = datetime.now(UTC)
    row = grant_subscription(db_session, owner, PaidPlanCode.BASIC, 30)
    after = datetime.now(UTC)
    assert isinstance(row, Subscription)
    assert row.owner_id == owner.id
    assert row.plan == "basic"
    assert before + timedelta(days=30) <= row.ends_at <= after + timedelta(days=30)
    assert row.ends_at.utcoffset() == timedelta(0)


def test_grant_is_visible_in_the_same_session(db_session, owner):
    from app.services.subscriptions import current_plan, grant_subscription

    grant_subscription(db_session, owner, PaidPlanCode.PRO, 1)
    assert current_plan(db_session, owner.id) is PlanCode.PRO


def test_grant_flushes_but_does_not_commit(database, db_session, owner):
    from sqlalchemy.orm import Session

    from app.models import Subscription
    from app.services.subscriptions import grant_subscription

    grant_subscription(db_session, owner, PaidPlanCode.BASIC, 30)
    assert db_session.in_transaction()
    with Session(database) as other:
        assert other.get(Subscription, owner.id) is None
    db_session.commit()
    with Session(database) as other:
        assert other.get(Subscription, owner.id) is not None


def test_grant_for_one_day(db_session, owner):
    from app.services.subscriptions import grant_subscription

    row = grant_subscription(db_session, owner, PaidPlanCode.PRO, 1)
    remaining = row.ends_at - datetime.now(UTC)
    assert timedelta(hours=23) < remaining <= timedelta(days=1)


@pytest.mark.parametrize("days", [0, -1, -30])
def test_grant_rejects_a_period_shorter_than_one_day(db_session, owner, days):
    from app.models import Subscription
    from app.services.subscriptions import grant_subscription

    with pytest.raises(ValueError):
        grant_subscription(db_session, owner, PaidPlanCode.BASIC, days)
    assert db_session.get(Subscription, owner.id) is None


def test_granting_again_replaces_the_row(db_session, owner):
    from sqlalchemy import func, select

    from app.models import Subscription
    from app.services.subscriptions import grant_subscription

    first = grant_subscription(db_session, owner, PaidPlanCode.BASIC, 30)
    second = grant_subscription(db_session, owner, PaidPlanCode.BASIC, 60)
    assert second is first
    count = db_session.scalar(select(func.count()).select_from(Subscription))
    assert count == 1


def test_granting_pro_upgrades_a_running_basic_subscription(db_session, owner):
    from app.services.subscriptions import current_plan, grant_subscription

    grant_subscription(db_session, owner, PaidPlanCode.BASIC, 30)
    grant_subscription(db_session, owner, PaidPlanCode.PRO, 30)
    db_session.commit()
    db_session.expire_all()
    assert current_plan(db_session, owner.id) is PlanCode.PRO


def test_a_shorter_regrant_shortens_the_period(db_session, owner):
    from app.services.subscriptions import grant_subscription

    long = grant_subscription(db_session, owner, PaidPlanCode.PRO, 365).ends_at
    short = grant_subscription(db_session, owner, PaidPlanCode.PRO, 7).ends_at
    assert short < long
    assert short - datetime.now(UTC) <= timedelta(days=7)


def test_regrant_counts_days_from_now_not_from_the_old_end(db_session, owner):
    from app.services.subscriptions import grant_subscription

    grant_subscription(db_session, owner, PaidPlanCode.BASIC, 100)
    row = grant_subscription(db_session, owner, PaidPlanCode.BASIC, 10)
    assert row.ends_at <= datetime.now(UTC) + timedelta(days=10)


def test_regranting_an_expired_subscription_revives_it(db_session, owner):
    from app.services.subscriptions import current_plan, grant_subscription

    store(db_session, owner, "basic", datetime.now(UTC) - timedelta(days=5))
    assert current_plan(db_session, owner.id) is PlanCode.FREE
    grant_subscription(db_session, owner, PaidPlanCode.PRO, 30)
    assert current_plan(db_session, owner.id) is PlanCode.PRO


def test_granting_one_owner_leaves_others_unchanged(db_session, owner, make_user):
    from app.services.subscriptions import current_plan, grant_subscription

    other = make_user()
    grant_subscription(db_session, owner, PaidPlanCode.PRO, 30)
    assert current_plan(db_session, other.id) is PlanCode.FREE
    grant_subscription(db_session, other, PaidPlanCode.BASIC, 30)
    assert current_plan(db_session, owner.id) is PlanCode.PRO
    assert current_plan(db_session, other.id) is PlanCode.BASIC
