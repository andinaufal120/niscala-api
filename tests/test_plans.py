"""The limits each subscription plan grants."""

import dataclasses

import pytest

from app.schemas.subscriptions import PlanCode


def test_every_plan_has_limits():
    from app.plans import PLAN_LIMITS

    assert set(PLAN_LIMITS) == set(PlanCode)


@pytest.mark.parametrize(
    ("plan", "max_properties", "max_rooms_per_property", "ai_enabled"),
    [
        (PlanCode.FREE, 1, 15, False),
        (PlanCode.BASIC, 3, None, True),
        (PlanCode.PRO, None, None, True),
    ],
)
def test_plan_grants_its_limits(
    plan, max_properties, max_rooms_per_property, ai_enabled
):
    from app.plans import PLAN_LIMITS

    limits = PLAN_LIMITS[plan]
    assert limits.max_properties == max_properties
    assert limits.max_rooms_per_property == max_rooms_per_property
    assert limits.ai_enabled is ai_enabled


def test_limits_equal_when_their_fields_are_equal():
    from app.plans import PlanLimits

    assert PlanLimits(1, 15, False) == PlanLimits(
        max_properties=1, max_rooms_per_property=15, ai_enabled=False
    )


def test_limits_are_immutable():
    from app.plans import PLAN_LIMITS

    with pytest.raises(dataclasses.FrozenInstanceError):
        PLAN_LIMITS[PlanCode.FREE].max_properties = 99
