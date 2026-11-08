"""Linking a Google identity to an account that has a password."""

import pytest
from google_support import (
    ME_URL,
    assert_error,
    bearer,
    login,
    make_google_user,
    password_login,
    register,
    snapshot,
    stored_user,
    user_by_subject,
)
from user_account_support import sessions_of

URL = "/me/google-link"
TOKEN = "rina-token"
SUBJECT = "sub-rina"
EMAIL = "rina@example.com"
GOOGLE_EMAIL = "rina.gmail@example.com"
NAME = "Rina Owner"
PASSWORD = "correct horse battery"


def link(client, headers, token: str = TOKEN):
    return client.post(URL, json={"idToken": token}, headers=headers)


def assert_still_signed_in(client, signed_in) -> None:
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    refreshed = client.post(
        "/auth/refresh", json={"refreshToken": signed_in.tokens.refresh_token}
    )
    assert refreshed.status_code == 200


def make_password_user(make_user, **options):
    from app.services.passwords import hash_password

    options.setdefault("email", EMAIL)
    options.setdefault("name", NAME)
    return make_user(password_hash=hash_password(PASSWORD), **options)


@pytest.fixture
def rina(database, google, make_user):
    """An Owner with a password and no Google identity."""
    google.add(TOKEN, subject=SUBJECT, email=GOOGLE_EMAIL)
    return make_password_user(make_user)


@pytest.fixture
def signed_in(rina, sign_in):
    return sign_in(rina)


# Success


def test_the_account_is_returned_with_the_google_email(client, rina, signed_in):
    response = link(client, signed_in.headers)
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


def test_the_profile_shows_the_google_email_afterwards(client, rina, signed_in):
    assert client.get(ME_URL, headers=signed_in.headers).json()["googleEmail"] is None
    assert link(client, signed_in.headers).status_code == 200
    assert client.get(ME_URL, headers=signed_in.headers).json()["googleEmail"] == (
        GOOGLE_EMAIL
    )


def test_the_given_token_is_handed_to_the_verifier(client, google, rina, signed_in):
    link(client, signed_in.headers)
    assert google.verified == [TOKEN]


def test_the_identity_and_google_email_are_stored(client, database, rina, signed_in):
    assert link(client, signed_in.headers).status_code == 200
    user = stored_user(database, rina.id)
    assert user.google_subject == SUBJECT
    assert user.google_email == GOOGLE_EMAIL


def test_the_account_is_otherwise_unchanged(client, database, rina, signed_in):
    before = stored_user(database, rina.id)
    assert link(client, signed_in.headers).status_code == 200
    after = stored_user(database, rina.id)
    assert after.email == before.email == EMAIL
    assert after.name == before.name == NAME
    assert after.password_hash == before.password_hash
    assert after.email_verified is True
    assert after.status == before.status
    assert after.role == before.role


def test_the_account_email_is_kept_when_the_google_email_differs(
    client, database, google, rina, signed_in
):
    google.add("other-mail", subject=SUBJECT, email="completely.other@example.org")
    response = link(client, signed_in.headers, token="other-mail")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == EMAIL
    assert body["googleEmail"] == "completely.other@example.org"
    user = stored_user(database, rina.id)
    assert user.email == EMAIL
    assert user.google_email == "completely.other@example.org"
    assert password_login(client, EMAIL, PASSWORD).status_code == 200


def test_the_account_name_is_kept_when_the_google_name_differs(
    client, database, google, rina, signed_in
):
    google.add("named", subject=SUBJECT, email=GOOGLE_EMAIL, name="Someone Else")
    assert link(client, signed_in.headers, token="named").status_code == 200
    assert stored_user(database, rina.id).name == NAME


def test_google_login_works_afterwards(client, database, rina, signed_in):
    assert link(client, signed_in.headers).status_code == 200
    response = login(client, TOKEN)
    assert response.status_code == 200, response.text
    account = response.json()["account"]
    assert account["id"] == str(rina.id)
    assert account["hasPassword"] is True
    assert account["googleEmail"] == GOOGLE_EMAIL


def test_google_login_starts_a_session_with_the_google_method(
    client, database, rina, signed_in
):
    from app.schemas.sessions import LoginMethod

    assert link(client, signed_in.headers).status_code == 200
    body = login(client, TOKEN).json()
    methods = {
        s.login_method for s in sessions_of(database, rina.id) if s.revoked_at is None
    }
    assert methods == {LoginMethod.PASSWORD, LoginMethod.GOOGLE}
    items = client.get("/me/sessions", headers=bearer(body)).json()["items"]
    current = next(item for item in items if item["isCurrent"])
    assert current["loginMethod"] == "google"


