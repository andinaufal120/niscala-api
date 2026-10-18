"""Classifying a complaint description into a category and urgency."""

from collections.abc import Sequence
from typing import Protocol

from app.schemas.complaints import AiComplaintClassification


class ClassificationUnavailable(Exception):
    """The classifier cannot produce a result right now."""


class ComplaintClassifier(Protocol):
    """Something that classifies a complaint description."""

    def classify(
        self, description: str, categories: Sequence[str]
    ) -> AiComplaintClassification:
        """Return the category, urgency and suggested action for `description`.

        Raises ClassificationUnavailable when no result can be produced.
        """
        ...


class UnavailableClassifier:
    """The classifier used until a real one is configured; it never classifies."""

    def classify(
        self, description: str, categories: Sequence[str]
    ) -> AiComplaintClassification:
        raise ClassificationUnavailable("No complaint classifier is configured.")


def get_complaint_classifier() -> ComplaintClassifier:
    """Return the classifier complaints are classified with."""
    return UnavailableClassifier()
