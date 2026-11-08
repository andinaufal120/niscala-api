"""Login with a Google ID token."""

from datetime import UTC, datetime, timedelta

import pytest
from google_support import (
    DEVICE,
    LOGIN_URL,
    ME_URL,
    SESSIONS_URL,
    assert_error,
    assert_locked,
    bearer,
    login,
    make_google_user,
    password_login,
    read_failure,
    set_failure,
    sha256,
    snapshot,
    stored_user,
)
from user_account_support import sessions_of

TOKEN = "rina-token"
SUBJECT = "sub-rina"
EMAIL = "rina@example.com"
PASSWORD = "correct horse battery"


@pytest.fixture
def rina(database, google):
    """An Owner linked to a Google account whose email differs from the login email."""
    google.add(TOKEN, subject=SUBJECT, email="rina.gmail@example.com")
    return make_google_user(
        database,
        subject=SUBJECT,
        email=EMAIL,
        google_email="rina.gmail@example.com",
        name="Rina Owner",
    )


# Success


def test_a_known_subject_gets_a_session_for_its_account(client, database, google, rina):
    response = login(client, TOKEN)
    assert response.status_code == 200, response.text
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
    assert body["account"] == {
        "id": str(rina.id),
        "name": "Rina Owner",
        "email": EMAIL,
        "role": "owner",
        "emailVerified": True,
        "hasPassword": False,
        "googleEmail": "rina.gmail@example.com",
    }


def test_the_account_of_a_user_with_a_password_and_google_reports_both(
    client, database, google, rina
):
    from sqlalchemy.orm import Session

    from app.models import UserAccount
    from app.services.passwords import hash_password

    with Session(database) as db:
        db.get(UserAccount, rina.id).password_hash = hash_password(PASSWORD)
        db.commit()
    account = login(client, TOKEN).json()["account"]
    assert account["hasPassword"] is True
    assert account["googleEmail"] == "rina.gmail@example.com"


def test_a_name_in_the_login_body_never_renames_the_account(
    client, database, google, rina
):
    response = login(client, TOKEN, name="Another Name")
    assert response.status_code == 200, response.text
    assert response.json()["account"]["name"] == "Rina Owner"
    assert stored_user(database, rina.id).name == "Rina Owner"


def test_a_null_name_in_the_login_body_is_ignored(client, database, google, rina):
    response = login(client, TOKEN, name=None)
    assert response.status_code == 200, response.text
    assert response.json()["account"]["name"] == "Rina Owner"


def test_a_name_in_the_login_body_does_not_change_the_account_endpoint(
    client, database, google, rina
):
    body = login(client, TOKEN, name="Another Name").json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.json()["name"] == "Rina Owner"


def test_login_hands_the_given_token_to_the_verifier(client, database, google, rina):
    login(client, TOKEN)
    assert google.verified == [TOKEN]


def test_login_starts_a_google_session_on_the_given_device(
    client, database, google, rina
):
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = login(client, TOKEN, device=device).json()
    (session,) = sessions_of(database, rina.id)
    assert session.login_method == LoginMethod.GOOGLE
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_the_session_is_listed_with_the_google_login_method(
    client, database, google, rina
):
    body = login(client, TOKEN).json()
    response = client.get(SESSIONS_URL, headers=bearer(body))
    (item,) = response.json()["items"]
    assert item["loginMethod"] == "google"
    assert item["isCurrent"] is True


def test_every_login_starts_its_own_session(client, database, google, rina):
    first = login(client, TOKEN).json()
    second = login(client, TOKEN, device={"name": "Galaxy", "platform": "Android"})
    assert second.status_code == 200
    assert len(sessions_of(database, rina.id)) == 2
    assert first["refreshToken"] != second.json()["refreshToken"]


def test_login_tokens_work_on_the_account_endpoint(client, database, google, rina):
    body = login(client, TOKEN).json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_login_refresh_token_can_be_refreshed(client, database, google, rina):
    body = login(client, TOKEN).json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_login_does_not_require_authentication(client, database, google, rina):
    assert "Authorization" not in client.headers
    response = client.post(
        LOGIN_URL,
        json={"idToken": TOKEN, "device": DEVICE},
        headers={"Authorization": "Bearer garbage"},
    )
    assert response.status_code == 200, response.text


