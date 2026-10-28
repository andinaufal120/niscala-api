"""The `niscala-api create-admin` command."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.auth import UserRole

EMAIL = "ops@example.com"
NAME = "Sari Admin"
PASSWORD = "violet-lantern-92"
PASSWORD_VARIABLE = "NISCALA_ADMIN_PASSWORD"


@pytest.fixture(autouse=True)
def no_password_in_environment(monkeypatch):
    monkeypatch.delenv(PASSWORD_VARIABLE, raising=False)


def accounts(database):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as session:
        return list(session.scalars(select(UserAccount)))


def row_counts(database) -> dict[str, int]:
    from app.models import Base

    with Session(database) as session:
        return {
            table.name: session.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }


def run(argv):
    from app.cli import main

    return main(argv)


def test_creates_one_verified_admin_and_exits_zero(database, capsys):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD]) == 0
    (admin,) = accounts(database)
    assert admin.role == UserRole.ADMIN
    assert admin.email == EMAIL
    assert admin.name == NAME
    assert admin.email_verified is True
    assert capsys.readouterr().err == ""


def test_stored_hash_accepts_the_password_and_rejects_others(database):
    from app.services.passwords import verify_password

    run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD])
    (admin,) = accounts(database)
    assert admin.password_hash != PASSWORD
    assert verify_password(PASSWORD, admin.password_hash)
    assert not verify_password(PASSWORD + "x", admin.password_hash)


def test_prints_one_line_with_the_email_and_never_the_password(database, capsys):
    run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD])
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    assert EMAIL in lines[0]
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err


def test_email_is_trimmed_and_lower_cased(database, capsys):
    assert (
        run(
            [
                "create-admin",
                "  Ops@Example.COM ",
                "--name",
                NAME,
                "--password",
                PASSWORD,
            ]
        )
        == 0
    )
    (admin,) = accounts(database)
    assert admin.email == EMAIL
    assert EMAIL in capsys.readouterr().out


def test_name_is_trimmed(database):
    assert (
        run(["create-admin", EMAIL, "--name", f"  {NAME}  ", "--password", PASSWORD])
        == 0
    )
    (admin,) = accounts(database)
    assert admin.name == NAME


def test_password_is_read_from_the_environment_when_the_flag_is_absent(
    database, monkeypatch
):
    from app.services.passwords import verify_password

    monkeypatch.setenv(PASSWORD_VARIABLE, PASSWORD)
    assert run(["create-admin", EMAIL, "--name", NAME]) == 0
    (admin,) = accounts(database)
    assert verify_password(PASSWORD, admin.password_hash)


def test_flag_wins_over_the_environment(database, monkeypatch):
    from app.services.passwords import verify_password

    monkeypatch.setenv(PASSWORD_VARIABLE, "amber-harbor-4471")
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD]) == 0
    (admin,) = accounts(database)
    assert verify_password(PASSWORD, admin.password_hash)
    assert not verify_password("amber-harbor-4471", admin.password_hash)


def test_password_from_the_environment_is_not_printed(database, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_VARIABLE, PASSWORD)
    run(["create-admin", EMAIL, "--name", NAME])
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err


def test_without_any_password_it_fails_and_creates_nothing(database, capsys):
    before = row_counts(database)
    assert run(["create-admin", EMAIL, "--name", NAME]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() != ""
    assert captured.out == ""
    assert row_counts(database) == before


def test_without_a_password_it_does_not_wait_for_input(database, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the command must not prompt")

    monkeypatch.setattr("builtins.input", refuse)
    monkeypatch.setattr("getpass.getpass", refuse)
    assert run(["create-admin", EMAIL, "--name", NAME]) == 1


def test_an_empty_environment_password_counts_as_absent(database, monkeypatch):
    monkeypatch.setenv(PASSWORD_VARIABLE, "")
    assert run(["create-admin", EMAIL, "--name", NAME]) == 1
    assert accounts(database) == []


@pytest.mark.parametrize(
    "password",
    [
        "short1!",
        "a" * 7,
        "",
    ],
)
def test_too_short_password_is_rejected(database, capsys, password):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", password]) == 1
    assert capsys.readouterr().err.strip() != ""
    assert accounts(database) == []


def test_password_of_eight_characters_is_accepted(database):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", "qT7#vK9z"]) == 0
    assert len(accounts(database)) == 1


def test_password_of_128_characters_is_accepted(database):
    password = ("qT7#vK9z" * 16)[:128]
    assert len(password) == 128
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", password]) == 0
    assert len(accounts(database)) == 1


def test_too_long_password_is_rejected(database, capsys):
    password = ("qT7#vK9z" * 17)[:129]
    assert len(password) == 129
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", password]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() != ""
    assert password not in captured.err
    assert accounts(database) == []


@pytest.mark.parametrize(
    "password",
    [
        "password123",
        "12345678",
        "aaaaaaaaaa",
        "abcdefghij",
        "my-niscala-key-77",
        "sari admin 2468",
    ],
)
def test_guessable_password_is_rejected(database, capsys, password):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", password]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() != ""
    assert password not in captured.out
    assert accounts(database) == []


def test_guessable_password_from_the_environment_is_rejected(database, monkeypatch):
    monkeypatch.setenv(PASSWORD_VARIABLE, "password123")
    assert run(["create-admin", EMAIL, "--name", NAME]) == 1
    assert accounts(database) == []


def test_password_containing_a_short_email_local_part_is_allowed(database):
    assert (
        run(
            [
                "create-admin",
                "ab@example.com",
                "--name",
                NAME,
                "--password",
                "xab-" + PASSWORD,
            ]
        )
        == 0
    )
    assert len(accounts(database)) == 1


@pytest.mark.parametrize("email", [EMAIL, "  OPS@Example.com  ", "Ops@EXAMPLE.COM"])
@pytest.mark.parametrize("role", list(UserRole))
def test_existing_account_with_the_email_blocks_creation(
    database, make_user, capsys, email, role
):
    existing = make_user(name="Someone Else", email=EMAIL, role=role)
    before = row_counts(database)
    assert run(["create-admin", email, "--name", NAME, "--password", PASSWORD]) == 1
    captured = capsys.readouterr()
    assert EMAIL in captured.err
    assert captured.out == ""
    assert row_counts(database) == before
    (kept,) = accounts(database)
    assert kept.id == existing.id
    assert kept.role == role
    assert kept.name == "Someone Else"
    assert kept.password_hash == existing.password_hash


def test_existing_account_is_not_promoted_or_given_a_password(database, make_user):
    existing = make_user(email=EMAIL, role=UserRole.OWNER, password_hash=None)
    run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD])
    (kept,) = accounts(database)
    assert kept.id == existing.id
    assert kept.role == UserRole.OWNER
    assert kept.password_hash is None


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_name_is_rejected(database, capsys, name):
    assert run(["create-admin", EMAIL, "--name", name, "--password", PASSWORD]) == 1
    assert capsys.readouterr().err.strip() != ""
    assert accounts(database) == []


def test_name_is_required(database):
    with pytest.raises(SystemExit) as raised:
        run(["create-admin", EMAIL, "--password", PASSWORD])
    assert raised.value.code == 2
    assert accounts(database) == []


def test_email_is_required(database):
    with pytest.raises(SystemExit) as raised:
        run(["create-admin", "--name", NAME, "--password", PASSWORD])
    assert raised.value.code == 2
    assert accounts(database) == []


def test_two_different_emails_create_two_admins(database):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD]) == 0
    assert (
        run(
            [
                "create-admin",
                "second@example.com",
                "--name",
                "Budi Admin",
                "--password",
                "amber-harbor-4471",
            ]
        )
        == 0
    )
    rows = accounts(database)
    assert sorted(row.email for row in rows) == [EMAIL, "second@example.com"]
    assert {row.role for row in rows} == {UserRole.ADMIN}


def test_running_twice_with_the_same_email_creates_one_admin(database, capsys):
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD]) == 0
    capsys.readouterr()
    assert run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD]) == 1
    assert len(accounts(database)) == 1


def test_creates_no_rows_besides_the_account(database):
    from app.models import UserAccount

    table = UserAccount.__tablename__
    before = row_counts(database)
    run(["create-admin", EMAIL, "--name", NAME, "--password", PASSWORD])
    after = row_counts(database)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {table}
    assert after[table] == before[table] + 1
