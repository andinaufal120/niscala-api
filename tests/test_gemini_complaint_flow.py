"""Submitting complaints end to end with the Gemini classifier configured."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
DESCRIPTION = "Lampu di kamar mati total sejak semalam."
VALID = json.dumps(
    {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Panggil teknisi listrik",
    }
)


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


@pytest.fixture
def gemini(monkeypatch):
    """Configure an API key and return a function installing the fake client."""
    from app.ai import gemini as gemini_module
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()

    def install(text=VALID, error=None) -> FakeClient:
        client = FakeClient(text, error)
        monkeypatch.setattr(gemini_module, "create_client", lambda api_key: client)
        return client

    yield install
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def owner(make_user, subscribe_owner):
    user = make_user(name="Rina Owner")
    subscribe_owner(user, "basic")
    return user


@pytest.fixture
def headers(owner, make_property, make_room, make_verified_tenant, sign_in):
    room = make_room(make_property(owner, name="Kos Melati"), number="A1")
    return sign_in(make_verified_tenant(room).user).headers


def submit(client, headers):
    return client.post(COMPLAINTS, json={"description": DESCRIPTION}, headers=headers)


def stored(database, complaint_id):
    from app.models import Complaint

    with Session(database, expire_on_commit=False) as db:
        return db.get(Complaint, UUID(str(complaint_id)))


def test_a_valid_gemini_answer_is_shown_on_the_complaint(
    client, database, headers, app, gemini
):
    from app.ai.classifier import get_complaint_classifier

    fake = gemini()
    assert get_complaint_classifier not in app.dependency_overrides
    response = submit(client, headers)
    assert response.status_code == 201, response.text
    detail = client.get(f"{COMPLAINTS}/{response.json()['id']}", headers=headers)
    body = detail.json()
    assert body["classification"]["category"] == "Listrik"
    assert body["classification"]["urgency"] == "high"
    assert body["classification"]["suggestedAction"] == "Panggil teknisi listrik"
    assert body["classificationState"] is None
    assert len(fake.models.calls) == 1
    assert DESCRIPTION in fake.models.calls[0]["contents"]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        pytest.param(None, RuntimeError("boom"), id="client_error"),
        pytest.param(None, TimeoutError("slow"), id="timeout"),
        pytest.param("not json", None, id="invalid_json"),
        pytest.param(None, None, id="no_text"),
        pytest.param(
            json.dumps(
                {"category": "Astrologi", "urgency": "low", "suggestedAction": "x"}
            ),
            None,
            id="category_outside_the_list",
        ),
        pytest.param(
            json.dumps(
                {"category": "Air", "urgency": "urgent", "suggestedAction": "x"}
            ),
            None,
            id="unknown_urgency",
        ),
    ],
)
def test_an_unusable_gemini_outcome_leaves_the_complaint_awaiting(
    client, database, headers, gemini, text, error
):
    gemini(text=text, error=error)
    response = submit(client, headers)
    assert response.status_code == 201, response.text
    row = stored(database, response.json()["id"])
    assert row.classification_state == "awaitingClassification"
    assert row.ai_category is None
    assert row.ai_urgency is None
    assert row.ai_suggested_action is None
    detail = client.get(f"{COMPLAINTS}/{row.id}", headers=headers).json()
    assert detail["classificationState"] == "awaitingClassification"
    assert detail["classification"] is None
    assert detail["status"] == "new"


def test_without_an_api_key_the_complaint_is_left_awaiting(
    client, database, headers, monkeypatch
):
    from app.config import get_settings

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    response = submit(client, headers)
    assert response.status_code == 201, response.text
    row = stored(database, response.json()["id"])
    assert row.classification_state == "awaitingClassification"
    get_settings.cache_clear()


def test_an_owner_without_a_subscription_is_not_classified(
    client,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
    gemini,
):
    fake = gemini()
    free_owner = make_user(name="Free Owner")
    room = make_room(make_property(free_owner, name="Kos Gratis"), number="Z1")
    tenant = make_verified_tenant(room)
    response = submit(client, sign_in(tenant.user).headers)
    assert response.status_code == 201, response.text
    row = stored(database, response.json()["id"])
    assert row.classification_state == "notClassified"
    assert row.ai_category is None
    assert fake.models.calls == []
