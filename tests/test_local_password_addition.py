"""Adding a local password to a Google account."""

from datetime import UTC, datetime, timedelta

import pytest
from google_support import (
    ME_URL,
    assert_error,
    bearer,
    login,
    make_google_user,
    password_login,
    read_failure,
    set_failure,
    snapshot,
    stored_user,
)

URL = "/me/local-password"
TOKEN = "rina-token"
SUBJECT = "sub-rina"
EMAIL = "rina@example.com"
GOOGLE_EMAIL = "rina.gmail@example.com"
NAME = "Rina Owner"
NEW = "T7#vq9-lorem-ipsum"
EXISTING = "correct horse battery"


def add(client, headers, password: str = NEW, token: str = TOKEN):
    body = {"googleIdToken": token, "password": password}
    return client.post(URL, json=body, headers=headers)


def other_users(state: dict, user_id) -> list:
    return [row for row in state["users"] if row[0] != user_id]


def assert_too_common(response) -> None:
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def assert_still_signed_in(client, signed_in) -> None:
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    refreshed = client.post(
        "/auth/refresh", json={"refreshToken": signed_in.tokens.refresh_token}
    )
    assert refreshed.status_code == 200


@pytest.fixture
def rina(database, google):
    """A Google-only Owner whose Google email differs from the account email."""
    google.add(TOKEN, subject=SUBJECT, email=GOOGLE_EMAIL)
    return make_google_user(
        database, subject=SUBJECT, email=EMAIL, google_email=GOOGLE_EMAIL, name=NAME
    )


@pytest.fixture
def signed_in(rina, sign_in):
    from app.schemas.sessions import LoginMethod

    return sign_in(rina, login_method=LoginMethod.GOOGLE)


# Success


def test_the_account_is_returned_with_a_password(client, rina, signed_in):
    response = add(client, signed_in.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(rina.id),
        "name": NAME,
        "email": EMAIL,
        "role": "owner",
        "emailVerified": True,
        "hasPassword": True,
        "googleEmail": GOOGLE_EMAIL,
    }


def test_the_profile_shows_the_password_afterwards(client, rina, signed_in):
    assert add(client, signed_in.headers).status_code == 200
    body = client.get(ME_URL, headers=signed_in.headers).json()
    assert body["hasPassword"] is True
    assert body["googleEmail"] == GOOGLE_EMAIL
    assert body["emailVerified"] is True


def test_the_given_token_is_handed_to_the_verifier(client, rina, signed_in, google):
    add(client, signed_in.headers)
    assert google.verified == [TOKEN]


def test_the_new_password_works_for_login(client, database, rina, signed_in):
    assert add(client, signed_in.headers).status_code == 200
    response = password_login(client, EMAIL, NEW)
    assert response.status_code == 200
    assert response.json()["account"]["id"] == str(rina.id)


def test_a_wrong_password_still_fails_for_login(client, database, rina, signed_in):
    assert add(client, signed_in.headers).status_code == 200
    response = password_login(client, EMAIL, NEW + "x")
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_the_password_is_stored_as_an_argon2_hash(client, database, rina, signed_in):
    assert stored_user(database, rina.id).password_hash is None
    assert add(client, signed_in.headers).status_code == 200
    stored = stored_user(database, rina.id).password_hash
    assert stored.startswith("$argon2")
    assert NEW not in stored


def test_the_google_email_and_identity_are_unchanged(client, database, rina, signed_in):
    assert add(client, signed_in.headers).status_code == 200
    user = stored_user(database, rina.id)
    assert user.google_subject == SUBJECT
    assert user.google_email == GOOGLE_EMAIL
    assert user.email == EMAIL
    assert user.name == NAME
    assert user.email_verified is True
    assert user.status == rina.status


def test_google_login_still_works(client, database, rina, signed_in):
    assert add(client, signed_in.headers).status_code == 200
    response = login(client, TOKEN)
    assert response.status_code == 200
    assert response.json()["account"]["hasPassword"] is True


def test_the_calling_session_stays_signed_in(
    client, database, rina, signed_in, read_session
):
    assert add(client, signed_in.headers).status_code == 200
    assert read_session(signed_in.session_id).revoked_at is None
    assert_still_signed_in(client, signed_in)


def test_other_sessions_of_the_user_stay_signed_in(
    client, database, rina, signed_in, sign_in, read_session
):
    phone = sign_in(rina, device_name="Phone")
    tablet = sign_in(rina, device_name="Tablet")
    assert add(client, signed_in.headers).status_code == 200
    for other in (phone, tablet):
        assert read_session(other.session_id).revoked_at is None
        assert_still_signed_in(client, other)
    assert_still_signed_in(client, signed_in)