def test_login_changes_no_account_data(client, database, google, rina):
    before = snapshot(database)["users"]
    login(client, TOKEN)
    assert snapshot(database)["users"] == before


def test_login_sends_no_email_and_stores_no_code(
    client, database, google, rina, mailbox
):
    from google_support import count_rows

    from app.models import EmailVerificationCode

    login(client, TOKEN)
    assert mailbox.is_empty
    assert count_rows(database, EmailVerificationCode) == 0


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_with_a_linked_subject_can_log_in(client, database, google, role):
    from app.schemas.auth import UserRole

    google.add("role-token", subject="sub-role")
    user = make_google_user(database, subject="sub-role", role=UserRole(role))
    response = login(client, "role-token")
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(user.id)
    assert response.json()["account"]["role"] == role


def test_the_token_email_does_not_have_to_match_the_stored_google_email(
    client, database, google, rina
):
    google.add("moved", subject=SUBJECT, email="brand.new@example.com")
    response = login(client, "moved")
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(rina.id)


def test_the_token_email_does_not_have_to_match_the_account_email(
    client, database, google, rina
):
    google.add("elsewhere", subject=SUBJECT, email="nobody@example.org")
    assert login(client, "elsewhere").status_code == 200


def test_the_account_is_found_by_subject_among_several_accounts(
    client, database, google, rina
):
    other = make_google_user(database, subject="sub-other", email="other@example.com")
    google.add("other-token", subject="sub-other", email=EMAIL)
    response = login(client, "other-token")
    assert response.json()["account"]["id"] == str(other.id)


# Never by email


def test_an_unknown_subject_with_the_email_of_a_password_account_is_refused(
    client, database, google, make_user
):
    from app.services.passwords import hash_password

    owner = make_user(email=EMAIL, password_hash=hash_password(PASSWORD))
    google.add("stranger", subject="sub-stranger", email=EMAIL)
    before = snapshot(database)
    response = login(client, "stranger")
    assert_error(response, 401, "INVALID_CREDENTIALS")
    assert snapshot(database) == before
    assert stored_user(database, owner.id).google_subject is None
    assert sessions_of(database, owner.id) == []


def test_an_unknown_subject_with_the_email_of_a_passwordless_account_is_refused(
    client, database, google, make_user
):
    owner = make_user(email=EMAIL)
    google.add("stranger", subject="sub-stranger", email=EMAIL)
    assert_error(login(client, "stranger"), 401, "INVALID_CREDENTIALS")
    assert stored_user(database, owner.id).google_subject is None


def test_an_unknown_subject_with_the_email_of_another_google_account_is_refused(
    client, database, google, rina
):
    google.add("stranger", subject="sub-stranger", email=EMAIL)
    assert_error(login(client, "stranger"), 401, "INVALID_CREDENTIALS")
    assert sessions_of(database, rina.id) == []


def test_an_unknown_subject_with_a_stored_google_email_is_refused(
    client, database, google, rina
):
    google.add("stranger", subject="sub-stranger", email="rina.gmail@example.com")
    assert_error(login(client, "stranger"), 401, "INVALID_CREDENTIALS")


def test_a_refused_login_creates_no_account(client, database, google):
    from google_support import count_rows

    from app.models import UserAccount

    google.add("stranger", subject="sub-stranger")
    assert login(client, "stranger").status_code == 401
    assert count_rows(database, UserAccount) == 0


# Invalid token