def test_google_login_does_not_work_before_linking(client, database, rina):
    response = login(client, TOKEN)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_password_login_still_works(client, database, rina, signed_in):
    assert link(client, signed_in.headers).status_code == 200
    assert password_login(client, EMAIL, PASSWORD).status_code == 200


def test_the_calling_session_and_other_sessions_stay_signed_in(
    client, database, rina, signed_in, sign_in, read_session
):
    phone = sign_in(rina, device_name="Phone")
    assert link(client, signed_in.headers).status_code == 200
    for session in (signed_in, phone):
        assert read_session(session.session_id).revoked_at is None
        assert_still_signed_in(client, session)


def test_the_calling_session_keeps_its_password_method(
    client, database, rina, signed_in, read_session
):
    from app.schemas.sessions import LoginMethod

    assert link(client, signed_in.headers).status_code == 200
    assert read_session(signed_in.session_id).login_method == LoginMethod.PASSWORD


def test_a_session_started_by_a_real_password_login_may_link(client, database, rina):
    body = password_login(client, EMAIL, PASSWORD).json()
    assert link(client, bearer(body)).status_code == 200


def test_no_other_account_changes(client, database, rina, signed_in, make_user):
    stranger = make_password_user(make_user, email="budi@example.com", name="Budi")
    google_user = make_google_user(database, subject="sub-other")
    before = snapshot(database)
    assert link(client, signed_in.headers).status_code == 200
    after = snapshot(database)
    keep = {stranger.id, google_user.id}
    assert [r for r in after["users"] if r[0] in keep] == [
        r for r in before["users"] if r[0] in keep
    ]
    assert after["sessions"] == before["sessions"]
    assert after["failures"] == before["failures"]


def test_an_account_with_the_google_email_is_not_linked_by_email(
    client, database, google, rina, signed_in, make_user
):
    namesake = make_password_user(make_user, email=GOOGLE_EMAIL, name="Namesake")
    assert link(client, signed_in.headers).status_code == 200
    assert stored_user(database, namesake.id).google_subject is None
    assert stored_user(database, namesake.id).google_email is None
    assert user_by_subject(database, SUBJECT).id == rina.id
    assert login(client, TOKEN).json()["account"]["id"] == str(rina.id)


