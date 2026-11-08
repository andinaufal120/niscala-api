"""The tenant, emergency contact, lease and invitation tables and their models."""

from datetime import UTC, date, datetime, timedelta
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


def saved_room(db_session, **overrides):
    from app.models import Property, Room

    owner = new_user()
    db_session.add(owner)
    db_session.flush()
    prop = Property(owner_id=owner.id, name="Kos Melati", address="Jl. Melati 5")
    db_session.add(prop)
    db_session.flush()
    fields = {"property_id": prop.id, "number": "A1", "base_rate": 1500000}
    row = Room(**{**fields, **overrides})
    db_session.add(row)
    db_session.flush()
    return row


def saved_account(db_session):
    from app.schemas.auth import UserRole

    user = new_user(name="Budi Tenant", email=None, role=UserRole.TENANT)
    db_session.add(user)
    db_session.flush()
    return user


def saved_tenant(db_session, user=None, **overrides):
    """A Tenant record of a new account, or of `user` when given."""
    from app.models import Tenant

    if user is None:
        user = saved_account(db_session)
    fields = {"user_id": user.id, "phone": "081234567890"}
    row = Tenant(**{**fields, **overrides})
    db_session.add(row)
    db_session.flush()
    return row


def new_contact(tenant_id, **overrides):
    from app.models import EmergencyContact

    fields = {
        "tenant_id": tenant_id,
        "name": "Siti",
        "relationship": "Ibu",
        "phone": "081234567890",
        "position": 0,
    }
    return EmergencyContact(**{**fields, **overrides})


def new_lease(tenant_id, room_id, **overrides):
    from app.models import Lease

    fields = {
        "tenant_id": tenant_id,
        "room_id": room_id,
        "billing_cycle": "monthly",
        "rent": 1500000,
        "grace_period_days": 0,
    }
    return Lease(**{**fields, **overrides})


def saved_lease(db_session, tenant_id=None, room_id=None, **overrides):
    if tenant_id is None:
        tenant_id = saved_tenant(db_session).id
    if room_id is None:
        room_id = saved_room(db_session).id
    row = new_lease(tenant_id, room_id, **overrides)
    db_session.add(row)
    db_session.flush()
    return row


def new_invitation(tenant_id=None, **overrides):
    from app.models import Invitation

    fields = {
        "tenant_id": tenant_id,
        "token_hash": uuid4().hex,
        "token_encrypted": "encrypted",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    return Invitation(**{**fields, **overrides})


def test_tenant_tables_are_registered_on_the_metadata():
    from app.models import Base

    for name in ("tenants", "emergency_contacts", "leases", "invitations"):
        assert name in Base.metadata.tables


@pytest.mark.parametrize(
    ("model", "table"),
    [
        ("Tenant", "tenants"),
        ("EmergencyContact", "emergency_contacts"),
        ("Lease", "leases"),
        ("Invitation", "invitations"),
    ],
)
def test_models_use_the_expected_table_names(model, table):
    import app.models

    assert getattr(app.models, model).__tablename__ == table


# Tenant


def test_tenant_gets_defaults_on_insert(db_session):
    before = datetime.now(UTC)
    row = saved_tenant(db_session)
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert isinstance(row.user_id, UUID)
    assert row.occupation is None
    assert row.activated_at is None
    assert row.deleted_at is None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_a_tenant_record_has_an_id_of_its_own(db_session):
    row = saved_tenant(db_session)
    assert row.id != row.user_id


def test_the_tenant_record_id_is_the_primary_key(db_session):
    from app.models import Tenant

    key = [column.name for column in Tenant.__table__.primary_key.columns]
    assert key == ["id"]


def test_the_account_of_a_tenant_record_is_not_unique(db_session):
    from app.models import Tenant

    column = Tenant.__table__.c.user_id
    assert not column.primary_key
    assert not column.unique
    assert column.nullable is False


def test_tenant_round_trips_its_fields(db_session):
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    row = saved_tenant(
        db_session,
        phone="08111222333",
        occupation="Mahasiswa",
        activated_at=when,
        deleted_at=when,
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.user_id is not None
    assert stored.phone == "08111222333"
    assert stored.occupation == "Mahasiswa"
    assert stored.activated_at == when
    assert stored.deleted_at == when


def test_a_tenant_record_can_be_given_an_id(db_session):
    user = saved_account(db_session)
    row = saved_tenant(db_session, user, id=user.id)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), user.id)
    assert stored.id == stored.user_id == user.id


