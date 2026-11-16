"""Delivery of emails to users."""

import logging
from typing import Any, Protocol

import requests

from app.config import get_settings

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

    def send_password_reset_link(self, to: str, url: str) -> None:
        """Email the password-reset link to the address."""
        ...


class ConsoleEmailSender:
    """Logs emails instead of sending them."""

    def send_verification_code(self, to: str, code: str) -> None:
        logger.info("Verification code for %s: %s", to, code)

    def send_email_change_link(self, to: str, url: str) -> None:
        logger.info("Email change link for %s: %s", to, url)

    def send_email_change_notice(self, to: str, new_email: str) -> None:
        logger.info("Email change notice for %s: change to %s requested", to, new_email)

    def send_password_reset_link(self, to: str, url: str) -> None:
        logger.info("Password reset link for %s: %s", to, url)


class EmailDeliveryFailed(Exception):
    """The provider refused the message or could not be reached."""


RESEND_URL = "https://api.resend.com/emails"

# Template name -> (subject, body). Bodies are formatted with the message values.
TEMPLATES = {
    "verification_code": (
        "Kode verifikasi Niscala",
        (
            "Kode verifikasi email Anda:\n"
            "\n"
            "{code}\n"
            "\n"
            "Jangan berikan kode ini kepada siapa pun. "
            "Jika Anda tidak memintanya, abaikan email ini."
        ),
    ),
    "password_reset_link": (
        "Atur ulang kata sandi Niscala",
        (
            "Buka tautan berikut untuk membuat kata sandi baru akun Niscala Anda:\n"
            "{url}\n"
            "Tautan ini hanya bisa dipakai sekali. "
            "Jika Anda tidak memintanya, abaikan email ini; "
            "kata sandi Anda tidak berubah."
        ),
    ),
    "email_change_link": (
        "Konfirmasi email baru akun Niscala",
        (
            "Buka tautan berikut untuk menjadikan alamat ini email akun Niscala Anda:\n"
            "{url}\n"
            "Jika Anda tidak mengenali permintaan ini, abaikan email ini."
        ),
    ),
    "email_change_notice": (
        "Permintaan perubahan email akun Niscala",
        (
            "Ada permintaan untuk mengganti email akun Niscala Anda "
            "menjadi {new_email}. "
            "Perubahan baru berlaku setelah dikonfirmasi dari alamat tersebut. "
            "Jika Anda tidak mengenali permintaan ini, hubungi Admin Niscala."
        ),
    ),
}


class ResendEmailSender:
    """Delivers plain-text Indonesian emails through the Resend REST API.

    `session` is a `requests`-like object. A refusal or a network error raises
    EmailDeliveryFailed, whose message carries only the HTTP status and
    Resend's error name, never the message content or the API key.
    """

    def __init__(self, api_key: str, sender: str, session: Any) -> None:
        self.api_key = api_key
        self.sender = sender
        self.session = session

    def send_verification_code(self, to: str, code: str) -> None:
        self._send_template(to, "verification_code", code=code)

    def send_email_change_link(self, to: str, url: str) -> None:
        self._send_template(to, "email_change_link", url=url)

    def send_email_change_notice(self, to: str, new_email: str) -> None:
        self._send_template(to, "email_change_notice", new_email=new_email)

    def send_password_reset_link(self, to: str, url: str) -> None:
        self._send_template(to, "password_reset_link", url=url)

    def _send_template(self, to: str, name: str, **values: str) -> None:
        subject, body = TEMPLATES[name]
        self._send(to, subject, body.format(**values))

    def _send(self, to: str, subject: str, text: str) -> None:
        try:
            response = self.session.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.sender,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                },
                timeout=10,
            )
        except requests.RequestException as error:
            raise EmailDeliveryFailed(
                f"Resend request failed: {type(error).__name__}"
            ) from None
        if response.status_code >= 400:
            details = f"Resend refused the email with HTTP {response.status_code}"
            try:
                name = response.json().get("name")
            except ValueError, AttributeError:
                name = None
            if isinstance(name, str):
                details += f" ({name})"
            raise EmailDeliveryFailed(details)


def get_email_sender() -> EmailSender:
    """Return the Resend sender when an API key is configured, else the console one."""
    settings = get_settings()
    if settings.resend_api_key and settings.resend_api_key.strip():
        assert settings.email_from is not None
        return ResendEmailSender(
            settings.resend_api_key, settings.email_from, requests.Session()
        )
    return ConsoleEmailSender()
