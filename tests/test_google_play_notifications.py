"""The endpoint that receives Google Play real-time developer notifications."""

import base64
import logging
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from google_play_support import (
    AUDIENCE,
    GOOD_BEARER,
    NOTIFICATIONS_URL,
    PACKAGE,
    SERVICE_ACCOUNT,
    current_plan_of,
    envelope,
    everything,
    now,
    pubsub_verifier_getter,
    push,
    set_token,
    subscription_message,
    subscription_state,
)
from subscription_support import (
    assert_error,
    insert_order,
    is_property_view_only,
    set_subscription,
    stored_order,
)

TOKEN = "play-token-1"
OLD_TOKEN = "play-token-0"


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


def in_days(days: float):
    return now() + timedelta(days=days)


# Where the endpoint is exposed


def test_the_endpoint_is_not_in_the_openapi_document(app):
    document = app.openapi()
    assert not [p for p in document["paths"] if "google-play" in p]


def test_the_endpoint_is_absent_when_no_audience_is_configured(
    client, play, rtdn, monkeypatch
):
    from app.config import get_settings

    monkeypatch.delenv("GOOGLE_PLAY_RTDN_AUDIENCE")
    get_settings.cache_clear()
    response = push(client, envelope(subscription_message(TOKEN)))
    assert_error(response, 404, "NOT_FOUND")
    assert play.fetched == []
    assert rtdn.verified == []


def test_the_endpoint_is_absent_by_default(client, play):
    response = push(client, envelope(subscription_message(TOKEN)))
    assert response.status_code == 404
    assert play.fetched == []


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_only_post_is_allowed(client, rtdn, method):
    response = client.request(method, NOTIFICATIONS_URL)
    assert response.status_code == 405


# Authentication


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic pubsub-jwt-good"},
        {"Authorization": "pubsub-jwt-good"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer unknown-jwt"},
    ],
    ids=["missing", "basic-scheme", "no-scheme", "no-token", "empty-token", "unknown"],
)
def test_a_missing_or_unverifiable_token_is_unauthorized(client, play, rtdn, headers):
    response = client.post(
        NOTIFICATIONS_URL, json=envelope(subscription_message(TOKEN)), headers=headers
    )
    assert_error(response, 401, "UNAUTHORIZED")
    assert play.fetched == []


def test_the_bearer_token_is_given_to_the_verifier(client, play, rtdn):
    push(client, envelope(subscription_message(TOKEN)))
    assert rtdn.verified == [GOOD_BEARER]


def test_a_token_of_another_service_account_is_unauthorized(client, play, rtdn):
    rtdn.add("other-account", email="someone-else@example.com")
    response = push(client, envelope(subscription_message(TOKEN)), "other-account")
    assert_error(response, 401, "UNAUTHORIZED")
    assert play.fetched == []


def test_a_token_without_an_email_is_unauthorized(client, play, rtdn):
    rtdn.add("no-email")
    del rtdn.claims["no-email"]["email"]
    response = push(client, envelope(subscription_message(TOKEN)), "no-email")
    assert_error(response, 401, "UNAUTHORIZED")


@pytest.mark.parametrize(
    "verified", [False, None, "true"], ids=["false", "absent", "text"]
)
def test_a_token_whose_email_is_not_verified_is_unauthorized(
    client, play, rtdn, verified
):
    rtdn.add("unverified", email_verified=verified)
    if verified is None:
        del rtdn.claims["unverified"]["email_verified"]
    response = push(client, envelope(subscription_message(TOKEN)), "unverified")
    assert_error(response, 401, "UNAUTHORIZED")
    assert play.fetched == []


def test_authentication_is_checked_before_the_body(client, play, rtdn):
    response = push(client, b"not json at all", bearer=None)
    assert_error(response, 401, "UNAUTHORIZED")


def test_a_user_access_token_is_not_accepted(client, play, rtdn, owner, sign_in):
    token = sign_in(owner).tokens.access_token
    response = push(client, envelope(subscription_message(TOKEN)), token)
    assert_error(response, 401, "UNAUTHORIZED")


def test_the_endpoint_needs_no_user_login(client, play, rtdn, owner):
    play.add(TOKEN, owner=owner)
    response = push(client, envelope(subscription_message(TOKEN)))
    assert response.status_code == 204


# The real verifier


