"""Settings are read from environment variables."""

import pytest

ENV_NAMES = ("GEMINI_MODEL", "GEMINI_API_KEY", "INVITATION_BASE_URL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    from app.config import get_settings

    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_settings():
    from app.config import Settings

    return Settings(_env_file=None)


def test_defaults_apply_when_environment_is_empty():
    settings = make_settings()
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_api_key is None
    assert settings.invitation_base_url == "https://niscala.app"


def test_gemini_model_is_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "other")
    assert make_settings().gemini_model == "other"


def test_gemini_api_key_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert make_settings().gemini_api_key == "secret"


def test_invitation_base_url_is_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("INVITATION_BASE_URL", "https://example.test")
    assert make_settings().invitation_base_url == "https://example.test"


def test_environment_names_are_case_insensitive(monkeypatch):
    monkeypatch.setenv("gemini_model", "lower-case")
    assert make_settings().gemini_model == "lower-case"


def test_unknown_environment_variables_are_ignored(monkeypatch):
    monkeypatch.setenv("SOMETHING_UNRELATED", "value")
    settings = make_settings()
    assert not hasattr(settings, "something_unrelated")


def test_get_settings_returns_the_same_cached_object():
    from app.config import get_settings

    assert get_settings() is get_settings()


def test_get_settings_reflects_environment_after_cache_clear(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_MODEL", "first")
    assert get_settings().gemini_model == "first"
    monkeypatch.setenv("GEMINI_MODEL", "second")
    assert get_settings().gemini_model == "first"
    get_settings.cache_clear()
    assert get_settings().gemini_model == "second"