def test_a_session_of_another_user_is_untouched(
    client, database, rina, signed_in, make_user, sign_in, read_session
):
    stranger = sign_in(make_user(email="budi@example.com"))
    assert add(client, signed_in.headers).status_code == 200
    assert read_session(stranger.session_id).revoked_at is None


def test_no_other_account_changes(client, database, rina, signed_in, make_user):
    stranger = make_user(email="budi@example.com")
    before = snapshot(database)
    assert add(client, signed_in.headers).status_code == 200
    after = snapshot(database)
    assert other_users(after, rina.id) == other_users(before, rina.id)
    assert stored_user(database, stranger.id).password_hash is None


def test_no_session_is_created_or_failure_recorded(client, database, rina, signed_in):
    before = snapshot(database)
    assert add(client, signed_in.headers).status_code == 200
    after = snapshot(database)
    assert after["sessions"] == before["sessions"]
    assert after["failures"] == before["failures"]
    assert after["codes"] == before["codes"]


def test_a_matching_token_with_another_current_email_is_accepted(
    client, database, google, rina, signed_in
):
    google.add("renamed-token", subject=SUBJECT, email="rina.new@example.com")
    response = add(client, signed_in.headers, token="renamed-token")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == EMAIL
    assert body["googleEmail"] == GOOGLE_EMAIL
    user = stored_user(database, rina.id)
    assert user.email == EMAIL
    assert user.google_email == GOOGLE_EMAIL
    assert password_login(client, EMAIL, NEW).status_code == 200


