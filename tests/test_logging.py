"""The `app` logger emits INFO records to a stream once the application is imported."""

import importlib
import io
import logging
from collections.abc import Iterator

import pytest

import app.main
from app.email import ConsoleEmailSender


def _stream_handlers() -> list[logging.StreamHandler]:
    return [
        h
        for h in logging.getLogger("app").handlers
        if isinstance(h, logging.StreamHandler)
    ]


@pytest.fixture
def captured_stream() -> Iterator[io.StringIO]:
    """Point the `app` logger's stream handler at a StringIO."""
    handlers = _stream_handlers()
    assert handlers, "no stream handler attached to the app logger"
    handler = handlers[0]
    original = handler.stream
    stream = io.StringIO()
    handler.setStream(stream)
    try:
        yield stream
    finally:
        handler.setStream(original)


def test_app_logger_level_is_info() -> None:
    assert logging.getLogger("app").level == logging.INFO


def test_app_logger_has_exactly_one_handler() -> None:
    assert len(logging.getLogger("app").handlers) == 1


def test_app_logger_handler_is_a_stream_handler() -> None:
    (handler,) = logging.getLogger("app").handlers
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)


def test_reloading_main_keeps_exactly_one_handler() -> None:
    importlib.reload(app.main)
    importlib.reload(app.main)
    assert len(logging.getLogger("app").handlers) == 1
    assert logging.getLogger("app").level == logging.INFO


def test_email_logger_inherits_info_level_from_app_logger() -> None:
    assert logging.getLogger("app.email").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("app.email").isEnabledFor(logging.INFO)


def test_info_record_from_email_logger_is_written_to_the_stream(
    captured_stream: io.StringIO,
) -> None:
    logging.getLogger("app.email").info("hello from email")
    assert "hello from email" in captured_stream.getvalue()


def test_console_email_sender_writes_the_verification_code_to_the_stream(
    captured_stream: io.StringIO,
) -> None:
    ConsoleEmailSender().send_verification_code("owner@example.com", "123456")
    output = captured_stream.getvalue()
    assert "owner@example.com" in output
    assert "123456" in output


def test_debug_record_is_not_written_to_the_stream(
    captured_stream: io.StringIO,
) -> None:
    logging.getLogger("app.email").debug("too verbose")
    assert "too verbose" not in captured_stream.getvalue()


def test_each_record_is_written_once_after_reload(
    captured_stream: io.StringIO,
) -> None:
    importlib.reload(app.main)
    # reload may replace nothing, but the handler under test must still be attached
    handlers = _stream_handlers()
    assert len(handlers) == 1
    handlers[0].setStream(captured_stream)
    logging.getLogger("app.email").info("only once")
    assert captured_stream.getvalue().count("only once") == 1
