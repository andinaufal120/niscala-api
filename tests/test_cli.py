"""The `niscala-api` command line."""

import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.auth import UserRole
from app.schemas.subscriptions import PlanCode

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_subscription(database, owner_id):
    from app.models import Subscription

    with Session(database, expire_on_commit=False) as session:
        return session.get(Subscription, owner_id)


def count_subscriptions(database) -> int:
    from app.models import Subscription

    with Session(database) as session:
        return session.scalar(select(func.count()).select_from(Subscription))


def test_console_script_runs_the_cli_main():
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)
    assert config["project"]["scripts"]["niscala-api"] == "app.cli:main"


def test_main_is_callable():
    from app.cli import main

    assert callable(main)


def test_grant_creates_a_subscription_and_exits_zero(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    before = datetime.now(UTC)
    assert main(["grant-subscription", "rina@example.com", "pro"]) == 0
    row = read_subscription(database, owner.id)
    assert row.plan == "pro"
    expected = before + timedelta(days=30)
    assert expected <= row.ends_at <= datetime.now(UTC) + timedelta(days=30)
    assert capsys.readouterr().err == ""


def test_grant_prints_one_line_with_email_plan_and_end(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert (
        main(["grant-subscription", "rina@example.com", "basic", "--days", "10"]) == 0
    )
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 1
    row = read_subscription(database, owner.id)
    assert "rina@example.com" in lines[0]
    assert "basic" in lines[0]
    assert row.ends_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M") in lines[0]


def test_printed_end_is_iso_8601_utc(database, make_user, capsys):
    from app.cli import main

    make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "pro"])
    tokens = capsys.readouterr().out.split()
    stamps = []
    for token in tokens:
        try:
            stamps.append(datetime.fromisoformat(token))
        except ValueError:
            continue
    assert len(stamps) == 1
    assert stamps[0].utcoffset() == timedelta(0)


def test_days_option_sets_the_period(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "7"])
    row = read_subscription(database, owner.id)
    remaining = row.ends_at - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


def test_one_day_is_accepted(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert main(["grant-subscription", "rina@example.com", "pro", "--days", "1"]) == 0
    assert read_subscription(database, owner.id) is not None


def test_email_lookup_ignores_case_and_surrounding_spaces(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    assert main(["grant-subscription", "  Rina@Example.COM ", "pro"]) == 0
    assert read_subscription(database, owner.id).plan == "pro"
    out = capsys.readouterr().out
    assert "rina@example.com" in out
    assert "Rina@Example.COM" not in out


def test_running_twice_replaces_the_subscription(database, make_user):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "90"])
    first_end = read_subscription(database, owner.id).ends_at
    main(["grant-subscription", "rina@example.com", "pro", "--days", "5"])
    row = read_subscription(database, owner.id)
    assert row.plan == "pro"
    assert row.ends_at < first_end
    assert count_subscriptions(database) == 1


def test_grant_makes_the_subscription_active(database, make_user):
    from app.cli import main
    from app.services.subscriptions import current_plan, has_active_subscription

    owner = make_user(email="rina@example.com")
    with Session(database) as session:
        assert has_active_subscription(session, owner.id) is False
    main(["grant-subscription", "rina@example.com", "basic"])
    with Session(database) as session:
        assert has_active_subscription(session, owner.id) is True
        assert current_plan(session, owner.id) is PlanCode.BASIC


def test_unknown_email_fails_without_saving(database, make_user, capsys):
    from app.cli import main

    make_user(email="rina@example.com")
    assert main(["grant-subscription", "nobody@example.com", "pro"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert count_subscriptions(database) == 0


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.TENANT, UserRole.ADMIN])
def test_account_that_is_not_an_owner_fails_without_saving(
    database, make_user, capsys, role
):
    from app.cli import main

    user = make_user(email="someone@example.com", role=role)
    assert main(["grant-subscription", "someone@example.com", "pro"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert read_subscription(database, user.id) is None


def test_failure_leaves_an_existing_subscription_unchanged(database, make_user, capsys):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    main(["grant-subscription", "rina@example.com", "basic", "--days", "10"])
    before = read_subscription(database, owner.id)
    main(["grant-subscription", "nobody@example.com", "pro"])
    after = read_subscription(database, owner.id)
    assert (after.plan, after.ends_at) == (before.plan, before.ends_at)


@pytest.mark.parametrize("plan", ["free", "gold", "PRO", ""])
def test_unknown_plan_is_a_usage_error(database, make_user, plan):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    with pytest.raises(SystemExit) as exit_info:
        main(["grant-subscription", "rina@example.com", plan])
    assert exit_info.value.code == 2
    assert read_subscription(database, owner.id) is None


@pytest.mark.parametrize("days", ["0", "-3", "abc", "1.5", ""])
def test_invalid_days_is_a_usage_error(database, make_user, days):
    from app.cli import main

    owner = make_user(email="rina@example.com")
    with pytest.raises(SystemExit) as exit_info:
        main(["grant-subscription", "rina@example.com", "pro", "--days", days])
    assert exit_info.value.code == 2
    assert read_subscription(database, owner.id) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["grant-subscription"],
        ["grant-subscription", "rina@example.com"],
        ["unknown-command", "rina@example.com", "pro"],
        [],
    ],
)
def test_malformed_command_line_is_a_usage_error(database, argv):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_usage_error_prints_nothing_to_stdout(database, capsys):
    from app.cli import main

    with pytest.raises(SystemExit):
        main(["grant-subscription", "rina@example.com", "gold"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
