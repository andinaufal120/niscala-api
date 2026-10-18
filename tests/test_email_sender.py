"""The email sender used to deliver verification codes."""

import logging


def test_default_sender_is_a_console_sender():
    from app.email import ConsoleEmailSender, get_email_sender

    assert isinstance(get_email_sender(), ConsoleEmailSender)


def test_console_sender_logs_the_address_and_code_at_info_level(caplog):
    from app.email import ConsoleEmailSender

    with caplog.at_level(logging.INFO):
        result = ConsoleEmailSender().send_verification_code(
            "owner@example.com", "012345"
        )
    assert result is None
    records = [r for r in caplog.records if "owner@example.com" in r.getMessage()]
    assert records
    assert any("012345" in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_console_sender_logs_every_message_it_sends(caplog):
    from app.email import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        sender.send_verification_code("a@example.com", "111111")
        sender.send_verification_code("b@example.com", "222222")
    assert "a@example.com" in caplog.text
    assert "111111" in caplog.text
    assert "b@example.com" in caplog.text
    assert "222222" in caplog.text


def test_dependency_can_be_replaced_with_a_fake(app, sent_emails):
    from app.email import get_email_sender

    sender = app.dependency_overrides[get_email_sender]()
    sender.send_verification_code("owner@example.com", "123456")
    assert sent_emails == [("owner@example.com", "123456")]


def test_sent_emails_fixture_removes_the_override_afterwards(app):
    from app.email import get_email_sender

    assert get_email_sender not in app.dependency_overrides
