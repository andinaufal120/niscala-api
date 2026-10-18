"""Settings are read from environment variables."""

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

ENV_NAMES = ("GEMINI_MODEL", "GEMINI_API_KEY", "INVITATION_BASE_URL", "DATABASE_URL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    from app.config import get_settings

    for name in (*ENV_NAMES, "JWT_SECRET", "INVITATION_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("JWT_SECRET", "settings-test-secret-0123456789abcdef")
    monkeypatch.setenv("INVITATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
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


def test_database_url_defaults_to_local_postgres():
    assert (
        make_settings().database_url
        == "postgresql+psycopg://niscala:niscala@localhost:5432/niscala"
    )


def test_database_url_is_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5433/other")
    assert make_settings().database_url == "postgresql+psycopg://u:p@db:5433/other"


def test_jwt_secret_is_required(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ValidationError):
        make_settings()


def test_jwt_secret_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "another-secret-0123456789abcdef0123")
    assert make_settings().jwt_secret == "another-secret-0123456789abcdef0123"


def test_invitation_encryption_key_is_required(monkeypatch):
    monkeypatch.delenv("INVITATION_ENCRYPTION_KEY")
    with pytest.raises(ValidationError):
        make_settings()


def test_invitation_encryption_key_is_read_from_environment(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("INVITATION_ENCRYPTION_KEY", key)
    assert make_settings().invitation_encryption_key == key


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
