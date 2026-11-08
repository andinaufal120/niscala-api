"""Owner sign-up with a Google ID token."""

import pytest
from google_support import (
    ANY_FIELD,
    DEVICE,
    ME_URL,
    REGISTER_URL,
    SESSIONS_URL,
    assert_error,
    bearer,
    login,
    make_google_user,
    register,
    sha256,
    snapshot,
    stored_user,
    user_by_subject,
)
from user_account_support import sessions_of

TOKEN = "rina-token"
SUBJECT = "sub-rina"
EMAIL = "rina@example.com"


@pytest.fixture
def rina(google):
    return google.add(TOKEN, subject=SUBJECT, email=EMAIL, name="Rina Owner")


# Success


def test_registration_answers_with_a_session_for_the_new_owner(
    client, database, google, rina, mailbox
):
    response = register(client, TOKEN)
    assert response.status_code == 201, response.text
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
    user = user_by_subject(database, SUBJECT)
    assert body["account"] == {
        "id": str(user.id),
        "name": "Rina Owner",
        "email": EMAIL,
        "role": "owner",
        "emailVerified": True,
        "hasPassword": False,
        "googleEmail": EMAIL,
    }


def test_registration_stores_a_verified_owner_without_a_password(
    client, database, google, rina, mailbox
):
    from app.schemas.auth import UserRole

    register(client, TOKEN)
    user = user_by_subject(database, SUBJECT)
    assert user.role == UserRole.OWNER
    assert user.name == "Rina Owner"
    assert user.email == EMAIL
    assert user.email_verified is True
    assert user.password_hash is None
    assert user.google_subject == SUBJECT
    assert user.google_email == EMAIL


def test_registration_creates_an_active_account(
    client, database, google, rina, mailbox
):
    register(client, TOKEN)
    assert user_by_subject(database, SUBJECT).status == "active"
    assert user_by_subject(database, SUBJECT).deleted_at is None


def test_registration_hands_the_given_token_to_the_verifier(
    client, database, google, rina, mailbox
):
    register(client, TOKEN)
    assert google.verified == [TOKEN]


@pytest.mark.parametrize("email", ["Rina.Owner@Example.COM", "RINA.OWNER@EXAMPLE.COM"])
def test_registration_lowercases_the_email(client, database, google, mailbox, email):
    google.add("mixed", subject="sub-mixed", email=email)
    response = register(client, "mixed")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == "rina.owner@example.com"
    assert user_by_subject(database, "sub-mixed").email == "rina.owner@example.com"


def test_registration_strips_the_name_claim(client, database, google, mailbox):
    google.add("padded", subject="sub-padded", name="  Rina Owner \n")
    response = register(client, "padded")
    assert response.json()["account"]["name"] == "Rina Owner"
    assert user_by_subject(database, "sub-padded").name == "Rina Owner"


@pytest.mark.parametrize("claim", [None, "", "   ", "\n\t"])
def test_registration_names_the_account_after_the_email_local_part_without_a_name(
    client, database, google, mailbox, claim
):
    google.add(
        "nameless", subject="sub-nameless", email="budi.s@example.com", name=claim
    )
    response = register(client, "nameless")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "budi.s"
    assert user_by_subject(database, "sub-nameless").name == "budi.s"


def test_registration_accepts_a_unicode_name_claim(client, database, google, mailbox):
    google.add("unicode", subject="sub-unicode", name="Dewi Šandra 山田")
    response = register(client, "unicode")
    assert response.json()["account"]["name"] == "Dewi Šandra 山田"


def test_registration_uses_the_requested_name(client, database, google, rina, mailbox):
    response = register(client, TOKEN, name="Budi Pemilik")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "Budi Pemilik"
    assert user_by_subject(database, SUBJECT).name == "Budi Pemilik"


def test_the_requested_name_wins_over_the_name_claim(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN, name="Chosen Name").json()
    assert body["account"]["name"] != "Rina Owner"
    assert user_by_subject(database, SUBJECT).name == "Chosen Name"


def test_the_requested_name_is_returned_by_the_account_endpoint(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN, name="Budi Pemilik").json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.json()["name"] == "Budi Pemilik"


def test_the_requested_name_is_kept_when_logging_in_again(
    client, database, google, rina, mailbox
):
    register(client, TOKEN, name="Budi Pemilik")
    response = login(client, TOKEN)
    assert response.json()["account"]["name"] == "Budi Pemilik"


