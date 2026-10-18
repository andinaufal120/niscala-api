"""The Gemini complaint classifier and the choice of the default classifier."""

import json
from types import SimpleNamespace

import pytest

CATEGORIES = (
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
)
DESCRIPTION = "Lampu di kamar saya mati total sejak semalam."
MODEL = "test-model-1"


def answer(**overrides):
    body = {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Panggil teknisi listrik",
    }
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


def make_classifier(text=None, error=None, model=MODEL):
    from app.ai.gemini import GeminiComplaintClassifier

    client = FakeClient(text, error)
    return GeminiComplaintClassifier(client, model), client


def classify(text=None, error=None):
    classifier, client = make_classifier(text, error)
    return classifier.classify(DESCRIPTION, CATEGORIES), client


def assert_unavailable(text=None, error=None):
    from app.ai.classifier import ClassificationUnavailable

    classifier, client = make_classifier(text, error)
    with pytest.raises(ClassificationUnavailable) as caught:
        classifier.classify(DESCRIPTION, CATEGORIES)
    return caught.value, client


# A valid answer


def test_a_valid_answer_becomes_a_classification():
    from app.schemas.complaints import AiComplaintClassification, ComplaintUrgency

    result, _ = classify(answer())
    assert isinstance(result, AiComplaintClassification)
    assert result.category == "Listrik"
    assert result.urgency == ComplaintUrgency.HIGH
    assert result.suggested_action == "Panggil teknisi listrik"


@pytest.mark.parametrize("urgency", ["low", "medium", "high"])
def test_every_urgency_is_accepted(urgency):
    from app.schemas.complaints import ComplaintUrgency

    result, _ = classify(answer(urgency=urgency))
    assert result.urgency == ComplaintUrgency(urgency)


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_of_the_list_is_accepted(category):
    result, _ = classify(answer(category=category))
    assert result.category == category


def test_surrounding_whitespace_is_trimmed():
    result, _ = classify(
        answer(category="  Air\n", urgency=" low ", suggestedAction="\n Cek pipa \t")
    )
    assert result.category == "Air"
    assert result.suggested_action == "Cek pipa"


def test_only_the_given_categories_are_accepted():
    from app.ai.classifier import ClassificationUnavailable

    classifier, _ = make_classifier(answer(category="Listrik"))
    with pytest.raises(ClassificationUnavailable):
        classifier.classify(DESCRIPTION, ("Air", "Lainnya"))


# The request sent to the model


def test_the_client_is_called_exactly_once():
    _, client = classify(answer())
    assert len(client.models.calls) == 1


def test_the_configured_model_is_requested():
    classifier, client = make_classifier(answer(), model="another-model")
    classifier.classify(DESCRIPTION, CATEGORIES)
    assert client.models.calls[0]["model"] == "another-model"


def test_the_prompt_is_a_string_with_the_description_verbatim():
    _, client = classify(answer())
    contents = client.models.calls[0]["contents"]
    assert isinstance(contents, str)
    assert DESCRIPTION in contents


def test_the_prompt_lists_every_category_in_order():
    _, client = classify(answer())
    contents = client.models.calls[0]["contents"]
    positions = [contents.index(category) for category in CATEGORIES]
    assert positions == sorted(positions)


def test_the_prompt_lists_only_the_given_categories():
    classifier, client = make_classifier(answer(category="Air"))
    classifier.classify(DESCRIPTION, ("Air", "Lainnya"))
    contents = client.models.calls[0]["contents"]
    assert "Air" in contents
    assert "Lainnya" in contents
    assert "Perabot" not in contents


def test_the_description_is_not_altered_by_the_prompt():
    tricky = '  Pintu "rusak" {braces} dan\nbaris baru  '
    classifier, client = make_classifier(answer())
    classifier.classify(tricky, CATEGORIES)
    assert tricky in client.models.calls[0]["contents"]


def test_the_request_asks_for_json():
    _, client = classify(answer())
    config = client.models.calls[0]["config"]
    assert config.response_mime_type == "application/json"


def test_the_response_schema_restricts_the_category_to_the_given_categories():
    classifier, client = make_classifier(answer(category="Air"))
    classifier.classify(DESCRIPTION, ("Air", "Lainnya"))
    dumped = json.dumps(client.models.calls[0]["config"].model_dump(mode="json"))
    assert "application/json" in dumped
    assert "Air" in dumped
    assert "Lainnya" in dumped
    assert "Perabot" not in dumped


def test_the_response_schema_names_the_answer_fields():
    _, client = classify(answer())
    dumped = json.dumps(client.models.calls[0]["config"].model_dump(mode="json"))
    for name in ("category", "urgency", "suggestedAction"):
        assert name in dumped
    for urgency in ("low", "medium", "high"):
        assert urgency in dumped


