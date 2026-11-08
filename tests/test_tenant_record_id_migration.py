"""The migration that gives a Tenant record an id of its own."""

from uuid import uuid4

import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import inspect, text

BEFORE = "0020"
AFTER = "0021"

USER_INSERT = text(
    "INSERT INTO user_accounts (id, name, email, role, email_verified, created_at) "
    "VALUES (:id, :name, :email, :role, false, now())"
)
PROPERTY_INSERT = text(
    "INSERT INTO properties (id, owner_id, name, address, view_only, created_at) "
    "VALUES (:id, :owner_id, 'Kos Melati', 'Jl. Melati 5', false, now())"
)
ROOM_INSERT = text(
    "INSERT INTO rooms (id, property_id, number, base_rate, facilities, view_only, "
    "created_at) VALUES (:id, :property_id, :number, 1000000, '{}', false, now())"
)
TENANT_INSERT = text(
    "INSERT INTO tenants (user_id, phone, created_at) "
    "VALUES (:user_id, '081234567890', now())"
)
CONTACT_INSERT = text(
    "INSERT INTO emergency_contacts (id, tenant_id, name, relationship, phone, "
    "position) VALUES (:id, :tenant_id, 'Siti', 'Ibu', '081234567890', 0)"
)
LEASE_INSERT = text(
    "INSERT INTO leases (id, tenant_id, room_id, billing_cycle, rent, "
    "grace_period_days, created_at) "
    "VALUES (:id, :tenant_id, :room_id, 'monthly', 1000000, 0, now())"
)
INVITATION_INSERT = text(
    "INSERT INTO invitations (id, tenant_id, token_hash, token_encrypted, "
    "expires_at, created_at) "
    "VALUES (:id, :tenant_id, :token_hash, 'encrypted', now() + interval '7 days', "
    "now())"
)
COMPLAINT_INSERT = text(
    "INSERT INTO complaints (id, tenant_id, room_id, description, status, "
    "created_at) VALUES (:id, :tenant_id, :room_id, 'The tap leaks badly.', 'new', "
    "now())"
)
DEPENDENTS = ("emergency_contacts", "leases", "invitations", "complaints")


@pytest.fixture
def migrated(database, postgres_url, db_engine):
    """Yield the Alembic config; always restore head afterwards."""
    config = alembic_config(postgres_url)
    yield config
    command.upgrade(config, "head")


def add_world(connection) -> dict:
    """Insert one tenant with a contact, a lease, an invitation and a complaint."""
    ids = {name: uuid4() for name in ("owner", "tenant", "property", "room")}
    connection.execute(
        USER_INSERT,
        {
            "id": ids["owner"],
            "name": "Rina Owner",
            "email": f"{uuid4().hex}@x.com",
            "role": "owner",
        },
    )
    connection.execute(
        USER_INSERT,
        {"id": ids["tenant"], "name": "Budi", "email": None, "role": "tenant"},
    )
    connection.execute(
        PROPERTY_INSERT, {"id": ids["property"], "owner_id": ids["owner"]}
    )
    connection.execute(
        ROOM_INSERT, {"id": ids["room"], "property_id": ids["property"], "number": "A1"}
    )
    connection.execute(TENANT_INSERT, {"user_id": ids["tenant"]})
    ids["contact"], ids["lease"], ids["invitation"], ids["complaint"] = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    connection.execute(
        CONTACT_INSERT, {"id": ids["contact"], "tenant_id": ids["tenant"]}
    )
    connection.execute(
        LEASE_INSERT,
        {"id": ids["lease"], "tenant_id": ids["tenant"], "room_id": ids["room"]},
    )
    connection.execute(
        INVITATION_INSERT,
        {
            "id": ids["invitation"],
            "tenant_id": ids["tenant"],
            "token_hash": uuid4().hex,
        },
    )
    connection.execute(
        COMPLAINT_INSERT,
        {"id": ids["complaint"], "tenant_id": ids["tenant"], "room_id": ids["room"]},
    )
    return ids


def column_names(db_engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(db_engine).get_columns(table)}


def test_upgrade_adds_the_record_id_as_primary_key(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    assert "id" not in column_names(db_engine, "tenants")
    command.upgrade(migrated, AFTER)
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("tenants")}
    assert columns["id"]["nullable"] is False
    assert columns["user_id"]["nullable"] is False
    assert inspector.get_pk_constraint("tenants")["constrained_columns"] == ["id"]