def test_the_requested_name_is_trimmed(client, database, google, rina, mailbox):
    response = register(client, TOKEN, name="  Budi Pemilik \n")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "Budi Pemilik"
    assert user_by_subject(database, SUBJECT).name == "Budi Pemilik"


def test_the_requested_name_need_not_match_the_token(client, database, google, mailbox):
    google.add("other", subject="sub-other", email="x@example.com", name="Totally Else")
    response = register(client, "other", name="Someone Different")
    assert response.json()["account"]["name"] == "Someone Different"


def test_the_requested_name_accepts_unicode(client, database, google, rina, mailbox):
    response = register(client, TOKEN, name="Dewi Šandra 山田")
    assert response.json()["account"]["name"] == "Dewi Šandra 山田"


@pytest.mark.parametrize("claim", [None, "", "   "])
def test_the_requested_name_is_used_when_the_token_has_no_name(
    client, database, google, mailbox, claim
):
    google.add("nameless", subject="sub-nameless", name=claim)
    response = register(client, "nameless", name="Budi Pemilik")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "Budi Pemilik"
    assert user_by_subject(database, "sub-nameless").name == "Budi Pemilik"


def test_a_requested_name_of_100_characters_is_accepted(
    client, database, google, rina, mailbox
):
    name = "n" * 100
    response = register(client, TOKEN, name=name)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == name
    assert user_by_subject(database, SUBJECT).name == name


def test_a_null_requested_name_falls_back_to_the_name_claim(
    client, database, google, rina, mailbox
):
    response = register(client, TOKEN, name=None)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "Rina Owner"


def test_a_null_requested_name_falls_back_to_the_email_local_part(
    client, database, google, mailbox
):
    google.add(
        "nameless", subject="sub-nameless", email="budi.s@example.com", name=None
    )
    response = register(client, "nameless", name=None)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "budi.s"


def test_an_omitted_requested_name_falls_back_to_the_name_claim(
    client, database, google, rina, mailbox
):
    response = client.post(REGISTER_URL, json={"idToken": TOKEN, "device": DEVICE})
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "Rina Owner"


def test_a_name_claim_over_100_characters_is_cut_to_100(
    client, database, google, mailbox
):
    google.add("longname", subject="sub-long", name="c" * 150)
    response = register(client, "longname")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "c" * 100
    assert user_by_subject(database, "sub-long").name == "c" * 100


def test_a_padded_name_claim_is_trimmed_before_it_is_cut(
    client, database, google, mailbox
):
    google.add("padlong", subject="sub-padlong", name="  " + "c" * 150)
    response = register(client, "padlong")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "c" * 100


def test_an_email_local_part_over_100_characters_is_cut_to_100(
    client, database, google, mailbox
):
    google.add(
        "longmail", subject="sub-longmail", email="l" * 150 + "@example.com", name=None
    )
    response = register(client, "longmail")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == "l" * 100
    assert user_by_subject(database, "sub-longmail").name == "l" * 100


@pytest.mark.parametrize("name", ["", "   ", "\n\t", "n" * 101, f"  {'n' * 101}  "])
def test_an_unusable_requested_name_is_a_validation_failure_before_the_token_is_checked(
    client, database, google, rina, mailbox, name
):
    before = snapshot(database)
    response = register(client, TOKEN, name=name)
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert google.verified == []
    assert snapshot(database) == before
    assert user_by_subject(database, SUBJECT) is None


@pytest.mark.parametrize("name", [5, ["Budi"], {"first": "Budi"}, True])
def test_a_non_string_requested_name_is_a_validation_failure(
    client, database, google, rina, mailbox, name
):
    before = snapshot(database)
    response = register(client, TOKEN, name=name)
    assert_error(response, 422, "VALIDATION_FAILED", "name")
    assert google.verified == []
    assert snapshot(database) == before


def test_a_requested_name_does_not_bypass_the_token_check(
    client, database, google, mailbox
):
    before = snapshot(database)
    response = register(client, "forged-token", name="Budi Pemilik")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert snapshot(database) == before


def test_a_requested_name_does_not_bypass_the_taken_email_check(
    client, database, google, rina, mailbox, make_user
):
    make_user(email=EMAIL, name="Existing Name")
    response = register(client, TOKEN, name="Budi Pemilik")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert user_by_subject(database, SUBJECT) is None


