"""Alembic migrations apply cleanly and match the models."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from conftest import SCRATCH_PREFIX, alembic_config


def test_upgrade_head_succeeds_and_repeating_it_changes_nothing(database, postgres_url):
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    command.upgrade(config, "head")


def test_database_schema_matches_the_models_after_upgrade(database, postgres_url):
    from app.models import Base

    command.upgrade(alembic_config(postgres_url), "head")

    def include_object(obj, name, type_, reflected, compare_to):
        ignored = name == "alembic_version" or name.startswith(SCRATCH_PREFIX)
        return not (type_ == "table" and ignored)

    with database.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": include_object,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_downgrade_to_base_then_upgrade_head_succeeds(database, postgres_url):
    config = alembic_config(postgres_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_migration_history_has_at_most_one_head(postgres_url):
    script = ScriptDirectory.from_config(alembic_config(postgres_url))
    assert len(script.get_heads()) <= 1


def test_alembic_falls_back_to_application_settings_without_a_url_option(database):
    command.upgrade(alembic_config(), "head")
