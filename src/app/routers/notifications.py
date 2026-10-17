"""Endpoints under /notifications and the caller's notification settings and push token under /me. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.notifications import (
    Notification,
    NotificationList,
    NotificationSettings,
    NotificationSettingsInput,
    PushTokenInput,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
me_router = APIRouter(prefix="/me", tags=["notifications"])

NotificationId = Annotated[UUID, Path(alias="notificationId")]


@router.get("")
def list_notifications() -> NotificationList:
    """List the caller's notifications, newest first, with the unread count."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post(
    "/read-all", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def mark_all_notifications_read() -> None:
    """Mark all of the caller's notifications read."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{notificationId}/read")
def mark_notification_read(notification_id: NotificationId) -> Notification:
    """Mark one of the caller's notifications read; already read stays read."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@me_router.get("/notification-settings")
def get_notification_settings() -> NotificationSettings:
    """Return the caller's push settings, one entry per category of their role."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@me_router.put("/notification-settings")
def update_notification_settings(
    body: NotificationSettingsInput,
) -> NotificationSettings:
    """Replace the caller's push settings."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@me_router.put(
    "/push-token", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def register_push_token(body: PushTokenInput) -> None:
    """Register the current session's device push token, replacing any earlier one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
