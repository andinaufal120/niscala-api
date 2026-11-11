"""What each subscription plan grants, ranks and costs."""

from dataclasses import dataclass

from app.schemas.subscriptions import PaidPlanCode, PlanCode, SubscriptionPeriod


@dataclass(frozen=True)
class PlanLimits:
    """What a plan allows; None means unlimited."""

    max_properties: int | None
    max_rooms_per_property: int | None
    ai_enabled: bool


PLAN_LIMITS: dict[PlanCode, PlanLimits] = {
    PlanCode.FREE: PlanLimits(1, 15, False),
    PlanCode.BASIC: PlanLimits(3, None, True),
    PlanCode.PRO: PlanLimits(None, None, True),
}

# A higher rank is a higher plan.
PLAN_RANK: dict[PlanCode, int] = {PlanCode.FREE: 0, PlanCode.BASIC: 1, PlanCode.PRO: 2}

# Plans in the order they are offered.
SUBSCRIPTION_PLANS: list[PlanCode] = [PlanCode.FREE, PlanCode.BASIC, PlanCode.PRO]

# Rupiah charged each billing period.
PLAN_PRICES: dict[PaidPlanCode, dict[SubscriptionPeriod, int]] = {
    PaidPlanCode.BASIC: {
        SubscriptionPeriod.MONTHLY: 49000,
        SubscriptionPeriod.YEARLY: 490000,
    },
    PaidPlanCode.PRO: {
        SubscriptionPeriod.MONTHLY: 129000,
        SubscriptionPeriod.YEARLY: 1290000,
    },
}

GOOGLE_PLAY_PRODUCT_IDS: dict[PaidPlanCode, str] = {
    PaidPlanCode.BASIC: "niscala_basic",
    PaidPlanCode.PRO: "niscala_pro",
}

GOOGLE_PLAY_BASE_PLAN_IDS: dict[SubscriptionPeriod, str] = {
    SubscriptionPeriod.MONTHLY: "monthly",
    SubscriptionPeriod.YEARLY: "yearly",
}
