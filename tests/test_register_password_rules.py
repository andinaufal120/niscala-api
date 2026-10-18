"""Sign-up refuses weak or guessable passwords."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def count_rows(database, model) -> int:
    with Session(database) as db:
        return db.scalar(select(func.count()).select_from(model))


def assert_password_too_common(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PASSWORD_TOO_COMMON"
    assert body["field"] == "password"
    assert body["message"]


def assert_nothing_saved(database, sent_emails) -> None:
    from app.models import EmailVerificationCode, UserAccount, UserSession

    assert count_rows(database, UserAccount) == 0
    assert count_rows(database, UserSession) == 0
    assert count_rows(database, EmailVerificationCode) == 0
    assert sent_emails == []


@pytest.mark.parametrize(
    "password",
    [
        "password123",
        "qwertyuiop",
        "PASSWORD123",
        "aaaaaaaa",
        "AAAAAAAA",
        "11111111",
        "12345678",
        "abcdefgh",
        "87654321",
        "HGFEDCBA",
        "niscala!",
        "xx-NISCALA-xx",
    ],
)
def test_register_rejects_a_blocked_password_and_saves_nothing(
    database, register_owner, sent_emails, password
):
    response = register_owner(password=password)
    assert_password_too_common(response)
    assert_nothing_saved(database, sent_emails)


def test_register_rejects_a_password_containing_the_email_local_part(
    database, register_owner, sent_emails
):
    response = register_owner(email="budi.s@example.com", password="T7#vq9-Budi.S-x")
    assert_password_too_common(response)
    assert_nothing_saved(database, sent_emails)


def test_register_checks_the_normalized_email_local_part(
    database, register_owner, sent_emails
):
    response = register_owner(email="  Budi.S@Example.COM ", password="T7#vq9-budi.s-x")
    assert_password_too_common(response)
    assert_nothing_saved(database, sent_emails)


def test_register_rejects_a_password_containing_the_name(
    database, register_owner, sent_emails
):
    response = register_owner(
        name="Budi Santoso",
        email="owner@example.com",
        password="T7#vq9-budi santoso-x",
    )
    assert_password_too_common(response)
    assert_nothing_saved(database, sent_emails)


def test_register_rejects_a_password_containing_niscala(
    database, register_owner, sent_emails
):
    response = register_owner(password="T7#vq9-Niscala-lorem")
    assert_password_too_common(response)
    assert_nothing_saved(database, sent_emails)


def test_register_accepts_a_strong_password(database, register_owner, sent_emails):
    response = register_owner(password="T7#vq9-lorem-ipsum")
    assert response.status_code == 201
    assert len(sent_emails) == 1


def test_register_accepts_a_short_email_local_part_inside_the_password(
    register_owner,
):
    response = register_owner(email="abc@example.com", password="T7#vq9-abc-ipsum")
    assert response.status_code == 201


def test_register_accepts_a_short_name_inside_the_password(register_owner):
    response = register_owner(
        name="Ann", email="owner@example.com", password="T7#vq9-ann-ipsum"
    )
    assert response.status_code == 201


def test_register_accepts_a_128_character_password(register_owner):
    password = ("T7#vq9-lorem-ipsum-" * 10)[:128]
    assert register_owner(password=password).status_code == 201


def test_register_checks_the_password_before_the_duplicate_email(
    database, register_owner, sent_emails
):
    assert register_owner(password="T7#vq9-lorem-ipsum").status_code == 201
    response = register_owner(password="password123")
    assert response.status_code == 422
    assert response.json()["code"] == "PASSWORD_TOO_COMMON"
    assert len(sent_emails) == 1


def test_register_still_reports_a_taken_email_for_a_strong_password(register_owner):
    assert register_owner(password="T7#vq9-lorem-ipsum").status_code == 201
    response = register_owner(password="mUk3!xqz-Plover")
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_reports_the_length_rule_before_the_blocklist(
    database, register_owner, sent_emails
):
    response = register_owner(password="1234567")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert_nothing_saved(database, sent_emails)
