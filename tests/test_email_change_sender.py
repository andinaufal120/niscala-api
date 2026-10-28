"""The email sender delivers email change links and notices."""

import logging

LINK = "https://niscala.example/email-changes/abc123"


def test_the_sender_protocol_declares_the_email_change_methods():
    from app.email import EmailSender

    assert callable(getattr(EmailSender, "send_email_change_link", None))
    assert callable(getattr(EmailSender, "send_email_change_notice", None))


def test_console_sender_logs_the_link_with_its_address_at_info_level(caplog):
    from app.email import ConsoleEmailSender

    with caplog.at_level(logging.INFO):
        result = ConsoleEmailSender().send_email_change_link("new@example.com", LINK)
    assert result is None
    records = [r for r in caplog.records if "new@example.com" in r.getMessage()]
    assert records
    assert any(LINK in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_console_sender_logs_the_notice_with_both_addresses_at_info_level(caplog):
    from app.email import ConsoleEmailSender

    with caplog.at_level(logging.INFO):
        result = ConsoleEmailSender().send_email_change_notice(
            "old@example.com", "new@example.com"
        )
    assert result is None
    records = [r for r in caplog.records if "old@example.com" in r.getMessage()]
    assert records
    assert any("new@example.com" in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_console_sender_logs_every_email_change_message_it_sends(caplog):
    from app.email import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        sender.send_email_change_link("a@example.com", "https://niscala.example/a")
        sender.send_email_change_link("b@example.com", "https://niscala.example/b")
        sender.send_email_change_notice("c@example.com", "d@example.com")
    for text in (
        "a@example.com",
        "https://niscala.example/a",
        "b@example.com",
        "https://niscala.example/b",
        "c@example.com",
        "d@example.com",
    ):
        assert text in caplog.text
