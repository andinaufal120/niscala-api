"""The limits each subscription plan grants."""

from dataclasses import dataclass

from app.schemas.subscriptions import PlanCode


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
