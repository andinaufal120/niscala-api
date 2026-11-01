"""Delivery of emails to users."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """Something that can deliver emails."""

    def send_verification_code(self, to: str, code: str) -> None:
        """Email the 6-digit verification code to the address."""
        ...

    def send_email_change_link(self, to: str, url: str) -> None:
        """Email the confirmation link of an email change to the new address."""
        ...

    def send_email_change_notice(self, to: str, new_email: str) -> None:
        """Tell the current address that a change to `new_email` was requested."""
        ...


class ConsoleEmailSender:
    """Logs emails instead of sending them."""

    def send_verification_code(self, to: str, code: str) -> None:
        logger.info("Verification code for %s: %s", to, code)

    def send_email_change_link(self, to: str, url: str) -> None:
        logger.info("Email change link for %s: %s", to, url)

    def send_email_change_notice(self, to: str, new_email: str) -> None:
        logger.info("Email change notice for %s: change to %s requested", to, new_email)


def get_email_sender() -> EmailSender:
    """Return the sender used to deliver emails."""
    return ConsoleEmailSender()
