"""Endpoints under /subscription and /subscription-plans. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.subscriptions import (
    PurchaseVerificationInput,
    ScheduledDowngrade,
    ScheduledDowngradeInput,
    Subscription,
    SubscriptionOrder,
    SubscriptionOrderInput,
    SubscriptionPlanList,
)

router = APIRouter(prefix="/subscription", tags=["subscriptions"])
plans_router = APIRouter(prefix="/subscription-plans", tags=["subscriptions"])

OrderId = Annotated[UUID, Path(alias="orderId")]


@plans_router.get("")
def list_subscription_plans() -> SubscriptionPlanList:
    """List the available plans with limits, AI availability and prices."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("")
def get_subscription() -> Subscription:
    """Return the Owner's current subscription."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_subscription_order(body: SubscriptionOrderInput) -> SubscriptionOrder:
    """Start a purchase of a paid plan; the order expires if no purchase completes."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/orders/{orderId}")
def get_subscription_order(order_id: OrderId) -> SubscriptionOrder:
    """Return an order with its status."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/orders/{orderId}/purchase-verification")
def verify_subscription_purchase(
    order_id: OrderId, body: PurchaseVerificationInput
) -> SubscriptionOrder:
    """Verify the Google Play purchase token of an order and update the order and subscription."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/scheduled-downgrade")
def schedule_subscription_downgrade(
    body: ScheduledDowngradeInput,
) -> ScheduledDowngrade:
    """Confirm a downgrade at the end of the paid period and the properties and rooms that stay editable."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/scheduled-downgrade",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def cancel_subscription_downgrade() -> None:
    """Cancel the scheduled downgrade."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
