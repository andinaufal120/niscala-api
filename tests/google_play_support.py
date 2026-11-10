"""Helpers shared by the Google Play purchase, notification and reconcile tests."""

import base64
import dataclasses
import importlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

PACKAGE = "com.niscala.app"
AUDIENCE = "https://api.example.com/internal/google-play/notifications"
SERVICE_ACCOUNT = "pubsub-push@niscala-test.iam.gserviceaccount.com"
NOTIFICATIONS_URL = "/internal/google-play/notifications"
GOOD_BEARER = "pubsub-jwt-good"

PRODUCT_OF_PLAN = {"basic": "niscala_basic", "pro": "niscala_pro"}

# Google states that keep a paid plan running (when not past expiry), and the rest.
RUNNING_STATES = ["ACTIVE", "IN_GRACE_PERIOD"]
ENDED_STATES = ["EXPIRED", "ON_HOLD", "PAUSED", "PENDING_PURCHASE_CANCELED"]


def now() -> datetime:
    return datetime.now(UTC)


def verification_url(order_id) -> str:
    return f"/subscription/orders/{order_id}/purchase-verification"


def verify(client, headers, order_id, token: str = "play-token-1"):
    return client.post(
        verification_url(order_id), json={"purchaseToken": token}, headers=headers
    )


class FakeGooglePlay:
    """A Google Play client that knows a fixed set of purchases.

    `add` registers a purchase under its token. `fetched` records every token
    asked for and `acknowledged` every successful `(product_id, token)`
    acknowledgement; `acknowledge_attempts` also holds failed ones.
    `unreachable` makes every call raise `GooglePlayUnreachable`;
    `unreachable_tokens` only the calls for those tokens; `acknowledge_fails`
    only the acknowledgements. A token that was never added is not found.
    """

    def __init__(self) -> None:
        self.purchases: dict[str, Any] = {}
        self.fetched: list[str] = []
        self.acknowledged: list[tuple[str, str]] = []
        self.acknowledge_attempts: list[tuple[str, str]] = []
        self.unreachable = False
        self.unreachable_tokens: set[str] = set()
        self.acknowledge_fails = False

    def add(self, token: str, **fields: Any) -> Any:
        from app.google_play import PlaySubscription

        values: dict[str, Any] = {
            "state": "ACTIVE",
            "product_id": "niscala_basic",
            "base_plan_id": "monthly",
            "expiry_time": now() + timedelta(days=30),
            "auto_renewing": True,
            "acknowledged": False,
            "obfuscated_account_id": None,
            "linked_purchase_token": None,
        }
        values.update(fields)
        owner = values.pop("owner", None)
        if owner is not None:
            values["obfuscated_account_id"] = str(owner.id)
        purchase = PlaySubscription(**values)
        self.purchases[token] = purchase
        return purchase

    def change(self, token: str, **fields: Any) -> None:
        self.purchases[token] = dataclasses.replace(self.purchases[token], **fields)

    def get_subscription(self, token: str) -> Any:
        from app.google_play import GooglePlayUnreachable, PurchaseNotFound

        self.fetched.append(token)
        if self.unreachable or token in self.unreachable_tokens:
            raise GooglePlayUnreachable("Google Play is down")
        if token not in self.purchases:
            raise PurchaseNotFound(token)
        return self.purchases[token]

    def acknowledge(self, product_id: str, token: str) -> None:
        from app.google_play import GooglePlayUnreachable, PurchaseNotFound

        self.acknowledge_attempts.append((product_id, token))
        if self.unreachable or self.acknowledge_fails:
            raise GooglePlayUnreachable("Google Play is down")
        if token not in self.purchases:
            raise PurchaseNotFound(token)
        self.acknowledged.append((product_id, token))
        self.change(token, acknowledged=True)


