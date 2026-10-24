"""Login with an email and a password."""

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

LOGIN_URL = "/auth/login"
ME_URL = "/me"
PASSWORD = "correct horse battery"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def login(client, email: str = "rina@example.com", password: str = PASSWORD, **extra):
    body = {"email": email, "password": password, "device": DEVICE, **extra}
    return client.post(LOGIN_URL, json=body)


def sessions_of(database, user_id):
    from app.models import UserSession

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(select(UserSession).where(UserSession.user_id == user_id))
        )


@pytest.fixture
def owner(make_user):
    from app.services.passwords import hash_password

    return make_user(
        name="Rina Owner",
        email="rina@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified=True,
    )


def assert_invalid_credentials(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "INVALID_CREDENTIALS"
    assert body["field"] is None
    assert body["message"]


def test_login_returns_a_session_for_the_account(client, owner):
    response = login(client)
    assert response.status_code == 200
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
    assert body["account"] == {
        "id": str(owner.id),
        "name": "Rina Owner",
        "email": "rina@example.com",
        "role": "owner",
        "emailVerified": True,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_login_tokens_work_on_the_account_endpoint(client, owner):
    body = login(client).json()
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(owner.id)


def test_login_does_not_require_authentication(client, owner):
    assert "Authorization" not in client.headers
    assert login(client).status_code == 200


@pytest.mark.parametrize(
    "email",
    [
        "RINA@EXAMPLE.COM",
        "Rina@Example.com",
        "  rina@example.com",
        "rina@example.com  ",
        " Rina@Example.COM ",
    ],
)
def test_login_matches_the_email_after_trimming_and_lower_casing(client, owner, email):
    response = login(client, email=email)
    assert response.status_code == 200
    assert response.json()["account"]["id"] == str(owner.id)


def test_login_starts_a_password_session_on_the_given_device(client, database, owner):
    from app.schemas.sessions import LoginMethod

    body = login(client, device={"name": "Galaxy S24", "platform": "Android 15"}).json()
    (session,) = sessions_of(database, owner.id)
    assert session.login_method == LoginMethod.PASSWORD
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_each_login_creates_a_new_independent_session(client, database, owner):
    first = login(client).json()
    second = login(client).json()
    assert len(sessions_of(database, owner.id)) == 2
    assert first["refreshToken"] != second["refreshToken"]
    assert first["accessToken"] != second["accessToken"]
    for body in (first, second):
        response = client.get(
            ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
        )
        assert response.status_code == 200


def test_logging_out_one_login_leaves_the_other_working(client, owner):
    first = login(client).json()
    second = login(client).json()
    client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {first['accessToken']}"}
    )
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {second['accessToken']}"}
    )
    assert response.status_code == 200


def test_login_of_an_unverified_account_still_works(client, make_user):
    from app.services.passwords import hash_password

    make_user(
        email="rina@example.com",
        password_hash=hash_password(PASSWORD),
        email_verified=False,
    )
    response = login(client)
    assert response.status_code == 200
    assert response.json()["account"]["emailVerified"] is False


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_login_works_for_every_role_with_a_password(client, make_user, role):
    from app.schemas.auth import UserRole
    from app.services.passwords import hash_password

    make_user(
        email="rina@example.com",
        password_hash=hash_password(PASSWORD),
        role=UserRole(role),
    )
    response = login(client)
    assert response.status_code == 200
    assert response.json()["account"]["role"] == role


def test_login_accepts_a_one_character_password(client, make_user):
    from app.services.passwords import hash_password

    make_user(email="rina@example.com", password_hash=hash_password("x"))
    assert login(client, password="x").status_code == 200


def test_login_does_not_trim_the_password(client, make_user):
    from app.services.passwords import hash_password

    make_user(email="rina@example.com", password_hash=hash_password(" spaced pass "))
    assert login(client, password=" spaced pass ").status_code == 200
    assert_invalid_credentials(login(client, password="spaced pass"))


def test_wrong_password_is_rejected(client, database, owner):
    assert_invalid_credentials(login(client, password="wrong password"))
    assert sessions_of(database, owner.id) == []


def test_password_comparison_is_case_sensitive(client, owner):
    assert_invalid_credentials(login(client, password=PASSWORD.upper()))


def test_unknown_email_is_rejected(client, database, owner):
    assert_invalid_credentials(login(client, email="nobody@example.com"))


def test_account_without_a_password_is_rejected(client, database, make_user):
    user = make_user(email="google@example.com", password_hash=None)
    response = login(client, email="google@example.com")
    assert_invalid_credentials(response)
    assert sessions_of(database, user.id) == []


