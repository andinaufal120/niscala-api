"""Steps shared by the subscription, downgrade and Admin account scenarios.

Everything goes through the public HTTP API, except what the callers do with the
shared `expire_subscription` and `rtdn` fixtures: ending a paid period and
authenticating Google Play notifications have no endpoint to drive.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from google_play_support import GOOD_BEARER, envelope, push, subscription_message

from e2e.e2e_people import Owner
from e2e.e2e_rent import JAKARTA

ORDERS = "/subscription/orders"
DOWNGRADE = "/subscription/scheduled-downgrade"
OWNER_ONLY_REQUESTS = [
    ("GET", "/subscription-plans", None),
    ("GET", "/subscription", None),
    ("POST", ORDERS, {"planCode": "basic", "billingPeriod": "monthly"}),
    ("GET", f"{ORDERS}/00000000-0000-4000-8000-000000000001", None),
    (
        "POST",
        f"{ORDERS}/00000000-0000-4000-8000-000000000001/purchase-verification",
        {"purchaseToken": "any"},
    ),
    (
        "PUT",
        DOWNGRADE,
        {"planCode": "free", "keptPropertyIds": [], "keptRoomIds": []},
    ),
    ("DELETE", DOWNGRADE, None),
]


def place_order(owner: Owner, plan: str = "basic", period: str = "monthly") -> dict:
    """Start an order for a paid plan and return it."""
    return owner.post(
        ORDERS, json={"planCode": plan, "billingPeriod": period}, expect=201
    ).json()


def order_of(owner: Owner, order: dict) -> dict:
    return owner.read(f"{ORDERS}/{order['id']}")


def send_token(owner: Owner, order: dict, token: str):
    """Send a purchase token for an order and return the raw answer."""
    return owner.post(
        f"{ORDERS}/{order['id']}/purchase-verification",
        json={"purchaseToken": token},
    )


def last_token(world) -> str:
    """The purchase token the Play stub learned about most recently."""
    return list(world.stubs.play.purchases)[-1]


def play_end_date(world, token: str) -> str:
    """The last paid day, in Asia/Jakarta, of the purchase the Play stub holds."""
    expiry = world.stubs.play.purchases[token].expiry_time
    return expiry.astimezone(JAKARTA).date().isoformat()


def days_from_now(days: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def play_plan_change(
    world, owner: Owner, old_token: str, plan: str, period: str = "monthly"
) -> str:
    """Let Google move the owner to another plan at renewal and return the new token.

    Google gives the renewed purchase a new token linked to the previous one.
    The app does not call the API for it; a notification does (`notify_play`).
    """
    token = f"{old_token}-renewed-as-{plan}"
    world.stubs.play.add(
        token,
        product_id=f"niscala_{plan}",
        base_plan_id=period,
        obfuscated_account_id=str(owner.user_id),
        linked_purchase_token=old_token,
        acknowledged=True,
        expiry_time=days_from_now(30 if period == "monthly" else 365),
    )
    return token


def end_in_play(world, token: str) -> None:
    """Make Google report the purchase as ended, with its period over, as a refund would."""
    world.stubs.play.change(
        token, state="EXPIRED", expiry_time=days_from_now(-1), auto_renewing=False
    )


def notify_play(world, token: str, *, bearer: str | None = GOOD_BEARER):
    """Deliver a real-time notification about a purchase and return the raw answer."""
    return push(world.client, envelope(subscription_message(token)), bearer)


def schedule_downgrade(
    owner: Owner,
    plan: str,
    kept_properties: list,
    kept_rooms: list | None = None,
):
    """Confirm a downgrade and return the raw answer.

    Properties and rooms may be records returned by the API or ids.
    """
    return owner.put(
        DOWNGRADE,
        json={
            "planCode": plan,
            "keptPropertyIds": [_id(item) for item in kept_properties],
            "keptRoomIds": [_id(item) for item in kept_rooms or []],
        },
    )


def _id(thing) -> str:
    return thing["id"] if isinstance(thing, dict) else str(thing)


def by_name(items: list[dict]) -> dict[str, dict]:
    return {item["name"]: item for item in items}


def by_number(items: list[dict]) -> dict[str, dict]:
    return {item["number"]: item for item in items}


def editable_numbers(rooms: list[dict], editable: bool) -> list[str]:
    """The numbers of the rooms whose `editable` flag is as given, sorted."""
    return sorted(room["number"] for room in rooms if room["editable"] is editable)


def day_after(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()


def property_body(prop: dict, **changes) -> dict:
    """The full edit request of a property, as read from the property."""
    body = {"name": prop["name"], "address": prop["address"]}
    if prop.get("bankAccount") is not None:
        body["bankAccount"] = prop["bankAccount"]
    body.update(changes)
    return body


def room_body(room: dict, **changes) -> dict:
    """The full edit request of a room, as read from the room."""
    body = {
        "number": room["number"],
        "baseRate": room["baseRate"],
        "facilities": room["facilities"],
    }
    body.update(changes)
    return body


def unknown_id() -> str:
    return str(UUID(int=0x1234567890))
