"""Verifying Google ID tokens."""

from dataclasses import dataclass
from typing import Protocol

from google.auth.transport import requests
from google.oauth2 import id_token as google_id_token

from app.config import get_settings
from app.errors import ApiError


@dataclass(frozen=True)
class GoogleIdentity:
    """The claims of a verified Google ID token that the app uses."""

    subject: str
    email: str
    email_verified: bool
    name: str | None = None


class GoogleTokenInvalid(Exception):
    """The ID token is malformed, forged, expired or meant for another audience."""


class GoogleVerifier(Protocol):
    """Turns a Google ID token into the identity it vouches for."""

    def verify(self, id_token: str) -> GoogleIdentity:
        """Return the identity of the token.

        Raises GoogleTokenInvalid when the token cannot be trusted.
        """
        ...


class GoogleIdTokenVerifier:
    """Verifies ID tokens against Google's signing keys and the given audiences."""

    def __init__(self, client_ids: list[str]) -> None:
        self.client_ids = client_ids

    def verify(self, id_token: str) -> GoogleIdentity:
        if not self.client_ids:
            raise GoogleTokenInvalid("no Google client IDs are configured")
        parts = id_token.split(".")
        if len(parts) != 3 or not all(parts):
            raise GoogleTokenInvalid("malformed token")
        try:
            claims = google_id_token.verify_oauth2_token(
                id_token, requests.Request(), self.client_ids
            )
        except Exception as error:
            raise GoogleTokenInvalid("token verification failed") from error
        subject = claims.get("sub")
        email = claims.get("email")
        if not subject or not email:
            raise GoogleTokenInvalid("token lacks sub or email")
        return GoogleIdentity(
            subject=subject,
            email=email,
            email_verified=claims.get("email_verified") is True,
            name=claims.get("name"),
        )


def verify_google_token(verifier: GoogleVerifier, id_token: str) -> GoogleIdentity:
    """Return the identity of a Google ID token.

    Raises 401 GOOGLE_TOKEN_INVALID (field `idToken`) when it cannot be trusted.
    """
    try:
        return verifier.verify(id_token)
    except GoogleTokenInvalid:
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", field="idToken") from None


def get_google_verifier() -> GoogleVerifier:
    """Return a verifier for the audiences in the settings."""
    return GoogleIdTokenVerifier(get_settings().google_client_ids)
