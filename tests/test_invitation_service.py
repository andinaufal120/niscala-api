"""Creating invitations and revealing or addressing their tokens."""

import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select


@pytest.fixture
def tenant_id(db_session, make_user):
    from app.models import Tenant
    from app.schemas.auth import UserRole

    user = make_user(name="Budi Tenant", role=UserRole.TENANT)
    db_session.add(Tenant(user_id=user.id, phone="081234567890"))
    db_session.commit()
    return user.id


@pytest.fixture
def other_tenant_id(db_session, make_user):
    from app.models import Tenant
    from app.schemas.auth import UserRole

    user = make_user(name="Dewi Tenant", role=UserRole.TENANT)
    db_session.add(Tenant(user_id=user.id, phone="081298765432"))
    db_session.commit()
    return user.id


@pytest.fixture
def settings_env(monkeypatch):
    """Set environment variables and reload the cached settings around the test."""
    from app.config import get_settings

    def setenv(name: str, value: str) -> None:
        monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield setenv
    get_settings.cache_clear()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def count_invitations(db_session) -> int:
    from app.models import Invitation

    return db_session.scalar(select(func.count()).select_from(Invitation))


# create_invitation


def test_create_invitation_returns_the_row_and_the_raw_token(db_session, tenant_id):
    from app.services.invitations import create_invitation

    from app.models import Invitation

    row, token = create_invitation(db_session, tenant_id)
    assert isinstance(row, Invitation)
    assert row.tenant_id == tenant_id
    assert isinstance(token, str)


def test_the_token_is_urlsafe_and_long_enough_for_32_random_bytes(
    db_session, tenant_id
):
    from app.services.invitations import create_invitation

    _, token = create_invitation(db_session, tenant_id)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def test_every_invitation_gets_a_different_token(db_session, tenant_id):
    from app.services.invitations import create_invitation

    tokens = {create_invitation(db_session, tenant_id)[1] for _ in range(5)}
    assert len(tokens) == 5


def test_the_token_hash_is_the_sha256_hex_of_the_token(db_session, tenant_id):
    from app.services.invitations import create_invitation

    row, token = create_invitation(db_session, tenant_id)
    assert row.token_hash == sha256_hex(token)
    assert len(row.token_hash) == 64


def test_the_raw_token_is_not_stored_in_the_row(db_session, tenant_id):
    from app.services.invitations import create_invitation

    row, token = create_invitation(db_session, tenant_id)
    db_session.commit()
    db_session.expire_all()
    stored = [
        getattr(row, column.key)
        for column in type(row).__table__.columns
        if isinstance(getattr(row, column.key), str)
    ]
    assert stored
    assert all(token not in value for value in stored)


def test_the_encrypted_token_decrypts_with_the_configured_key(db_session, tenant_id):
    from app.services.invitations import create_invitation

    from app.config import get_settings

    row, token = create_invitation(db_session, tenant_id)
    fernet = Fernet(get_settings().invitation_encryption_key.encode())
    assert fernet.decrypt(row.token_encrypted.encode()).decode() == token


def test_the_encrypted_token_differs_from_the_token(db_session, tenant_id):
    from app.services.invitations import create_invitation

    row, token = create_invitation(db_session, tenant_id)
    assert row.token_encrypted != token


def test_the_token_cannot_be_decrypted_with_another_key(db_session, tenant_id):
    from app.services.invitations import create_invitation
    from cryptography.fernet import InvalidToken

    row, _ = create_invitation(db_session, tenant_id)
    with pytest.raises(InvalidToken):
        Fernet(Fernet.generate_key()).decrypt(row.token_encrypted.encode())


def test_the_invitation_expires_seven_days_after_it_was_created(db_session, tenant_id):
    from app.services.invitations import create_invitation

    before = datetime.now(UTC)
    row, _ = create_invitation(db_session, tenant_id)
    after = datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert before <= row.created_at <= after
    assert row.expires_at.utcoffset() == timedelta(0)


def test_a_new_invitation_is_unused_and_valid(db_session, tenant_id):
    from app.services.invitations import create_invitation

    row, _ = create_invitation(db_session, tenant_id)
    assert row.used_at is None
    assert row.invalidated_at is None


def test_the_invitation_is_flushed_so_it_has_an_id_and_is_queryable(
    db_session, tenant_id
):
    from app.services.invitations import create_invitation

    from app.models import Invitation

    row, _ = create_invitation(db_session, tenant_id)
    assert row.id is not None
    assert db_session.get(Invitation, row.id) is row
    assert count_invitations(db_session) == 1


def test_the_invitation_is_not_committed(db_session, tenant_id):
    from app.services.invitations import create_invitation

    create_invitation(db_session, tenant_id)
    db_session.rollback()
    assert count_invitations(db_session) == 0


