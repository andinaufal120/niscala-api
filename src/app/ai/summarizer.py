"""Summarizing how a tenant pays, for the property manager."""

from collections.abc import Sequence
from typing import Protocol

from app.config import get_settings
from app.services.payment_patterns import CountedBill, PaymentFacts


class SummaryUnavailable(Exception):
    """The summarizer cannot produce a summary right now."""


class PaymentPatternSummarizer(Protocol):
    """Something that summarizes the payment facts of a lease."""

    def summarize(self, facts: PaymentFacts, bills: Sequence[CountedBill]) -> str:
        """Return a short summary of the facts and the counted bills.

        Raises SummaryUnavailable when no summary can be produced.
        """
        ...


class UnavailablePaymentSummarizer:
    """The summarizer used until a real one is configured; it never summarizes."""

    def summarize(self, facts: PaymentFacts, bills: Sequence[CountedBill]) -> str:
        raise SummaryUnavailable("No payment pattern summarizer is configured.")


def get_payment_pattern_summarizer() -> PaymentPatternSummarizer:
    """Return the summarizer payment patterns are summarized with."""
    from app.ai import gemini

    settings = get_settings()
    key = settings.gemini_api_key
    if key and key.strip():
        return gemini.GeminiPaymentPatternSummarizer(
            gemini.create_client(key), settings.gemini_model
        )
    return UnavailablePaymentSummarizer()
