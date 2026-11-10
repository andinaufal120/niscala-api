"""Reading and acknowledging Google Play subscription purchases, and checking Pub/Sub push tokens."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Any, Protocol
from urllib.parse import quote

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google.oauth2 import service_account

from app.config import get_settings

API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
TIMEOUT_SECONDS = 10
STATE_PREFIX = "SUBSCRIPTION_STATE_"


class PurchaseNotFound(Exception):
    """Google Play does not know the purchase token, or it is gone."""


class GooglePlayUnreachable(Exception):
    """Google Play could not be asked or gave an answer that cannot be used."""


@dataclass(frozen=True)
class PlaySubscription:
    """A subscription purchase as Google Play reports it.

    `state` is Google's subscription state without its prefix, such as ACTIVE,
    CANCELED or EXPIRED.
    """

    state: str
    product_id: str
    base_plan_id: str
    expiry_time: datetime
    auto_renewing: bool
    acknowledged: bool
    obfuscated_account_id: str | None
    linked_purchase_token: str | None


class GooglePlay(Protocol):
    """Reads and acknowledges subscription purchases."""

    def get_subscription(self, token: str) -> PlaySubscription:
        """Return the purchase.

        Raises PurchaseNotFound for an unknown token and GooglePlayUnreachable
        when Google Play cannot be reached or answers with an error.
        """
        ...

    def acknowledge(self, product_id: str, token: str) -> None:
        """Acknowledge the purchase; raises like `get_subscription`."""
        ...


def _parse(body: dict[str, Any]) -> PlaySubscription:
    line = (body.get("lineItems") or [{}])[0]
    # A purchase that is still pending may not carry an expiry yet; the epoch
    # means "no paid period".
    expiry = datetime.fromisoformat(line.get("expiryTime") or "1970-01-01T00:00:00Z")
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    accounts = body.get("externalAccountIdentifiers") or {}
    return PlaySubscription(
        state=body["subscriptionState"].removeprefix(STATE_PREFIX),
        product_id=line.get("productId", ""),
        base_plan_id=(line.get("offerDetails") or {}).get("basePlanId", ""),
        expiry_time=expiry,
        auto_renewing=(line.get("autoRenewingPlan") or {}).get("autoRenewEnabled")
        is True,
        acknowledged=body.get("acknowledgementState")
        == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        obfuscated_account_id=accounts.get("obfuscatedExternalAccountId"),
        linked_purchase_token=body.get("linkedPurchaseToken"),
    )


class AndroidPublisherGooglePlay:
    """Talks to the Android Publisher REST API through an authorized session."""

    def __init__(self, package_name: str, session: Any) -> None:
        self.package_name = package_name
        self.session = session

    def _url(self, path: str) -> str:
        return f"{API_BASE}/{self.package_name}/purchases/{path}"

    def _check(self, response: Any) -> None:
        if response.status_code in (404, 410):
            raise PurchaseNotFound
        if response.status_code >= 400:
            raise GooglePlayUnreachable(f"Google Play answered {response.status_code}")

    def get_subscription(self, token: str) -> PlaySubscription:
        url = self._url(f"subscriptionsv2/tokens/{quote(token, safe='')}")
        try:
            response = self.session.get(url, timeout=TIMEOUT_SECONDS)
            self._check(response)
            return _parse(response.json())
        except PurchaseNotFound, GooglePlayUnreachable:
            raise
        except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
            raise GooglePlayUnreachable(str(error)) from error

    def acknowledge(self, product_id: str, token: str) -> None:
        url = self._url(
            f"subscriptions/{quote(product_id, safe='')}"
            f"/tokens/{quote(token, safe='')}:acknowledge"
        )
        try:
            self._check(self.session.post(url, json={}, timeout=TIMEOUT_SECONDS))
        except PurchaseNotFound, GooglePlayUnreachable:
            raise
        except OSError as error:
            raise GooglePlayUnreachable(str(error)) from error


class UnavailableGooglePlay:
    """Stands in when Google Play is not configured; every call fails."""

    def get_subscription(self, token: str) -> PlaySubscription:
        raise GooglePlayUnreachable("Google Play is not configured")

    def acknowledge(self, product_id: str, token: str) -> None:
        raise GooglePlayUnreachable("Google Play is not configured")


@cache
def _android_publisher(
    package_name: str, credentials: str
) -> AndroidPublisherGooglePlay:
    account = service_account.Credentials.from_service_account_info(
        json.loads(credentials), scopes=SCOPES
    )
    return AndroidPublisherGooglePlay(
        package_name, google_requests.AuthorizedSession(account)
    )


def get_google_play() -> GooglePlay:
    """Return the Android Publisher client when configured, else the unavailable one."""
    settings = get_settings()
    package_name = (settings.google_play_package_name or "").strip()
    credentials = (settings.google_play_credentials or "").strip()
    if not package_name or not credentials:
        return UnavailableGooglePlay()
    return _android_publisher(package_name, credentials)


class PubSubTokenVerifier:
    """Verifies the OIDC token Pub/Sub attaches to its pushes."""

    def __init__(self, audience: str | None) -> None:
        self.audience = audience

    def verify(self, token: str) -> dict[str, Any]:
        """Return the claims of the token; raises when it cannot be trusted."""
        return google_id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=self.audience
        )


def get_pubsub_token_verifier() -> PubSubTokenVerifier:
    """Return a verifier for the audience in the settings."""
    return PubSubTokenVerifier(get_settings().google_play_rtdn_audience)
