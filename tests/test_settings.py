"""Settings are read from environment variables."""

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

ENV_NAMES = (
    "GEMINI_MODEL",
    "GEMINI_API_KEY",
    "INVITATION_BASE_URL",
    "DATABASE_URL",
    "RESEND_API_KEY",
    "EMAIL_FROM",
)


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


def test_email_settings_default_to_none():
    settings = make_settings()
    assert settings.resend_api_key is None
    assert settings.email_from is None


def test_resend_api_key_and_email_from_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_key")
    monkeypatch.setenv("EMAIL_FROM", "Niscala <no-reply@example.com>")
    settings = make_settings()
    assert settings.resend_api_key == "re_key"
    assert settings.email_from == "Niscala <no-reply@example.com>"


def test_resend_api_key_without_email_from_fails_naming_email_from(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_key")
    with pytest.raises(ValidationError) as error:
        make_settings()
    assert "email_from" in str(error.value).lower()


def test_email_from_without_resend_api_key_fails_naming_resend_api_key(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "Niscala <no-reply@example.com>")
    with pytest.raises(ValidationError) as error:
        make_settings()
    assert "resend_api_key" in str(error.value).lower()


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_email_from_with_a_key_fails_naming_email_from(monkeypatch, blank):
    monkeypatch.setenv("RESEND_API_KEY", "re_key")
    monkeypatch.setenv("EMAIL_FROM", blank)
    with pytest.raises(ValidationError) as error:
        make_settings()
    assert "email_from" in str(error.value).lower()


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_resend_api_key_with_a_sender_fails_naming_resend_api_key(
    monkeypatch, blank
):
    monkeypatch.setenv("RESEND_API_KEY", blank)
    monkeypatch.setenv("EMAIL_FROM", "Niscala <no-reply@example.com>")
    with pytest.raises(ValidationError) as error:
        make_settings()
    assert "resend_api_key" in str(error.value).lower()


@pytest.mark.parametrize("blank", ["", "   "])
def test_both_email_settings_blank_load_as_unset(monkeypatch, blank):
    monkeypatch.setenv("RESEND_API_KEY", blank)
    monkeypatch.setenv("EMAIL_FROM", blank)
    settings = make_settings()
    assert not (settings.resend_api_key or "").strip()
    assert not (settings.email_from or "").strip()
