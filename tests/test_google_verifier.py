"""The Google ID token verifier, its identity type and its settings."""

import dataclasses
import socket

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    from app.config import get_settings

    for name in ("GOOGLE_CLIENT_IDS", "DATABASE_URL"):
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


@pytest.fixture
def network(monkeypatch):
    """Record every attempt to reach the network and refuse it."""
    attempts: list[object] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("the network is not available in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


def real_verifier(monkeypatch, client_ids: str | None):
    from app.config import get_settings
    from app.google import get_google_verifier

    if client_ids is None:
        monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)
    else:
        monkeypatch.setenv("GOOGLE_CLIENT_IDS", client_ids)
    get_settings.cache_clear()
    clear = getattr(get_google_verifier, "cache_clear", None)
    if callable(clear):
        clear()
    return get_google_verifier()


# Settings


def test_no_client_ids_are_configured_by_default():
    assert make_settings().google_client_ids == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", ["a"]),
        ("a,b", ["a", "b"]),
        ("a,b,c", ["a", "b", "c"]),
        (" a , b ", ["a", "b"]),
        ("a,,b", ["a", "b"]),
        (",a,b,", ["a", "b"]),
        ("a, ,b", ["a", "b"]),
        ("", []),
        ("   ", []),
        (",", []),
        (
            "123-abc.apps.googleusercontent.com,456-def.apps.googleusercontent.com",
            [
                "123-abc.apps.googleusercontent.com",
                "456-def.apps.googleusercontent.com",
            ],
        ),
    ],
)
def test_client_ids_are_read_from_a_comma_separated_environment_variable(
    monkeypatch, raw, expected
):
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", raw)
    assert make_settings().google_client_ids == expected


def test_the_client_ids_variable_name_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("google_client_ids", "a,b")
    assert make_settings().google_client_ids == ["a", "b"]


def test_the_cached_settings_reflect_the_client_ids_after_a_cache_clear(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "first")
    assert get_settings().google_client_ids == ["first"]
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "second")
    assert get_settings().google_client_ids == ["first"]
    get_settings.cache_clear()
    assert get_settings().google_client_ids == ["second"]


# GoogleIdentity and GoogleTokenInvalid


def test_an_identity_holds_the_token_claims():
    from app.google import GoogleIdentity

    identity = GoogleIdentity(
        subject="sub-1", email="a@example.com", email_verified=True, name="Ayu"
    )
    assert identity.subject == "sub-1"
    assert identity.email == "a@example.com"
    assert identity.email_verified is True
    assert identity.name == "Ayu"


def test_an_identity_name_defaults_to_none():
    from app.google import GoogleIdentity

    identity = GoogleIdentity(subject="s", email="a@example.com", email_verified=False)
    assert identity.name is None
    assert identity.email_verified is False


def test_an_identity_cannot_be_changed():
    from app.google import GoogleIdentity

    identity = GoogleIdentity(subject="s", email="a@example.com", email_verified=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.subject = "other"


def test_identities_with_the_same_claims_are_equal():
    from app.google import GoogleIdentity

    first = GoogleIdentity(subject="s", email="a@example.com", email_verified=True)
    second = GoogleIdentity(subject="s", email="a@example.com", email_verified=True)
    assert first == second


def test_a_rejected_token_is_an_exception():
    from app.google import GoogleTokenInvalid

    assert issubclass(GoogleTokenInvalid, Exception)
    with pytest.raises(GoogleTokenInvalid):
        raise GoogleTokenInvalid("bad signature")


# The real verifier


def test_the_dependency_provides_an_object_that_verifies_tokens(monkeypatch):
    verifier = real_verifier(monkeypatch, "client-1")
    assert callable(verifier.verify)


@pytest.mark.parametrize("token", ["anything", "a.b.c", "", "x" * 2000])
def test_without_client_ids_every_token_is_rejected(monkeypatch, network, token):
    from app.google import GoogleTokenInvalid

    verifier = real_verifier(monkeypatch, None)
    with pytest.raises(GoogleTokenInvalid):
        verifier.verify(token)
    assert network == []


def test_with_blank_client_ids_every_token_is_rejected(monkeypatch, network):
    from app.google import GoogleTokenInvalid

    verifier = real_verifier(monkeypatch, " , ,")
    with pytest.raises(GoogleTokenInvalid):
        verifier.verify("anything")
    assert network == []


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "a.b.c",
        "...",
        "x" * 2000,
        " ",
    ],
)
def test_a_garbage_token_is_rejected_when_client_ids_are_set(
    monkeypatch, network, token
):
    from app.google import GoogleTokenInvalid

    verifier = real_verifier(monkeypatch, "client-1,client-2")
    with pytest.raises(GoogleTokenInvalid):
        verifier.verify(token)


def test_a_garbage_token_never_reaches_google(monkeypatch, network):
    from app.google import GoogleTokenInvalid

    verifier = real_verifier(monkeypatch, "client-1")
    with pytest.raises(GoogleTokenInvalid):
        verifier.verify("not-a-token")
    assert network == []
