"""The email sender used to deliver verification codes."""

import logging
from typing import Any

import pytest
import requests

RESEND_URL = "https://api.resend.com/emails"
API_KEY = "re_test_key_9f8e7d"
SENDER = "Niscala <no-reply@example.com>"
RECIPIENT = "owner@example.com"
CODE = "483920"
LINK = "https://niscala.app/reset?token=tok-abc123XYZ"
NEW_EMAIL = "fresh-address@example.org"


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status_code = status
        self._body = {"id": "msg_1"} if body is None else body
        self.text = str(self._body)
        self.ok = status < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Records requests and answers them with a prepared response or error."""

    def __init__(self, response: Any = None) -> None:
        self.response = response if response is not None else FakeResponse()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _answer(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((method.upper(), url, kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._answer("POST", url, kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._answer(method, url, kwargs)


def resend_sender(session: FakeSession):
    from app.email import ResendEmailSender

    return ResendEmailSender(API_KEY, SENDER, session)


# method name, the value it sends (code, link or new email), expected subject
METHODS = [
    ("send_verification_code", CODE, "Kode verifikasi Niscala"),
    ("send_password_reset_link", LINK, "Atur ulang kata sandi Niscala"),
    ("send_email_change_link", LINK, "Konfirmasi email baru akun Niscala"),
    (
        "send_email_change_notice",
        NEW_EMAIL,
        "Permintaan perubahan email akun Niscala",
    ),
]
METHOD_IDS = [method for method, _, _ in METHODS]
SECRETS = (CODE, LINK, NEW_EMAIL, API_KEY)


def send(sender, method: str, argument: str) -> None:
    return getattr(sender, method)(RECIPIENT, argument)


@pytest.fixture
def configured_settings(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_default_sender_is_a_console_sender():
    from app.email import ConsoleEmailSender, get_email_sender

    assert isinstance(get_email_sender(), ConsoleEmailSender)


def test_console_sender_logs_the_address_and_code_at_info_level(caplog):
    from app.email import ConsoleEmailSender

    with caplog.at_level(logging.INFO):
        result = ConsoleEmailSender().send_verification_code(
            "owner@example.com", "012345"
        )
    assert result is None
    records = [r for r in caplog.records if "owner@example.com" in r.getMessage()]
    assert records
    assert any("012345" in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_console_sender_logs_every_message_it_sends(caplog):
    from app.email import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        sender.send_verification_code("a@example.com", "111111")
        sender.send_verification_code("b@example.com", "222222")
    assert "a@example.com" in caplog.text
    assert "111111" in caplog.text
    assert "b@example.com" in caplog.text
    assert "222222" in caplog.text


def test_dependency_can_be_replaced_with_a_fake(app, sent_emails):
    from app.email import get_email_sender

    sender = app.dependency_overrides[get_email_sender]()
    sender.send_verification_code("owner@example.com", "123456")
    assert sent_emails == [("owner@example.com", "123456")]


def test_sent_emails_fixture_removes_the_override_afterwards(app):
    from app.email import get_email_sender

    assert get_email_sender not in app.dependency_overrides


def test_sender_is_console_when_no_resend_settings_are_set(configured_settings):
    from app.email import ConsoleEmailSender, get_email_sender

    configured_settings.delenv("RESEND_API_KEY", raising=False)
    configured_settings.delenv("EMAIL_FROM", raising=False)
    assert isinstance(get_email_sender(), ConsoleEmailSender)


def test_sender_is_resend_when_both_resend_settings_are_set(configured_settings):
    from app.email import ResendEmailSender, get_email_sender

    configured_settings.setenv("RESEND_API_KEY", API_KEY)
    configured_settings.setenv("EMAIL_FROM", SENDER)
    assert isinstance(get_email_sender(), ResendEmailSender)


@pytest.mark.parametrize("method", METHOD_IDS)
def test_resend_sender_has_every_protocol_method(method):
    sender = resend_sender(FakeSession())
    assert callable(getattr(sender, method))


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_posts_exactly_once_to_the_emails_endpoint(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    assert len(session.calls) == 1
    http_method, url, _ = session.calls[0]
    assert http_method == "POST"
    assert url == RESEND_URL


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_authenticates_with_a_bearer_header(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    headers = session.calls[0][2]["headers"]
    assert headers["Authorization"] == f"Bearer {API_KEY}"


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_body_has_sender_recipient_and_subject(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    body = session.calls[0][2]["json"]
    assert body["from"] == SENDER
    assert body["to"] == [RECIPIENT]
    assert body["subject"] == subject


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_text_contains_the_argument(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    text = session.calls[0][2]["json"]["text"]
    assert isinstance(text, str)
    assert argument in text


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_sends_plain_text_only(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    body = session.calls[0][2]["json"]
    assert "html" not in body
    assert "<" not in body["text"]
    assert ">" not in body["text"]


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_waits_at_most_ten_seconds(method, argument, subject):
    session = FakeSession()
    send(resend_sender(session), method, argument)
    assert session.calls[0][2]["timeout"] == 10


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
def test_resend_returns_nothing_and_logs_nothing_on_success(
    method, argument, subject, caplog
):
    session = FakeSession()
    with caplog.at_level(logging.DEBUG):
        result = send(resend_sender(session), method, argument)
    assert result is None
    assert [r for r in caplog.records if r.levelno >= logging.INFO] == []


def test_verification_code_is_alone_on_its_own_line():
    session = FakeSession()
    resend_sender(session).send_verification_code(RECIPIENT, CODE)
    lines = session.calls[0][2]["json"]["text"].splitlines()
    assert [line.strip() for line in lines].count(CODE) == 1


def test_verification_code_text_is_indonesian_and_warns_against_sharing():
    session = FakeSession()
    resend_sender(session).send_verification_code(RECIPIENT, CODE)
    text = session.calls[0][2]["json"]["text"]
    assert "Kode verifikasi email Anda:" in text
    assert "Jangan berikan kode ini kepada siapa pun." in text


def test_reset_link_text_is_indonesian():
    session = FakeSession()
    resend_sender(session).send_password_reset_link(RECIPIENT, LINK)
    text = session.calls[0][2]["json"]["text"]
    assert "Tautan ini hanya bisa dipakai sekali." in text


def test_email_change_notice_names_the_new_address_in_indonesian():
    session = FakeSession()
    resend_sender(session).send_email_change_notice(RECIPIENT, NEW_EMAIL)
    text = session.calls[0][2]["json"]["text"]
    assert f"menjadi {NEW_EMAIL}" in text


FAILURES = [
    pytest.param(FakeResponse(400, {"name": "validation_error"}), id="400"),
    pytest.param(FakeResponse(422, {"name": "validation_error"}), id="422"),
    pytest.param(FakeResponse(429, {"name": "rate_limit_exceeded"}), id="429"),
    pytest.param(FakeResponse(500, {"name": "internal_server_error"}), id="500"),
    pytest.param(requests.ConnectionError("connection refused"), id="connection"),
    pytest.param(requests.Timeout("timed out"), id="timeout"),
]


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
@pytest.mark.parametrize("failure", FAILURES)
def test_resend_failure_raises_email_delivery_failed(
    method, argument, subject, failure
):
    from app.email import EmailDeliveryFailed

    with pytest.raises(EmailDeliveryFailed):
        send(resend_sender(FakeSession(failure)), method, argument)


@pytest.mark.parametrize(("method", "argument", "subject"), METHODS, ids=METHOD_IDS)
@pytest.mark.parametrize("failure", FAILURES)
def test_resend_failure_leaks_no_secret_in_message_or_logs(
    method, argument, subject, failure, caplog
):
    from app.email import EmailDeliveryFailed

    with caplog.at_level(logging.DEBUG), pytest.raises(EmailDeliveryFailed) as error:
        send(resend_sender(FakeSession(failure)), method, argument)
    visible = [str(error.value), caplog.text]
    visible += [r.getMessage() for r in caplog.records]
    for secret in SECRETS:
        assert all(secret not in text for text in visible)


def test_email_delivery_failed_is_an_exception():
    from app.email import EmailDeliveryFailed

    assert issubclass(EmailDeliveryFailed, Exception)


def test_delivery_failure_message_names_the_http_status():
    from app.email import EmailDeliveryFailed

    with pytest.raises(EmailDeliveryFailed) as error:
        resend_sender(FakeSession(FakeResponse(429))).send_verification_code(
            RECIPIENT, CODE
        )
    assert "429" in str(error.value)


def test_a_failed_send_is_not_retried():
    from app.email import EmailDeliveryFailed

    session = FakeSession(FakeResponse(500))
    with pytest.raises(EmailDeliveryFailed):
        resend_sender(session).send_verification_code(RECIPIENT, CODE)
    assert len(session.calls) == 1
