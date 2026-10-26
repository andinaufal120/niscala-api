"""Activating a Manager account through an invitation link with a password."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from manager_invitation_support import (
    ACTIVATION_URL,
    code_count,
    edit_invitation,
    install_hook,
    preview_status,
    sha256,
    stored_record,
    stored_user,
)
from manager_support import (
    LOGIN_URL,
    ME_URL,
    PROPERTIES,
    assert_error,
    fetch_all,
    get_manager,
    invitation_rows,
    list_managers,
    regenerate,
    role,
    state,
    token_of,
)

CONFIRMATION_URL = "/auth/email-verification/confirmation"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"
EMAIL = "dewi.new@example.com"
NAME = "Dewi Lestari"
CONTACTS = [
    {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
    {"name": "Wati", "relationship": "Adik", "phone": "628222222222"},
]


def body_for(token: str, **overrides) -> dict:
    body = {
        "token": token,
        "name": NAME,
        "email": EMAIL,
        "password": PASSWORD,
        "device": DEVICE,
    }
    return {**body, **overrides}


def activate(client, token: str, **overrides):
    return client.post(ACTIVATION_URL, json=body_for(token, **overrides))


def activate_without(client, token: str, *keys: str):
    body = {k: v for k, v in body_for(token).items() if k not in keys}
    return client.post(ACTIVATION_URL, json=body)


def snapshot(database) -> dict:
    """Everything a failed activation must leave untouched."""
    return {**state(database), "codes": code_count(database)}


def assert_unchanged(database, before: dict, sent_emails) -> None:
    assert snapshot(database) == before
    assert sent_emails == []


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def melati(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def anggrek(owner, make_property):
    return make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")


@pytest.fixture
def manager(owner, melati, anggrek, make_manager):
    return make_manager(
        owner,
        [melati, anggrek],
        name="Mira Manager",
        nickname="Bu Mira",
        phone="081298765432",
    )


# Success


def test_activation_answers_with_a_session_for_the_manager_account(
    client, database, manager, sent_emails
):
    response = activate(client, manager.token)
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
    assert body["account"] == {
        "id": str(manager.user_id),
        "name": NAME,
        "email": EMAIL,
        "role": "manager",
        "emailVerified": False,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_activation_completes_the_existing_account_instead_of_creating_one(
    client, database, manager, sent_emails
):
    from app.models import Manager, UserAccount

    assert activate(client, manager.token).status_code == 201
    assert len(fetch_all(database, UserAccount)) == 2
    assert len(fetch_all(database, Manager)) == 1


def test_activation_stores_the_name_email_and_an_argon2_hash(
    client, database, manager, sent_emails
):
    from app.services.passwords import verify_password

    activate(client, manager.token)
    user = stored_user(database, manager.user_id)
    assert user.name == NAME
    assert user.email == EMAIL
    assert user.role == role("manager")
    assert user.email_verified is False
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert verify_password(PASSWORD, user.password_hash)


def test_activation_trims_the_name(client, database, manager, sent_emails):
    response = activate(client, manager.token, name="  Dewi Lestari \n")
    assert response.json()["account"]["name"] == NAME
    assert stored_user(database, manager.user_id).name == NAME


def test_activation_can_keep_the_name_the_owner_entered(
    client, database, manager, sent_emails
):
    response = activate(client, manager.token, name="Mira Manager")
    assert response.status_code == 201
    assert stored_user(database, manager.user_id).name == "Mira Manager"


def test_activation_accepts_a_unicode_name(client, database, manager, sent_emails):
    name = "Dewi Šandra 山田 Ñandú"
    response = activate(client, manager.token, name=name)
    assert response.status_code == 201, response.text
    assert stored_user(database, manager.user_id).name == name


def test_activation_trims_and_lowercases_the_email(
    client, database, manager, sent_emails
):
    response = activate(client, manager.token, email="  Dewi.New@Example.COM ")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == EMAIL
    assert stored_user(database, manager.user_id).email == EMAIL


def test_activation_keeps_the_password_untrimmed(
    client, database, manager, sent_emails
):
    activate(client, manager.token, password="  secret T7#vq9 pass  ")
    ok = client.post(
        LOGIN_URL,
        json={"email": EMAIL, "password": "  secret T7#vq9 pass  ", "device": DEVICE},
    )
    trimmed = client.post(
        LOGIN_URL,
        json={"email": EMAIL, "password": "secret T7#vq9 pass", "device": DEVICE},
    )
    assert ok.status_code == 200
    assert trimmed.status_code == 401


def test_activation_marks_the_record_activated_and_the_invitation_used(
    client, database, manager, sent_emails
):
    from app.models import Invitation

    before = datetime.now(UTC)
    activate(client, manager.token)
    record = stored_record(database, manager.id)
    (invitation,) = fetch_all(database, Invitation)
    assert before - timedelta(seconds=5) <= record.activated_at <= datetime.now(UTC)
    assert before - timedelta(seconds=5) <= invitation.used_at <= datetime.now(UTC)
    assert invitation.invalidated_at is None
    assert record.deleted_at is None


def test_activation_keeps_the_nickname_phone_and_owner_of_the_record(
    client, database, owner, manager, sent_emails
):
    assert activate(client, manager.token).status_code == 201
    record = stored_record(database, manager.id)
    assert record.owner_id == owner.id
    assert record.user_id == manager.user_id
    assert record.nickname == "Bu Mira"
    assert record.phone == "081298765432"


def test_activation_keeps_the_assignments(
    client, database, melati, anggrek, manager, sent_emails
):
    from manager_invitation_support import assignments_of

    assert activate(client, manager.token).status_code == 201
    assert assignments_of(database, manager.user_id) == {melati.id, anggrek.id}


def test_activation_starts_a_password_session_on_the_given_device(
    client, database, manager, sent_emails
):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = activate(client, manager.token, device=device).json()
    (session,) = fetch_all(database, UserSession)
    assert session.user_id == manager.user_id
    assert session.login_method == LoginMethod.PASSWORD
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_activation_tokens_work_on_the_account_endpoint(
    client, database, manager, sent_emails
):
    body = activate(client, manager.token).json()
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
    )
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_activation_refresh_token_can_be_refreshed(
    client, database, manager, sent_emails
):
    body = activate(client, manager.token).json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_activation_sends_a_verification_code_to_the_normalized_email(
    client, database, manager, sent_emails
):
    activate(client, manager.token, email=" Dewi.New@Example.COM ")
    assert len(sent_emails) == 1
    to, code = sent_emails[0]
    assert to == EMAIL
    assert len(code) == 6
    assert code.isascii()
    assert code.isdigit()


def test_activation_stores_a_hashed_code_valid_for_ten_minutes(
    client, database, manager, sent_emails, read_verification_code
):
    before = datetime.now(UTC)
    activate(client, manager.token)
    row = read_verification_code(manager.user_id)
    assert row.code_hash == sha256(sent_emails[0][1])
    assert row.failed_attempts == 0
    assert before - timedelta(seconds=5) <= row.created_at <= datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(minutes=10)


def test_the_emailed_code_verifies_the_activated_account(
    client, database, manager, sent_emails
):
    body = activate(client, manager.token).json()
    headers = {"Authorization": f"Bearer {body['accessToken']}"}
    response = client.post(
        CONFIRMATION_URL, json={"code": sent_emails[0][1]}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["emailVerified"] is True
    assert stored_user(database, manager.user_id).email_verified is True


def test_activation_is_public_and_ignores_a_valid_bearer_token(
    client, database, manager, make_user, sign_in, sent_emails
):
    headers = sign_in(make_user()).headers
    response = client.post(
        ACTIVATION_URL, json=body_for(manager.token), headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["account"]["id"] == str(manager.user_id)


def test_activation_ignores_an_invalid_bearer_token(
    client, database, manager, sent_emails
):
    response = client.post(
        ACTIVATION_URL,
        json=body_for(manager.token),
        headers={"Authorization": "Bearer garbage"},
    )
    assert response.status_code == 201, response.text


# After activation


def test_the_owner_sees_the_manager_as_active_with_the_email_and_no_invitation(
    client, database, manager, signed_in, melati, anggrek, sent_emails
):
    activate(client, manager.token)
    response = get_manager(client, signed_in.headers, manager.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(manager.id)
    assert body["accountStatus"] == "active"
    assert body["email"] == EMAIL
    assert body["name"] == NAME
    assert body["nickname"] == "Bu Mira"
    assert body["phone"] == "081298765432"
    assert body["invitation"] is None
    assert [p["id"] for p in body["properties"]] == [str(anggrek.id), str(melati.id)]


def test_the_owner_sees_the_active_manager_in_the_list(
    client, database, manager, signed_in, sent_emails
):
    activate(client, manager.token)
    response = list_managers(client, signed_in.headers)
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["id"] == str(manager.id)
    assert item["accountStatus"] == "active"
    assert item["email"] == EMAIL
    assert item["name"] == NAME


def test_the_used_token_previews_as_used(client, database, manager, sent_emails):
    activate(client, manager.token)
    assert preview_status(client, manager.token) == "used"


def test_activating_again_with_the_same_token_is_refused(
    client, database, manager, sent_emails
):
    assert activate(client, manager.token).status_code == 201
    before = snapshot(database)
    sent_emails.clear()
    response = activate(client, manager.token, email="other@example.com")
    assert_error(response, 409, "INVITATION_USED")
    assert_unchanged(database, before, sent_emails)


def test_the_manager_can_log_in_with_the_new_email_and_password(
    client, database, manager, sent_emails
):
    activate(client, manager.token)
    response = client.post(
        LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "device": DEVICE}
    )
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(manager.user_id)
    assert response.json()["account"]["role"] == "manager"


def test_the_manager_cannot_use_verified_only_endpoints_until_the_code_is_confirmed(
    client, database, manager, sent_emails
):
    body = activate(client, manager.token).json()
    headers = {"Authorization": f"Bearer {body['accessToken']}"}
    assert_error(client.get(PROPERTIES, headers=headers), 403, "EMAIL_NOT_VERIFIED")
    confirmed = client.post(
        CONFIRMATION_URL, json={"code": sent_emails[0][1]}, headers=headers
    )
    assert confirmed.status_code == 200
    assert client.get(PROPERTIES, headers=headers).status_code == 200


def test_the_activated_manager_sees_the_assigned_properties_once_verified(
    client, database, manager, melati, anggrek, sent_emails
):
    body = activate(client, manager.token).json()
    headers = {"Authorization": f"Bearer {body['accessToken']}"}
    client.post(CONFIRMATION_URL, json={"code": sent_emails[0][1]}, headers=headers)
    items = client.get(PROPERTIES, headers=headers).json()["items"]
    assert {item["id"] for item in items} == {str(melati.id), str(anggrek.id)}


def test_activating_one_manager_does_not_touch_another_managers_invitation(
    client, database, owner, melati, manager, make_manager, sent_emails
):
    other = make_manager(owner, [melati], name="Other Manager")
    activate(client, manager.token)
    assert preview_status(client, other.token) == "valid"
    assert stored_record(database, other.id).activated_at is None


# Emergency contacts


def test_emergency_contacts_sent_for_a_manager_are_ignored(
    client, database, manager, sent_emails
):
    from app.models import EmergencyContact

    response = activate(client, manager.token, emergencyContacts=CONTACTS)
    assert response.status_code == 201, response.text
    assert fetch_all(database, EmergencyContact) == []


def test_a_manager_activates_without_emergency_contacts(
    client, database, manager, sent_emails
):
    assert activate(client, manager.token).status_code == 201


def test_a_manager_activates_with_null_emergency_contacts(
    client, database, manager, sent_emails
):
    response = activate(client, manager.token, emergencyContacts=None)
    assert response.status_code == 201, response.text


def test_activating_a_manager_creates_no_tenant_profile(
    client, database, manager, sent_emails
):
    from app.models import Tenant

    response = activate(client, manager.token, emergencyContacts=CONTACTS)
    assert response.status_code == 201
    assert fetch_all(database, Tenant) == []


# Link states and check order


def test_an_unknown_token_is_not_found(client, database, manager, sent_emails):
    before = snapshot(database)
    response = activate(client, "unknown-token")
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert_unchanged(database, before, sent_emails)


def test_a_deleted_managers_token_is_not_found(
    client, database, owner, melati, make_manager, sent_emails
):
    stored = make_manager(owner, [melati], deleted=True)
    before = snapshot(database)
    assert_error(activate(client, stored.token), 404, "INVITATION_NOT_FOUND")
    assert_unchanged(database, before, sent_emails)


def test_an_expired_link_is_refused_and_nothing_is_saved(
    client, database, owner, melati, make_manager, sent_emails
):
    stored = make_manager(owner, [melati], expired=True)
    before = snapshot(database)
    response = activate(client, stored.token)
    assert_error(response, 409, "INVITATION_EXPIRED")
    assert_unchanged(database, before, sent_emails)
    assert preview_status(client, stored.token) == "expired"


def test_a_link_that_expired_a_moment_ago_is_refused(
    client, database, manager, sent_emails
):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert_error(activate(client, manager.token), 409, "INVITATION_EXPIRED")


def test_a_link_about_to_expire_still_activates(client, database, manager, sent_emails):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert activate(client, manager.token).status_code == 201


def test_a_used_link_is_refused(client, database, manager, sent_emails):
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    before = snapshot(database)
    response = activate(client, manager.token)
    assert_error(response, 409, "INVITATION_USED")
    assert_unchanged(database, before, sent_emails)


def test_a_link_of_an_already_activated_manager_is_refused(
    client, database, owner, melati, make_manager, sent_emails
):
    stored = make_manager(owner, [melati], activated=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_USED")


def test_used_wins_over_expired(client, database, manager, sent_emails):
    edit_invitation(
        database,
        manager.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(activate(client, manager.token), 409, "INVITATION_USED")


def test_a_replaced_link_is_refused_and_the_new_link_works(
    client, database, manager, signed_in, sent_emails
):
    renewed = regenerate(client, signed_in.headers, manager.id)
    new_token = token_of(renewed.json()["url"])
    before = snapshot(database)
    assert_error(activate(client, manager.token), 409, "INVITATION_USED")
    assert_unchanged(database, before, sent_emails)
    response = activate(client, new_token)
    assert response.status_code == 201, response.text
    assert preview_status(client, new_token) == "used"
    assert preview_status(client, manager.token) == "used"
    assert len(invitation_rows(database, manager.id)) == 2


def test_an_expired_link_can_be_renewed_and_then_activates(
    client, database, owner, melati, make_manager, signed_in, sent_emails
):
    stored = make_manager(owner, [melati], expired=True)
    renewed = regenerate(client, signed_in.headers, stored.id)
    assert activate(client, token_of(renewed.json()["url"])).status_code == 201


def test_the_link_is_checked_before_the_email_is_required(
    client, database, manager, sent_emails
):
    assert_error(
        activate_without(client, "unknown-token", "email"),
        404,
        "INVITATION_NOT_FOUND",
    )
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    assert_error(
        activate_without(client, manager.token, "email"), 409, "INVITATION_USED"
    )


def test_an_expired_link_is_reported_before_a_taken_email(
    client, database, owner, melati, make_manager, make_user, sent_emails
):
    make_user(email=EMAIL)
    stored = make_manager(owner, [melati], expired=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_EXPIRED")


def test_a_used_link_is_reported_before_a_weak_password(
    client, database, manager, sent_emails
):
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    response = activate(client, manager.token, password="password123")
    assert_error(response, 409, "INVITATION_USED")


def test_validation_is_reported_before_the_link_lookup(client, database, sent_emails):
    response = activate(client, "unknown-token", password="short")
    assert_error(response, 422, "VALIDATION_FAILED", "password")


# Email


@pytest.mark.parametrize("missing", ["omitted", "null"])
def test_an_email_is_required(client, database, manager, sent_emails, missing):
    before = snapshot(database)
    if missing == "omitted":
        response = activate_without(client, manager.token, "email")
    else:
        response = activate(client, manager.token, email=None)
    assert_error(response, 422, "VALIDATION_FAILED", "email")
    assert_unchanged(database, before, sent_emails)


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", ""])
def test_an_invalid_email_is_a_validation_failure(
    client, database, manager, sent_emails, email
):
    response = activate(client, manager.token, email=email)
    assert_error(response, 422, "VALIDATION_FAILED", "email")


@pytest.mark.parametrize("name", ["owner", "manager", "tenant", "admin"])
def test_an_email_of_any_existing_account_is_refused(
    client, database, manager, make_user, sent_emails, name
):
    make_user(email=EMAIL, role=role(name))
    before = snapshot(database)
    response = activate(client, manager.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert_unchanged(database, before, sent_emails)
    assert preview_status(client, manager.token) == "valid"


@pytest.mark.parametrize(
    "submitted",
    [EMAIL.upper(), "Dewi.New@Example.com", f"  {EMAIL}", f"{EMAIL}  "],
)
def test_the_email_comparison_ignores_case_and_surrounding_spaces(
    client, database, manager, make_user, sent_emails, submitted
):
    make_user(email=EMAIL)
    response = activate(client, manager.token, email=submitted)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_an_email_of_an_unverified_account_is_still_taken(
    client, database, manager, make_user, sent_emails
):
    make_user(email=EMAIL, email_verified=False)
    response = activate(client, manager.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_the_email_of_another_activated_manager_is_taken(
    client, database, owner, melati, manager, make_manager, sent_emails
):
    other = make_manager(owner, [melati], name="Other Manager")
    assert activate(client, manager.token).status_code == 201
    before = snapshot(database)
    sent_emails.clear()
    response = activate(client, other.token, email=EMAIL.upper())
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert_unchanged(database, before, sent_emails)


def test_a_registered_owner_email_is_taken(
    client, database, manager, register_owner, sent_emails
):
    assert register_owner(email=EMAIL).status_code == 201
    sent_emails.clear()
    response = activate(client, manager.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


# Password


@pytest.mark.parametrize("length", [8, 64, 128])
def test_passwords_of_8_to_128_characters_are_accepted(
    client, database, manager, sent_emails, length
):
    password = ("T7#vq9-lorem-ipsum-" * 10)[:length]
    assert activate(client, manager.token, password=password).status_code == 201


@pytest.mark.parametrize("length", [0, 7, 129, 200])
def test_passwords_outside_8_to_128_characters_are_a_validation_failure(
    client, database, manager, sent_emails, length
):
    before = snapshot(database)
    response = activate(client, manager.token, password="a" * length)
    assert_error(response, 422, "VALIDATION_FAILED", "password")
    assert_unchanged(database, before, sent_emails)


@pytest.mark.parametrize(
    "password",
    [
        "password123",
        "qwertyuiop",
        "PASSWORD123",
        "aaaaaaaa",
        "12345678",
        "abcdefgh",
        "87654321",
        "niscala!",
        "xx-NISCALA-xx",
    ],
)
def test_a_blocked_password_is_refused_and_nothing_is_saved(
    client, database, manager, sent_emails, password
):
    before = snapshot(database)
    response = activate(client, manager.token, password=password)
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")
    assert_unchanged(database, before, sent_emails)
    assert preview_status(client, manager.token) == "valid"


def test_a_password_containing_the_submitted_email_local_part_is_refused(
    client, database, manager, sent_emails
):
    response = activate(
        client, manager.token, email="mira.s@example.com", password="T7#vq9-Mira.S-x"
    )
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def test_a_password_containing_the_submitted_name_is_refused(
    client, database, manager, sent_emails
):
    response = activate(
        client, manager.token, name="Dewi Lestari", password="T7#vq9-dewi lestari-x"
    )
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def test_a_password_containing_the_name_the_owner_entered_is_accepted_when_renamed(
    client, database, manager, sent_emails
):
    response = activate(
        client, manager.token, name="Dewi Lestari", password="T7#vq9-mira manager-x"
    )
    assert response.status_code == 201, response.text


# Other validation


def test_a_missing_device_is_a_validation_failure(
    client, database, manager, sent_emails
):
    before = snapshot(database)
    response = activate_without(client, manager.token, "device")
    assert_error(response, 422, "VALIDATION_FAILED", "device")
    assert_unchanged(database, before, sent_emails)


@pytest.mark.parametrize("platform", ["", "p" * 51])
def test_a_device_platform_outside_1_to_50_characters_is_refused(
    client, database, manager, sent_emails, platform
):
    device = {**DEVICE, "platform": platform}
    response = activate(client, manager.token, device=device)
    assert_error(response, 422, "VALIDATION_FAILED", "device.platform")


@pytest.mark.parametrize("name", ["", "   ", "n" * 101])
def test_a_blank_or_overlong_name_is_a_validation_failure(
    client, database, manager, sent_emails, name
):
    response = activate(client, manager.token, name=name)
    assert_error(response, 422, "VALIDATION_FAILED", "name")


# Atomicity


class BrokenSender:
    def send_verification_code(self, to: str, code: str) -> None:
        raise RuntimeError("mail server down")


def test_nothing_is_saved_when_sending_the_email_fails(
    app, database, manager, sent_emails, monkeypatch
):
    from app.email import get_email_sender

    before = snapshot(database)
    monkeypatch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
    failing = TestClient(app, raise_server_exceptions=False)
    response = failing.post(ACTIVATION_URL, json=body_for(manager.token))
    assert response.status_code == 500
    assert snapshot(database) == before


def test_the_link_still_works_after_a_failed_email_send(
    app, client, database, manager, sent_emails, monkeypatch
):
    from app.email import get_email_sender

    with monkeypatch.context() as patch:
        patch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
        failing = TestClient(app, raise_server_exceptions=False)
        failing.post(ACTIVATION_URL, json=body_for(manager.token))
    response = activate(client, manager.token)
    assert response.status_code == 201, response.text
    assert len(sent_emails) == 1


def test_a_failed_activation_leaves_the_account_without_credentials(
    client, database, manager, sent_emails
):
    from app.models import UserSession

    activate(client, manager.token, password="12345678")
    user = stored_user(database, manager.user_id)
    assert user.email is None
    assert user.password_hash is None
    assert user.name == "Mira Manager"
    assert stored_record(database, manager.id).activated_at is None
    assert fetch_all(database, UserSession) == []


# Notification hook


def test_the_activation_hook_is_called_once_with_the_manager_record(
    client, database, manager, sent_emails, monkeypatch
):
    calls = install_hook(monkeypatch)
    assert activate(client, manager.token).status_code == 201
    assert calls.record_ids == [manager.id]


@pytest.mark.parametrize(
    "case",
    [
        "unknown_token",
        "used_link",
        "expired_link",
        "missing_email",
        "weak_password",
        "taken_email",
    ],
)
def test_the_activation_hook_is_not_called_for_a_rejected_request(
    client, database, manager, make_user, sent_emails, monkeypatch, case
):
    calls = install_hook(monkeypatch)
    token = manager.token
    overrides: dict = {}
    if case == "unknown_token":
        token = "unknown-token"
    elif case == "used_link":
        edit_invitation(database, token, used_at=datetime.now(UTC))
    elif case == "expired_link":
        edit_invitation(
            database, token, expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    elif case == "missing_email":
        overrides = {"email": None}
    elif case == "weak_password":
        overrides = {"password": "password123"}
    else:
        make_user(email=EMAIL)
    response = activate(client, token, **overrides)
    assert response.status_code >= 400
    assert calls.records == []


def test_the_activation_hook_is_not_called_when_the_replayed_token_is_refused(
    client, database, manager, sent_emails, monkeypatch
):
    calls = install_hook(monkeypatch)
    activate(client, manager.token)
    activate(client, manager.token)
    assert calls.record_ids == [manager.id]


def test_activation_succeeds_when_the_hook_raises(
    client, database, manager, sent_emails, monkeypatch
):
    calls = install_hook(monkeypatch, error=RuntimeError("notification down"))
    response = activate(client, manager.token)
    assert response.status_code == 201, response.text
    assert calls.record_ids == [manager.id]
    assert stored_record(database, manager.id).activated_at is not None
    assert stored_user(database, manager.user_id).email == EMAIL
    assert preview_status(client, manager.token) == "used"
