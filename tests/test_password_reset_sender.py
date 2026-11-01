"""The email sender delivers password-reset links."""

import logging

LINK = "https://niscala.example/password-resets/abc123"


def test_the_sender_protocol_declares_the_password_reset_method():
    from app.email import EmailSender

    assert callable(getattr(EmailSender, "send_password_reset_link", None))


def test_console_sender_logs_the_link_with_its_address_at_info_level(caplog):
    from app.email import ConsoleEmailSender

    with caplog.at_level(logging.INFO):
        result = ConsoleEmailSender().send_password_reset_link("rina@example.com", LINK)
    assert result is None
    records = [r for r in caplog.records if "rina@example.com" in r.getMessage()]
    assert records
    assert any(LINK in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_console_sender_logs_every_reset_link_it_sends(caplog):
    from app.email import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        sender.send_password_reset_link("a@example.com", "https://niscala.example/a")
        sender.send_password_reset_link("b@example.com", "https://niscala.example/b")
    for text in (
        "a@example.com",
        "https://niscala.example/a",
        "b@example.com",
        "https://niscala.example/b",
    ):
        assert text in caplog.text