def test_all_credential_failures_give_the_same_response(client, make_user, owner):
    make_user(email="google@example.com", password_hash=None)
    responses = [
        login(client, password="wrong password"),
        login(client, email="nobody@example.com"),
        login(client, email="google@example.com"),
    ]
    assert len({(r.status_code, r.text) for r in responses}) == 1


def test_failed_login_does_not_affect_existing_sessions(client, owner):
    body = login(client).json()
    login(client, password="wrong password")
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
    )
    assert response.status_code == 200


def test_login_with_an_empty_password_is_a_validation_failure(client, database):
    response = login(client, password="")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "password"


def test_login_with_an_invalid_email_is_a_validation_failure(client, database):
    response = login(client, email="not-an-email")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "email"


TENANT_EMAIL = "budi@example.com"


@pytest.fixture
def make_tenant_account(make_user, make_property, make_room, make_tenant, database):
    """Commit an activated tenant account that can log in with `PASSWORD`."""
    from app.models import UserAccount
    from app.services.passwords import hash_password

    def factory(*, deleted: bool, email: str = TENANT_EMAIL):
        room = make_room(make_property(make_user(), name="Kos Melati"))
        stored = make_tenant(
            room, activated=True, email=email, deleted=deleted, invitation=False
        )
        with Session(database) as db:
            user = db.get(UserAccount, stored.id)
            user.password_hash = hash_password(PASSWORD)
            user.email_verified = True
            db.commit()
        return stored

    return factory


def failure_count(database, email: str) -> int:
    from app.models import LoginFailure

    with Session(database, expire_on_commit=False) as db:
        row = db.get(LoginFailure, email)
        return 0 if row is None else row.failed_attempts


def test_an_active_tenant_account_logs_in(client, make_tenant_account):
    stored = make_tenant_account(deleted=False)
    response = login(client, email=TENANT_EMAIL)
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(stored.id)
    assert response.json()["account"]["role"] == "tenant"


def test_a_deleted_tenant_with_the_right_password_is_rejected(
    client, database, make_tenant_account
):
    stored = make_tenant_account(deleted=True)
    assert_invalid_credentials(login(client, email=TENANT_EMAIL))
    assert sessions_of(database, stored.id) == []


def test_a_deleted_tenant_is_rejected_whatever_the_email_case(
    client, make_tenant_account
):
    make_tenant_account(deleted=True)
    assert_invalid_credentials(login(client, email=" Budi@Example.COM "))


def test_a_deleted_tenant_gets_the_same_answer_as_an_unknown_email(
    client, make_tenant_account
):
    make_tenant_account(deleted=True)
    deleted = login(client, email=TENANT_EMAIL)
    unknown = login(client, email="nobody@example.com")
    assert (deleted.status_code, deleted.text) == (unknown.status_code, unknown.text)


def test_a_deleted_tenant_does_not_block_another_tenant_from_logging_in(
    client, make_tenant_account
):
    make_tenant_account(deleted=True)
    other = make_tenant_account(deleted=False, email="dewi@example.com")
    response = login(client, email="dewi@example.com")
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(other.id)


def test_a_rejected_deleted_tenant_login_counts_as_a_failure(
    client, database, make_tenant_account
):
    make_tenant_account(deleted=True)
    assert failure_count(database, TENANT_EMAIL) == 0
    login(client, email=TENANT_EMAIL)
    assert failure_count(database, TENANT_EMAIL) == 1


def test_the_sixth_login_of_a_deleted_tenant_is_locked(client, make_tenant_account):
    make_tenant_account(deleted=True)
    for _ in range(5):
        assert_invalid_credentials(login(client, email=TENANT_EMAIL))
    response = login(client, email=TENANT_EMAIL)
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert body["field"] is None
    assert body["message"]
    assert int(response.headers["Retry-After"]) >= 1


def test_deleted_tenant_logins_and_wrong_passwords_share_one_failure_count(
    client, make_tenant_account
):
    make_tenant_account(deleted=True)
    for _ in range(3):
        assert_invalid_credentials(
            login(client, email=TENANT_EMAIL, password="wrong password")
        )
    for _ in range(2):
        assert_invalid_credentials(login(client, email=TENANT_EMAIL))
    assert login(client, email=TENANT_EMAIL).status_code == 429


@pytest.mark.parametrize("platform", ["a", "p" * 50])
def test_login_accepts_a_device_platform_of_1_to_50_characters(client, owner, platform):
    device = {**DEVICE, "platform": platform}
    assert login(client, device=device).status_code == 200
