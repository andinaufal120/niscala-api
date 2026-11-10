"""The Google Play client, its settings and the dependency that supplies it."""

import dataclasses
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

PACKAGE = "com.niscala.app"
BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
TOKEN = "purchase-token-abc"
GET_URL = f"{BASE}/{PACKAGE}/purchases/subscriptionsv2/tokens/{TOKEN}"
ACK_URL = (
    f"{BASE}/{PACKAGE}/purchases/subscriptions/niscala_basic/tokens/{TOKEN}:acknowledge"
)
CREDENTIALS = '{"type": "service_account", "project_id": "niscala-test"}'


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status_code = status
        self._body = {} if body is None else body
        self.text = str(self._body)
        self.content = b"" if body is None else b"{}"
        self.ok = status < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Records requests and answers them with a prepared response or error."""

    def __init__(self, response: Any = None) -> None:
        self.response = response if response is not None else FakeResponse()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _answer(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((method.upper(), url, kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._answer("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._answer("POST", url, kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._answer(method, url, kwargs)


def google_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "androidpublisher#subscriptionPurchaseV2",
        "startTime": "2026-01-01T00:00:00Z",
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "externalAccountIdentifiers": {"obfuscatedExternalAccountId": "owner-1"},
        "lineItems": [
            {
                "productId": "niscala_basic",
                "expiryTime": "2026-12-01T10:30:15.250Z",
                "autoRenewingPlan": {"autoRenewEnabled": True},
                "offerDetails": {"basePlanId": "monthly"},
            }
        ],
    }
    body.update(overrides)
    return body


def client_with(response: Any = None):
    from app.google_play import AndroidPublisherGooglePlay

    session = FakeSession(response)
    return AndroidPublisherGooglePlay(PACKAGE, session), session


def fetch(body: dict[str, Any] | None = None):
    client, session = client_with(FakeResponse(200, body or google_body()))
    return client.get_subscription(TOKEN), session


# Settings


@pytest.mark.parametrize(
    "name",
    [
        "google_play_package_name",
        "google_play_credentials",
        "google_play_rtdn_audience",
        "google_play_rtdn_service_account",
    ],
)
def test_google_play_settings_are_unset_by_default(monkeypatch, name):
    from app.config import Settings

    for variable in (
        "GOOGLE_PLAY_PACKAGE_NAME",
        "GOOGLE_PLAY_CREDENTIALS",
        "GOOGLE_PLAY_RTDN_AUDIENCE",
        "GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(variable, raising=False)
    assert getattr(Settings(_env_file=None), name) is None


@pytest.mark.parametrize(
    ("variable", "name"),
    [
        ("GOOGLE_PLAY_PACKAGE_NAME", "google_play_package_name"),
        ("GOOGLE_PLAY_CREDENTIALS", "google_play_credentials"),
        ("GOOGLE_PLAY_RTDN_AUDIENCE", "google_play_rtdn_audience"),
        ("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT", "google_play_rtdn_service_account"),
    ],
)
def test_google_play_settings_are_read_from_the_environment(
    monkeypatch, variable, name
):
    from app.config import Settings

    monkeypatch.setenv(variable, "some-value")
    assert getattr(Settings(_env_file=None), name) == "some-value"


# The purchase as the application sees it


def test_a_play_subscription_holds_the_fields_of_a_purchase():
    from app.google_play import PlaySubscription

    expiry = datetime(2026, 12, 1, tzinfo=UTC)
    purchase = PlaySubscription(
        state="ACTIVE",
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
        auto_renewing=True,
        acknowledged=False,
        obfuscated_account_id="owner-1",
        linked_purchase_token="old-token",
    )
    assert dataclasses.is_dataclass(purchase)
    assert purchase.state == "ACTIVE"
    assert purchase.product_id == "niscala_pro"
    assert purchase.base_plan_id == "yearly"
    assert purchase.expiry_time == expiry
    assert purchase.auto_renewing is True
    assert purchase.acknowledged is False
    assert purchase.obfuscated_account_id == "owner-1"
    assert purchase.linked_purchase_token == "old-token"


def test_the_client_protocol_declares_both_calls():
    from app.google_play import GooglePlay

    assert callable(getattr(GooglePlay, "get_subscription", None))
    assert callable(getattr(GooglePlay, "acknowledge", None))


def test_the_failures_are_exceptions_of_their_own():
    from app.google_play import GooglePlayUnreachable, PurchaseNotFound

    assert issubclass(PurchaseNotFound, Exception)
    assert issubclass(GooglePlayUnreachable, Exception)
    assert not issubclass(PurchaseNotFound, GooglePlayUnreachable)
    assert not issubclass(GooglePlayUnreachable, PurchaseNotFound)


# Fetching a purchase over REST


def test_fetching_asks_the_subscriptions_v2_endpoint_for_the_token():
    _, session = fetch()
    ((method, url, _),) = session.calls
    assert method == "GET"
    assert url == GET_URL


def test_fetching_times_out_after_ten_seconds():
    _, session = fetch()
    ((_, _, kwargs),) = session.calls
    assert kwargs.get("timeout") == 10


def test_fetching_maps_the_fields_of_the_purchase():
    purchase, _ = fetch()
    assert purchase.state == "ACTIVE"
    assert purchase.product_id == "niscala_basic"
    assert purchase.base_plan_id == "monthly"
    assert purchase.expiry_time == datetime(2026, 12, 1, 10, 30, 15, 250000, tzinfo=UTC)
    assert purchase.auto_renewing is True
    assert purchase.acknowledged is True
    assert purchase.obfuscated_account_id == "owner-1"
    assert purchase.linked_purchase_token is None


@pytest.mark.parametrize(
    "state",
    [
        "ACTIVE",
        "IN_GRACE_PERIOD",
        "CANCELED",
        "PENDING",
        "PENDING_PURCHASE_CANCELED",
        "EXPIRED",
        "ON_HOLD",
        "PAUSED",
    ],
)
def test_fetching_keeps_the_state_without_its_prefix(state):
    purchase, _ = fetch(google_body(subscriptionState=f"SUBSCRIPTION_STATE_{state}"))
    assert purchase.state == state


def test_the_expiry_is_timezone_aware_whatever_the_offset_written():
    body = google_body()
    body["lineItems"][0]["expiryTime"] = "2026-12-01T17:30:15+07:00"
    purchase, _ = fetch(body)
    assert purchase.expiry_time.tzinfo is not None
    assert purchase.expiry_time == datetime(2026, 12, 1, 10, 30, 15, tzinfo=UTC)


def test_a_missing_auto_renewing_plan_means_not_renewing():
    body = google_body()
    del body["lineItems"][0]["autoRenewingPlan"]
    purchase, _ = fetch(body)
    assert purchase.auto_renewing is False


def test_auto_renew_switched_off_means_not_renewing():
    body = google_body()
    body["lineItems"][0]["autoRenewingPlan"] = {"autoRenewEnabled": False}
    purchase, _ = fetch(body)
    assert purchase.auto_renewing is False


def test_an_auto_renewing_plan_without_the_flag_means_not_renewing():
    body = google_body()
    body["lineItems"][0]["autoRenewingPlan"] = {}
    purchase, _ = fetch(body)
    assert purchase.auto_renewing is False


def test_a_pending_acknowledgement_means_not_acknowledged():
    purchase, _ = fetch(
        google_body(acknowledgementState="ACKNOWLEDGEMENT_STATE_PENDING")
    )
    assert purchase.acknowledged is False


def test_a_missing_acknowledgement_state_means_not_acknowledged():
    body = google_body()
    del body["acknowledgementState"]
    purchase, _ = fetch(body)
    assert purchase.acknowledged is False


def test_a_missing_account_identifier_is_none():
    body = google_body()
    del body["externalAccountIdentifiers"]
    purchase, _ = fetch(body)
    assert purchase.obfuscated_account_id is None


def test_account_identifiers_without_the_obfuscated_id_give_none():
    purchase, _ = fetch(google_body(externalAccountIdentifiers={}))
    assert purchase.obfuscated_account_id is None


def test_the_linked_purchase_token_is_passed_on():
    purchase, _ = fetch(google_body(linkedPurchaseToken="previous-token"))
    assert purchase.linked_purchase_token == "previous-token"


@pytest.mark.parametrize("status", [404, 410])
def test_an_unknown_or_gone_purchase_is_not_found(status):
    from app.google_play import PurchaseNotFound

    client, _ = client_with(FakeResponse(status, {"error": {"code": status}}))
    with pytest.raises(PurchaseNotFound):
        client.get_subscription(TOKEN)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 503])
def test_any_other_error_status_means_unreachable_when_fetching(status):
    from app.google_play import GooglePlayUnreachable

    client, _ = client_with(FakeResponse(status, {"error": {"code": status}}))
    with pytest.raises(GooglePlayUnreachable):
        client.get_subscription(TOKEN)


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("timed out"),
        requests.ConnectionError("no route"),
        OSError("socket closed"),
    ],
    ids=["timeout", "connection", "os"],
)
def test_a_network_failure_means_unreachable_when_fetching(error):
    from app.google_play import GooglePlayUnreachable

    client, _ = client_with(error)
    with pytest.raises(GooglePlayUnreachable):
        client.get_subscription(TOKEN)


def test_an_unreadable_answer_means_unreachable():
    from app.google_play import GooglePlayUnreachable

    class Broken(FakeResponse):
        def json(self):
            raise ValueError("not json")

    client, _ = client_with(Broken(200, {}))
    with pytest.raises(GooglePlayUnreachable):
        client.get_subscription(TOKEN)


# Acknowledging over REST


def test_acknowledging_posts_to_the_acknowledge_endpoint_of_the_product():
    client, session = client_with(FakeResponse(204))
    assert client.acknowledge("niscala_basic", TOKEN) is None
    ((method, url, kwargs),) = session.calls
    assert method == "POST"
    assert url == ACK_URL
    assert kwargs.get("timeout") == 10


def test_acknowledging_uses_the_product_it_is_given():
    client, session = client_with(FakeResponse(204))
    client.acknowledge("niscala_pro", TOKEN)
    ((_, url, _),) = session.calls
    assert url == (
        f"{BASE}/{PACKAGE}/purchases/subscriptions/niscala_pro"
        f"/tokens/{TOKEN}:acknowledge"
    )


@pytest.mark.parametrize("status", [404, 410])
def test_acknowledging_an_unknown_or_gone_purchase_is_not_found(status):
    from app.google_play import PurchaseNotFound

    client, _ = client_with(FakeResponse(status, {"error": {"code": status}}))
    with pytest.raises(PurchaseNotFound):
        client.acknowledge("niscala_basic", TOKEN)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_any_other_error_status_means_unreachable_when_acknowledging(status):
    from app.google_play import GooglePlayUnreachable

    client, _ = client_with(FakeResponse(status, {"error": {"code": status}}))
    with pytest.raises(GooglePlayUnreachable):
        client.acknowledge("niscala_basic", TOKEN)


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("timed out"), requests.ConnectionError("no route")],
    ids=["timeout", "connection"],
)
def test_a_network_failure_means_unreachable_when_acknowledging(error):
    from app.google_play import GooglePlayUnreachable

    client, _ = client_with(error)
    with pytest.raises(GooglePlayUnreachable):
        client.acknowledge("niscala_basic", TOKEN)


# The client used when Google Play is not configured


def test_the_unavailable_client_is_always_unreachable():
    from app.google_play import GooglePlayUnreachable, UnavailableGooglePlay

    client = UnavailableGooglePlay()
    with pytest.raises(GooglePlayUnreachable):
        client.get_subscription(TOKEN)
    with pytest.raises(GooglePlayUnreachable):
        client.acknowledge("niscala_basic", TOKEN)


# The dependency that supplies the client


@pytest.fixture
def play_settings(monkeypatch):
    """Control the Google Play settings for one test; no arguments unsets them."""
    from app import google_play
    from app.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)

    def forget() -> None:
        get_settings.cache_clear()
        for value in vars(google_play).values():
            clear = getattr(value, "cache_clear", None)
            if callable(clear):
                clear()

    def configure(package: str | None = None, credentials: str | None = None) -> None:
        for variable, value in (
            ("GOOGLE_PLAY_PACKAGE_NAME", package),
            ("GOOGLE_PLAY_CREDENTIALS", credentials),
        ):
            if value is None:
                monkeypatch.delenv(variable, raising=False)
            else:
                monkeypatch.setenv(variable, value)
        forget()

    configure()
    yield configure
    forget()


@pytest.fixture
def fake_service_account(monkeypatch):
    """Keep the service account loading away from real keys and the network."""
    from google.oauth2 import service_account

    credentials = MagicMock(name="credentials")
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        classmethod(lambda cls, info, **kwargs: credentials),
    )
    monkeypatch.setattr(
        "google.auth.load_credentials_from_dict",
        lambda info, **kwargs: (credentials, "niscala-test"),
    )
    return credentials


def test_nothing_configured_gives_the_unavailable_client(play_settings):
    from app.google_play import UnavailableGooglePlay, get_google_play

    assert isinstance(get_google_play(), UnavailableGooglePlay)


def test_a_package_without_credentials_gives_the_unavailable_client(play_settings):
    from app.google_play import UnavailableGooglePlay, get_google_play

    play_settings(package=PACKAGE)
    assert isinstance(get_google_play(), UnavailableGooglePlay)


def test_credentials_without_a_package_give_the_unavailable_client(play_settings):
    from app.google_play import UnavailableGooglePlay, get_google_play

    play_settings(credentials=CREDENTIALS)
    assert isinstance(get_google_play(), UnavailableGooglePlay)


def test_both_settings_give_the_android_publisher_client(
    play_settings, fake_service_account
):
    from app.google_play import AndroidPublisherGooglePlay, get_google_play

    play_settings(package=PACKAGE, credentials=CREDENTIALS)
    assert isinstance(get_google_play(), AndroidPublisherGooglePlay)


def test_the_android_publisher_client_is_created_once(
    play_settings, fake_service_account
):
    from app.google_play import get_google_play

    play_settings(package=PACKAGE, credentials=CREDENTIALS)
    assert get_google_play() is get_google_play()