class FakePubSubVerifier:
    """Stands in for the check of the Pub/Sub push token.

    `add` registers a token and the claims it carries; any other token is
    rejected with a ValueError, as the Google library does. Every token passed
    to `verify` is recorded in `verified`.
    """

    def __init__(self) -> None:
        self.claims: dict[str, dict[str, Any]] = {}
        self.verified: list[str] = []

    def add(self, token: str, **claims: Any) -> None:
        self.claims[token] = {
            "email": SERVICE_ACCOUNT,
            "email_verified": True,
            "aud": AUDIENCE,
            **claims,
        }

    def verify(self, token: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.verified.append(token)
        if token not in self.claims:
            raise ValueError("Could not verify token signature.")
        return self.claims[token]


def pubsub_verifier_getter():
    """The dependency function that supplies the Pub/Sub token verifier."""
    for module_name in ("app.google_play", "app.google", "app.routers.google_play"):
        module = importlib.import_module(module_name)
        found = getattr(module, "get_pubsub_token_verifier", None)
        if found is not None:
            return found
    raise AssertionError("get_pubsub_token_verifier is not defined")


# Pub/Sub push messages


def envelope(notification: Any, **message: Any) -> dict[str, Any]:
    """A Pub/Sub push body carrying `notification` as its base64 JSON data."""
    raw = notification if isinstance(notification, bytes) else None
    if raw is None:
        raw = json.dumps(notification).encode()
    return {
        "message": {
            "data": base64.b64encode(raw).decode(),
            "messageId": "1234567890",
            **message,
        },
        "subscription": "projects/niscala-test/subscriptions/play-push",
    }


def subscription_message(
    token: str, *, notification_type: int = 2, package: str = PACKAGE
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "packageName": package,
        "eventTimeMillis": "1700000000000",
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": notification_type,
            "purchaseToken": token,
            "subscriptionId": "niscala_basic",
        },
    }


def push(client, body: Any, bearer: str | None = GOOD_BEARER):
    headers = {} if bearer is None else {"Authorization": f"Bearer {bearer}"}
    if isinstance(body, dict):
        return client.post(NOTIFICATIONS_URL, json=body, headers=headers)
    return client.post(NOTIFICATIONS_URL, content=body, headers=headers)


# Stored rows


def edit_order(database, order_id, **columns: Any) -> None:
    from app.models import SubscriptionOrder

    with Session(database) as db:
        row = db.get(SubscriptionOrder, UUID(str(order_id)))
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def set_token(database, owner, token: str) -> None:
    from app.models import Subscription

    with Session(database) as db:
        db.get(Subscription, owner.id).purchase_token = token
        db.commit()


def subscription_state(database, owner) -> tuple | None:
    """The stored subscription of an owner as a tuple, or None without a row."""
    from app.models import Subscription

    with Session(database) as db:
        row = db.get(Subscription, owner.id)
        if row is None:
            return None
        return (
            row.plan,
            row.billing_period,
            row.ends_at,
            row.auto_renew,
            row.purchase_token,
        )


def all_orders(database) -> list[tuple]:
    from app.models import SubscriptionOrder

    with Session(database) as db:
        return [
            (o.id, o.status, o.purchase_token)
            for o in db.scalars(
                select(SubscriptionOrder).order_by(SubscriptionOrder.created_at)
            )
        ]


def everything(database) -> dict[str, Any]:
    """Subscriptions and orders of all owners, to compare before and after."""
    from app.models import Subscription

    with Session(database) as db:
        rows = [
            (s.owner_id, s.plan, s.billing_period, s.ends_at, s.auto_renew)
            for s in db.scalars(select(Subscription).order_by(Subscription.owner_id))
        ]
    return {"subscriptions": rows, "orders": all_orders(database)}


def current_plan_of(database, owner) -> str:
    from app.services.subscriptions import current_plan

    with Session(database) as db:
        return current_plan(db, owner.id).value


def sync(database, play, token: str) -> None:
    from app.services.subscriptions import sync_purchase

    with Session(database) as db:
        sync_purchase(db, play, token)
        db.commit()