@pytest.fixture
def real_verifier(app, rtdn, monkeypatch):
    """Use the real verifier with the Google library call replaced."""
    from google.oauth2 import id_token

    app.dependency_overrides.pop(pubsub_verifier_getter(), None)
    library = MagicMock(
        return_value={"email": SERVICE_ACCOUNT, "email_verified": True, "aud": AUDIENCE}
    )
    monkeypatch.setattr(id_token, "verify_oauth2_token", library)
    return library


def audience_given(library) -> object:
    call = library.call_args
    return call.kwargs.get("audience", call.args[2] if len(call.args) > 2 else None)


def token_given(library) -> object:
    call = library.call_args
    return call.args[0] if call.args else call.kwargs.get("id_token")


def test_the_real_verifier_checks_the_token_against_the_configured_audience(
    client, play, real_verifier, owner
):
    play.add(TOKEN, owner=owner)
    response = push(client, envelope(subscription_message(TOKEN)))
    assert response.status_code == 204
    real_verifier.assert_called_once()
    assert token_given(real_verifier) == GOOD_BEARER
    assert audience_given(real_verifier) == AUDIENCE


def test_the_real_verifier_rejects_what_the_library_rejects(
    client, play, real_verifier
):
    real_verifier.side_effect = ValueError("Token expired")
    response = push(client, envelope(subscription_message(TOKEN)))
    assert_error(response, 401, "UNAUTHORIZED")
    assert play.fetched == []


def test_the_real_verifier_rejects_a_token_of_another_service_account(
    client, play, real_verifier
):
    real_verifier.return_value = {"email": "x@example.com", "email_verified": True}
    response = push(client, envelope(subscription_message(TOKEN)))
    assert_error(response, 401, "UNAUTHORIZED")


def test_the_verifier_getter_returns_an_object_that_verifies_tokens(rtdn, monkeypatch):
    from google.oauth2 import id_token

    library = MagicMock(return_value={"email": SERVICE_ACCOUNT, "email_verified": True})
    monkeypatch.setattr(id_token, "verify_oauth2_token", library)
    verifier = pubsub_verifier_getter()()
    claims = verifier.verify("some-jwt")
    assert claims["email"] == SERVICE_ACCOUNT
    assert token_given(library) == "some-jwt"
    assert audience_given(library) == AUDIENCE


# Messages that are acknowledged and dropped


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[]",
        b"{}",
        b'{"subscription": "x"}',
        b'{"message": null}',
        b'{"message": {}}',
        b'{"message": {"data": null}}',
        b'{"message": {"data": 12}}',
        b'{"message": {"data": "!!! not base64 !!!"}}',
        b'{"message": []}',
    ],
    ids=[
        "not-json",
        "list",
        "empty-object",
        "no-message",
        "null-message",
        "no-data",
        "null-data",
        "numeric-data",
        "bad-base64",
        "list-message",
    ],
)
def test_a_malformed_envelope_is_acknowledged_and_dropped(
    client, database, play, rtdn, body
):
    before = everything(database)
    response = push(client, body)
    assert response.status_code == 204
    assert response.content == b""
    assert play.fetched == []
    assert everything(database) == before


@pytest.mark.parametrize(
    "raw",
    [b"plain text", b"[1, 2]", b'"a string"', b"123", b"null", b"{broken"],
    ids=["text", "list", "string", "number", "null", "broken-json"],
)
def test_data_that_is_not_a_json_object_is_acknowledged_and_dropped(
    client, play, rtdn, raw
):
    response = push(client, envelope(raw))
    assert response.status_code == 204
    assert play.fetched == []


def test_data_that_is_not_text_is_acknowledged_and_dropped(client, play, rtdn):
    body = {"message": {"data": base64.b64encode(b"\xff\xfe\x00").decode()}}
    response = push(client, body)
    assert response.status_code == 204
    assert play.fetched == []


def test_a_dropped_message_is_logged(client, play, rtdn, caplog):
    with caplog.at_level(logging.INFO):
        push(client, b"not json at all")
    assert [r for r in caplog.records if r.levelno >= logging.INFO]