def test_the_request_carries_a_ten_second_timeout():
    _, client = classify(answer())
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
        pytest.param('{"category": "Listrik"', id="truncated_json"),
        pytest.param("[]", id="array"),
        pytest.param('["Listrik", "high", "x"]', id="array_of_strings"),
        pytest.param('"Listrik"', id="string"),
        pytest.param("42", id="number"),
        pytest.param("null", id="null"),
        pytest.param("{}", id="empty_object"),
    ],
)
def test_an_answer_that_is_not_a_json_object_with_the_keys_is_unavailable(text):
    assert_unavailable(text)


@pytest.mark.parametrize("missing", ["category", "urgency", "suggestedAction"])
def test_a_missing_key_is_unavailable(missing):
    body = json.loads(answer())
    del body[missing]
    assert_unavailable(json.dumps(body))


@pytest.mark.parametrize("category", ["Astrologi", "listrik", "LISTRIK", "", " "])
def test_a_category_outside_the_list_is_unavailable(category):
    assert_unavailable(answer(category=category))


@pytest.mark.parametrize("urgency", ["urgent", "HIGH", "Medium", "", "critical"])
def test_an_unknown_urgency_is_unavailable(urgency):
    assert_unavailable(answer(urgency=urgency))


@pytest.mark.parametrize("action", ["", "   ", "\n\t"])
def test_an_empty_suggested_action_is_unavailable(action):
    assert_unavailable(answer(suggestedAction=action))


@pytest.mark.parametrize("key", ["category", "urgency", "suggestedAction"])
@pytest.mark.parametrize("value", [None, 1, True, ["Listrik"], {"a": "b"}])
def test_a_value_that_is_not_a_string_is_unavailable(key, value):
    assert_unavailable(answer(**{key: value}))


def test_an_unusable_answer_is_not_retried():
    _, client = assert_unavailable("garbage")
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


def test_a_classification_unavailable_from_the_client_is_re_raised_as_is():
    from app.ai.classifier import ClassificationUnavailable

    original = ClassificationUnavailable("down")
    classifier, _ = make_classifier(error=original)
    with pytest.raises(ClassificationUnavailable) as caught:
        classifier.classify(DESCRIPTION, CATEGORIES)
    assert caught.value is original


# The client factory


def test_create_client_returns_an_sdk_client():
    from google import genai

    from app.ai.gemini import create_client

    assert isinstance(create_client("dummy-key"), genai.Client)


def test_create_client_carries_a_ten_second_timeout():
    from app.ai.gemini import create_client

    client = create_client("dummy-key")
    options = client._api_client._http_options
    assert options.timeout == 10000


# Choosing the default classifier


@pytest.fixture
def gemini_env(monkeypatch):
    """Set or clear the Gemini settings and refresh the settings cache."""
    from app.config import get_settings

    def configure(key=None, model=None):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        if key is not None:
            monkeypatch.setenv("GEMINI_API_KEY", key)
        if model is not None:
            monkeypatch.setenv("GEMINI_MODEL", model)
        get_settings.cache_clear()

    yield configure
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def created_clients(monkeypatch):
    """Replace `create_client` with a recorder returning `FakeClient`s."""
    from app.ai import gemini

    made: list[tuple[str, FakeClient]] = []

    def fake_create_client(api_key):
        client = FakeClient(answer())
        made.append((api_key, client))
        return client

    monkeypatch.setattr(gemini, "create_client", fake_create_client)
    return made


def test_a_configured_key_selects_the_gemini_classifier(gemini_env, created_clients):
    from app.ai.classifier import get_complaint_classifier
    from app.ai.gemini import GeminiComplaintClassifier

    gemini_env(key="secret-key")
    assert isinstance(get_complaint_classifier(), GeminiComplaintClassifier)


def test_the_key_is_passed_to_create_client(gemini_env, created_clients):
    from app.ai.classifier import get_complaint_classifier

    gemini_env(key="secret-key")
    get_complaint_classifier()
    assert [key for key, _ in created_clients] == ["secret-key"]


def test_the_configured_model_is_used_by_the_default_classifier(
    gemini_env, created_clients
):
    from app.ai.classifier import get_complaint_classifier

    gemini_env(key="secret-key", model="configured-model")
    get_complaint_classifier().classify(DESCRIPTION, CATEGORIES)
    ((_, client),) = created_clients
    assert client.models.calls[0]["model"] == "configured-model"


def test_the_default_model_is_used_when_none_is_configured(gemini_env, created_clients):
    from app.ai.classifier import get_complaint_classifier
    from app.config import Settings

    gemini_env(key="secret-key")
    get_complaint_classifier().classify(DESCRIPTION, CATEGORIES)
    ((_, client),) = created_clients
    assert (
        client.models.calls[0]["model"] == Settings.model_fields["gemini_model"].default
    )


@pytest.mark.parametrize("key", [None, "", "   "])
def test_without_a_usable_key_the_classifier_is_unavailable(
    gemini_env, created_clients, key
):
    from app.ai.classifier import UnavailableClassifier, get_complaint_classifier

    gemini_env(key=key)
    assert isinstance(get_complaint_classifier(), UnavailableClassifier)
    assert created_clients == []
