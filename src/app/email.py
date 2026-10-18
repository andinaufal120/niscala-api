"""Delivery of emails to users."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """Something that can deliver emails."""

    def send_verification_code(self, to: str, code: str) -> None:
        """Email the 6-digit verification code to the address."""
        ...


class ConsoleEmailSender:
    """Logs emails instead of sending them."""

    def send_verification_code(self, to: str, code: str) -> None:
        logger.info("Verification code for %s: %s", to, code)


def get_email_sender() -> EmailSender:
    """Return the sender used to deliver emails."""
    return ConsoleEmailSender()