def test_any_fresh_token_of_the_linked_identity_is_accepted(
    client, database, google, rina, signed_in
):
    google.add("other-token", subject=SUBJECT, email=GOOGLE_EMAIL, name=None)
    assert add(client, signed_in.headers, token="other-token").status_code == 200


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_can_add_a_password(client, database, google, sign_in, role):
    from app.schemas.auth import UserRole
    from app.schemas.sessions import LoginMethod

    google.add("role-token", subject="sub-role", email="role.gmail@example.com")
    user = make_google_user(
        database,
        subject="sub-role",
        email="role@example.com",
        google_email="role.gmail@example.com",
        role=UserRole(role),
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = add(client, session.headers, token="role-token")
    assert response.status_code == 200, response.text
    assert response.json()["role"] == role
    assert password_login(client, "role@example.com", NEW).status_code == 200


@pytest.mark.parametrize(
    "password",
    ["pässwörd with spaces", "  padded passphrase  ", ("T7#vq9-lorem-" * 10)[:128]],
)
def test_the_password_is_stored_exactly_as_given(
    client, database, rina, signed_in, password
):
    assert add(client, signed_in.headers, password=password).status_code == 200
    assert password_login(client, EMAIL, password).status_code == 200
    assert password_login(client, EMAIL, password.strip() + "x").status_code == 401


def test_a_password_of_exactly_8_characters_is_accepted(
    client, database, rina, signed_in
):
    assert add(client, signed_in.headers, password="T7#vq9-l").status_code == 200
    assert password_login(client, EMAIL, "T7#vq9-l").status_code == 200


def test_a_successful_addition_does_not_clear_a_failure_count(
    client, database, rina, signed_in
):
    set_failure(database, EMAIL, failed_attempts=2)
    assert add(client, signed_in.headers).status_code == 200
    assert read_failure(database, EMAIL).failed_attempts == 2


def test_a_second_addition_gets_password_already_set(
    client, database, google, rina, signed_in
):
    assert add(client, signed_in.headers).status_code == 200
    again = add(client, signed_in.headers, password="mUk3!xqz-Plover")
    assert_error(again, 409, "PASSWORD_ALREADY_SET")


# Account that already has a password


def test_an_account_with_a_password_gets_password_already_set(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod
    from app.services.passwords import hash_password

    google.add("both-token", subject="sub-both")
    user = make_google_user(
        database, subject="sub-both", password_hash=hash_password(EXISTING)
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    before = snapshot(database)
    response = add(client, session.headers, token="both-token")
    assert_error(response, 409, "PASSWORD_ALREADY_SET")
    assert snapshot(database) == before
    assert password_login(client, user.email, EXISTING).status_code == 200
    assert password_login(client, user.email, NEW).status_code == 401


def test_password_already_set_is_answered_before_the_token_is_checked(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    user = make_google_user(
        database, subject="sub-both", password_hash=hash_password(EXISTING)
    )
    session = sign_in(user)
    response = add(client, session.headers, token="unknown-token")
    assert_error(response, 409, "PASSWORD_ALREADY_SET")


def test_password_already_set_is_answered_before_the_password_rules(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("both-token", subject="sub-both")
    user = make_google_user(
        database, subject="sub-both", password_hash=hash_password(EXISTING)
    )
    session = sign_in(user)
    response = add(client, session.headers, password="password123", token="both-token")
    assert_error(response, 409, "PASSWORD_ALREADY_SET")


def test_password_already_set_is_answered_before_a_mismatching_token(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("stranger-token", subject="sub-stranger")
    user = make_google_user(
        database, subject="sub-both", password_hash=hash_password(EXISTING)
    )
    session = sign_in(user)
    response = add(client, session.headers, token="stranger-token")
    assert_error(response, 409, "PASSWORD_ALREADY_SET")


def test_a_password_account_without_google_gets_password_already_set(
    client, database, google, make_user, sign_in
):
    from app.services.passwords import hash_password

    google.add("some-token")
    user = make_user(password_hash=hash_password(EXISTING))
    session = sign_in(user)
    response = add(client, session.headers, token="some-token")
    assert_error(response, 409, "PASSWORD_ALREADY_SET")


# Google token


def test_a_token_that_fails_verification_gets_google_token_invalid(
    client, database, rina, signed_in
):
    before = snapshot(database)
    response = add(client, signed_in.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "googleIdToken")
    assert snapshot(database) == before
    assert stored_user(database, rina.id).password_hash is None
    assert_still_signed_in(client, signed_in)


def test_an_invalid_token_is_answered_before_the_account_is_checked_for_a_link(
    client, database, google, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    user = make_user(email="nolink@example.com", password_hash=None)
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = add(client, session.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "googleIdToken")


def test_an_invalid_token_is_answered_before_the_password_rules(
    client, database, rina, signed_in
):
    response = add(client, signed_in.headers, password="password123", token="nope")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "googleIdToken")


def test_invalid_tokens_are_not_counted_as_login_failures(
    client, database, rina, signed_in
):
    for _ in range(6):
        response = add(client, signed_in.headers, token="unknown-token")
        assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "googleIdToken")
    assert read_failure(database, EMAIL) is None
    assert add(client, signed_in.headers).status_code == 200


# Account without a linked Google identity


def test_an_account_without_a_linked_google_identity_gets_google_not_linked(
    client, database, google, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("some-token")
    user = make_user(email="nolink@example.com", password_hash=None)
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    before = snapshot(database)
    response = add(client, session.headers, token="some-token")
    assert_error(response, 409, "GOOGLE_NOT_LINKED")
    assert snapshot(database) == before


def test_google_not_linked_is_answered_before_the_password_rules(
    client, database, google, make_user, sign_in
):
    google.add("some-token")
    user = make_user(email="nolink@example.com", password_hash=None)
    session = sign_in(user)
    response = add(client, session.headers, password="password123", token="some-token")
    assert_error(response, 409, "GOOGLE_NOT_LINKED")


# Token of another identity


def test_a_token_of_another_identity_gets_google_account_mismatch(
    client, database, google, rina, signed_in
):
    google.add("stranger-token", subject="sub-stranger", email=GOOGLE_EMAIL)
    before = snapshot(database)
    response = add(client, signed_in.headers, token="stranger-token")
    assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "googleIdToken")
    assert snapshot(database) == before
    assert password_login(client, EMAIL, NEW).status_code == 401
    assert_still_signed_in(client, signed_in)


def test_a_mismatch_is_not_decided_by_email(client, database, google, rina, signed_in):
    google.add("same-email", subject="sub-other", email=GOOGLE_EMAIL)
    response = add(client, signed_in.headers, token="same-email")
    assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "googleIdToken")


def test_a_mismatch_is_answered_before_the_password_rules(
    client, database, google, rina, signed_in
):
    google.add("stranger-token", subject="sub-stranger")
    response = add(
        client, signed_in.headers, password="password123", token="stranger-token"
    )
    assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "googleIdToken")


def test_the_token_of_another_account_cannot_be_used(
    client, database, google, rina, signed_in
):
    google.add("budi-token", subject="sub-budi")
    make_google_user(database, subject="sub-budi", email="budi@example.com")
    response = add(client, signed_in.headers, token="budi-token")
    assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "googleIdToken")


def test_mismatches_and_invalid_tokens_never_lock_the_email(
    client, database, google, rina, signed_in
):
    google.add("stranger-token", subject="sub-stranger")
    for _ in range(6):
        response = add(client, signed_in.headers, token="stranger-token")
        assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "googleIdToken")
        response = add(client, signed_in.headers, token="unknown-token")
        assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "googleIdToken")
    assert read_failure(database, EMAIL) is None
    assert add(client, signed_in.headers).status_code == 200
    assert login(client, TOKEN).status_code == 200


def test_an_existing_failure_count_is_left_alone_by_a_mismatch(
    client, database, google, rina, signed_in
):
    google.add("stranger-token", subject="sub-stranger")
    set_failure(database, EMAIL, failed_attempts=3)
    add(client, signed_in.headers, token="stranger-token")
    add(client, signed_in.headers, token="unknown-token")
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 3
    assert row.locked_until is None