def test_tenant_requires_an_existing_user_account(db_session):
    from app.models import Tenant

    db_session.add(Tenant(user_id=uuid4(), phone="081234567890"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tenant_requires_a_user_account(db_session):
    from app.models import Tenant

    db_session.add(Tenant(user_id=None, phone="081234567890"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_user_account_may_have_several_tenant_rows(db_session):
    user = saved_account(db_session)
    first = saved_tenant(db_session, user)
    second = saved_tenant(db_session, user, phone="08111222333")
    db_session.commit()
    db_session.expire_all()
    assert first.id != second.id
    assert first.user_id == second.user_id == user.id


def test_tenant_requires_a_phone(db_session):
    with pytest.raises(IntegrityError):
        saved_tenant(db_session, phone=None)


# EmergencyContact


def test_emergency_contact_gets_an_id_and_round_trips(db_session):
    tenant = saved_tenant(db_session)
    row = new_contact(tenant.id, name="Agus", relationship="Kakak", position=2)
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert isinstance(stored.id, UUID)
    assert stored.tenant_id == tenant.id
    assert (stored.name, stored.relationship) == ("Agus", "Kakak")
    assert stored.phone == "081234567890"
    assert stored.position == 2


def test_emergency_contact_requires_an_existing_tenant(db_session):
    db_session.add(new_contact(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_emergency_contact_refers_to_the_tenant_record_not_the_account(db_session):
    tenant = saved_tenant(db_session)
    db_session.add(new_contact(tenant.user_id))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["name", "relationship", "phone", "position"])
def test_emergency_contact_requires_its_mandatory_columns(db_session, field):
    tenant = saved_tenant(db_session)
    db_session.add(new_contact(**{"tenant_id": tenant.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_tenant_cannot_have_two_contacts_at_one_position(db_session):
    tenant = saved_tenant(db_session)
    db_session.add(new_contact(tenant.id, position=0))
    db_session.flush()
    db_session.add(new_contact(tenant.id, position=0))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_different_positions_and_different_tenants_may_share_a_position(db_session):
    first, second = saved_tenant(db_session), saved_tenant(db_session)
    db_session.add_all(
        [
            new_contact(first.id, position=0),
            new_contact(first.id, position=1),
            new_contact(second.id, position=0),
        ]
    )
    db_session.flush()


def test_two_records_of_one_account_keep_their_own_contacts(db_session):
    user = saved_account(db_session)
    first, second = saved_tenant(db_session, user), saved_tenant(db_session, user)
    db_session.add_all([new_contact(first.id), new_contact(second.id)])
    db_session.flush()


# Lease


def test_lease_gets_defaults_on_insert(db_session):
    before = datetime.now(UTC)
    row = saved_lease(db_session)
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.start_date is None
    assert row.end_date is None
    assert row.ended_at is None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_lease_round_trips_its_fields(db_session):
    tenant, room = saved_tenant(db_session), saved_room(db_session)
    ended = datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC)
    row = saved_lease(
        db_session,
        tenant.id,
        room.id,
        start_date=date(2026, 1, 31),
        end_date=date(2027, 1, 30),
        billing_cycle="quarterly",
        rent=4500000,
        grace_period_days=5,
        ended_at=ended,
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.tenant_id == tenant.id
    assert stored.room_id == room.id
    assert stored.start_date == date(2026, 1, 31)
    assert stored.end_date == date(2027, 1, 30)
    assert stored.billing_cycle == "quarterly"
    assert stored.rent == 4500000
    assert stored.grace_period_days == 5
    assert stored.ended_at == ended


def test_lease_requires_an_existing_tenant(db_session):
    room = saved_room(db_session)
    db_session.add(new_lease(uuid4(), room.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_lease_refers_to_the_tenant_record_not_the_account(db_session):
    tenant, room = saved_tenant(db_session), saved_room(db_session)
    db_session.add(new_lease(tenant.user_id, room.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_lease_requires_an_existing_room(db_session):
    tenant = saved_tenant(db_session)
    db_session.add(new_lease(tenant.id, uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field", ["tenant_id", "room_id", "billing_cycle", "rent", "grace_period_days"]
)
def test_lease_requires_its_mandatory_columns(db_session, field):
    tenant, room = saved_tenant(db_session), saved_room(db_session)
    fields = {"tenant_id": tenant.id, "room_id": room.id}
    db_session.add(new_lease(**{**fields, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"]
)
def test_lease_accepts_every_billing_cycle(db_session, cycle):
    row = saved_lease(db_session, billing_cycle=cycle)
    db_session.refresh(row)
    assert row.billing_cycle == cycle


@pytest.mark.parametrize("cycle", ["biweekly", "Monthly", "", "daily"])
def test_lease_refuses_an_unknown_billing_cycle(db_session, cycle):
    with pytest.raises(IntegrityError):
        saved_lease(db_session, billing_cycle=cycle)


def test_billing_cycle_values_match_the_schema_enum(db_session):
    from app.schemas.tenants import BillingCycle

    for cycle in BillingCycle:
        saved_lease(db_session, billing_cycle=cycle.value)


@pytest.mark.parametrize("value", [0, -1])
def test_lease_rent_must_be_positive(db_session, value):
    with pytest.raises(IntegrityError):
        saved_lease(db_session, rent=value)


def test_lease_rent_of_one_is_accepted(db_session):
    saved_lease(db_session, rent=1)


def test_lease_grace_period_cannot_be_negative(db_session):
    with pytest.raises(IntegrityError):
        saved_lease(db_session, grace_period_days=-1)


@pytest.mark.parametrize("days", [0, 1, 30])
def test_lease_grace_period_accepts_zero_and_up(db_session, days):
    saved_lease(db_session, grace_period_days=days)


def test_a_room_has_at_most_one_active_lease(db_session):
    room = saved_room(db_session)
    saved_lease(db_session, room_id=room.id)
    with pytest.raises(IntegrityError):
        saved_lease(db_session, room_id=room.id)


def test_a_tenant_record_has_at_most_one_active_lease(db_session):
    tenant = saved_tenant(db_session)
    saved_lease(db_session, tenant_id=tenant.id)
    with pytest.raises(IntegrityError):
        saved_lease(db_session, tenant_id=tenant.id)


def test_an_account_may_have_an_active_lease_through_each_of_its_records(db_session):
    user = saved_account(db_session)
    first, second = saved_tenant(db_session, user), saved_tenant(db_session, user)
    saved_lease(db_session, tenant_id=first.id)
    saved_lease(db_session, tenant_id=second.id)


def test_a_room_stays_exclusive_between_records_of_one_account(db_session):
    user = saved_account(db_session)
    first, second = saved_tenant(db_session, user), saved_tenant(db_session, user)
    room = saved_room(db_session)
    saved_lease(db_session, tenant_id=first.id, room_id=room.id)
    with pytest.raises(IntegrityError):
        saved_lease(db_session, tenant_id=second.id, room_id=room.id)


def test_a_second_active_lease_on_a_record_of_a_multi_record_account_is_refused(
    db_session,
):
    user = saved_account(db_session)
    first, _ = saved_tenant(db_session, user), saved_tenant(db_session, user)
    saved_lease(db_session, tenant_id=first.id)
    with pytest.raises(IntegrityError):
        saved_lease(db_session, tenant_id=first.id)


def test_an_ended_lease_does_not_block_a_new_lease_of_the_room(db_session):
    room = saved_room(db_session)
    saved_lease(db_session, room_id=room.id, ended_at=datetime.now(UTC))
    saved_lease(db_session, room_id=room.id)


def test_an_ended_lease_does_not_block_a_new_lease_of_the_tenant(db_session):
    tenant = saved_tenant(db_session)
    saved_lease(db_session, tenant_id=tenant.id, ended_at=datetime.now(UTC))
    saved_lease(db_session, tenant_id=tenant.id)


def test_several_ended_leases_may_share_a_room_and_a_tenant(db_session):
    room, tenant = saved_room(db_session), saved_tenant(db_session)
    for _ in range(3):
        saved_lease(
            db_session,
            tenant_id=tenant.id,
            room_id=room.id,
            ended_at=datetime.now(UTC),
        )


def test_different_rooms_and_tenants_each_have_their_own_active_lease(db_session):
    saved_lease(db_session)
    saved_lease(db_session)


def test_ending_a_lease_frees_the_room(db_session):
    room = saved_room(db_session)
    first = saved_lease(db_session, room_id=room.id)
    first.ended_at = datetime.now(UTC)
    db_session.flush()
    saved_lease(db_session, room_id=room.id)


def test_reactivating_an_ended_lease_onto_a_taken_room_is_refused(db_session):
    room = saved_room(db_session)
    old = saved_lease(db_session, room_id=room.id, ended_at=datetime.now(UTC))
    saved_lease(db_session, room_id=room.id)
    old.ended_at = None
    with pytest.raises(IntegrityError):
        db_session.flush()


# Invitation


def test_invitation_gets_defaults_on_insert(db_session):
    tenant = saved_tenant(db_session)
    before = datetime.now(UTC)
    row = new_invitation(tenant.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert isinstance(row.id, UUID)
    assert row.used_at is None
    assert row.invalidated_at is None
    assert row.created_at.utcoffset() == timedelta(0)
    assert before - timedelta(minutes=1) <= row.created_at <= datetime.now(UTC)


def test_invitation_round_trips_its_fields(db_session):
    tenant = saved_tenant(db_session)
    when = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    row = new_invitation(
        tenant.id,
        token_hash="a" * 64,
        token_encrypted="gAAAA-token",
        expires_at=when,
        used_at=when,
        invalidated_at=when,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(type(row), row.id)
    assert stored.tenant_id == tenant.id
    assert stored.token_hash == "a" * 64
    assert stored.token_encrypted == "gAAAA-token"
    assert stored.expires_at == when
    assert stored.used_at == when
    assert stored.invalidated_at == when


def test_invitation_requires_an_existing_tenant(db_session):
    db_session.add(new_invitation(uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_invitation_refers_to_the_tenant_record_not_the_account(db_session):
    tenant = saved_tenant(db_session)
    db_session.add(new_invitation(tenant.user_id))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field", ["tenant_id", "token_hash", "token_encrypted", "expires_at"]
)
def test_invitation_requires_its_mandatory_columns(db_session, field):
    tenant = saved_tenant(db_session)
    db_session.add(new_invitation(**{"tenant_id": tenant.id, field: None}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_token_hashes_are_unique(db_session):
    first, second = saved_tenant(db_session), saved_tenant(db_session)
    db_session.add(new_invitation(first.id, token_hash="same"))
    db_session.flush()
    db_session.add(new_invitation(second.id, token_hash="same"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_tenant_may_have_several_invitations(db_session):
    tenant = saved_tenant(db_session)
    db_session.add(new_invitation(tenant.id))
    db_session.add(new_invitation(tenant.id))
    db_session.flush()
