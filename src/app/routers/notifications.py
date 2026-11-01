"""Endpoints under /notifications and the caller's notification settings and push token under /me."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.notifications import (
    Notification,
    NotificationList,
    NotificationSettings,
    NotificationSettingsInput,
    PushTokenInput,
)
from app.security import CurrentUser
from app.services import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])
me_router = APIRouter(prefix="/me", tags=["notifications"])

NotificationId = Annotated[UUID, Path(alias="notificationId")]
Db = SessionDep
Caller = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.TENANT, UserRole.OWNER, UserRole.MANAGER)),
]


@router.get("")
def list_notifications(caller: Caller, db: Db) -> NotificationList:
    """List the caller's notifications, newest first, with the unread count."""
    return notifications.list_notifications(db, caller.user)


@router.post(
    "/read-all", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def mark_all_notifications_read(caller: Caller, db: Db) -> None:
    """Mark all of the caller's notifications read."""
    notifications.mark_all_read(db, caller.user)


@router.post("/{notificationId}/read")
def mark_notification_read(
    notification_id: NotificationId, caller: Caller, db: Db
) -> Notification:
    """Mark one of the caller's notifications read; already read stays read."""
    return notifications.mark_read(db, caller.user, notification_id)


@me_router.get("/notification-settings")
def get_notification_settings(caller: Caller, db: Db) -> NotificationSettings:
    """Return the caller's push settings, one entry per category of their role."""
    return notifications.get_settings(db, caller.user)


@me_router.put("/notification-settings")
def update_notification_settings(
    body: NotificationSettingsInput, caller: Caller, db: Db
) -> NotificationSettings:
    """Replace the caller's push settings."""
    return notifications.replace_settings(db, caller.user, body)


@me_router.put(
    "/push-token", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def register_push_token(body: PushTokenInput, caller: Caller, db: Db) -> None:
    """Register the current session's device push token, replacing any earlier one."""
    notifications.register_push_token(db, caller.session, body.token)