def test_a_token_the_verifier_rejects_answers_unauthorized(
    client, database, google, rina
):
    before = snapshot(database)
    response = login(client, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert snapshot(database) == before


def test_an_invalid_token_does_not_count_as_a_failed_login(
    client, database, google, rina
):
    for _ in range(6):
        assert_error(login(client, "forged"), 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert snapshot(database)["failures"] == 0
    assert login(client, TOKEN).status_code == 200


# Deleted and inactive accounts


def test_a_deleted_account_is_refused_like_an_unknown_one(client, database, google):
    google.add("gone", subject="sub-gone")
    user = make_google_user(database, subject="sub-gone", deleted=True)
    response = login(client, "gone")
    assert_error(response, 401, "INVALID_CREDENTIALS")
    assert sessions_of(database, user.id) == []


def test_a_deleted_account_that_is_also_inactive_is_refused_as_deleted(
    client, database, google
):
    google.add("gone", subject="sub-gone")
    make_google_user(database, subject="sub-gone", deleted=True, status="inactive")
    assert_error(login(client, "gone"), 401, "INVALID_CREDENTIALS")


def test_an_inactive_account_is_told_it_is_inactive(client, database, google):
    google.add("away", subject="sub-away")
    user = make_google_user(database, subject="sub-away", status="inactive")
    response = login(client, "away")
    assert_error(response, 403, "ACCOUNT_INACTIVE")
    assert sessions_of(database, user.id) == []


@pytest.mark.parametrize("role", ["owner", "manager", "tenant"])
def test_an_inactive_account_of_any_role_is_told_it_is_inactive(
    client, database, google, role
):
    from app.schemas.auth import UserRole

    google.add("away", subject="sub-away")
    make_google_user(
        database, subject="sub-away", status="inactive", role=UserRole(role)
    )
    assert_error(login(client, "away"), 403, "ACCOUNT_INACTIVE")


def test_a_reactivated_account_can_log_in_again(client, database, google):
    from user_account_support import set_status

    google.add("away", subject="sub-away")
    user = make_google_user(database, subject="sub-away", status="inactive")
    assert login(client, "away").status_code == 403
    set_status(database, user, "active")
    assert login(client, "away").status_code == 200


# Failed-login counting


def test_failed_google_logins_do_not_lock_a_password_login(
    client, database, google, make_user
):
    from app.services.passwords import hash_password

    make_user(email="budi@example.com", password_hash=hash_password(PASSWORD))
    google.add("stranger", subject="sub-stranger", email="unrelated@example.com")
    for _ in range(12):
        assert_error(login(client, "stranger"), 401, "INVALID_CREDENTIALS")
    assert password_login(client, "budi@example.com", PASSWORD).status_code == 200
    assert snapshot(database)["failures"] == 0


def test_failed_google_logins_with_the_email_of_an_account_leave_its_password_login_free(
    client, database, google, make_user
):
    from app.services.passwords import hash_password

    make_user(email=EMAIL, password_hash=hash_password(PASSWORD))
    google.add("stranger", subject="sub-stranger", email=EMAIL)
    for _ in range(7):
        assert_error(login(client, "stranger"), 401, "INVALID_CREDENTIALS")
    assert read_failure(database, EMAIL) is None
    assert password_login(client, EMAIL, PASSWORD).status_code == 200


def test_failed_google_logins_do_not_start_a_lock(client, database, google, rina):
    google.add("stranger", subject="sub-stranger", email=EMAIL)
    for _ in range(6):
        login(client, "stranger")
    assert read_failure(database, EMAIL) is None
    assert login(client, TOKEN).status_code == 200


def test_a_locked_email_does_not_block_a_google_login(client, database, google, rina):
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert_locked(password_login(client, EMAIL, PASSWORD))
    response = login(client, TOKEN)
    assert response.status_code == 200, response.text


def test_a_google_login_leaves_the_failure_row_of_the_email_alone(
    client, database, google, rina
):
    locked_until = datetime.now(UTC) + timedelta(minutes=10)
    set_failure(database, EMAIL, failed_attempts=5, locked_until=locked_until)
    login(client, TOKEN)
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 5
    assert row.locked_until == locked_until


# Validation


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_id_token_is_a_validation_failure(
    client, database, google, rina, value
):
    response = login(client, value)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []


def test_a_missing_device_is_a_validation_failure(client, database, google, rina):
    response = client.post(LOGIN_URL, json={"idToken": TOKEN})
    assert_error(response, 422, "VALIDATION_FAILED", "device")
    assert google.verified == []
    assert sessions_of(database, rina.id) == []
