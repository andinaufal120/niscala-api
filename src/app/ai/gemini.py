"""Classifying complaints with Google Gemini."""

import json
from collections.abc import Sequence

from google import genai
from google.genai import types

from app.ai.classifier import ClassificationUnavailable
from app.schemas.complaints import AiComplaintClassification, ComplaintUrgency

TIMEOUT_MS = 10000

_URGENCIES = [urgency.value for urgency in ComplaintUrgency]


def create_client(api_key: str) -> genai.Client:
    """Return a Gemini client whose requests time out after 10 seconds."""
    return genai.Client(
        api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS)
    )


def _response_schema(categories: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(categories)},
            "urgency": {"type": "string", "enum": _URGENCIES},
            "suggestedAction": {"type": "string"},
        },
        "required": ["category", "urgency", "suggestedAction"],
    }


def _prompt(description: str, categories: Sequence[str]) -> str:
    return (
        "The text below is a maintenance complaint from a boarding house tenant, "
        "written in Indonesian.\n"
        f"Choose exactly one category from this list: {', '.join(categories)}.\n"
        f"Choose an urgency: {', '.join(_URGENCIES)}.\n"
        "Write a short suggested action for the property manager in Indonesian.\n\n"
        f"Complaint:\n{description}"
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ClassificationUnavailable("The model answer has a non-text field.")
    return value.strip()


def _parse(text: str | None, categories: Sequence[str]) -> AiComplaintClassification:
    if text is None or not text.strip():
        raise ClassificationUnavailable("The model returned no text.")
    try:
        body = json.loads(text)
    except ValueError as error:
        raise ClassificationUnavailable("The model answer is not JSON.") from error
    if not isinstance(body, dict):
        raise ClassificationUnavailable("The model answer is not a JSON object.")
    try:
        category = _text(body["category"])
        urgency = _text(body["urgency"])
        action = _text(body["suggestedAction"])
    except KeyError as error:
        raise ClassificationUnavailable("The model answer lacks a field.") from error
    if category not in categories:
        raise ClassificationUnavailable("The model chose an unknown category.")
    if urgency not in _URGENCIES:
        raise ClassificationUnavailable("The model chose an unknown urgency.")
    if not action:
        raise ClassificationUnavailable("The model gave no suggested action.")
    return AiComplaintClassification(
        category=category,
        urgency=ComplaintUrgency(urgency),
        suggested_action=action,
    )


class GeminiComplaintClassifier:
    """Classifies complaints with a single Gemini request and no retries."""

    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    def classify(
        self, description: str, categories: Sequence[str]
    ) -> AiComplaintClassification:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=_response_schema(categories),
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=_prompt(description, categories),
                config=config,
            )
            text = response.text
        except ClassificationUnavailable:
            raise
        except Exception as error:
            raise ClassificationUnavailable("The Gemini request failed.") from error
        return _parse(text, categories)
