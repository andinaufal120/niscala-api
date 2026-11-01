"""The Gemini payment pattern summarizer."""

import json
import re
from datetime import date
from types import SimpleNamespace

import pytest

MODEL = "test-model-1"
SUMMARY = "Penyewa sering terlambat membayar, sebaiknya dihubungi."


def answer(**overrides):
    body = {"summary": SUMMARY}
    body.update(overrides)
    return json.dumps(body)


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


class FakeClient:
    def __init__(self, text=None, error=None):
        self.models = FakeModels(text, error)


def facts():
    from app.services.payment_patterns import PaymentFacts

    return PaymentFacts(
        on_time_count=3,
        counted_bill_count=5,
        average_days_late=4,
        arrears=2750000,
        at_risk=True,
    )


def bills():
    from app.schemas.payments import PaymentStatus
    from app.services.payment_patterns import CountedBill

    return [
        CountedBill(date(2026, 10, 5), PaymentStatus.UNPAID, 18),
        CountedBill(date(2026, 9, 5), PaymentStatus.PAID, 6),
        CountedBill(date(2026, 8, 5), PaymentStatus.REJECTED, 49),
    ]


def make_summarizer(text=None, error=None, model=MODEL):
    from app.ai.gemini import GeminiPaymentPatternSummarizer

    client = FakeClient(text, error)
    return GeminiPaymentPatternSummarizer(client, model), client


def summarize(text=None, error=None):
    summarizer, client = make_summarizer(text, error)
    return summarizer.summarize(facts(), bills()), client


def assert_unavailable(text=None, error=None):
    from app.ai.summarizer import SummaryUnavailable

    summarizer, client = make_summarizer(text, error)
    with pytest.raises(SummaryUnavailable) as caught:
        summarizer.summarize(facts(), bills())
    return caught.value, client


# A valid answer


def test_a_valid_answer_becomes_the_summary():
    result, _ = summarize(answer())
    assert result == SUMMARY


def test_surrounding_whitespace_is_trimmed():
    result, _ = summarize(answer(summary="\n  Tepat waktu. \t"))
    assert result == "Tepat waktu."


def test_a_two_sentence_summary_is_accepted():
    text = "Penyewa sering terlambat. Tunggakan Rp 2.750.000 perlu ditagih."
    result, _ = summarize(answer(summary=text))
    assert result == text


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("a" * 500, id="exactly_five_hundred"),
        pytest.param("Tunggakan 2750000000 rupiah", id="long_digit_run"),
        pytest.param("Rekening 1234 5678 9012", id="spaced_digits"),
        pytest.param("Terlambat < 7 hari", id="less_than_sign_before_space"),
        pytest.param("Terlambat 3 kali, rata-rata 4 hari", id="small_numbers"),
    ],
)
def test_an_ordinary_summary_is_accepted(text):
    result, _ = summarize(answer(summary=text))
    assert result == text


def test_a_summary_of_five_hundred_characters_with_padding_is_accepted():
    result, _ = summarize(answer(summary="  " + "a" * 500 + "\n"))
    assert result == "a" * 500


# The request sent to the model


def test_the_client_is_called_exactly_once():
    _, client = summarize(answer())
    assert len(client.models.calls) == 1


def test_the_configured_model_is_requested():
    summarizer, client = make_summarizer(answer(), model="another-model")
    summarizer.summarize(facts(), bills())
    assert client.models.calls[0]["model"] == "another-model"


def system_instruction(client):
    instruction = client.models.calls[0]["config"].system_instruction
    assert isinstance(instruction, str)
    return instruction


def contents(client):
    value = client.models.calls[0]["contents"]
    assert isinstance(value, str)
    return value


def test_the_system_instruction_asks_for_one_or_two_indonesian_sentences():
    _, client = summarize(answer())
    instruction = system_instruction(client)
    assert "Indonesian" in instruction
    assert re.search(r"(1|one)\s+(to|or)\s+(2|two)", instruction, re.IGNORECASE)
    assert "sentence" in instruction.lower()


def test_the_system_instruction_names_the_property_manager_as_the_reader():
    _, client = summarize(answer())
    assert "manager" in system_instruction(client).lower()


def test_the_system_instruction_forbids_links_and_html():
    _, client = summarize(answer())
    instruction = system_instruction(client).lower()
    assert "link" in instruction
    assert "html" in instruction


