"""The push sender delivers notifications to device tokens."""

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


def test_the_default_sender_is_the_console_sender():
    from app.push import ConsolePushSender, get_push_sender

    assert isinstance(get_push_sender(), ConsolePushSender)


def test_the_default_sender_can_send_without_raising():
    from app.push import get_push_sender

    assert get_push_sender().send(TOKEN, notification()) is None
