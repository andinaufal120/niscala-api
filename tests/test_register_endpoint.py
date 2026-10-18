"""Owner sign-up with an email and a password."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

REGISTER_URL = "/auth/register"
ME_URL = "/me"
LOGIN_URL = "/auth/login"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def count_rows(database, model) -> int:
    with Session(database) as db:
        return db.scalar(select(func.count()).select_from(model))


def find_user(database, email: str):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.scalars(
            select(UserAccount).where(UserAccount.email == email)
        ).one_or_none()


def sessions_of(database, user_id):
    from app.models import UserSession

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(select(UserSession).where(UserSession.user_id == user_id))
        )


def assert_error(response, status: int, code: str, field: str | None) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def test_register_creates_the_account_and_returns_a_session(database, register_owner):
    response = register_owner()
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "accessToken",
        "refreshToken",
        "tokenType",
        "expiresIn",
        "account",
    }
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 900
    assert body["accessToken"]
    assert body["refreshToken"]
    user = find_user(database, "rina@example.com")
    assert body["account"] == {
        "id": str(user.id),
        "name": "Rina Owner",
        "email": "rina@example.com",
        "role": "owner",
        "emailVerified": False,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_register_stores_an_owner_with_an_unverified_email(database, register_owner):
    from app.schemas.auth import UserRole

    register_owner()
    user = find_user(database, "rina@example.com")
    assert user.role == UserRole.OWNER
    assert user.email_verified is False
    assert user.name == "Rina Owner"


def test_register_stores_an_argon2_hash_never_the_password(database, register_owner):
    from app.services.passwords import verify_password

    register_owner(password="correct horse battery")
    user = find_user(database, "rina@example.com")
    assert user.password_hash.startswith("$argon2id$")
    assert "correct horse battery" not in user.password_hash
    assert verify_password("correct horse battery", user.password_hash)


def test_register_trims_the_name(database, register_owner):
    response = register_owner(name="  Rina Owner  ")
    assert response.json()["account"]["name"] == "Rina Owner"
    assert find_user(database, "rina@example.com").name == "Rina Owner"


def test_register_normalizes_the_email(database, register_owner):
    response = register_owner(email=" Owner@Example.COM ")
    assert response.status_code == 201
    assert response.json()["account"]["email"] == "owner@example.com"
    assert find_user(database, "owner@example.com") is not None


def test_register_keeps_the_password_untrimmed(client, database, register_owner):
    register_owner(email="spaces@example.com", password="  secret pass  ")
    ok = client.post(
        LOGIN_URL,
        json={
            "email": "spaces@example.com",
            "password": "  secret pass  ",
            "device": DEVICE,
        },
    )
    trimmed = client.post(
        LOGIN_URL,
        json={
            "email": "spaces@example.com",
            "password": "secret pass",
            "device": DEVICE,
        },
    )
    assert ok.status_code == 200
    assert trimmed.status_code == 401


def test_register_starts_a_password_session_on_the_given_device(
    database, register_owner
):
    from app.schemas.sessions import LoginMethod

    response = register_owner(device={"name": "Galaxy S24", "platform": "Android 15"})
    user = find_user(database, "rina@example.com")
    (session,) = sessions_of(database, user.id)
    assert session.login_method == LoginMethod.PASSWORD
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(response.json()["refreshToken"])


def test_register_tokens_work_on_the_account_endpoint(client, register_owner):
    body = register_owner().json()
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
    )
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_register_refresh_token_can_be_refreshed(client, register_owner):
    body = register_owner().json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_register_does_not_require_authentication(client, register_owner):
    assert "Authorization" not in client.headers
    assert register_owner().status_code == 201


def test_registered_owner_can_log_in_with_the_password(client, register_owner):
    register_owner(email="login@example.com", password="correct horse battery")
    response = client.post(
        LOGIN_URL,
        json={
            "email": "login@example.com",
            "password": "correct horse battery",
            "device": DEVICE,
        },
    )
    assert response.status_code == 200


def test_register_sends_the_verification_code_to_the_normalized_email(
    register_owner, sent_emails
):
    register_owner(email=" Owner@Example.COM ")
    assert len(sent_emails) == 1
    to, code = sent_emails[0]
    assert to == "owner@example.com"
    assert len(code) == 6
    assert code.isascii()
    assert code.isdigit()


def test_register_stores_a_hashed_code_valid_for_ten_minutes(
    database, register_owner, sent_emails, read_verification_code
):
    before = datetime.now(UTC)
    body = register_owner().json()
    row = read_verification_code(body["account"]["id"])
    assert row.code_hash == sha256(sent_emails[0][1])
    assert row.code_hash != sent_emails[0][1]
    assert row.failed_attempts == 0
    assert before - timedelta(seconds=5) <= row.created_at <= datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(minutes=10)


def test_register_creates_one_user_one_session_one_code(
    database, register_owner, sent_emails
):
    from app.models import EmailVerificationCode, UserAccount, UserSession

    register_owner()
    assert count_rows(database, UserAccount) == 1
    assert count_rows(database, UserSession) == 1
    assert count_rows(database, EmailVerificationCode) == 1
    assert len(sent_emails) == 1


def test_register_gives_each_new_owner_their_own_code(
    database, register_owner, sent_emails, read_verification_code
):
    first = register_owner(email="first@example.com").json()
    second = register_owner(email="second@example.com").json()
    assert [to for to, _ in sent_emails] == ["first@example.com", "second@example.com"]
    assert read_verification_code(first["account"]["id"]) is not None
    assert read_verification_code(second["account"]["id"]) is not None
    assert first["account"]["id"] != second["account"]["id"]


@pytest.mark.parametrize(
    "email",
    [
        "rina@example.com",
        "RINA@EXAMPLE.COM",
        "Rina@Example.com",
        "  rina@example.com",
        "rina@example.com  ",
        "  Rina@Example.COM  ",
    ],
)
def test_register_with_a_taken_email_is_rejected_and_changes_nothing(
    database, register_owner, sent_emails, email
):
    from app.models import EmailVerificationCode, UserAccount, UserSession

    assert register_owner().status_code == 201
    response = register_owner(email=email, name="Someone Else", password="another pass")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert count_rows(database, UserAccount) == 1
    assert count_rows(database, UserSession) == 1
    assert count_rows(database, EmailVerificationCode) == 1
    assert len(sent_emails) == 1
    assert find_user(database, "rina@example.com").name == "Rina Owner"


def test_register_with_the_email_of_an_existing_account_is_rejected(
    database, make_user, register_owner, sent_emails
):
    make_user(email="taken@example.com")
    response = register_owner(email="Taken@Example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert sent_emails == []


@pytest.mark.parametrize("length", [8, 64, 128])
def test_register_accepts_passwords_of_8_to_128_characters(register_owner, length):
    password = ("T7#vq9-lorem-ipsum-" * 10)[:length]
    assert register_owner(password=password).status_code == 201


def test_register_accepts_a_128_character_multibyte_password(register_owner):
    assert register_owner(password="é" * 127 + "x").status_code == 201


@pytest.mark.parametrize("length", [0, 7, 129, 200])
def test_register_rejects_passwords_outside_8_to_128_characters(
    database, register_owner, sent_emails, length
):
    from app.models import UserAccount

    response = register_owner(password="a" * length)
    assert_error(response, 422, "VALIDATION_FAILED", "password")
    assert count_rows(database, UserAccount) == 0
    assert sent_emails == []


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", ""])
def test_register_rejects_an_invalid_email(database, register_owner, email):
    response = register_owner(email=email)
    assert_error(response, 422, "VALIDATION_FAILED", "email")


@pytest.mark.parametrize("platform", ["a", "p" * 50])
def test_register_accepts_a_device_platform_of_1_to_50_characters(
    register_owner, platform
):
    device = {**DEVICE, "platform": platform}
    assert register_owner(device=device).status_code == 201


def test_register_rejects_a_blank_name(database, register_owner):
    response = register_owner(name="   ")
    assert_error(response, 422, "VALIDATION_FAILED", "name")


def test_register_saves_nothing_when_sending_the_email_fails(
    app, database, sent_emails, monkeypatch
):
    from app.email import get_email_sender
    from app.models import EmailVerificationCode, UserAccount, UserSession

    class BrokenSender:
        def send_verification_code(self, to: str, code: str) -> None:
            raise RuntimeError("mail server down")

    monkeypatch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        REGISTER_URL,
        json={
            "name": "Rina Owner",
            "email": "rina@example.com",
            "password": "correct horse battery",
            "device": DEVICE,
        },
    )
    assert response.status_code == 500
    assert count_rows(database, UserAccount) == 0
    assert count_rows(database, UserSession) == 0
    assert count_rows(database, EmailVerificationCode) == 0
