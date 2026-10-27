"""The manager table and the invitation link to a manager or a tenant."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError


def new_user(**overrides):
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    fields = {
        "name": "Rina Owner",
        "email": f"{uuid4().hex}@example.com",
        "password_hash": None,
        "role": UserRole.OWNER,
    }
    return UserAccount(**{**fields, **overrides})


def saved_user(db_session, **overrides):
    row = new_user(**overrides)
    db_session.add(row)
    db_session.flush()
    return row


def saved_manager_user(db_session):
    from app.schemas.auth import UserRole

    return saved_user(
        db_session, name="Mira Manager", email=None, role=UserRole.MANAGER
    )


def new_manager(owner_id, user_id, **overrides):
    from app.models import Manager

    fields = {"owner_id": owner_id, "user_id": user_id, "phone": "081234567890"}
    return Manager(**{**fields, **overrides})


def saved_manager(db_session, owner=None, user=None, **overrides):
    owner = owner or saved_user(db_session)
    user = user or saved_manager_user(db_session)
    row = new_manager(owner.id, user.id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def saved_tenant(db_session):
    from app.models import Tenant
    from app.schemas.auth import UserRole

    user = saved_user(db_session, email=None, role=UserRole.TENANT)
    row = Tenant(user_id=user.id, phone="081234567890")
    db_session.add(row)
    db_session.flush()
    return row


def new_invitation(**overrides):
    from app.models import Invitation

    fields = {
        "token_hash": uuid4().hex,
        "token_encrypted": "encrypted",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    return Invitation(**{**fields, **overrides})


def test_the_managers_table_is_registered_on_the_metadata():
    from app.models import Base

    assert "managers" in Base.metadata.tables


def test_the_manager_model_uses_the_managers_table():
    import app.models

    assert app.models.Manager.__tablename__ == "managers"


def test_manager_gets_defaults_on_insert(db_session):
    before = datetime.now(UTC)
    row = saved_manager(db_session)
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.nickname is None
    assert row.activated_at is None
    assert row.deleted_at is None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_manager_round_trips_its_fields(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = saved_manager(
        db_session,
        owner,
        user,
        nickname="Pak Budi",
        phone="08111222333",
        activated_at=when,
        deleted_at=when,
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.owner_id == owner.id
    assert stored.user_id == user.id
    assert stored.nickname == "Pak Budi"
    assert stored.phone == "08111222333"
    assert stored.activated_at == when
    assert stored.deleted_at == when


def test_manager_requires_an_existing_owner_account(db_session):
    user = saved_manager_user(db_session)
    db_session.add(new_manager(uuid4(), user.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manager_requires_an_existing_user_account(db_session):
    owner = saved_user(db_session)
    db_session.add(new_manager(owner.id, uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["owner_id", "user_id", "phone"])
def test_manager_requires_its_mandatory_columns(db_session, field):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    fields = {"owner_id": owner.id, "user_id": user.id, "phone": "081234567890"}
    from app.models import Manager

    db_session.add(Manager(**{**fields, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_nickname_and_activation_and_deletion_times_may_be_empty(db_session):
    row = saved_manager(db_session, nickname=None, activated_at=None, deleted_at=None)
    assert row.id is not None


def test_two_live_records_of_one_owner_and_user_are_refused(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    saved_manager(db_session, owner, user)
    with pytest.raises(IntegrityError):
        saved_manager(db_session, owner, user)


def test_a_deleted_record_does_not_block_a_new_live_one(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    saved_manager(db_session, owner, user, deleted_at=datetime.now(UTC))
    saved_manager(db_session, owner, user)


def test_a_live_record_does_not_block_a_new_deleted_one(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    saved_manager(db_session, owner, user)
    saved_manager(db_session, owner, user, deleted_at=datetime.now(UTC))


def test_several_deleted_records_of_one_owner_and_user_may_coexist(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    for _ in range(3):
        saved_manager(db_session, owner, user, deleted_at=datetime.now(UTC))


def test_two_owners_may_each_have_a_live_record_for_one_user(db_session):
    user = saved_manager_user(db_session)
    saved_manager(db_session, saved_user(db_session), user)
    saved_manager(db_session, saved_user(db_session), user)


def test_one_owner_may_have_live_records_for_different_users(db_session):
    owner = saved_user(db_session)
    saved_manager(db_session, owner, saved_manager_user(db_session))
    saved_manager(db_session, owner, saved_manager_user(db_session))


def test_deleting_a_record_frees_the_owner_and_user_pair(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    first = saved_manager(db_session, owner, user)
    first.deleted_at = datetime.now(UTC)
    db_session.flush()
    saved_manager(db_session, owner, user)


def test_reviving_a_deleted_record_next_to_a_live_one_is_refused(db_session):
    owner = saved_user(db_session)
    user = saved_manager_user(db_session)
    old = saved_manager(db_session, owner, user, deleted_at=datetime.now(UTC))
    saved_manager(db_session, owner, user)
    old.deleted_at = None
    with pytest.raises(IntegrityError):
        db_session.flush()


# Invitation for a manager or a tenant


def test_an_invitation_may_belong_to_a_manager_alone(db_session):
    manager = saved_manager(db_session)
    row = new_invitation(manager_id=manager.id)
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.manager_id == manager.id
    assert stored.tenant_id is None


def test_an_invitation_may_belong_to_a_tenant_alone(db_session):
    tenant = saved_tenant(db_session)
    row = new_invitation(tenant_id=tenant.user_id)
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.tenant_id == tenant.user_id
    assert stored.manager_id is None


def test_an_invitation_without_a_tenant_or_a_manager_is_refused(db_session):
    db_session.add(new_invitation())
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_an_invitation_for_a_tenant_and_a_manager_is_refused(db_session):
    manager = saved_manager(db_session)
    tenant = saved_tenant(db_session)
    db_session.add(new_invitation(tenant_id=tenant.user_id, manager_id=manager.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_an_invitation_requires_an_existing_manager_record(db_session):
    db_session.add(new_invitation(manager_id=uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_manager_invitation_gets_defaults_on_insert(db_session):
    manager = saved_manager(db_session)
    before = datetime.now(UTC)
    row = new_invitation(manager_id=manager.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.used_at is None
    assert row.invalidated_at is None
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


@pytest.mark.parametrize("field", ["token_hash", "token_encrypted", "expires_at"])
def test_a_manager_invitation_requires_its_mandatory_columns(db_session, field):
    manager = saved_manager(db_session)
    db_session.add(new_invitation(manager_id=manager.id, **{field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_token_hashes_stay_unique_across_managers_and_tenants(db_session):
    manager = saved_manager(db_session)
    tenant = saved_tenant(db_session)
    db_session.add(new_invitation(manager_id=manager.id, token_hash="same"))
    db_session.flush()
    db_session.add(new_invitation(tenant_id=tenant.user_id, token_hash="same"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_manager_may_have_several_invitations(db_session):
    manager = saved_manager(db_session)
    db_session.add(new_invitation(manager_id=manager.id))
    db_session.add(new_invitation(manager_id=manager.id))
    db_session.flush()
