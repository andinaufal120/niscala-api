"""The push sender delivers notifications to device tokens."""

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

TOKEN = "fcm-device-token-123"


def notification(type_: str = "receiptUploaded"):
    from app.schemas.notifications import Notification, NotificationType

    return Notification(
        id=uuid4(),
        type=NotificationType(type_),
        created_at=datetime.now(UTC),
        read=False,
        rent_bill=None,
        complaint=None,
        tenant=None,
        room=None,
        property=None,
        actor_name=None,
    )


def test_the_sender_protocol_declares_send():
    from app.push import PushSender

    assert callable(getattr(PushSender, "send", None))


def test_console_sender_logs_the_token_type_and_id_at_info_level(caplog):
    from app.push import ConsolePushSender

    sent = notification("receiptUploaded")
    with caplog.at_level(logging.INFO):
        result = ConsolePushSender().send(TOKEN, sent)
    assert result is None
    records = [r for r in caplog.records if TOKEN in r.getMessage()]
    assert records
    assert any("receiptUploaded" in r.getMessage() for r in records)
    assert any(str(sent.id) in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


@pytest.mark.parametrize(
    "type_",
    [
        "paymentStatusChanged",
        "complaintStatusChanged",
        "complaintSubmitted",
        "receiptUploaded",
        "cashPaymentRecorded",
        "tenantActivated",
        "managerActivated",
    ],
)
def test_console_sender_logs_the_type_of_every_notification(caplog, type_):
    from app.push import ConsolePushSender

    with caplog.at_level(logging.INFO):
        ConsolePushSender().send(TOKEN, notification(type_))
    assert type_ in caplog.text


def test_console_sender_logs_every_push_it_sends(caplog):
    from app.push import ConsolePushSender

    first, second = notification(), notification("tenantActivated")
    sender = ConsolePushSender()
    with caplog.at_level(logging.INFO):
        sender.send("token-one", first)
        sender.send("token-two", second)
    for text in ("token-one", str(first.id), "token-two", str(second.id)):
        assert text in caplog.text


def test_the_default_sender_is_the_console_sender(firebase_credentials):
    from app.push import ConsolePushSender, get_push_sender

    assert isinstance(get_push_sender(), ConsolePushSender)


def test_the_default_sender_can_send_without_raising(firebase_credentials):
    from app.push import get_push_sender

    assert get_push_sender().send(TOKEN, notification()) is None


# Choosing the sender

ALL_TYPES = [
    "billIssued",
    "dueDateReminder",
    "billOverdue",
    "paymentStatusChanged",
    "complaintStatusChanged",
    "complaintSubmitted",
    "receiptUploaded",
    "cashPaymentRecorded",
    "tenantActivated",
    "managerActivated",
]
SERVICE_ACCOUNT = json.dumps(
    {
        "type": "service_account",
        "project_id": "niscala-test",
        "private_key_id": "abc",
        "client_email": "push@niscala-test.iam.gserviceaccount.com",
    }
)


def test_the_credentials_setting_is_empty_by_default(firebase_credentials):
    from app.config import get_settings

    assert get_settings().firebase_credentials is None


def test_the_credentials_setting_reads_the_environment(firebase_credentials):
    from app.config import get_settings

    firebase_credentials(SERVICE_ACCOUNT)
    assert get_settings().firebase_credentials == SERVICE_ACCOUNT


@pytest.mark.parametrize("value", ["", " ", "   \n\t "])
def test_blank_credentials_select_the_console_sender(
    firebase_credentials, fake_firebase, value
):
    from app.push import ConsolePushSender, get_push_sender

    firebase_credentials(value)
    assert isinstance(get_push_sender(), ConsolePushSender)
    assert fake_firebase.initializations == []


def test_missing_credentials_select_the_console_sender(
    firebase_credentials, fake_firebase
):
    from app.push import ConsolePushSender, get_push_sender

    firebase_credentials()
    assert isinstance(get_push_sender(), ConsolePushSender)
    assert fake_firebase.certificates == []
    assert fake_firebase.initializations == []


def test_credentials_select_the_fcm_sender(firebase_credentials, fake_firebase):
    from app.push import FcmPushSender, get_push_sender

    firebase_credentials(SERVICE_ACCOUNT)
    assert isinstance(get_push_sender(), FcmPushSender)


def test_the_credentials_are_parsed_as_json_content_not_a_file_path(
    firebase_credentials, fake_firebase
):
    from app.push import get_push_sender

    firebase_credentials(SERVICE_ACCOUNT)
    get_push_sender()
    assert fake_firebase.certificates == [json.loads(SERVICE_ACCOUNT)]


def test_the_firebase_app_is_initialised_with_the_certificate_under_its_own_name(
    firebase_credentials, fake_firebase
):
    from app.push import get_push_sender

    firebase_credentials(SERVICE_ACCOUNT)
    get_push_sender()
    (initialization,) = fake_firebase.initializations
    assert initialization["credential"] == ("certificate", 1)
    assert initialization["name"] not in (None, "", "[DEFAULT]")


def test_the_firebase_app_is_initialised_once_across_calls(
    firebase_credentials, fake_firebase, fcm
):
    from app.push import get_push_sender

    firebase_credentials(SERVICE_ACCOUNT)
    first, second = get_push_sender(), get_push_sender()
    first.send(TOKEN, notification())
    second.send(TOKEN, notification())
    assert len(fake_firebase.initializations) == 1
    assert len(fake_firebase.certificates) == 1
    assert [app_ for _, app_ in fcm.sent] == [fake_firebase.apps[0]] * 2


def test_credentials_that_are_not_json_raise_when_the_sender_is_requested(
    firebase_credentials, fake_firebase
):
    from app.push import get_push_sender

    firebase_credentials("this is not json")
    with pytest.raises(Exception):  # noqa: B017
        get_push_sender()


# The FCM message


def test_the_push_error_for_a_dead_token_is_an_exception():
    from app.push import InvalidPushToken

    assert issubclass(InvalidPushToken, Exception)


def test_the_fcm_sender_hands_one_message_to_firebase_with_its_app(fcm):
    from firebase_admin import messaging

    from app.push import FcmPushSender

    app_ = object()
    result = FcmPushSender(app_).send(TOKEN, notification())
    assert result is None
    ((message, used_app),) = fcm.sent
    assert isinstance(message, messaging.Message)
    assert used_app is app_


def test_the_fcm_message_is_addressed_to_the_device_token(fcm):
    from app.push import FcmPushSender

    FcmPushSender(object()).send(TOKEN, notification())
    assert fcm.sent[0][0].token == TOKEN


@pytest.mark.parametrize("type_", ALL_TYPES)
def test_the_fcm_message_data_carries_the_notification_id_and_type(fcm, type_):
    from app.push import FcmPushSender

    sent = notification(type_)
    FcmPushSender(object()).send(TOKEN, sent)
    assert fcm.sent[0][0].data == {"notificationId": str(sent.id), "type": type_}


@pytest.mark.parametrize("type_", ALL_TYPES)
def test_the_fcm_message_asks_the_device_to_show_text_from_its_own_strings(fcm, type_):
    from app.push import FcmPushSender

    FcmPushSender(object()).send(TOKEN, notification(type_))
    android = fcm.sent[0][0].android
    assert android.notification.title_loc_key == f"notification_{type_}_title"
    assert android.notification.body_loc_key == f"notification_{type_}_body"


@pytest.mark.parametrize("type_", ALL_TYPES)
def test_the_fcm_message_has_high_priority(fcm, type_):
    from app.push import FcmPushSender

    FcmPushSender(object()).send(TOKEN, notification(type_))
    assert fcm.sent[0][0].android.priority == "high"


def test_the_fcm_message_carries_no_text_of_its_own(fcm):
    from app.push import FcmPushSender

    FcmPushSender(object()).send(TOKEN, notification())
    message = fcm.sent[0][0]
    shown = message.android.notification
    assert shown.title is None
    assert shown.body is None
    assert message.notification is None


def test_the_fcm_message_data_values_are_strings(fcm):
    from app.push import FcmPushSender

    FcmPushSender(object()).send(TOKEN, notification())
    assert all(isinstance(v, str) for v in fcm.sent[0][0].data.values())


def test_the_fcm_sender_sends_each_call_as_its_own_message(fcm):
    from app.push import FcmPushSender

    sender = FcmPushSender(object())
    first, second = notification(), notification("tenantActivated")
    sender.send("token-one", first)
    sender.send("token-two", second)
    assert fcm.tokens() == ["token-one", "token-two"]
    assert fcm.sent[0][0].data["notificationId"] == str(first.id)
    assert fcm.sent[1][0].data["notificationId"] == str(second.id)


# Errors from FCM


def firebase_errors():
    from firebase_admin import exceptions, messaging

    return {
        "unregistered": messaging.UnregisteredError("Requested entity was not found."),
        "sender_id_mismatch": messaging.SenderIdMismatchError("Wrong sender."),
        "invalid_argument": exceptions.InvalidArgumentError("Bad registration token."),
    }


@pytest.mark.parametrize(
    "name", ["unregistered", "sender_id_mismatch", "invalid_argument"]
)
def test_errors_that_mean_a_dead_token_become_invalid_push_token(fcm, name):
    from app.push import FcmPushSender, InvalidPushToken

    fcm.error = firebase_errors()[name]
    with pytest.raises(InvalidPushToken):
        FcmPushSender(object()).send(TOKEN, notification())


def other_errors():
    from firebase_admin import exceptions, messaging

    return [
        RuntimeError("socket closed"),
        ValueError("bad value"),
        messaging.QuotaExceededError("Quota exceeded."),
        messaging.ThirdPartyAuthError("APNs auth failed."),
        exceptions.UnavailableError("FCM unavailable."),
        exceptions.InternalError("FCM failed."),
        exceptions.UnauthenticatedError("Credentials rejected."),
        exceptions.PermissionDeniedError("Not allowed."),
    ]


@pytest.mark.parametrize("index", range(8))
def test_every_other_error_propagates_unchanged(fcm, index):
    from app.push import FcmPushSender, InvalidPushToken

    error = other_errors()[index]
    fcm.error = error
    with pytest.raises(type(error)) as caught:
        FcmPushSender(object()).send(TOKEN, notification())
    assert caught.value is error
    assert not isinstance(caught.value, InvalidPushToken)
