"""The payment pattern summarizer contract, its unavailable default and its factory."""

from datetime import date
from types import SimpleNamespace

import pytest


def facts():
    from app.services.payment_patterns import PaymentFacts

    return PaymentFacts(
        on_time_count=1,
        counted_bill_count=2,
        average_days_late=3,
        arrears=0,
        at_risk=False,
    )


def counted():
    from app.services.payment_patterns import CountedBill

    return [CountedBill(date(2026, 10, 5), "paid", 0)]


def test_summary_unavailable_is_an_exception():
    from app.ai.summarizer import SummaryUnavailable

    assert issubclass(SummaryUnavailable, Exception)


def test_the_summarizer_protocol_declares_summarize():
    from app.ai.summarizer import PaymentPatternSummarizer

    assert callable(PaymentPatternSummarizer.summarize)


def test_the_summary_timeout_is_ten_seconds():
    from app.services import payment_patterns

    assert payment_patterns.SUMMARY_TIMEOUT_SECONDS == 10.0


def test_the_unavailable_summarizer_never_summarizes():
    from app.ai.summarizer import SummaryUnavailable, UnavailablePaymentSummarizer

    with pytest.raises(SummaryUnavailable):
        UnavailablePaymentSummarizer().summarize(facts(), counted())


def test_the_unavailable_summarizer_fails_without_bills_too():
    from app.ai.summarizer import SummaryUnavailable, UnavailablePaymentSummarizer

    with pytest.raises(SummaryUnavailable):
        UnavailablePaymentSummarizer().summarize(facts(), [])


def test_fake_summarizer_override_replaces_the_dependency(app, fake_summarizer):
    from app.ai.summarizer import get_payment_pattern_summarizer

    overridden = app.dependency_overrides[get_payment_pattern_summarizer]
    assert overridden() is fake_summarizer


def test_fake_summarizer_override_is_removed_after_the_test(app):
    from app.ai.summarizer import get_payment_pattern_summarizer

    assert get_payment_pattern_summarizer not in app.dependency_overrides


# Choosing the default summarizer


class FakeModels:
    def __init__(self):
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text='{"summary": "Tepat waktu."}')


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


@pytest.fixture
def gemini_settings(monkeypatch):
    """Set the Gemini key explicitly, whatever the environment files say."""
    from app.config import get_settings

    def configure(key: str, model: str | None = None):
        monkeypatch.setenv("GEMINI_API_KEY", key)
        if model is not None:
            monkeypatch.setenv("GEMINI_MODEL", model)
        get_settings.cache_clear()

    yield configure
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def created_clients(monkeypatch):
    """Replace `create_client` with a recorder returning fake clients."""
    from app.ai import gemini

    made: list[tuple[str, FakeClient]] = []

    def fake_create_client(api_key):
        client = FakeClient()
        made.append((api_key, client))
        return client

    monkeypatch.setattr(gemini, "create_client", fake_create_client)
    return made


def test_a_configured_key_selects_the_gemini_summarizer(
    gemini_settings, created_clients
):
    from app.ai.gemini import GeminiPaymentPatternSummarizer
    from app.ai.summarizer import get_payment_pattern_summarizer

    gemini_settings("secret-key")
    assert isinstance(get_payment_pattern_summarizer(), GeminiPaymentPatternSummarizer)


def test_the_key_is_passed_to_create_client(gemini_settings, created_clients):
    from app.ai.summarizer import get_payment_pattern_summarizer

    gemini_settings("secret-key")
    get_payment_pattern_summarizer()
    assert [key for key, _ in created_clients] == ["secret-key"]


def test_the_configured_model_is_used_by_the_default_summarizer(
    gemini_settings, created_clients
):
    from app.ai.summarizer import get_payment_pattern_summarizer

    gemini_settings("secret-key", model="configured-model")
    get_payment_pattern_summarizer().summarize(facts(), counted())
    ((_, client),) = created_clients
    assert client.models.calls[0]["model"] == "configured-model"


@pytest.mark.parametrize("key", ["", "   "])
def test_without_a_usable_key_the_summarizer_is_unavailable(
    gemini_settings, created_clients, key
):
    from app.ai.summarizer import (
        UnavailablePaymentSummarizer,
        get_payment_pattern_summarizer,
    )

    gemini_settings(key)
    assert isinstance(get_payment_pattern_summarizer(), UnavailablePaymentSummarizer)
    assert created_clients == []
