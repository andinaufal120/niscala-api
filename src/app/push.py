"""Delivering a notification to a device push token."""

import logging
from typing import Protocol

from app.schemas.notifications import Notification

logger = logging.getLogger(__name__)


class PushSender(Protocol):
    """Delivers a notification to one device."""

    def send(self, token: str, notification: Notification) -> None:
        """Push the notification to the device; raises when delivery fails."""
        ...


class ConsolePushSender:
    """Logs each push instead of delivering it."""

    def send(self, token: str, notification: Notification) -> None:
        logger.info(
            "Push to %s: %s %s", token, notification.type.value, notification.id
        )


def get_push_sender() -> PushSender:
    """Return the sender used for pushes."""
    return ConsolePushSender()