@pytest.mark.parametrize(
    "notification",
    [
        {"version": "1.0", "packageName": PACKAGE},
        {"version": "1.0", "packageName": PACKAGE, "subscriptionNotification": None},
        {"version": "1.0", "packageName": PACKAGE, "subscriptionNotification": []},
        {
            "packageName": PACKAGE,
            "subscriptionNotification": {"notificationType": 2},
        },
        {
            "packageName": PACKAGE,
            "subscriptionNotification": {"notificationType": 2, "purchaseToken": ""},
        },
        {
            "packageName": PACKAGE,
            "subscriptionNotification": {"notificationType": 2, "purchaseToken": 7},
        },
    ],
    ids=[
        "no-notification",
        "null-notification",
        "list-notification",
        "no-token",
        "empty-token",
        "numeric-token",
    ],
)
def test_a_notification_without_a_usable_purchase_is_acknowledged_and_dropped(
    client, play, rtdn, notification
):
    response = push(client, envelope(notification))
    assert response.status_code == 204
    assert play.fetched == []


def test_a_notification_for_another_package_is_ignored(
    client, database, play, rtdn, owner
):
    play.add(TOKEN, owner=owner)
    response = push(
        client, envelope(subscription_message(TOKEN, package="com.other.app"))
    )
    assert response.status_code == 204
    assert play.fetched == []
    assert subscription_state(database, owner) is None


def test_a_notification_without_a_package_is_ignored(client, play, rtdn):
    message = subscription_message(TOKEN)
    del message["packageName"]
    response = push(client, envelope(message))
    assert response.status_code == 204
    assert play.fetched == []


@pytest.mark.parametrize(
    "notification",
    [
        {
            "version": "1.0",
            "packageName": PACKAGE,
            "eventTimeMillis": "1700000000000",
            "testNotification": {"version": "1.0"},
        },
        {
            "version": "1.0",
            "packageName": PACKAGE,
            "eventTimeMillis": "1700000000000",
            "oneTimeProductNotification": {
                "version": "1.0",
                "notificationType": 1,
                "purchaseToken": TOKEN,
                "sku": "coins",
            },
        },
        {
            "version": "1.0",
            "packageName": PACKAGE,
            "eventTimeMillis": "1700000000000",
            "voidedPurchaseNotification": {
                "purchaseToken": TOKEN,
                "orderId": "GPA.1234",
                "productType": 1,
                "refundType": 1,
            },
        },
    ],
    ids=["test", "one-time-product", "voided-purchase"],
)
def test_other_kinds_of_notification_are_acknowledged_without_a_lookup(
    client, database, play, rtdn, owner, notification
):
    play.add(TOKEN, owner=owner)
    response = push(client, envelope(notification))
    assert response.status_code == 204
    assert response.content == b""
    assert play.fetched == []
    assert subscription_state(database, owner) is None


# Subscription notifications


def test_a_subscription_notification_updates_the_subscription(
    client, database, play, rtdn, owner
):
    expiry = in_days(30)
    play.add(
        TOKEN,
        owner=owner,
        product_id="niscala_pro",
        base_plan_id="yearly",
        expiry_time=expiry,
    )
    response = push(client, envelope(subscription_message(TOKEN)))
    assert response.status_code == 204
    assert response.content == b""
    assert play.fetched == [TOKEN]
    assert subscription_state(database, owner) == (
        "pro",
        "yearly",
        expiry,
        True,
        TOKEN,
    )


@pytest.mark.parametrize("notification_type", [*range(1, 14), 20])
def test_every_kind_of_subscription_notification_fetches_the_purchase(
    client, play, rtdn, owner, notification_type
):
    play.add(TOKEN, owner=owner)
    response = push(
        client,
        envelope(subscription_message(TOKEN, notification_type=notification_type)),
    )
    assert response.status_code == 204
    assert play.fetched == [TOKEN]


def test_a_renewal_extends_the_period(client, database, play, rtdn, owner):
    set_subscription(database, owner, plan="basic", ends_at=in_days(1))
    set_token(database, owner, TOKEN)
    expiry = in_days(31)
    play.add(TOKEN, owner=owner, expiry_time=expiry)
    push(client, envelope(subscription_message(TOKEN, notification_type=2)))
    assert subscription_state(database, owner)[2] == expiry


def test_a_cancellation_switches_off_renewal(client, database, play, rtdn, owner):
    set_subscription(
        database, owner, plan="basic", ends_at=in_days(10), auto_renew=True
    )
    set_token(database, owner, TOKEN)
    play.add(
        TOKEN,
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=in_days(10),
    )
    push(client, envelope(subscription_message(TOKEN, notification_type=3)))
    assert subscription_state(database, owner)[3] is False
    assert current_plan_of(database, owner) == "basic"