def test_registration_starts_a_google_session_on_the_given_device(
    client, database, google, rina, mailbox
):
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = register(client, TOKEN, device=device).json()
    user = user_by_subject(database, SUBJECT)
    (session,) = sessions_of(database, user.id)
    assert session.login_method == LoginMethod.GOOGLE
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_the_session_is_listed_with_the_google_login_method(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN).json()
    response = client.get(SESSIONS_URL, headers=bearer(body))
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["loginMethod"] == "google"
    assert item["isCurrent"] is True
    assert item["deviceName"] == DEVICE["name"]


def test_registration_tokens_work_on_the_account_endpoint(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN).json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.status_code == 200, response.text
    assert response.json() == body["account"]


def test_registration_refresh_token_can_be_refreshed(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN).json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_the_new_owner_can_use_verified_only_endpoints_at_once(
    client, database, google, rina, mailbox
):
    body = register(client, TOKEN).json()
    assert client.get("/properties", headers=bearer(body)).status_code == 200


def test_registration_sends_and_stores_no_verification_code(
    client, database, google, rina, mailbox
):
    from google_support import count_rows

    from app.models import EmailVerificationCode

    assert register(client, TOKEN).status_code == 201
    assert mailbox.is_empty
    assert count_rows(database, EmailVerificationCode) == 0


def test_the_new_owner_has_nothing_to_verify(client, database, google, rina, mailbox):
    body = register(client, TOKEN).json()
    response = client.post("/auth/email-verification", headers=bearer(body))
    assert_error(response, 409, "EMAIL_ALREADY_VERIFIED")
    assert mailbox.is_empty