def test_a_locked_email_does_not_block_the_addition(client, database, rina, signed_in):
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert add(client, signed_in.headers).status_code == 200


# Password rules


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
        "T7#vq9-rina-ipsum",
        "T7#vq9-RINA-ipsum",
        "T7#vq9-rina owner-ipsum",
        "T7#vq9-RINA OWNER-ipsum",
    ],
)
def test_a_blocklisted_password_is_rejected_and_nothing_changes(
    client, database, rina, signed_in, sign_in, password
):
    other = sign_in(rina, device_name="Tablet")
    before = snapshot(database)
    assert_too_common(add(client, signed_in.headers, password=password))
    assert snapshot(database) == before
    assert stored_user(database, rina.id).password_hash is None
    assert password_login(client, EMAIL, password).status_code == 401
    assert_still_signed_in(client, signed_in)
    assert_still_signed_in(client, other)


def test_the_blocklist_checks_the_accounts_own_email_local_part(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("budi-token", subject="sub-budi")
    user = make_google_user(
        database, subject="sub-budi", email="budi.s@example.com", name="Someone Else"
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    assert_too_common(add(client, session.headers, "T7#vq9-budi.s-x", "budi-token"))
    assert (
        add(client, session.headers, "T7#vq9-rina-ipsum", "budi-token").status_code
        == 200
    )


def test_the_blocklist_checks_the_accounts_own_name(client, database, google, sign_in):
    from app.schemas.sessions import LoginMethod

    google.add("budi-token", subject="sub-budi")
    user = make_google_user(
        database,
        subject="sub-budi",
        email="owner@example.com",
        name="Budi Santoso",
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = add(client, session.headers, "T7#vq9-budi santoso-x", "budi-token")
    assert_too_common(response)


def test_a_short_email_local_part_or_name_is_not_blocked(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("ann-token", subject="sub-ann")
    user = make_google_user(
        database, subject="sub-ann", email="abc@example.com", name="Ann"
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = add(client, session.headers, "T7#vq9-abc-ann-x", "ann-token")
    assert response.status_code == 200


# Validation


@pytest.mark.parametrize("value", ["", "1234567", "a" * 129, None, 12345678])
def test_an_unusable_password_is_a_validation_failure(
    client, database, rina, signed_in, value
):
    response = client.post(
        URL,
        json={"googleIdToken": TOKEN, "password": value},
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "password")
    assert stored_user(database, rina.id).password_hash is None


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_google_token_is_a_validation_failure(
    client, database, rina, signed_in, value
):
    response = client.post(
        URL,
        json={"googleIdToken": value, "password": NEW},
        headers=signed_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "googleIdToken")


def test_a_missing_password_is_a_validation_failure(client, database, rina, signed_in):
    response = client.post(
        URL, json={"googleIdToken": TOKEN}, headers=signed_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "password")


def test_a_missing_google_token_is_a_validation_failure(
    client, database, rina, signed_in
):
    response = client.post(URL, json={"password": NEW}, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "googleIdToken")


def test_a_missing_body_is_a_validation_failure(client, database, rina, signed_in):
    response = client.post(URL, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_validation_failure_does_not_call_the_verifier(
    client, database, google, rina, signed_in
):
    client.post(
        URL,
        json={"googleIdToken": TOKEN, "password": "short"},
        headers=signed_in.headers,
    )
    assert google.verified == []


# Authentication


def test_no_token_is_rejected(client, database, rina):
    response = client.post(URL, json={"googleIdToken": TOKEN, "password": NEW})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None
    assert stored_user(database, rina.id).password_hash is None


def test_an_invalid_token_is_rejected(client, database, rina):
    response = add(client, {"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_a_revoked_session_is_rejected(client, database, rina, signed_in):
    client.post("/auth/logout", headers=signed_in.headers)
    response = add(client, signed_in.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"
    assert stored_user(database, rina.id).password_hash is None


def test_a_rejected_session_does_not_reach_the_verifier(client, database, google, rina):
    add(client, {"Authorization": "Bearer garbage"})
    assert google.verified == []


def test_an_unverified_account_gets_email_not_verified(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("new-token", subject="sub-new")
    user = make_google_user(
        database, subject="sub-new", email="new@example.com", email_verified=False
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    before = snapshot(database)
    response = add(client, session.headers, token="new-token")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
    assert snapshot(database) == before


def test_email_not_verified_is_answered_before_password_already_set(
    client, database, google, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_user(
        email="new@example.com",
        password_hash=hash_password(EXISTING),
        email_verified=False,
    )
    session = sign_in(user)
    response = add(client, session.headers, token="unknown-token")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_a_session_started_by_a_real_google_login_can_add_a_password(
    client, database, rina, signed_in
):
    body = login(client, TOKEN).json()
    assert add(client, bearer(body)).status_code == 200