def test_an_unused_earlier_invitation_is_invalidated(db_session, tenant_id):
    from app.services.invitations import create_invitation

    first, _ = create_invitation(db_session, tenant_id)
    before = datetime.now(UTC)
    second, _ = create_invitation(db_session, tenant_id)
    db_session.refresh(first)
    assert first.invalidated_at is not None
    assert before - timedelta(seconds=5) <= first.invalidated_at <= datetime.now(UTC)
    assert second.invalidated_at is None


def test_every_earlier_unused_invitation_is_invalidated(db_session, tenant_id):
    from app.services.invitations import create_invitation

    earlier = [create_invitation(db_session, tenant_id)[0] for _ in range(3)]
    latest, _ = create_invitation(db_session, tenant_id)
    for row in earlier:
        db_session.refresh(row)
        assert row.invalidated_at is not None
    assert latest.invalidated_at is None


def test_an_expired_unused_earlier_invitation_is_invalidated(db_session, tenant_id):
    from app.services.invitations import create_invitation

    first, _ = create_invitation(db_session, tenant_id)
    first.expires_at = datetime.now(UTC) - timedelta(days=1)
    db_session.flush()
    create_invitation(db_session, tenant_id)
    db_session.refresh(first)
    assert first.invalidated_at is not None


def test_a_used_earlier_invitation_is_left_alone(db_session, tenant_id):
    from app.services.invitations import create_invitation

    first, _ = create_invitation(db_session, tenant_id)
    first.used_at = datetime.now(UTC)
    db_session.flush()
    create_invitation(db_session, tenant_id)
    db_session.refresh(first)
    assert first.invalidated_at is None


def test_invitations_of_other_tenants_are_left_alone(
    db_session, tenant_id, other_tenant_id
):
    from app.services.invitations import create_invitation

    theirs, _ = create_invitation(db_session, other_tenant_id)
    create_invitation(db_session, tenant_id)
    db_session.refresh(theirs)
    assert theirs.invalidated_at is None


def test_an_already_invalidated_invitation_keeps_its_invalidation_time(
    db_session, tenant_id
):
    from app.services.invitations import create_invitation

    first, _ = create_invitation(db_session, tenant_id)
    when = datetime(2026, 1, 1, tzinfo=UTC)
    first.invalidated_at = when
    db_session.flush()
    create_invitation(db_session, tenant_id)
    db_session.refresh(first)
    assert first.invalidated_at == when


def test_the_first_invitation_of_a_tenant_invalidates_nothing(db_session, tenant_id):
    from app.services.invitations import create_invitation

    row, _ = create_invitation(db_session, tenant_id)
    assert row.invalidated_at is None


# reveal_token


def test_reveal_token_returns_the_original_token(db_session, tenant_id):
    from app.services.invitations import create_invitation, reveal_token

    row, token = create_invitation(db_session, tenant_id)
    assert reveal_token(row) == token


def test_reveal_token_works_after_a_round_trip_through_the_database(
    db_session, tenant_id
):
    from app.services.invitations import create_invitation, reveal_token

    from app.models import Invitation

    row, token = create_invitation(db_session, tenant_id)
    db_session.commit()
    db_session.expire_all()
    assert reveal_token(db_session.get(Invitation, row.id)) == token


def test_reveal_token_fails_for_a_tampered_token(db_session, tenant_id):
    from app.services.invitations import create_invitation, reveal_token
    from cryptography.fernet import InvalidToken

    row, _ = create_invitation(db_session, tenant_id)
    row.token_encrypted = "garbage"
    with pytest.raises(InvalidToken):
        reveal_token(row)


# invitation_url


def test_invitation_url_appends_the_token_to_the_default_base_url(settings_env):
    from app.services.invitations import invitation_url

    settings_env("INVITATION_BASE_URL", "https://niscala.app")
    assert invitation_url("abc123") == "https://niscala.app/invitations/abc123"


def test_invitation_url_uses_the_configured_base_url(settings_env):
    from app.services.invitations import invitation_url

    settings_env("INVITATION_BASE_URL", "https://example.test/app")
    assert invitation_url("tok-en_1") == "https://example.test/app/invitations/tok-en_1"


def test_invitation_url_ignores_a_trailing_slash_on_the_base_url(settings_env):
    from app.services.invitations import invitation_url

    settings_env("INVITATION_BASE_URL", "https://example.test/")
    assert invitation_url("abc") == "https://example.test/invitations/abc"


def test_the_url_of_a_created_invitation_contains_its_token(
    db_session, tenant_id, settings_env
):
    from app.services.invitations import create_invitation, invitation_url

    settings_env("INVITATION_BASE_URL", "https://example.test")
    _, token = create_invitation(db_session, tenant_id)
    assert invitation_url(token) == f"https://example.test/invitations/{token}"