def test_an_expiry_ends_the_plan(client, database, play, rtdn, owner):
    set_subscription(database, owner, plan="basic", ends_at=in_days(1))
    set_token(database, owner, TOKEN)
    play.add(TOKEN, owner=owner, state="EXPIRED", expiry_time=in_days(-1))
    push(client, envelope(subscription_message(TOKEN, notification_type=13)))
    assert current_plan_of(database, owner) == "free"


def test_a_refund_ends_the_plan_at_once(client, database, play, rtdn, owner):
    set_subscription(database, owner, plan="pro", ends_at=in_days(20))
    set_token(database, owner, TOKEN)
    play.add(
        TOKEN, owner=owner, state="EXPIRED", expiry_time=now() - timedelta(minutes=1)
    )
    push(client, envelope(subscription_message(TOKEN, notification_type=12)))
    assert current_plan_of(database, owner) == "free"


def test_a_pending_order_is_succeeded_by_the_notification(
    client, database, play, rtdn, owner, make_property
):
    prop = make_property(owner, view_only=True)
    bought = insert_order(database, owner, purchase_token=TOKEN)
    play.add(TOKEN, owner=owner)
    push(client, envelope(subscription_message(TOKEN, notification_type=4)))
    assert stored_order(database, bought.id).status == "succeeded"
    assert subscription_state(database, owner)[4] == TOKEN
    assert not is_property_view_only(database, prop)


def test_an_upgrade_notification_replaces_the_linked_subscription(
    client, database, play, rtdn, owner
):
    set_subscription(database, owner, plan="basic", ends_at=in_days(3))
    set_token(database, owner, OLD_TOKEN)
    play.add(
        TOKEN,
        owner=owner,
        product_id="niscala_pro",
        linked_purchase_token=OLD_TOKEN,
    )
    push(client, envelope(subscription_message(TOKEN, notification_type=4)))
    state = subscription_state(database, owner)
    assert (state[0], state[4]) == ("pro", TOKEN)


def test_a_purchase_of_an_unknown_owner_is_acknowledged_and_changes_nothing(
    client, database, play, rtdn, owner
):
    play.add(TOKEN, obfuscated_account_id="00000000-0000-4000-8000-000000000000")
    before = everything(database)
    response = push(client, envelope(subscription_message(TOKEN)))
    assert response.status_code == 204
    assert everything(database) == before


def test_redelivering_the_same_message_changes_nothing_more(
    client, database, play, rtdn, owner
):
    play.add(TOKEN, owner=owner)
    body = envelope(subscription_message(TOKEN))
    assert push(client, body).status_code == 204
    once = everything(database)
    state = subscription_state(database, owner)
    assert push(client, body).status_code == 204
    assert everything(database) == once
    assert subscription_state(database, owner) == state


# Google Play problems


def test_an_unreachable_google_play_answers_503_so_the_message_is_redelivered(
    client, database, play, rtdn, owner
):
    set_subscription(database, owner, plan="basic", ends_at=in_days(1))
    set_token(database, owner, TOKEN)
    insert_order(database, owner)
    before = everything(database)
    state = subscription_state(database, owner)
    play.unreachable = True
    response = push(client, envelope(subscription_message(TOKEN)))
    assert_error(response, 503, "GOOGLE_PLAY_UNREACHABLE")
    assert everything(database) == before
    assert subscription_state(database, owner) == state


def test_the_message_is_accepted_once_google_play_is_back(
    client, database, play, rtdn, owner
):
    play.add(TOKEN, owner=owner)
    body = envelope(subscription_message(TOKEN))
    play.unreachable = True
    assert push(client, body).status_code == 503
    play.unreachable = False
    assert push(client, body).status_code == 204
    assert subscription_state(database, owner)[4] == TOKEN


def test_without_google_play_configured_the_answer_is_503(client, rtdn):
    response = push(client, envelope(subscription_message(TOKEN)))
    assert_error(response, 503, "GOOGLE_PLAY_UNREACHABLE")


def test_a_token_unknown_to_google_play_is_acknowledged(
    client, database, play, rtdn, owner
):
    before = everything(database)
    response = push(client, envelope(subscription_message("never-issued")))
    assert response.status_code == 204
    assert play.fetched == ["never-issued"]
    assert everything(database) == before
