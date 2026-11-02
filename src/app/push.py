"""Delivering a notification to a device push token."""

import json
import logging
from functools import cache
from typing import Protocol

import firebase_admin
from firebase_admin import App, credentials, exceptions, messaging

from app.config import get_settings
from app.schemas.notifications import Notification

logger = logging.getLogger(__name__)

FIREBASE_APP_NAME = "niscala-push"


class InvalidPushToken(Exception):
    """The device token is unregistered or invalid and will never work again."""


class PushSender(Protocol):
    """Delivers a notification to one device."""

    def send(self, token: str, notification: Notification) -> None:
        """Push the notification to the device.

        Raises InvalidPushToken when the token is dead, and any other exception
        when delivery fails.
        """
        ...


class ConsolePushSender:
    """Logs each push instead of delivering it."""

    def send(self, token: str, notification: Notification) -> None:
        logger.info(
            "Push to %s: %s %s", token, notification.type.value, notification.id
        )


class FcmPushSender:
    """Delivers pushes through Firebase Cloud Messaging.

    The message carries no text: the device shows the strings named by the
    localization keys, which are derived from the notification type.
    """

    def __init__(self, app: App) -> None:
        self.app = app

    def send(self, token: str, notification: Notification) -> None:
        type_ = notification.type.value
        message = messaging.Message(
            token=token,
            data={"notificationId": str(notification.id), "type": type_},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    title_loc_key=f"notification_{type_}_title",
                    body_loc_key=f"notification_{type_}_body",
                ),
            ),
        )
        try:
            messaging.send(message, app=self.app)
        except (
            messaging.UnregisteredError,
            messaging.SenderIdMismatchError,
            exceptions.InvalidArgumentError,
        ) as error:
            raise InvalidPushToken from error


@cache
def _fcm_sender(service_account: str) -> FcmPushSender:
    app = firebase_admin.initialize_app(
        credentials.Certificate(json.loads(service_account)), name=FIREBASE_APP_NAME
    )
    return FcmPushSender(app)


def get_push_sender() -> PushSender:
    """Return the FCM sender when credentials are configured, else the console one."""
    service_account = get_settings().firebase_credentials
    if service_account is None or not service_account.strip():
        return ConsolePushSender()
    return _fcm_sender(service_account)