def test_registration_does_not_require_authentication(
    client, database, google, rina, mailbox, make_user, sign_in
):
    assert "Authorization" not in client.headers
    headers = sign_in(make_user(email="other@example.com")).headers
    response = client.post(
        REGISTER_URL, json={"idToken": TOKEN, "device": DEVICE}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == EMAIL


def test_registration_ignores_an_invalid_bearer_token(
    client, database, google, rina, mailbox
):
    response = client.post(
        REGISTER_URL,
        json={"idToken": TOKEN, "device": DEVICE},
        headers={"Authorization": "Bearer garbage"},
    )
    assert response.status_code == 201, response.text


def test_the_new_owner_cannot_log_in_with_a_password(
    client, database, google, rina, mailbox
):
    from google_support import password_login

    register(client, TOKEN)
    assert_error(
        password_login(client, EMAIL, "any password at all"), 401, "INVALID_CREDENTIALS"
    )


def test_the_new_owner_can_log_in_with_google(client, database, google, rina, mailbox):
    registered = register(client, TOKEN).json()
    response = login(client, TOKEN)
    assert response.status_code == 200, response.text
    assert response.json()["account"] == registered["account"]


def test_two_google_identities_register_two_accounts(
    client, database, google, rina, mailbox
):
    google.add("second", subject="sub-second", email="second@example.com")
    first = register(client, TOKEN).json()["account"]
    second = register(client, "second").json()["account"]
    assert first["id"] != second["id"]
    assert second["email"] == "second@example.com"


def test_a_later_password_sign_up_with_the_same_email_is_refused(
    client, database, google, rina, mailbox, register_owner
):
    register(client, TOKEN)
    response = register_owner(email=EMAIL)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


# Invalid token


def test_a_token_the_verifier_rejects_answers_unauthorized(
    client, database, google, mailbox
):
    before = snapshot(database)
    response = register(client, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert snapshot(database) == before
    assert mailbox.is_empty


# Unverified email


def test_an_unverified_google_email_is_refused(client, database, google, mailbox):
    google.add("unverified", subject="sub-unv", email_verified=False)
    before = snapshot(database)
    response = register(client, "unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert snapshot(database) == before
    assert mailbox.is_empty


# Subject already linked


def test_a_subject_linked_to_an_account_is_refused(
    client, database, google, rina, mailbox
):
    make_google_user(database, subject=SUBJECT, email="elsewhere@example.com")
    before = snapshot(database)
    response = register(client, TOKEN)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert snapshot(database) == before


def test_a_subject_linked_to_a_deleted_account_is_refused(
    client, database, google, rina, mailbox
):
    make_google_user(
        database, subject=SUBJECT, email="elsewhere@example.com", deleted=True
    )
    before = snapshot(database)
    response = register(client, TOKEN)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert snapshot(database) == before


def test_registering_twice_with_the_same_token_is_refused(
    client, database, google, rina, mailbox
):
    assert register(client, TOKEN).status_code == 201
    before = snapshot(database)
    response = register(client, TOKEN)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert snapshot(database) == before


def test_a_new_token_of_a_registered_subject_is_refused(
    client, database, google, rina, mailbox
):
    google.add("again", subject=SUBJECT, email="changed@example.com")
    assert register(client, TOKEN).status_code == 201
    response = register(client, "again")
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert user_by_subject(database, SUBJECT).email == EMAIL


# Email already registered


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_an_email_of_any_existing_account_is_refused(
    client, database, google, rina, mailbox, make_user, role
):
    from app.schemas.auth import UserRole

    make_user(email=EMAIL, role=UserRole(role))
    before = snapshot(database)
    response = register(client, TOKEN)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert snapshot(database) == before
    assert mailbox.is_empty


def test_an_email_of_a_deleted_account_is_still_taken(
    client, database, google, rina, mailbox, make_user
):
    make_user(email=EMAIL, deleted=True)
    before = snapshot(database)
    response = register(client, TOKEN)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert snapshot(database) == before


def test_an_email_of_an_unverified_account_is_still_taken(
    client, database, google, rina, mailbox, make_user
):
    make_user(email=EMAIL, email_verified=False)
    response = register(client, TOKEN)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_an_email_of_an_inactive_account_is_still_taken(
    client, database, google, rina, mailbox, make_user
):
    make_user(email=EMAIL, status="inactive")
    response = register(client, TOKEN)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_an_email_of_another_google_account_is_taken(
    client, database, google, rina, mailbox
):
    make_google_user(database, subject="sub-other", email=EMAIL)
    response = register(client, TOKEN)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert user_by_subject(database, SUBJECT) is None


@pytest.mark.parametrize(
    "submitted", ["RINA@EXAMPLE.COM", "Rina@Example.com", f"  {EMAIL}", f"{EMAIL}  "]
)
def test_the_email_comparison_ignores_case_and_surrounding_spaces(
    client, database, google, mailbox, make_user, submitted
):
    make_user(email=EMAIL)
    google.add("spaced", subject="sub-spaced", email=submitted)
    response = register(client, "spaced")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert user_by_subject(database, "sub-spaced") is None


# Order of checks


def test_an_unverified_email_is_reported_before_a_linked_subject(
    client, database, google, mailbox
):
    make_google_user(database, subject="sub-both", email="elsewhere@example.com")
    google.add("both", subject="sub-both", email_verified=False)
    response = register(client, "both")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")


def test_an_unverified_email_is_reported_before_a_taken_email(
    client, database, google, mailbox, make_user
):
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL, email_verified=False)
    response = register(client, "both")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")


def test_a_linked_subject_is_reported_before_a_taken_email(
    client, database, google, mailbox, make_user
):
    make_google_user(database, subject="sub-both", email="elsewhere@example.com")
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL)
    response = register(client, "both")
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)


# Validation


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_id_token_is_a_validation_failure(
    client, database, google, mailbox, value
):
    before = snapshot(database)
    response = register(client, value)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []
    assert snapshot(database) == before


def test_a_missing_device_is_a_validation_failure(
    client, database, google, rina, mailbox
):
    before = snapshot(database)
    response = client.post(REGISTER_URL, json={"idToken": TOKEN})
    assert_error(response, 422, "VALIDATION_FAILED", "device")
    assert google.verified == []
    assert snapshot(database) == before


@pytest.mark.parametrize("platform", ["", "p" * 51])
def test_a_device_platform_outside_1_to_50_characters_is_refused(
    client, database, google, rina, mailbox, platform
):
    response = register(client, TOKEN, device={**DEVICE, "platform": platform})
    assert_error(response, 422, "VALIDATION_FAILED", "device.platform")


def test_a_failed_registration_leaves_the_stored_account_unchanged(
    client, database, google, rina, mailbox, make_user
):
    existing = make_user(email=EMAIL, name="Existing Name")
    register(client, TOKEN)
    stored = stored_user(database, existing.id)
    assert stored.name == "Existing Name"
    assert stored.google_subject is None
    assert stored.google_email is None