def test_upgrade_lets_an_account_hold_several_records(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    inspector = inspect(db_engine)
    unique = [u["column_names"] for u in inspector.get_unique_constraints("tenants")]
    assert ["user_id"] not in unique
    indexes = inspector.get_indexes("tenants")
    assert not [i for i in indexes if i["unique"] and i["column_names"] == ["user_id"]]
    (foreign_key,) = inspector.get_foreign_keys("tenants")
    assert foreign_key["constrained_columns"] == ["user_id"]
    assert foreign_key["referred_table"] == "user_accounts"


@pytest.mark.parametrize("table", DEPENDENTS)
def test_upgrade_points_the_dependents_at_the_record_id(migrated, db_engine, table):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    foreign_keys = inspect(db_engine).get_foreign_keys(table)
    (to_tenants,) = [f for f in foreign_keys if f["referred_table"] == "tenants"]
    assert to_tenants["constrained_columns"] == ["tenant_id"]
    assert to_tenants["referred_columns"] == ["id"]


def test_upgrade_keeps_the_one_active_lease_per_record_and_room_indexes(
    migrated, db_engine
):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    indexes = {i["name"]: i for i in inspect(db_engine).get_indexes("leases")}
    assert indexes["uq_leases_active_room"]["unique"]
    assert indexes["uq_leases_active_room"]["column_names"] == ["room_id"]
    assert indexes["uq_leases_active_tenant"]["unique"]
    assert indexes["uq_leases_active_tenant"]["column_names"] == ["tenant_id"]


def test_upgrade_gives_existing_records_the_id_of_their_account(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        first, second = add_world(connection), add_world(connection)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        rows = connection.execute(text("SELECT id, user_id FROM tenants")).all()
    assert {(row.id, row.user_id) for row in rows} == {
        (first["tenant"], first["tenant"]),
        (second["tenant"], second["tenant"]),
    }


def test_upgrade_keeps_every_dependent_row_on_the_same_tenant_id(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        ids = add_world(connection)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        for table, key in (
            ("emergency_contacts", "contact"),
            ("leases", "lease"),
            ("invitations", "invitation"),
            ("complaints", "complaint"),
        ):
            tenant_id = connection.execute(
                text(f"SELECT tenant_id FROM {table} WHERE id = :id"),
                {"id": ids[key]},
            ).scalar_one()
            assert tenant_id == ids["tenant"], table


def test_upgrade_keeps_the_other_columns_of_a_record(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        add_world(connection)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        row = connection.execute(
            text("SELECT phone, occupation, activated_at, deleted_at FROM tenants")
        ).one()
    assert row.phone == "081234567890"
    assert row.occupation is None
    assert row.activated_at is None
    assert row.deleted_at is None


def test_upgrade_with_no_tenants_succeeds(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 0
        )


def test_after_the_upgrade_an_account_can_get_a_second_record(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        ids = add_world(connection)
    command.upgrade(migrated, AFTER)
    second = uuid4()
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, user_id, phone, created_at) "
                "VALUES (:id, :user_id, '085555555555', now())"
            ),
            {"id": second, "user_id": ids["tenant"]},
        )
        count = connection.execute(
            text("SELECT count(*) FROM tenants WHERE user_id = :user_id"),
            {"user_id": ids["tenant"]},
        ).scalar_one()
    assert count == 2


def test_downgrade_restores_the_account_id_as_primary_key(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    inspector = inspect(db_engine)
    assert "id" not in column_names(db_engine, "tenants")
    assert inspector.get_pk_constraint("tenants")["constrained_columns"] == ["user_id"]
    for table in DEPENDENTS:
        (to_tenants,) = [
            f
            for f in inspector.get_foreign_keys(table)
            if f["referred_table"] == "tenants"
        ]
        assert to_tenants["referred_columns"] == ["user_id"]


def test_upgrade_after_downgrade_round_trips_the_data(migrated, db_engine):
    command.downgrade(migrated, BEFORE)
    with db_engine.begin() as connection:
        ids = add_world(connection)
    command.upgrade(migrated, AFTER)
    command.downgrade(migrated, BEFORE)
    command.upgrade(migrated, AFTER)
    with db_engine.connect() as connection:
        row = connection.execute(text("SELECT id, user_id FROM tenants")).one()
        lease_tenant = connection.execute(
            text("SELECT tenant_id FROM leases WHERE id = :id"), {"id": ids["lease"]}
        ).scalar_one()
    assert row.id == row.user_id == ids["tenant"]
    assert lease_tenant == ids["tenant"]