def test_an_account_with_the_google_email_cannot_be_reached_by_the_link(
    client, database, google, rina, signed_in, make_user, sign_in
):
    namesake = make_password_user(make_user, email=GOOGLE_EMAIL, name="Namesake")
    other = sign_in(namesake)
    response = link(client, other.headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(namesake.id)
    assert stored_user(database, rina.id).google_subject is None


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_can_link(client, database, google, make_user, sign_in, role):
    from app.schemas.auth import UserRole

    google.add("role-token", subject="sub-role", email="role.gmail@example.com")
    user = make_password_user(make_user, email="role@example.com", role=UserRole(role))
    response = link(client, sign_in(user).headers, token="role-token")
    assert response.status_code == 200, response.text
    assert response.json()["role"] == role
    assert response.json()["googleEmail"] == "role.gmail@example.com"
    assert login(client, "role-token").status_code == 200


# Session must come from a password login


def test_a_session_started_by_google_login_gets_password_login_required(
    client, database, google, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    user = make_password_user(make_user)
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    google.add("new-token", subject="sub-new")
    before = snapshot(database)
    response = link(client, session.headers, token="new-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")
    assert snapshot(database) == before
    assert stored_user(database, user.id).google_subject is None


def test_a_google_only_account_session_gets_password_login_required(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("new-token", subject="sub-new")
    user = make_google_user(database, subject=SUBJECT)
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = link(client, session.headers, token="new-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")


def test_a_session_started_by_google_sign_up_gets_password_login_required(
    client, database, google
):
    google.add("signup-token", subject="sub-signup", email="signup@example.com")
    body = register(client, "signup-token").json()
    google.add("another-token", subject="sub-another")
    response = link(client, bearer(body), token="another-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")


def test_a_linked_account_logged_in_with_google_gets_password_login_required(
    client, database, google, make_user
):
    from app.services.passwords import hash_password

    google.add("both-token", subject="sub-both")
    make_google_user(
        database,
        subject="sub-both",
        email="both@example.com",
        password_hash=hash_password(PASSWORD),
    )
    body = login(client, "both-token").json()
    response = link(client, bearer(body), token="both-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")


def test_password_login_required_is_answered_before_the_token_is_checked(
    client, database, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    session = sign_in(make_password_user(make_user), login_method=LoginMethod.GOOGLE)
    response = link(client, session.headers, token="unknown-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")


def test_password_login_required_is_answered_before_already_linked(
    client, database, google, sign_in
):
    from app.schemas.sessions import LoginMethod
    from app.services.passwords import hash_password

    google.add("new-token", subject="sub-new")
    user = make_google_user(
        database, subject=SUBJECT, password_hash=hash_password(PASSWORD)
    )
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    response = link(client, session.headers, token="new-token")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")


def test_the_login_method_of_the_calling_session_decides_not_other_sessions(
    client, database, rina, sign_in
):
    from app.schemas.sessions import LoginMethod

    sign_in(rina, login_method=LoginMethod.GOOGLE)
    password_session = sign_in(rina, device_name="Tablet")
    assert link(client, password_session.headers).status_code == 200


# Google token


def test_a_token_that_fails_verification_gets_google_token_invalid(
    client, database, rina, signed_in
):
    before = snapshot(database)
    response = link(client, signed_in.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert snapshot(database) == before
    assert stored_user(database, rina.id).google_subject is None
    assert_still_signed_in(client, signed_in)


def test_an_invalid_token_is_answered_before_already_linked(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    user = make_google_user(
        database, subject=SUBJECT, password_hash=hash_password(PASSWORD)
    )
    session = sign_in(user)
    response = link(client, session.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")


def test_an_invalid_token_is_answered_before_a_taken_identity(
    client, database, rina, signed_in
):
    response = link(client, signed_in.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")


# Google email not verified


def test_a_token_with_an_unverified_google_email_gets_google_email_unverified(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject=SUBJECT, email=GOOGLE_EMAIL, email_verified=False)
    before = snapshot(database)
    response = link(client, signed_in.headers, token="unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert snapshot(database) == before
    user = stored_user(database, rina.id)
    assert user.google_subject is None
    assert user.google_email is None
    assert_still_signed_in(client, signed_in)


def test_an_unverified_google_email_leaves_google_login_unavailable(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject=SUBJECT, email=GOOGLE_EMAIL, email_verified=False)
    assert_error(
        link(client, signed_in.headers, token="unverified"),
        422,
        "GOOGLE_EMAIL_UNVERIFIED",
        "idToken",
    )
    response = login(client, "unverified")
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_the_verifier_is_called_for_a_token_with_an_unverified_google_email(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject=SUBJECT, email=GOOGLE_EMAIL, email_verified=False)
    link(client, signed_in.headers, token="unverified")
    assert google.verified == ["unverified"]


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_gets_google_email_unverified(
    client, database, google, make_user, sign_in, role
):
    from app.schemas.auth import UserRole

    google.add("role-token", subject="sub-role", email_verified=False)
    user = make_password_user(make_user, email="role@example.com", role=UserRole(role))
    before = snapshot(database)
    response = link(client, sign_in(user).headers, token="role-token")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert snapshot(database) == before


def test_a_verified_token_still_links_after_an_unverified_one_was_refused(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject="sub-other", email_verified=False)
    assert_error(
        link(client, signed_in.headers, token="unverified"),
        422,
        "GOOGLE_EMAIL_UNVERIFIED",
        "idToken",
    )
    response = link(client, signed_in.headers)
    assert response.status_code == 200, response.text
    assert response.json()["googleEmail"] == GOOGLE_EMAIL
    assert stored_user(database, rina.id).google_subject == SUBJECT


def test_password_login_required_is_answered_before_an_unverified_google_email(
    client, database, google, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    google.add("unverified", subject="sub-new", email_verified=False)
    user = make_password_user(make_user)
    session = sign_in(user, login_method=LoginMethod.GOOGLE)
    before = snapshot(database)
    response = link(client, session.headers, token="unverified")
    assert_error(response, 403, "PASSWORD_LOGIN_REQUIRED")
    assert snapshot(database) == before


def test_email_not_verified_is_answered_before_an_unverified_google_email(
    client, database, google, make_user, sign_in
):
    user = make_password_user(make_user, email_verified=False)
    google.add("unverified", subject="sub-new", email_verified=False)
    response = link(client, sign_in(user).headers, token="unverified")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_an_invalid_token_is_answered_before_an_unverified_google_email(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject=SUBJECT, email_verified=False)
    response = link(client, signed_in.headers, token="unknown-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")


def test_an_unverified_google_email_is_answered_before_already_linked(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("unverified", subject=SUBJECT, email=GOOGLE_EMAIL, email_verified=False)
    user = make_google_user(
        database,
        subject=SUBJECT,
        google_email=GOOGLE_EMAIL,
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(user)
    before = snapshot(database)
    response = link(client, session.headers, token="unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert snapshot(database) == before


def test_an_unverified_google_email_is_answered_before_a_taken_identity(
    client, database, google, rina, signed_in
):
    google.add("unverified", subject="sub-budi", email_verified=False)
    other = make_google_user(database, subject="sub-budi", email="budi@example.com")
    before = snapshot(database)
    response = link(client, signed_in.headers, token="unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert snapshot(database) == before
    assert stored_user(database, other.id).google_subject == "sub-budi"


# Account already linked


def test_an_account_with_a_linked_identity_gets_google_already_linked(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("same-token", subject=SUBJECT, email=GOOGLE_EMAIL)
    user = make_google_user(
        database,
        subject=SUBJECT,
        google_email=GOOGLE_EMAIL,
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(user)
    before = snapshot(database)
    response = link(client, session.headers, token="same-token")
    assert_error(response, 409, "GOOGLE_ALREADY_LINKED")
    assert snapshot(database) == before


def test_linking_a_different_identity_over_a_linked_one_is_refused(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("new-token", subject="sub-new", email="new@gmail.example")
    user = make_google_user(
        database,
        subject=SUBJECT,
        google_email=GOOGLE_EMAIL,
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(user)
    response = link(client, session.headers, token="new-token")
    assert_error(response, 409, "GOOGLE_ALREADY_LINKED")
    stored = stored_user(database, user.id)
    assert stored.google_subject == SUBJECT
    assert stored.google_email == GOOGLE_EMAIL


def test_already_linked_is_answered_before_the_identity_is_checked_for_use(
    client, database, google, sign_in
):
    from app.services.passwords import hash_password

    google.add("budi-token", subject="sub-budi")
    make_google_user(database, subject="sub-budi", email="budi@example.com")
    user = make_google_user(
        database, subject=SUBJECT, password_hash=hash_password(PASSWORD)
    )
    session = sign_in(user)
    response = link(client, session.headers, token="budi-token")
    assert_error(response, 409, "GOOGLE_ALREADY_LINKED")


# Identity linked to another account


def test_an_identity_of_another_account_gets_google_account_already_registered(
    client, database, google, rina, signed_in
):
    other = make_google_user(database, subject=SUBJECT, email="budi@example.com")
    before = snapshot(database)
    response = link(client, signed_in.headers)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    assert snapshot(database) == before
    assert stored_user(database, rina.id).google_subject is None
    assert stored_user(database, other.id).google_subject == SUBJECT
    assert_still_signed_in(client, signed_in)


def test_an_identity_of_a_deleted_account_gets_google_account_already_registered(
    client, database, google, rina, signed_in
):
    make_google_user(database, subject=SUBJECT, email="gone@example.com", deleted=True)
    response = link(client, signed_in.headers)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    assert stored_user(database, rina.id).google_subject is None


def test_an_identity_of_a_password_account_gets_google_account_already_registered(
    client, database, google, rina, signed_in, make_user
):
    from app.services.passwords import hash_password

    make_google_user(
        database,
        subject=SUBJECT,
        email="budi@example.com",
        password_hash=hash_password(PASSWORD),
    )
    response = link(client, signed_in.headers)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")


def test_two_accounts_cannot_link_the_same_identity(
    client, database, google, rina, signed_in, make_user, sign_in
):
    second = make_password_user(make_user, email="budi@example.com", name="Budi")
    assert link(client, signed_in.headers).status_code == 200
    response = link(client, sign_in(second).headers)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    assert stored_user(database, second.id).google_subject is None
    assert user_by_subject(database, SUBJECT).id == rina.id


# Validation


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_token_is_a_validation_failure(
    client, database, google, rina, signed_in, value
):
    response = client.post(URL, json={"idToken": value}, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []


def test_a_missing_token_is_a_validation_failure(client, database, rina, signed_in):
    response = client.post(URL, json={}, headers=signed_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")


def test_a_missing_body_is_a_validation_failure(client, database, rina, signed_in):
    response = client.post(URL, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


# Authentication


def test_no_token_is_rejected(client, database, rina):
    response = client.post(URL, json={"idToken": TOKEN})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None
    assert stored_user(database, rina.id).google_subject is None


def test_an_invalid_access_token_is_rejected(client, database, rina):
    response = link(client, {"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_a_revoked_session_is_rejected(client, database, rina, signed_in):
    client.post("/auth/logout", headers=signed_in.headers)
    response = link(client, signed_in.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"
    assert stored_user(database, rina.id).google_subject is None


def test_a_rejected_session_does_not_reach_the_verifier(client, database, google, rina):
    link(client, {"Authorization": "Bearer garbage"})
    assert google.verified == []


def test_an_unverified_account_gets_email_not_verified(
    client, database, google, make_user, sign_in
):
    user = make_password_user(make_user, email_verified=False)
    google.add("new-token", subject="sub-new")
    headers = sign_in(user).headers
    before = snapshot(database)
    response = link(client, headers, token="new-token")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
    assert snapshot(database) == before


def test_email_not_verified_is_answered_before_the_token_is_checked(
    client, database, make_user, sign_in
):
    user = make_password_user(make_user, email_verified=False)
    response = link(client, sign_in(user).headers, token="unknown-token")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
