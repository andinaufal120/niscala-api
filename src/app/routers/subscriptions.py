"""Endpoints under /subscription and /subscription-plans. Purchase verification is declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.subscriptions import (
    PurchaseVerificationInput,
    ScheduledDowngrade,
    ScheduledDowngradeInput,
    Subscription,
    SubscriptionOrder,
    SubscriptionOrderInput,
    SubscriptionPlanList,
)
from app.security import CurrentUser
from app.services import subscriptions

router = APIRouter(prefix="/subscription", tags=["subscriptions"])
plans_router = APIRouter(prefix="/subscription-plans", tags=["subscriptions"])

OrderId = Annotated[UUID, Path(alias="orderId")]
Db = SessionDep
OwnerOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER))]


@plans_router.get("")
def list_subscription_plans(owner: OwnerOnly) -> SubscriptionPlanList:
    """List the available plans with limits, AI availability and prices."""
    return subscriptions.list_plans()


@router.get("")
def get_subscription(owner: OwnerOnly, db: Db) -> Subscription:
    """Return the Owner's current subscription."""
    return subscriptions.get_subscription(db, owner.user)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_subscription_order(
    body: SubscriptionOrderInput, owner: OwnerOnly, db: Db
) -> SubscriptionOrder:
    """Start a purchase of a paid plan; the order expires if no purchase completes."""
    return subscriptions.create_order(db, owner.user, body)


@router.get("/orders/{orderId}")
def get_subscription_order(
    order_id: OrderId, owner: OwnerOnly, db: Db
) -> SubscriptionOrder:
    """Return an order with its status."""
    return subscriptions.get_order(db, owner.user, order_id)


@router.post("/orders/{orderId}/purchase-verification")
def verify_subscription_purchase(
    order_id: OrderId, body: PurchaseVerificationInput
) -> SubscriptionOrder:
    """Verify the Google Play purchase token of an order and update the order and subscription."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/scheduled-downgrade")
def schedule_subscription_downgrade(
    body: ScheduledDowngradeInput, owner: OwnerOnly, db: Db
) -> ScheduledDowngrade:
    """Confirm a downgrade at the end of the paid period and the properties and rooms that stay editable."""
    return subscriptions.schedule_downgrade(db, owner.user, body)


@router.delete(
    "/scheduled-downgrade",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def cancel_subscription_downgrade(owner: OwnerOnly, db: Db) -> None:
    """Cancel the scheduled downgrade."""
    subscriptions.cancel_downgrade(db, owner.user)
