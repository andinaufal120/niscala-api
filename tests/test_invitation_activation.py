"""Activating a tenant account through an invitation link with a password."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ACTIVATION_URL = "/invitations/activations/password"
PREVIEW_URL = "/invitations/previews"
LOGIN_URL = "/auth/login"
ME_URL = "/me"
CONFIRMATION_URL = "/auth/email-verification/confirmation"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"
EMAIL = "dewi.new@example.com"
NAME = "Dewi Lestari"
STORED_CONTACTS = [
    ("Siti", "Ibu", "081234567890"),
    ("Agus", "Kakak", "08571234567"),
]
CONTACTS = [
    {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
    {"name": "Wati", "relationship": "Adik", "phone": "628222222222"},
]


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


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


def preview_status(client, token: str) -> str:
    response = client.post(PREVIEW_URL, json={"token": token})
    assert response.status_code == 200, response.text
    return response.json()["status"]


def edit_invitation(database, token: str, **columns) -> None:
    from app.models import Invitation

    with Session(database) as db:
        row = db.scalars(
            select(Invitation).where(Invitation.token_hash == sha256(token))
        ).one()
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def snapshot(database, stored) -> dict:
    """Everything a failed activation must leave untouched."""
    from app.models import (
        EmailVerificationCode,
        EmergencyContact,
        Invitation,
        Lease,
        Tenant,
        UserAccount,
        UserSession,
    )

    with Session(database) as db:
        user = db.get(UserAccount, stored.id)
        tenant = db.get(Tenant, stored.id)
        invitations = db.scalars(select(Invitation).order_by(Invitation.created_at))
        contacts = db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.tenant_id == stored.id)
            .order_by(EmergencyContact.position)
        )
        leases = db.scalars(select(Lease).where(Lease.tenant_id == stored.id))
        return {
            "user": (
                user.name,
                user.email,
                user.password_hash,
                user.email_verified,
            ),
            "activated_at": tenant.activated_at,
            "invitations": [
                (i.token_hash, i.used_at, i.invalidated_at, i.expires_at)
                for i in invitations
            ],
            "contacts": [(c.name, c.relationship, c.phone) for c in contacts],
            "leases": [(x.room_id, x.rent, x.ended_at) for x in leases],
            "sessions": len(list(db.scalars(select(UserSession)))),
            "codes": len(list(db.scalars(select(EmailVerificationCode)))),
        }


def assert_unchanged(database, stored, before: dict, sent_emails) -> None:
    assert snapshot(database, stored) == before
    assert sent_emails == []


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def signed_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def room(owner, make_property, make_room):
    return make_room(
        make_property(owner, name="Kos Melati", address="Jl. Melati 5"), number="A1"
    )


@pytest.fixture
def tenant(room, make_tenant):
    """A tenant whose emergency contacts management already stored."""
    return make_tenant(room, name="Budi Tenant", contacts=STORED_CONTACTS)


@pytest.fixture
def bare_tenant(room, make_tenant):
    """A tenant without stored emergency contacts."""
    return make_tenant(room, name="Budi Tenant")


def stored_user(database, user_id):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.get(UserAccount, user_id)


def stored_contacts(database, tenant_id) -> list:
    from app.models import EmergencyContact

    with Session(database, expire_on_commit=False) as db:
        rows = db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.tenant_id == tenant_id)
            .order_by(EmergencyContact.position)
        )
        return list(rows)


# Success


def test_activation_answers_with_a_session_for_the_tenant_account(
    client, database, tenant, sent_emails
):
    response = activate(client, tenant.token)
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
        "id": str(tenant.id),
        "name": NAME,
        "email": EMAIL,
        "role": "tenant",
        "emailVerified": False,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_activation_completes_the_existing_account_instead_of_creating_one(
    client, database, tenant, sent_emails
):
    from app.models import Tenant, UserAccount

    assert activate(client, tenant.token).status_code == 201
    with Session(database) as db:
        assert len(list(db.scalars(select(UserAccount)))) == 2
        assert len(list(db.scalars(select(Tenant)))) == 1


def test_activation_stores_the_name_email_and_an_argon2_hash(
    client, database, tenant, sent_emails
):
    from app.schemas.auth import UserRole
    from app.services.passwords import verify_password

    activate(client, tenant.token)
    user = stored_user(database, tenant.id)
    assert user.name == NAME
    assert user.email == EMAIL
    assert user.role == UserRole.TENANT
    assert user.email_verified is False
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert verify_password(PASSWORD, user.password_hash)


def test_activation_trims_the_name(client, database, tenant, sent_emails):
    response = activate(client, tenant.token, name="  Dewi Lestari \n")
    assert response.json()["account"]["name"] == NAME
    assert stored_user(database, tenant.id).name == NAME


def test_activation_can_keep_the_name_management_entered(
    client, database, tenant, sent_emails
):
    response = activate(client, tenant.token, name="Budi Tenant")
    assert response.status_code == 201
    assert stored_user(database, tenant.id).name == "Budi Tenant"


def test_activation_accepts_a_unicode_name(client, database, tenant, sent_emails):
    name = "Dewi Šandra 山田 Ñandú"
    response = activate(client, tenant.token, name=name)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["name"] == name
    assert stored_user(database, tenant.id).name == name


def test_activation_trims_and_lowercases_the_email(
    client, database, tenant, sent_emails
):
    response = activate(client, tenant.token, email="  Dewi.New@Example.COM ")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == EMAIL
    assert stored_user(database, tenant.id).email == EMAIL


def test_activation_keeps_the_password_untrimmed(client, database, tenant, sent_emails):
    activate(client, tenant.token, password="  secret T7#vq9 pass  ")
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


def test_activation_marks_the_tenant_activated_and_the_invitation_used(
    client, database, tenant, sent_emails
):
    from app.models import Invitation, Tenant

    before = datetime.now(UTC)
    activate(client, tenant.token)
    with Session(database) as db:
        row = db.get(Tenant, tenant.id)
        invitation = db.scalars(select(Invitation)).one()
        assert before - timedelta(seconds=5) <= row.activated_at <= datetime.now(UTC)
        assert before - timedelta(seconds=5) <= invitation.used_at <= datetime.now(UTC)
        assert invitation.invalidated_at is None


def test_activation_starts_a_password_session_on_the_given_device(
    client, database, tenant, sent_emails
):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = activate(client, tenant.token, device=device).json()
    with Session(database) as db:
        (session,) = list(db.scalars(select(UserSession)))
    assert session.user_id == tenant.id
    assert session.login_method == LoginMethod.PASSWORD
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_activation_tokens_work_on_the_account_endpoint(
    client, database, tenant, sent_emails
):
    body = activate(client, tenant.token).json()
    response = client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['accessToken']}"}
    )
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_activation_refresh_token_can_be_refreshed(
    client, database, tenant, sent_emails
):
    body = activate(client, tenant.token).json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_activation_sends_a_verification_code_to_the_normalized_email(
    client, database, tenant, sent_emails
):
    activate(client, tenant.token, email=" Dewi.New@Example.COM ")
    assert len(sent_emails) == 1
    to, code = sent_emails[0]
    assert to == EMAIL
    assert len(code) == 6
    assert code.isascii()
    assert code.isdigit()


def test_activation_stores_a_hashed_code_valid_for_ten_minutes(
    client, database, tenant, sent_emails, read_verification_code
):
    before = datetime.now(UTC)
    activate(client, tenant.token)
    row = read_verification_code(tenant.id)
    assert row.code_hash == sha256(sent_emails[0][1])
    assert row.code_hash != sent_emails[0][1]
    assert row.failed_attempts == 0
    assert before - timedelta(seconds=5) <= row.created_at <= datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(minutes=10)


def test_the_emailed_code_verifies_the_activated_account(
    client, database, tenant, sent_emails
):
    body = activate(client, tenant.token).json()
    headers = {"Authorization": f"Bearer {body['accessToken']}"}
    response = client.post(
        CONFIRMATION_URL, json={"code": sent_emails[0][1]}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["emailVerified"] is True
    assert stored_user(database, tenant.id).email_verified is True


def test_activation_is_public_and_ignores_a_valid_bearer_token(
    client, database, tenant, make_user, sign_in, sent_emails
):
    headers = sign_in(make_user()).headers
    response = client.post(ACTIVATION_URL, json=body_for(tenant.token), headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["id"] == str(tenant.id)


def test_activation_ignores_an_invalid_bearer_token(
    client, database, tenant, sent_emails
):
    response = client.post(
        ACTIVATION_URL,
        json=body_for(tenant.token),
        headers={"Authorization": "Bearer garbage"},
    )
    assert response.status_code == 201, response.text


# After activation


def test_the_owner_sees_the_tenant_as_active_with_the_email_and_no_invitation(
    client, database, tenant, signed_in, sent_emails
):
    activate(client, tenant.token)
    response = client.get(f"/tenants/{tenant.id}", headers=signed_in.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accountStatus"] == "active"
    assert body["email"] == EMAIL
    assert body["name"] == NAME
    assert body["invitation"] is None


def test_activation_leaves_the_room_and_lease_unchanged(
    client, database, tenant, signed_in, room, sent_emails
):
    url = f"/tenants/{tenant.id}"
    before = client.get(url, headers=signed_in.headers).json()
    assert activate(client, tenant.token).status_code == 201
    after = client.get(url, headers=signed_in.headers).json()
    assert after["room"] == before["room"] == {"id": str(room.id), "number": "A1"}
    assert after["lease"] == before["lease"]
    assert after["phone"] == before["phone"]


def test_the_used_token_previews_as_used(client, database, tenant, sent_emails):
    activate(client, tenant.token)
    assert preview_status(client, tenant.token) == "used"


def test_activating_again_with_the_same_token_is_refused(
    client, database, tenant, sent_emails
):
    assert activate(client, tenant.token).status_code == 201
    before = snapshot(database, tenant)
    sent_emails.clear()
    response = activate(client, tenant.token, email="other@example.com")
    assert_error(response, 409, "INVITATION_USED")
    assert snapshot(database, tenant) == before
    assert sent_emails == []


def test_the_tenant_can_log_in_with_the_new_email_and_password(
    client, database, tenant, sent_emails
):
    activate(client, tenant.token)
    response = client.post(
        LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "device": DEVICE}
    )
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(tenant.id)
    assert response.json()["account"]["role"] == "tenant"


def test_activating_one_tenant_does_not_touch_another_tenants_invitation(
    client, database, room, tenant, make_room, make_tenant, sent_emails
):
    other_room = make_room(_property_of(database, room), number="A2")
    other = make_tenant(other_room, name="Other Tenant")
    activate(client, tenant.token)
    assert preview_status(client, other.token) == "valid"


def _property_of(database, room):
    from app.models import Property

    with Session(database, expire_on_commit=False) as db:
        return db.get(Property, room.property_id)


# Emergency contacts


def test_contacts_are_required_when_none_are_stored(
    client, database, bare_tenant, sent_emails
):
    before = snapshot(database, bare_tenant)
    response = activate(client, bare_tenant.token)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert_unchanged(database, bare_tenant, before, sent_emails)


def test_null_contacts_are_refused_when_they_are_required(
    client, database, bare_tenant, sent_emails
):
    response = activate(client, bare_tenant.token, emergencyContacts=None)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")


def test_a_single_contact_is_refused_when_they_are_required(
    client, database, bare_tenant, sent_emails
):
    before = snapshot(database, bare_tenant)
    response = activate(client, bare_tenant.token, emergencyContacts=CONTACTS[:1])
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert_unchanged(database, bare_tenant, before, sent_emails)


def test_five_contacts_are_refused(client, database, bare_tenant, sent_emails):
    response = activate(client, bare_tenant.token, emergencyContacts=CONTACTS * 3)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")


@pytest.mark.parametrize("count", [2, 3, 4])
def test_two_to_four_contacts_are_stored_in_submitted_order(
    client, database, bare_tenant, sent_emails, count
):
    contacts = [
        {"name": f"Zed {n}", "relationship": "Teman", "phone": f"08123456789{n}"}
        for n in reversed(range(count))
    ]
    response = activate(client, bare_tenant.token, emergencyContacts=contacts)
    assert response.status_code == 201, response.text
    rows = stored_contacts(database, bare_tenant.id)
    assert [r.position for r in rows] == list(range(count))
    assert [r.name for r in rows] == [c["name"] for c in contacts]


def test_required_contacts_are_stored_with_normalized_phones(
    client, database, bare_tenant, sent_emails
):
    contacts = [
        {"name": "A", "relationship": "Ibu", "phone": "0812-3456-789"},
        {"name": "B", "relationship": "Ayah", "phone": "62 812 3456 789"},
    ]
    activate(client, bare_tenant.token, emergencyContacts=contacts)
    rows = stored_contacts(database, bare_tenant.id)
    assert [(r.name, r.relationship, r.phone) for r in rows] == [
        ("A", "Ibu", "08123456789"),
        ("B", "Ayah", "08123456789"),
    ]


def test_activation_contacts_show_in_the_tenant_detail(
    client, database, bare_tenant, signed_in, sent_emails
):
    activate(client, bare_tenant.token, emergencyContacts=CONTACTS)
    body = client.get(f"/tenants/{bare_tenant.id}", headers=signed_in.headers).json()
    assert body["emergencyContacts"] == [
        {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
        {"name": "Wati", "relationship": "Adik", "phone": "08222222222"},
    ]


@pytest.mark.parametrize("field", ["name", "relationship"])
@pytest.mark.parametrize("index", [0, 1])
def test_a_blank_contact_text_is_refused_and_nothing_is_saved(
    client, database, bare_tenant, sent_emails, field, index
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index][field] = "   "
    before = snapshot(database, bare_tenant)
    response = activate(client, bare_tenant.token, emergencyContacts=contacts)
    assert_error(
        response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.{field}"
    )
    assert_unchanged(database, bare_tenant, before, sent_emails)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "phone", ["+628123456789", "12345", "abc", "081234567", "0712345678"]
)
def test_an_invalid_contact_phone_is_refused_and_nothing_is_saved(
    client, database, bare_tenant, sent_emails, index, phone
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index]["phone"] = phone
    before = snapshot(database, bare_tenant)
    response = activate(client, bare_tenant.token, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.phone")
    assert_unchanged(database, bare_tenant, before, sent_emails)


def test_stored_contacts_are_kept_and_submitted_ones_ignored(
    client, database, tenant, sent_emails
):
    response = activate(client, tenant.token, emergencyContacts=CONTACTS)
    assert response.status_code == 201, response.text
    rows = stored_contacts(database, tenant.id)
    assert [(r.name, r.relationship, r.phone) for r in rows] == STORED_CONTACTS
    assert [r.position for r in rows] == [0, 1]


def test_activation_without_contacts_is_fine_when_management_stored_them(
    client, database, tenant, sent_emails
):
    assert activate(client, tenant.token).status_code == 201
    assert activate(client, tenant.token).status_code == 409
    rows = stored_contacts(database, tenant.id)
    assert [(r.name, r.relationship, r.phone) for r in rows] == STORED_CONTACTS


def test_activation_with_null_contacts_is_fine_when_management_stored_them(
    client, database, tenant, sent_emails
):
    response = activate(client, tenant.token, emergencyContacts=None)
    assert response.status_code == 201, response.text


# Link states and check order


def test_an_unknown_token_is_not_found(client, database, tenant, sent_emails):
    before = snapshot(database, tenant)
    response = activate(client, "unknown-token")
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert_unchanged(database, tenant, before, sent_emails)


def test_a_deleted_tenants_token_is_not_found(
    client, database, room, make_tenant, sent_emails
):
    stored = make_tenant(room, deleted=True)
    assert_error(activate(client, stored.token), 404, "INVITATION_NOT_FOUND")
    assert sent_emails == []


def test_an_expired_link_is_refused_and_nothing_is_saved(
    client, database, room, make_tenant, sent_emails
):
    stored = make_tenant(room, contacts=STORED_CONTACTS, expired=True)
    before = snapshot(database, stored)
    response = activate(client, stored.token)
    assert_error(response, 409, "INVITATION_EXPIRED")
    assert_unchanged(database, stored, before, sent_emails)
    assert preview_status(client, stored.token) == "expired"


def test_a_link_that_expired_a_moment_ago_is_refused(
    client, database, tenant, sent_emails
):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert_error(activate(client, tenant.token), 409, "INVITATION_EXPIRED")


def test_a_link_about_to_expire_still_activates(client, database, tenant, sent_emails):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert activate(client, tenant.token).status_code == 201


def test_a_used_link_is_refused(client, database, tenant, sent_emails):
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    before = snapshot(database, tenant)
    response = activate(client, tenant.token)
    assert_error(response, 409, "INVITATION_USED")
    assert_unchanged(database, tenant, before, sent_emails)


def test_a_link_of_an_already_activated_tenant_is_refused(
    client, database, room, make_tenant, sent_emails
):
    stored = make_tenant(room, activated=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_USED")


def test_used_wins_over_expired(client, database, tenant, sent_emails):
    edit_invitation(
        database,
        tenant.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(activate(client, tenant.token), 409, "INVITATION_USED")


def test_a_replaced_link_is_refused_and_the_new_link_works(
    client, database, tenant, sent_emails
):
    from app.services.invitations import create_invitation

    with Session(database) as db:
        _, new_token = create_invitation(db, tenant.id)
        db.commit()
    assert_error(activate(client, tenant.token), 409, "INVITATION_USED")
    assert sent_emails == []
    response = activate(client, new_token)
    assert response.status_code == 201, response.text
    assert preview_status(client, new_token) == "used"
    assert preview_status(client, tenant.token) == "used"


def test_an_expired_link_can_be_replaced_and_then_activates(
    client, database, room, make_tenant, sent_emails
):
    from app.services.invitations import create_invitation

    stored = make_tenant(room, contacts=STORED_CONTACTS, expired=True)
    with Session(database) as db:
        _, new_token = create_invitation(db, stored.id)
        db.commit()
    assert activate(client, new_token).status_code == 201


def test_the_link_is_checked_before_the_email_is_required(
    client, database, tenant, sent_emails
):
    assert_error(
        activate_without(client, "unknown-token", "email"),
        404,
        "INVITATION_NOT_FOUND",
    )
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    assert_error(
        activate_without(client, tenant.token, "email"), 409, "INVITATION_USED"
    )


def test_an_expired_link_is_reported_before_a_taken_email(
    client, database, room, make_tenant, make_user, sent_emails
):
    make_user(email=EMAIL)
    stored = make_tenant(room, expired=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_EXPIRED")


def test_a_used_link_is_reported_before_a_weak_password(
    client, database, tenant, sent_emails
):
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    response = activate(client, tenant.token, password="password123")
    assert_error(response, 409, "INVITATION_USED")


def test_validation_is_reported_before_the_link_lookup(client, database, sent_emails):
    response = activate(client, "unknown-token", password="short")
    assert_error(response, 422, "VALIDATION_FAILED", "password")


# Email


@pytest.mark.parametrize("missing", ["omitted", "null"])
def test_an_email_is_required(client, database, tenant, sent_emails, missing):
    before = snapshot(database, tenant)
    if missing == "omitted":
        response = activate_without(client, tenant.token, "email")
    else:
        response = activate(client, tenant.token, email=None)
    assert_error(response, 422, "VALIDATION_FAILED", "email")
    assert_unchanged(database, tenant, before, sent_emails)


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", ""])
def test_an_invalid_email_is_a_validation_failure(
    client, database, tenant, sent_emails, email
):
    response = activate(client, tenant.token, email=email)
    assert_error(response, 422, "VALIDATION_FAILED", "email")


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_an_email_of_any_existing_account_is_refused(
    client, database, tenant, make_user, sent_emails, role
):
    from app.schemas.auth import UserRole

    make_user(email=EMAIL, role=UserRole(role))
    before = snapshot(database, tenant)
    response = activate(client, tenant.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert_unchanged(database, tenant, before, sent_emails)
    assert preview_status(client, tenant.token) == "valid"


@pytest.mark.parametrize(
    "submitted",
    [EMAIL.upper(), "Dewi.New@Example.com", f"  {EMAIL}", f"{EMAIL}  "],
)
def test_the_email_comparison_ignores_case_and_surrounding_spaces(
    client, database, tenant, make_user, sent_emails, submitted
):
    make_user(email=EMAIL)
    response = activate(client, tenant.token, email=submitted)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_an_email_of_an_unverified_account_is_still_taken(
    client, database, tenant, make_user, sent_emails
):
    make_user(email=EMAIL, email_verified=False)
    response = activate(client, tenant.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_two_tenants_cannot_use_the_same_email(
    client, database, tenant, room, make_room, make_tenant, sent_emails
):
    other_room = make_room(_property_of(database, room), number="A2")
    other = make_tenant(other_room, name="Other Tenant", contacts=STORED_CONTACTS)
    assert activate(client, tenant.token).status_code == 201
    before = snapshot(database, other)
    sent_emails.clear()
    response = activate(client, other.token, email=EMAIL.upper())
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert snapshot(database, other) == before
    assert sent_emails == []


def test_a_registered_owner_email_is_taken(
    client, database, tenant, register_owner, sent_emails
):
    assert register_owner(email=EMAIL).status_code == 201
    sent_emails.clear()
    response = activate(client, tenant.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


# Password


@pytest.mark.parametrize("length", [8, 64, 128])
def test_passwords_of_8_to_128_characters_are_accepted(
    client, database, tenant, sent_emails, length
):
    password = ("T7#vq9-lorem-ipsum-" * 10)[:length]
    assert activate(client, tenant.token, password=password).status_code == 201


def test_a_128_character_multibyte_password_is_accepted(
    client, database, tenant, sent_emails
):
    assert activate(client, tenant.token, password="é" * 127 + "x").status_code == 201


@pytest.mark.parametrize("length", [0, 7, 129, 200])
def test_passwords_outside_8_to_128_characters_are_a_validation_failure(
    client, database, tenant, sent_emails, length
):
    before = snapshot(database, tenant)
    response = activate(client, tenant.token, password="a" * length)
    assert_error(response, 422, "VALIDATION_FAILED", "password")
    assert_unchanged(database, tenant, before, sent_emails)


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
    client, database, tenant, sent_emails, password
):
    before = snapshot(database, tenant)
    response = activate(client, tenant.token, password=password)
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")
    assert_unchanged(database, tenant, before, sent_emails)
    assert preview_status(client, tenant.token) == "valid"


def test_a_password_containing_the_submitted_email_local_part_is_refused(
    client, database, tenant, sent_emails
):
    response = activate(
        client, tenant.token, email="budi.s@example.com", password="T7#vq9-Budi.S-x"
    )
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def test_the_email_local_part_is_checked_after_normalization(
    client, database, tenant, sent_emails
):
    response = activate(
        client,
        tenant.token,
        email="  Budi.S@Example.COM ",
        password="T7#vq9-budi.s-x",
    )
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def test_a_password_containing_the_submitted_name_is_refused(
    client, database, tenant, sent_emails
):
    response = activate(
        client, tenant.token, name="Dewi Lestari", password="T7#vq9-dewi lestari-x"
    )
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "password")


def test_a_password_containing_the_name_management_entered_is_accepted_when_renamed(
    client, database, tenant, sent_emails
):
    response = activate(
        client, tenant.token, name="Dewi Lestari", password="T7#vq9-budi tenant-x"
    )
    assert response.status_code == 201, response.text


def test_a_short_name_or_local_part_inside_the_password_is_accepted(
    client, database, tenant, sent_emails
):
    response = activate(
        client,
        tenant.token,
        name="Ann",
        email="abc@example.com",
        password="T7#vq9-ann-abc-ipsum",
    )
    assert response.status_code == 201, response.text


# Other validation


def test_a_missing_device_is_a_validation_failure(
    client, database, tenant, sent_emails
):
    before = snapshot(database, tenant)
    response = activate_without(client, tenant.token, "device")
    assert_error(response, 422, "VALIDATION_FAILED", "device")
    assert_unchanged(database, tenant, before, sent_emails)


@pytest.mark.parametrize("platform", ["a", "p" * 50])
def test_a_device_platform_of_1_to_50_characters_is_accepted(
    client, database, tenant, sent_emails, platform
):
    device = {**DEVICE, "platform": platform}
    assert activate(client, tenant.token, device=device).status_code == 201


@pytest.mark.parametrize("platform", ["", "p" * 51])
def test_a_device_platform_outside_1_to_50_characters_is_refused(
    client, database, tenant, sent_emails, platform
):
    device = {**DEVICE, "platform": platform}
    response = activate(client, tenant.token, device=device)
    assert_error(response, 422, "VALIDATION_FAILED", "device.platform")


@pytest.mark.parametrize("name", ["", "   ", "n" * 101])
def test_a_blank_or_overlong_name_is_a_validation_failure(
    client, database, tenant, sent_emails, name
):
    response = activate(client, tenant.token, name=name)
    assert_error(response, 422, "VALIDATION_FAILED", "name")


def test_an_empty_token_is_a_validation_failure(client, database, sent_emails):
    assert_error(activate(client, ""), 422, "VALIDATION_FAILED", "token")


# Atomicity


def test_nothing_is_saved_when_sending_the_email_fails(
    app, database, tenant, sent_emails, monkeypatch
):
    from app.email import get_email_sender

    class BrokenSender:
        def send_verification_code(self, to: str, code: str) -> None:
            raise RuntimeError("mail server down")

    before = snapshot(database, tenant)
    monkeypatch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
    failing = TestClient(app, raise_server_exceptions=False)
    response = failing.post(ACTIVATION_URL, json=body_for(tenant.token))
    assert response.status_code == 500
    assert snapshot(database, tenant) == before


def test_the_link_still_works_after_a_failed_email_send(
    app, client, database, tenant, sent_emails, monkeypatch
):
    from app.email import get_email_sender

    class BrokenSender:
        def send_verification_code(self, to: str, code: str) -> None:
            raise RuntimeError("mail server down")

    with monkeypatch.context() as patch:
        patch.setitem(app.dependency_overrides, get_email_sender, BrokenSender)
        failing = TestClient(app, raise_server_exceptions=False)
        failing.post(ACTIVATION_URL, json=body_for(tenant.token))
    response = activate(client, tenant.token)
    assert response.status_code == 201, response.text
    assert len(sent_emails) == 1


def test_a_failed_activation_does_not_store_contacts(
    client, database, bare_tenant, sent_emails
):
    activate(client, bare_tenant.token, emergencyContacts=CONTACTS, password="12345678")
    assert stored_contacts(database, bare_tenant.id) == []
    assert preview_status(client, bare_tenant.token) == "valid"
