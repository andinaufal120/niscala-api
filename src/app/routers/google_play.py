"""Internal endpoint that receives Google Play real-time developer notifications."""

import base64
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response

from app.config import get_settings
from app.db import SessionDep
from app.errors import ApiError
from app.google_play import (
    GooglePlay,
    GooglePlayUnreachable,
    PubSubTokenVerifier,
    PurchaseNotFound,
    get_google_play,
    get_pubsub_token_verifier,
)
from app.services import subscriptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/google-play", include_in_schema=False)


async def _raw_body(request: Request) -> bytes:
    return await request.body()


def _authenticate(authorization: str | None, verifier: PubSubTokenVerifier) -> None:
    """Raise 401 UNAUTHORIZED unless the bearer token is a Pub/Sub token of the configured service account."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "Bearer" or not token.strip():
        raise ApiError(401, "UNAUTHORIZED")
    try:
        claims = verifier.verify(token.strip())
    except Exception as error:
        logger.warning("Pub/Sub token rejected: %s", error)
        raise ApiError(401, "UNAUTHORIZED") from error
    account = get_settings().google_play_rtdn_service_account
    if (
        not account
        or claims.get("email") != account
        or claims.get("email_verified") is not True
    ):
        raise ApiError(401, "UNAUTHORIZED")


def _notification(raw: bytes) -> dict[str, Any] | None:
    """Return the notification carried by a Pub/Sub push body, or None if it carries none."""
    try:
        data = json.loads(raw)["message"]["data"]
        notification = json.loads(base64.b64decode(data, validate=True))
    except ValueError, LookupError, TypeError:
        return None
    return notification if isinstance(notification, dict) else None


@router.post("/notifications", status_code=204)
def post_notification(
    raw: Annotated[bytes, Depends(_raw_body)],
    verifier: Annotated[PubSubTokenVerifier, Depends(get_pubsub_token_verifier)],
    db: SessionDep,
    play: Annotated[GooglePlay, Depends(get_google_play)],
    authorization: Annotated[str | None, Header()] = None,
):
    """Fetch the purchase of a subscription notification and update its owner.

    Answers 404 when no audience is configured and 401 UNAUTHORIZED for a bad
    Pub/Sub token. Messages that carry no usable subscription notification are
    logged and acknowledged with 204. Answers 503 GOOGLE_PLAY_UNREACHABLE when
    Google Play cannot be asked, so that Pub/Sub delivers the message again.
    """
    settings = get_settings()
    if not settings.google_play_rtdn_audience:
        raise ApiError(404, "NOT_FOUND")
    _authenticate(authorization, verifier)
    notification = _notification(raw)
    if notification is None:
        logger.info("Dropped a Pub/Sub message without a notification")
        return Response(status_code=204)
    if notification.get("packageName") != settings.google_play_package_name:
        logger.info("Ignored a notification for another package")
        return Response(status_code=204)
    detail = notification.get("subscriptionNotification")
    token = detail.get("purchaseToken") if isinstance(detail, dict) else None
    if not isinstance(token, str) or not token:
        logger.info("Ignored a notification that is not about a subscription purchase")
        return Response(status_code=204)
    try:
        subscriptions.sync_purchase(db, play, token)
    except PurchaseNotFound:
        logger.info("Ignored a notification for a purchase Google Play does not know")
    except GooglePlayUnreachable:
        raise ApiError(503, "GOOGLE_PLAY_UNREACHABLE") from None
    return Response(status_code=204)