def test_the_contents_carry_every_fact():
    _, client = summarize(answer())
    text = contents(client)
    for value in ("3", "5", "4", "2750000"):
        assert value in text
    assert "true" in text.lower()


def test_the_contents_carry_every_counted_bill():
    _, client = summarize(answer())
    text = contents(client)
    for due_date in ("2026-10-05", "2026-09-05", "2026-08-05"):
        assert due_date in text
    for status in ("unpaid", "paid", "rejected"):
        assert status in text
    for days_late in ("18", "6", "49"):
        assert days_late in text


def test_the_request_asks_for_json_with_a_summary_field():
    _, client = summarize(answer())
    config = client.models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    dumped = json.dumps(config.model_dump(mode="json"))
    assert "summary" in dumped


def test_the_request_carries_a_ten_second_timeout():
    _, client = summarize(answer())
    config = client.models.calls[0]["config"]
    assert config.http_options is not None
    assert config.http_options.timeout == 10000


# Answers that cannot be used


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("   \n", id="blank"),
        pytest.param("not json at all", id="invalid_json"),
        pytest.param('{"summary": "Tepat waktu."', id="truncated_json"),
        pytest.param("[]", id="array"),
        pytest.param('"Tepat waktu."', id="string"),
        pytest.param("42", id="number"),
        pytest.param("null", id="null"),
        pytest.param("{}", id="empty_object"),
        pytest.param('{"other": "Tepat waktu."}', id="wrong_key"),
    ],
)
def test_an_answer_that_is_not_a_json_object_with_the_key_is_unavailable(text):
    assert_unavailable(text)


@pytest.mark.parametrize("value", [None, 1, True, ["Tepat waktu."], {"a": "b"}])
def test_a_summary_that_is_not_a_string_is_unavailable(value):
    assert_unavailable(answer(summary=value))


@pytest.mark.parametrize("summary", ["", "   ", "\n\t"])
def test_an_empty_summary_is_unavailable(summary):
    assert_unavailable(answer(summary=summary))


@pytest.mark.parametrize(
    "summary",
    [
        pytest.param("a" * 501, id="too_long"),
        pytest.param("a" * 1000, id="far_too_long"),
        pytest.param("http://x.id", id="http_link"),
        pytest.param("https://x.id/a", id="https_link"),
        pytest.param("Kunjungi www.evil.com", id="www_link"),
        pytest.param("Lihat WWW.EVIL.COM", id="uppercase_www_link"),
        pytest.param("Hubungi HTTP://x.id segera", id="uppercase_scheme_link"),
        pytest.param('<a href="x">klik</a>', id="anchor_tag"),
        pytest.param("<script>alert(1)</script>", id="script_tag"),
        pytest.param("Terlambat</b>", id="closing_tag"),
        pytest.param("Terlambat <!-- komentar -->", id="comment"),
        pytest.param("Terlambat <b>sekali", id="inline_tag"),
    ],
)
def test_a_suspicious_summary_is_unavailable(summary):
    assert_unavailable(answer(summary=summary))


def test_an_unusable_answer_is_not_retried():
    _, client = assert_unavailable("garbage")
    assert len(client.models.calls) == 1


def test_a_suspicious_summary_is_not_retried():
    _, client = assert_unavailable(answer(summary="https://x.id"))
    assert len(client.models.calls) == 1


# Failures of the client


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom"),
        TimeoutError("too slow"),
        ValueError("bad"),
        ConnectionError("down"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_a_client_error_is_unavailable_and_keeps_its_cause(error):
    raised, client = assert_unavailable(error=error)
    assert raised.__cause__ is error
    assert len(client.models.calls) == 1


def test_an_sdk_error_is_unavailable_and_keeps_its_cause():
    from google.genai import errors

    error = errors.APIError(500, {"error": {"message": "server"}})
    raised, _ = assert_unavailable(error=error)
    assert raised.__cause__ is error


def test_a_summary_unavailable_from_the_client_is_re_raised_as_is():
    from app.ai.summarizer import SummaryUnavailable

    original = SummaryUnavailable("down")
    summarizer, _ = make_summarizer(error=original)
    with pytest.raises(SummaryUnavailable) as caught:
        summarizer.summarize(facts(), bills())
    assert caught.value is original


def test_no_bills_still_makes_one_request():
    summarizer, client = make_summarizer(answer())
    assert summarizer.summarize(facts(), []) == SUMMARY
    assert len(client.models.calls) == 1
