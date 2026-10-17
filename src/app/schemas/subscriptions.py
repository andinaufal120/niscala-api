"""Schemas for subscription plans, orders, the current subscription and scheduled downgrades."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel


class PlanCode(StrEnum):
    """Subscription plans."""

    FREE = "free"
    BASIC = "basic"
    PRO = "pro"


class PaidPlanCode(StrEnum):
    """Plans that can be bought."""

    BASIC = "basic"
    PRO = "pro"


class SubscriptionPeriod(StrEnum):
    """How often a paid plan is billed."""

    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionStatus(StrEnum):
    """Whether a paid period is running."""

    FREE = "free"
    ACTIVE = "active"


class OrderStatus(StrEnum):
    """Progress of a subscription order."""

    AWAITING_PAYMENT = "awaitingPayment"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class SubscriptionPlanPrice(ApiModel):
    """The price of a paid plan for one billing period."""

    billing_period: SubscriptionPeriod
    amount: int = Field(gt=0, description="In rupiah, charged each billing period.")
    google_play_product_id: str
    google_play_base_plan_id: str


class SubscriptionPlan(ApiModel):
    """A plan with its limits, AI availability and prices."""

    code: PlanCode
    max_properties: int | None = Field(description="Null means unlimited.")
    max_rooms_per_property: int | None = Field(description="Null means unlimited.")
    ai_enabled: bool
    prices: list[SubscriptionPlanPrice] = Field(description="Empty for the free plan.")


class SubscriptionPlanList(ApiModel):
    """Available plans, ordered free, basic, pro."""

    items: list[SubscriptionPlan]


class ScheduledDowngrade(ApiModel):
    """A downgrade that takes effect when the paid period ends."""

    plan_code: PlanCode = Field(description="The plan that applies from effectiveDate.")
    effective_date: date = Field(description="The day after the paid period ends.")
    kept_property_ids: list[UUID]
    kept_room_ids: list[UUID] = Field(
        description="Rooms of the single kept property; empty unless planCode is free."
    )


class ScheduledDowngradeInput(ApiModel):
    """The properties and rooms that stay editable after a downgrade."""

    plan_code: PlanCode = Field(
        description="free or basic; must be lower than the current plan."
    )
    kept_property_ids: list[UUID] = Field(
        description=(
            "Exactly the target plan's property limit, or all properties if the "
            "Owner has fewer. No duplicates."
        )
    )
    kept_room_ids: list[UUID] = Field(
        default=[],
        description=(
            "Only for free: exactly 15 rooms of the kept property, or all its "
            "rooms if it has fewer. Must be empty otherwise."
        ),
    )


class SubscriptionOrderInput(ApiModel):
    """The paid plan and billing period to buy."""

    plan_code: PaidPlanCode
    billing_period: SubscriptionPeriod


class SubscriptionOrder(ApiModel):
    """An attempt to buy a paid plan through Google Play."""

    id: UUID
    plan_code: PaidPlanCode
    billing_period: SubscriptionPeriod
    status: OrderStatus
    google_play_product_id: str
    google_play_base_plan_id: str
    obfuscated_account_id: str = Field(
        description=(
            "Opaque id the app passes to Google Play Billing when it starts the "
            "purchase, so the purchase can be tied to this Owner."
        )
    )
    created_at: datetime


class PurchaseVerificationInput(ApiModel):
    """The Google Play purchase token to verify for an order."""

    purchase_token: str = Field(
        min_length=1,
        description="The token Google Play Billing returned for the purchase.",
    )


class Subscription(ApiModel):
    """The Owner's current subscription. The status is free exactly when the plan is free."""

    plan_code: PlanCode
    status: SubscriptionStatus
    billing_period: SubscriptionPeriod | None = Field(
        description="Null when status is free."
    )
    end_date: date | None = Field(
        description="Last day of the paid period; null when status is free."
    )
    auto_renew: bool = Field(
        description=(
            "False when the Owner cancelled renewal in Google Play; the plan "
            "stays active until endDate."
        )
    )
    property_count: int = Field(
        description="Properties the Owner has, view-only ones included."
    )
    open_order: SubscriptionOrder | None = Field(
        description="The order awaiting payment, if any."
    )
    scheduled_downgrade: ScheduledDowngrade | None
