"""The complaint categories, the classifier dependency and its default."""

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


def test_complaint_categories_are_the_agreed_list_in_order():
    from app.config import COMPLAINT_CATEGORIES

    assert tuple(COMPLAINT_CATEGORIES) == CATEGORIES


def test_complaint_categories_are_a_tuple_of_strings():
    from app.config import COMPLAINT_CATEGORIES

    assert isinstance(COMPLAINT_CATEGORIES, tuple)
    assert all(isinstance(name, str) for name in COMPLAINT_CATEGORIES)


def test_classification_timeout_is_ten_seconds():
    from app.services import complaints

    assert complaints.CLASSIFICATION_TIMEOUT_SECONDS == 10.0


def test_classification_unavailable_is_an_exception():
    from app.ai.classifier import ClassificationUnavailable

    assert issubclass(ClassificationUnavailable, Exception)


def test_default_classifier_is_always_unavailable():
    from app.ai.classifier import ClassificationUnavailable, get_complaint_classifier

    classifier = get_complaint_classifier()
    with pytest.raises(ClassificationUnavailable):
        classifier.classify("The tap leaks badly.", CATEGORIES)


def test_default_classifier_is_unavailable_for_every_description():
    from app.ai.classifier import ClassificationUnavailable, get_complaint_classifier

    classifier = get_complaint_classifier()
    for description in ("Lampu mati total di kamar.", "x" * 5000):
        with pytest.raises(ClassificationUnavailable):
            classifier.classify(description, CATEGORIES)


def test_fake_classifier_override_replaces_the_dependency(app, fake_classifier):
    from app.ai.classifier import get_complaint_classifier

    assert app.dependency_overrides[get_complaint_classifier]() is fake_classifier


def test_fake_classifier_override_is_removed_after_the_test(app):
    from app.ai.classifier import get_complaint_classifier

    assert get_complaint_classifier not in app.dependency_overrides
