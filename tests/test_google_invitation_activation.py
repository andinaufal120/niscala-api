"""Activating a Tenant or a Manager account through an invitation link with Google."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from google_support import (
    ACTIVATION_URL,
    ANY_FIELD,
    DEVICE,
    ME_URL,
    SESSIONS_URL,
    assert_error,
    bearer,
    count_rows,
    login,
    make_google_user,
    sha256,
    snapshot,
    stored_user,
    user_by_subject,
)
from manager_invitation_support import (
    assignments_of,
    edit_invitation,
    preview_status,
    stored_record,
)
from manager_support import get_manager, list_managers
from notification_support import (
    assert_item,
    items,
    only,
    property_ref,
    role,
    room_ref,
    stored_for,
    stored_rows,
    tenant_ref,
    types,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from user_account_support import sessions_of

ID_TOKEN = "dewi-token"
SUBJECT = "sub-dewi"
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


def activate(client, token: str, id_token: str = ID_TOKEN, **overrides):
    body = {
        "token": token,
        "name": NAME,
        "idToken": id_token,
        "device": DEVICE,
        **overrides,
    }
    return client.post(ACTIVATION_URL, json=body)


def activate_without(client, token: str, *keys: str):
    body = {
        "token": token,
        "name": NAME,
        "idToken": ID_TOKEN,
        "device": DEVICE,
    }
    return client.post(
        ACTIVATION_URL, json={k: v for k, v in body.items() if k not in keys}
    )


def stored_contacts(database, tenant_id) -> list:
    from app.models import EmergencyContact

    with Session(database, expire_on_commit=False) as db:
        rows = db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.tenant_id == tenant_id)
            .order_by(EmergencyContact.position)
        )
        return list(rows)


def tenant_state(database, stored) -> dict:
    """Everything a refused Tenant activation must leave untouched."""
    from app.models import Tenant

    with Session(database) as db:
        activated_at = db.get(Tenant, stored.id).activated_at
    contacts = [
        (c.name, c.relationship, c.phone) for c in stored_contacts(database, stored.id)
    ]
    return {**snapshot(database), "activated_at": activated_at, "contacts": contacts}


def manager_state(database, stored) -> dict:
    """Everything a refused Manager activation must leave untouched."""
    return {
        **snapshot(database),
        "activated_at": stored_record(database, stored.id).activated_at,
        "assignments": assignments_of(database, stored.user_id),
    }


@pytest.fixture
def world(make_user, make_property, make_room, assign_manager, sign_in):
    """An owner with two properties, a room and an assigned manager, both signed in."""
    owner = make_user(name="Rina Owner")
    colleague = make_user(name="Mira Manager", role=role("manager"))
    melati = make_property(owner, name="Kos Melati", address="Jl. Melati 5")
    anggrek = make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")
    assign_manager(colleague, melati)
    return SimpleNamespace(
        owner=owner,
        colleague=colleague,
        prop=melati,
        other_prop=anggrek,
        room=make_room(melati, number="A1"),
        owner_in=sign_in(owner),
        colleague_in=sign_in(colleague),
    )


@pytest.fixture
def identity(google):
    return google.add(ID_TOKEN, subject=SUBJECT, email=EMAIL, name="Token Name")


@pytest.fixture
def tenant(world, make_tenant):
    """A Tenant whose emergency contacts management already stored."""
    return make_tenant(world.room, name="Budi Tenant", contacts=STORED_CONTACTS)


@pytest.fixture
def bare_tenant(world, make_tenant):
    """A Tenant without stored emergency contacts."""
    return make_tenant(world.room, name="Budi Tenant")


@pytest.fixture
def manager(world, make_manager):
    return make_manager(
        world.owner,
        [world.prop, world.other_prop],
        name="Dewi Manager",
        nickname="Bu Dewi",
        phone="081298765432",
    )


# Tenant: success


def test_tenant_activation_answers_with_a_session_for_the_tenant_account(
    client, database, identity, tenant, mailbox
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
        "emailVerified": True,
        "hasPassword": False,
        "googleEmail": EMAIL,
    }


def test_tenant_activation_completes_the_existing_account_instead_of_creating_one(
    client, database, identity, tenant, mailbox
):
    from app.models import Tenant, UserAccount

    users = count_rows(database, UserAccount)
    assert activate(client, tenant.token).status_code == 201
    assert count_rows(database, UserAccount) == users
    assert count_rows(database, Tenant) == 1


def test_tenant_activation_stores_a_verified_google_account_without_a_password(
    client, database, identity, tenant, mailbox
):
    from app.schemas.auth import UserRole

    activate(client, tenant.token)
    user = stored_user(database, tenant.id)
    assert user.name == NAME
    assert user.email == EMAIL
    assert user.role == UserRole.TENANT
    assert user.email_verified is True
    assert user.password_hash is None
    assert user.google_subject == SUBJECT
    assert user.google_email == EMAIL
    assert user.status == "active"


def test_the_email_comes_from_the_token_and_never_from_the_request(
    client, database, identity, tenant, mailbox
):
    response = activate(client, tenant.token, email="other@example.com")
    assert response.status_code == 201, response.text
    assert response.json()["account"]["email"] == EMAIL
    assert stored_user(database, tenant.id).email == EMAIL


def test_the_token_email_is_lowercased(client, database, google, tenant, mailbox):
    google.add("mixed", subject="sub-mixed", email="Dewi.New@Example.COM")
    response = activate(client, tenant.token, "mixed")
    assert response.json()["account"]["email"] == EMAIL
    assert stored_user(database, tenant.id).email == EMAIL


def test_the_name_of_the_request_replaces_the_invited_name_and_the_token_claim(
    client, database, identity, tenant, mailbox
):
    response = activate(client, tenant.token, name="  Dewi Lestari \n")
    assert response.json()["account"]["name"] == NAME
    assert stored_user(database, tenant.id).name == NAME


def test_activation_can_keep_the_name_management_entered(
    client, database, identity, tenant, mailbox
):
    response = activate(client, tenant.token, name="Budi Tenant")
    assert response.status_code == 201
    assert stored_user(database, tenant.id).name == "Budi Tenant"


def test_activation_accepts_a_unicode_name(client, database, identity, tenant, mailbox):
    name = "Dewi Šandra 山田 Ñandú"
    response = activate(client, tenant.token, name=name)
    assert response.json()["account"]["name"] == name


def test_tenant_activation_marks_the_tenant_activated_and_the_link_used(
    client, database, identity, tenant, mailbox
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


def test_tenant_activation_starts_a_google_session_on_the_given_device(
    client, database, identity, tenant, mailbox
):
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = activate(client, tenant.token, device=device).json()
    (session,) = sessions_of(database, tenant.id)
    assert session.login_method == LoginMethod.GOOGLE
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.revoked_at is None
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_tenant_activation_session_is_listed_with_the_google_login_method(
    client, database, identity, tenant, mailbox
):
    body = activate(client, tenant.token).json()
    (item,) = client.get(SESSIONS_URL, headers=bearer(body)).json()["items"]
    assert item["loginMethod"] == "google"
    assert item["isCurrent"] is True


def test_tenant_activation_tokens_work_on_the_account_endpoint(
    client, database, identity, tenant, mailbox
):
    body = activate(client, tenant.token).json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_tenant_activation_refresh_token_can_be_refreshed(
    client, database, identity, tenant, mailbox
):
    body = activate(client, tenant.token).json()
    response = client.post("/auth/refresh", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200


def test_the_activated_tenant_can_use_verified_only_endpoints_at_once(
    client, database, identity, tenant, mailbox
):
    body = activate(client, tenant.token).json()
    assert client.get("/me/leases", headers=bearer(body)).status_code == 200


def test_tenant_activation_sends_and_stores_no_verification_code(
    client, database, identity, tenant, mailbox
):
    from app.models import EmailVerificationCode

    assert activate(client, tenant.token).status_code == 201
    assert mailbox.is_empty
    assert count_rows(database, EmailVerificationCode) == 0


def test_tenant_activation_hands_the_given_token_to_the_verifier(
    client, database, identity, tenant, mailbox, google
):
    activate(client, tenant.token)
    assert google.verified == [ID_TOKEN]


def test_tenant_activation_is_public_and_ignores_a_valid_bearer_token(
    client, database, identity, tenant, mailbox, make_user, sign_in
):
    headers = sign_in(make_user(email="stranger@example.com")).headers
    body = {"token": tenant.token, "name": NAME, "idToken": ID_TOKEN, "device": DEVICE}
    response = client.post(ACTIVATION_URL, json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["id"] == str(tenant.id)


def test_tenant_activation_ignores_an_invalid_bearer_token(
    client, database, identity, tenant, mailbox
):
    body = {"token": tenant.token, "name": NAME, "idToken": ID_TOKEN, "device": DEVICE}
    response = client.post(
        ACTIVATION_URL, json=body, headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 201, response.text


# Tenant: after activation


def test_the_owner_sees_the_tenant_as_active_with_the_email_and_no_invitation(
    client, database, identity, tenant, world, mailbox
):
    activate(client, tenant.token)
    response = client.get(f"/tenants/{tenant.id}", headers=world.owner_in.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accountStatus"] == "active"
    assert body["email"] == EMAIL
    assert body["name"] == NAME
    assert body["invitation"] is None


def test_activation_leaves_the_room_and_lease_unchanged(
    client, database, identity, tenant, world, mailbox
):
    url = f"/tenants/{tenant.id}"
    before = client.get(url, headers=world.owner_in.headers).json()
    assert activate(client, tenant.token).status_code == 201
    after = client.get(url, headers=world.owner_in.headers).json()
    assert after["room"] == before["room"]
    assert after["lease"] == before["lease"]
    assert after["phone"] == before["phone"]


def test_the_used_link_previews_as_used(client, database, identity, tenant, mailbox):
    activate(client, tenant.token)
    assert preview_status(client, tenant.token) == "used"


def test_activating_again_with_the_same_link_is_refused(
    client, database, google, identity, tenant, mailbox
):
    assert activate(client, tenant.token).status_code == 201
    google.add("second", subject="sub-second", email="second@example.com")
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token, "second")
    assert_error(response, 409, "INVITATION_USED")
    assert tenant_state(database, tenant) == before


def test_the_tenant_can_log_in_with_google_afterwards(
    client, database, identity, tenant, mailbox
):
    activate(client, tenant.token)
    response = login(client, ID_TOKEN)
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(tenant.id)
    assert response.json()["account"]["role"] == "tenant"


def test_the_tenant_cannot_log_in_with_a_password(
    client, database, identity, tenant, mailbox
):
    from google_support import password_login

    activate(client, tenant.token)
    assert_error(
        password_login(client, EMAIL, "any password"), 401, "INVALID_CREDENTIALS"
    )


def test_activating_one_tenant_does_not_touch_another_tenants_link(
    client, database, identity, world, tenant, make_room, make_tenant, mailbox
):
    other = make_tenant(make_room(world.prop, number="A2"), name="Other Tenant")
    activate(client, tenant.token)
    assert preview_status(client, other.token) == "valid"


# Tenant: emergency contacts


def test_contacts_are_required_when_none_are_stored(
    client, database, identity, bare_tenant, mailbox
):
    before = tenant_state(database, bare_tenant)
    response = activate(client, bare_tenant.token)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert tenant_state(database, bare_tenant) == before
    assert preview_status(client, bare_tenant.token) == "valid"


def test_null_contacts_are_refused_when_they_are_required(
    client, database, identity, bare_tenant, mailbox
):
    response = activate(client, bare_tenant.token, emergencyContacts=None)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")


def test_a_single_contact_is_refused(client, database, identity, bare_tenant, mailbox):
    response = activate(client, bare_tenant.token, emergencyContacts=CONTACTS[:1])
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")


def test_five_contacts_are_refused(client, database, identity, bare_tenant, mailbox):
    response = activate(client, bare_tenant.token, emergencyContacts=CONTACTS * 3)
    assert_error(response, 422, "VALIDATION_FAILED", "emergencyContacts")


@pytest.mark.parametrize("count", [2, 3, 4])
def test_two_to_four_contacts_are_stored_in_submitted_order(
    client, database, identity, bare_tenant, mailbox, count
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
    client, database, identity, bare_tenant, mailbox
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
    client, database, identity, bare_tenant, world, mailbox
):
    activate(client, bare_tenant.token, emergencyContacts=CONTACTS)
    body = client.get(
        f"/tenants/{bare_tenant.id}", headers=world.owner_in.headers
    ).json()
    assert body["emergencyContacts"] == [
        {"name": "Rudi", "relationship": "Ayah", "phone": "081111111111"},
        {"name": "Wati", "relationship": "Adik", "phone": "08222222222"},
    ]


@pytest.mark.parametrize("field", ["name", "relationship"])
@pytest.mark.parametrize("index", [0, 1])
def test_a_blank_contact_text_is_refused_and_nothing_is_saved(
    client, database, identity, bare_tenant, mailbox, field, index
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index][field] = "   "
    before = tenant_state(database, bare_tenant)
    response = activate(client, bare_tenant.token, emergencyContacts=contacts)
    assert_error(
        response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.{field}"
    )
    assert tenant_state(database, bare_tenant) == before


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("phone", ["+628123456789", "12345", "abc", "0712345678"])
def test_an_invalid_contact_phone_is_refused_and_nothing_is_saved(
    client, database, identity, bare_tenant, mailbox, index, phone
):
    contacts = [dict(c) for c in CONTACTS]
    contacts[index]["phone"] = phone
    before = tenant_state(database, bare_tenant)
    response = activate(client, bare_tenant.token, emergencyContacts=contacts)
    assert_error(response, 422, "VALIDATION_FAILED", f"emergencyContacts.{index}.phone")
    assert tenant_state(database, bare_tenant) == before


def test_stored_contacts_are_kept_and_submitted_ones_ignored(
    client, database, identity, tenant, mailbox
):
    response = activate(client, tenant.token, emergencyContacts=CONTACTS)
    assert response.status_code == 201, response.text
    rows = stored_contacts(database, tenant.id)
    assert [(r.name, r.relationship, r.phone) for r in rows] == STORED_CONTACTS
    assert [r.position for r in rows] == [0, 1]


@pytest.mark.parametrize("sent", ["omitted", "null"])
def test_activation_needs_no_contacts_when_management_stored_them(
    client, database, identity, tenant, mailbox, sent
):
    overrides = {} if sent == "omitted" else {"emergencyContacts": None}
    assert activate(client, tenant.token, **overrides).status_code == 201
    rows = stored_contacts(database, tenant.id)
    assert [(r.name, r.relationship, r.phone) for r in rows] == STORED_CONTACTS


def test_a_failed_activation_does_not_store_contacts(
    client, database, google, bare_tenant, mailbox
):
    activate(client, bare_tenant.token, "forged", emergencyContacts=CONTACTS)
    assert stored_contacts(database, bare_tenant.id) == []
    assert preview_status(client, bare_tenant.token) == "valid"


# Tenant: link states


def test_an_unknown_link_is_not_found_without_asking_the_verifier(
    client, database, google, identity, tenant, mailbox
):
    before = tenant_state(database, tenant)
    response = activate(client, "unknown-token")
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert google.verified == []
    assert tenant_state(database, tenant) == before


def test_a_deleted_tenants_link_is_not_found(
    client, database, google, identity, world, make_tenant, mailbox
):
    stored = make_tenant(world.room, deleted=True)
    assert_error(activate(client, stored.token), 404, "INVITATION_NOT_FOUND")
    assert google.verified == []


def test_an_expired_link_is_refused_and_nothing_is_saved(
    client, database, google, identity, world, make_tenant, mailbox
):
    stored = make_tenant(world.room, contacts=STORED_CONTACTS, expired=True)
    before = tenant_state(database, stored)
    assert_error(activate(client, stored.token), 409, "INVITATION_EXPIRED")
    assert google.verified == []
    assert tenant_state(database, stored) == before
    assert preview_status(client, stored.token) == "expired"


def test_a_link_that_expired_a_moment_ago_is_refused(
    client, database, identity, tenant, mailbox
):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert_error(activate(client, tenant.token), 409, "INVITATION_EXPIRED")


def test_a_link_about_to_expire_still_activates(
    client, database, identity, tenant, mailbox
):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert activate(client, tenant.token).status_code == 201


def test_a_used_link_is_refused(client, database, google, identity, tenant, mailbox):
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    before = tenant_state(database, tenant)
    assert_error(activate(client, tenant.token), 409, "INVITATION_USED")
    assert google.verified == []
    assert tenant_state(database, tenant) == before


def test_a_link_of_an_already_activated_tenant_is_refused(
    client, database, identity, world, make_tenant, mailbox
):
    stored = make_tenant(world.room, activated=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_USED")


def test_used_wins_over_expired(client, database, identity, tenant, mailbox):
    edit_invitation(
        database,
        tenant.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(activate(client, tenant.token), 409, "INVITATION_USED")


def test_a_replaced_link_is_refused_and_the_new_link_works(
    client, database, identity, tenant, mailbox
):
    from app.services.invitations import create_invitation

    with Session(database) as db:
        _, new_token = create_invitation(db, tenant.id)
        db.commit()
    assert_error(activate(client, tenant.token), 409, "INVITATION_USED")
    response = activate(client, new_token)
    assert response.status_code == 201, response.text
    assert preview_status(client, new_token) == "used"
    assert preview_status(client, tenant.token) == "used"


def test_the_link_is_checked_before_the_token_is_verified(
    client, database, google, identity, tenant, mailbox
):
    forged = "forged-token"
    assert_error(activate(client, "unknown-token", forged), 404, "INVITATION_NOT_FOUND")
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    assert_error(activate(client, tenant.token, forged), 409, "INVITATION_USED")
    edit_invitation(
        database,
        tenant.token,
        used_at=None,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(activate(client, tenant.token, forged), 409, "INVITATION_EXPIRED")
    assert google.verified == []


def test_validation_is_reported_before_the_link_lookup(
    client, database, google, identity, mailbox
):
    response = activate(client, "unknown-token", "")
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []


def test_a_missing_name_is_reported_before_the_link_lookup(
    client, database, identity, tenant, mailbox
):
    response = activate_without(client, "unknown-token", "name")
    assert_error(response, 422, "VALIDATION_FAILED", "name")


# Tenant: the Google token


def test_a_token_the_verifier_rejects_is_unauthorized(
    client, database, google, tenant, mailbox
):
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert tenant_state(database, tenant) == before
    assert preview_status(client, tenant.token) == "valid"
    assert mailbox.is_empty


def test_the_link_still_works_after_a_rejected_token(
    client, database, identity, tenant, mailbox
):
    assert activate(client, tenant.token, "forged-token").status_code == 401
    assert activate(client, tenant.token).status_code == 201


def test_an_unverified_google_email_is_refused(
    client, database, google, tenant, mailbox
):
    google.add("unverified", subject="sub-unv", email=EMAIL, email_verified=False)
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token, "unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert tenant_state(database, tenant) == before
    assert preview_status(client, tenant.token) == "valid"


def test_a_subject_linked_to_an_account_is_refused(
    client, database, identity, tenant, mailbox
):
    make_google_user(database, subject=SUBJECT, email="elsewhere@example.com")
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert tenant_state(database, tenant) == before
    assert preview_status(client, tenant.token) == "valid"


def test_one_google_identity_cannot_activate_two_tenants(
    client, database, google, identity, world, tenant, make_room, make_tenant, mailbox
):
    other = make_tenant(
        make_room(world.prop, number="A2"), name="Other", contacts=STORED_CONTACTS
    )
    assert activate(client, tenant.token).status_code == 201
    before = tenant_state(database, other)
    response = activate(client, other.token)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert tenant_state(database, other) == before
    assert preview_status(client, other.token) == "valid"


@pytest.mark.parametrize("who", ["owner", "manager", "tenant", "admin"])
def test_an_email_of_any_existing_account_is_refused(
    client, database, identity, tenant, make_user, mailbox, who
):
    from app.schemas.auth import UserRole

    make_user(email=EMAIL, role=UserRole(who))
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert tenant_state(database, tenant) == before
    assert preview_status(client, tenant.token) == "valid"


def test_an_email_of_a_deleted_account_is_still_taken(
    client, database, identity, tenant, make_user, mailbox
):
    make_user(email=EMAIL, deleted=True)
    assert_error(
        activate(client, tenant.token), 409, "EMAIL_ALREADY_REGISTERED", "email"
    )


@pytest.mark.parametrize(
    "submitted",
    [EMAIL.upper(), "Dewi.New@Example.com", f"  {EMAIL}", f"{EMAIL}  "],
)
def test_the_email_comparison_ignores_case_and_surrounding_spaces(
    client, database, google, tenant, make_user, mailbox, submitted
):
    make_user(email=EMAIL)
    google.add("spaced", subject="sub-spaced", email=submitted)
    response = activate(client, tenant.token, "spaced")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_two_tenants_cannot_use_the_same_email(
    client, database, google, identity, world, tenant, make_room, make_tenant, mailbox
):
    other = make_tenant(
        make_room(world.prop, number="A2"), name="Other", contacts=STORED_CONTACTS
    )
    google.add("second", subject="sub-second", email=EMAIL)
    assert activate(client, tenant.token).status_code == 201
    before = tenant_state(database, other)
    response = activate(client, other.token, "second")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert tenant_state(database, other) == before


def test_an_invalid_token_is_reported_before_missing_contacts(
    client, database, google, bare_tenant, mailbox
):
    response = activate(client, bare_tenant.token, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")


def test_an_unverified_email_is_reported_before_a_linked_subject(
    client, database, google, tenant, mailbox
):
    make_google_user(database, subject="sub-both", email="elsewhere@example.com")
    google.add("both", subject="sub-both", email_verified=False)
    response = activate(client, tenant.token, "both")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")


def test_an_unverified_email_is_reported_before_a_taken_email(
    client, database, google, tenant, make_user, mailbox
):
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL, email_verified=False)
    response = activate(client, tenant.token, "both")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")


def test_a_linked_subject_is_reported_before_a_taken_email(
    client, database, google, tenant, make_user, mailbox
):
    make_google_user(database, subject="sub-both", email="elsewhere@example.com")
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL)
    response = activate(client, tenant.token, "both")
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)


def test_a_taken_email_is_reported_before_missing_contacts(
    client, database, identity, bare_tenant, make_user, mailbox
):
    make_user(email=EMAIL)
    response = activate(client, bare_tenant.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


# Tenant: validation


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_id_token_is_a_validation_failure(
    client, database, google, tenant, mailbox, value
):
    before = tenant_state(database, tenant)
    response = activate(client, tenant.token, value)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []
    assert tenant_state(database, tenant) == before


@pytest.mark.parametrize("name", ["", "   ", "n" * 101])
def test_a_blank_or_overlong_name_is_a_validation_failure(
    client, database, identity, tenant, mailbox, name
):
    response = activate(client, tenant.token, name=name)
    assert_error(response, 422, "VALIDATION_FAILED", "name")


def test_a_missing_device_is_a_validation_failure(
    client, database, identity, tenant, mailbox
):
    response = activate_without(client, tenant.token, "device")
    assert_error(response, 422, "VALIDATION_FAILED", "device")


def test_an_empty_link_token_is_a_validation_failure(
    client, database, identity, mailbox
):
    assert_error(activate(client, ""), 422, "VALIDATION_FAILED", "token")


# Tenant: notifications


def test_a_tenant_activation_notifies_the_owner_and_the_assigned_manager(
    client, database, identity, world, tenant, mailbox
):
    assert activate(client, tenant.token, name="Budi Tenant").status_code == 201
    for recipient in (world.owner_in, world.colleague_in):
        item = only(client, recipient, "tenantActivated")
        assert_item(
            item,
            "tenantActivated",
            tenant=tenant_ref(tenant.user, "Budi Tenant"),
            room=room_ref(world.room),
            property=property_ref(world.prop),
        )
        assert types(client, recipient) == ["tenantActivated"]


def test_a_tenant_activation_does_not_notify_the_tenant(
    client, database, identity, world, tenant, mailbox
):
    activate(client, tenant.token, name="Budi Tenant")
    assert stored_for(database, tenant.user) == []


def test_a_tenant_activation_notifies_nobody_else(
    client, database, identity, world, tenant, mailbox, make_user, sign_in
):
    outsider = make_user(name="Outside Manager", role=role("manager"))
    stranger = make_user(name="Other Owner")
    activate(client, tenant.token, name="Budi Tenant")
    assert items(client, sign_in(outsider)) == []
    assert items(client, sign_in(stranger)) == []
    assert len(stored_rows(database)) == 2


@pytest.mark.parametrize(
    "case",
    [
        "unknown_link",
        "used_link",
        "expired_link",
        "forged_token",
        "unverified_email",
        "linked_subject",
        "taken_email",
    ],
)
def test_a_refused_tenant_activation_creates_no_notification(
    client, database, google, identity, world, tenant, make_user, mailbox, case
):
    link, id_token = tenant.token, ID_TOKEN
    if case == "unknown_link":
        link = "unknown-token"
    elif case == "used_link":
        edit_invitation(database, link, used_at=datetime.now(UTC))
    elif case == "expired_link":
        edit_invitation(
            database, link, expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    elif case == "forged_token":
        id_token = "forged-token"
    elif case == "unverified_email":
        google.add("unverified", subject="sub-unv", email=EMAIL, email_verified=False)
        id_token = "unverified"
    elif case == "linked_subject":
        make_google_user(database, subject=SUBJECT, email="elsewhere@example.com")
    else:
        make_user(email=EMAIL)
    response = activate(client, link, id_token, name="Budi Tenant")
    assert response.status_code >= 400
    assert stored_rows(database) == []


def test_replaying_a_tenant_activation_creates_no_second_notification(
    client, database, identity, world, tenant, mailbox
):
    activate(client, tenant.token, name="Budi Tenant")
    assert activate(client, tenant.token, name="Budi Tenant").status_code == 409
    assert len(stored_for(database, world.owner)) == 1


# Manager: success


def test_manager_activation_answers_with_a_session_for_the_manager_account(
    client, database, identity, manager, mailbox
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
    assert body["account"] == {
        "id": str(manager.user_id),
        "name": NAME,
        "email": EMAIL,
        "role": "manager",
        "emailVerified": True,
        "hasPassword": False,
        "googleEmail": EMAIL,
    }


def test_manager_activation_completes_the_existing_account_instead_of_creating_one(
    client, database, identity, manager, mailbox
):
    from app.models import Manager, UserAccount

    users = count_rows(database, UserAccount)
    assert activate(client, manager.token).status_code == 201
    assert count_rows(database, UserAccount) == users
    assert count_rows(database, Manager) == 1


def test_manager_activation_stores_a_verified_google_account_without_a_password(
    client, database, identity, manager, mailbox
):
    from app.schemas.auth import UserRole

    activate(client, manager.token)
    user = stored_user(database, manager.user_id)
    assert user.name == NAME
    assert user.email == EMAIL
    assert user.role == UserRole.MANAGER
    assert user.email_verified is True
    assert user.password_hash is None
    assert user.google_subject == SUBJECT
    assert user.google_email == EMAIL
    assert user.status == "active"


def test_the_manager_name_of_the_request_replaces_the_invited_name(
    client, database, identity, manager, mailbox
):
    response = activate(client, manager.token, name="  Dewi Lestari \n")
    assert response.json()["account"]["name"] == NAME
    assert stored_user(database, manager.user_id).name == NAME


def test_the_manager_email_comes_from_the_token_and_never_from_the_request(
    client, database, identity, manager, mailbox
):
    response = activate(client, manager.token, email="other@example.com")
    assert response.status_code == 201, response.text
    assert stored_user(database, manager.user_id).email == EMAIL


def test_manager_activation_marks_the_record_activated_and_the_link_used(
    client, database, identity, manager, mailbox
):
    from manager_support import fetch_all

    from app.models import Invitation

    before = datetime.now(UTC)
    activate(client, manager.token)
    record = stored_record(database, manager.id)
    (invitation,) = fetch_all(database, Invitation)
    assert before - timedelta(seconds=5) <= record.activated_at <= datetime.now(UTC)
    assert before - timedelta(seconds=5) <= invitation.used_at <= datetime.now(UTC)
    assert invitation.invalidated_at is None
    assert record.deleted_at is None


def test_manager_activation_keeps_the_nickname_phone_owner_and_assignments(
    client, database, identity, world, manager, mailbox
):
    assert activate(client, manager.token).status_code == 201
    record = stored_record(database, manager.id)
    assert record.owner_id == world.owner.id
    assert record.user_id == manager.user_id
    assert record.nickname == "Bu Dewi"
    assert record.phone == "081298765432"
    assert assignments_of(database, manager.user_id) == {
        world.prop.id,
        world.other_prop.id,
    }


def test_manager_activation_starts_a_google_session_on_the_given_device(
    client, database, identity, manager, mailbox
):
    from app.schemas.sessions import LoginMethod

    device = {"name": "Galaxy S24", "platform": "Android 15"}
    body = activate(client, manager.token, device=device).json()
    (session,) = sessions_of(database, manager.user_id)
    assert session.login_method == LoginMethod.GOOGLE
    assert session.device_name == "Galaxy S24"
    assert session.platform == "Android 15"
    assert session.refresh_token_hash == sha256(body["refreshToken"])


def test_manager_activation_tokens_work_on_the_account_endpoint(
    client, database, identity, manager, mailbox
):
    body = activate(client, manager.token).json()
    response = client.get(ME_URL, headers=bearer(body))
    assert response.status_code == 200
    assert response.json() == body["account"]


def test_the_activated_manager_sees_the_assigned_properties_at_once(
    client, database, identity, world, manager, mailbox
):
    body = activate(client, manager.token).json()
    response = client.get("/properties", headers=bearer(body))
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["items"]} == {
        str(world.prop.id),
        str(world.other_prop.id),
    }


def test_manager_activation_sends_and_stores_no_verification_code(
    client, database, identity, manager, mailbox
):
    from app.models import EmailVerificationCode

    assert activate(client, manager.token).status_code == 201
    assert mailbox.is_empty
    assert count_rows(database, EmailVerificationCode) == 0


def test_the_owner_sees_the_manager_as_active_with_the_email_and_no_invitation(
    client, database, identity, world, manager, mailbox
):
    activate(client, manager.token)
    response = get_manager(client, world.owner_in.headers, manager.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accountStatus"] == "active"
    assert body["email"] == EMAIL
    assert body["name"] == NAME
    assert body["nickname"] == "Bu Dewi"
    assert body["invitation"] is None
    listing = list_managers(client, world.owner_in.headers).json()["items"]
    assert [m["id"] for m in listing if m["accountStatus"] == "active"] == [
        str(manager.id)
    ]


def test_the_used_manager_link_previews_as_used(
    client, database, identity, manager, mailbox
):
    activate(client, manager.token)
    assert preview_status(client, manager.token) == "used"


def test_activating_a_manager_again_with_the_same_link_is_refused(
    client, database, google, identity, manager, mailbox
):
    assert activate(client, manager.token).status_code == 201
    google.add("second", subject="sub-second", email="second@example.com")
    before = manager_state(database, manager)
    assert_error(activate(client, manager.token, "second"), 409, "INVITATION_USED")
    assert manager_state(database, manager) == before


def test_the_manager_can_log_in_with_google_afterwards(
    client, database, identity, manager, mailbox
):
    activate(client, manager.token)
    response = login(client, ID_TOKEN)
    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == str(manager.user_id)
    assert response.json()["account"]["role"] == "manager"


def test_the_manager_cannot_log_in_with_a_password(
    client, database, identity, manager, mailbox
):
    from google_support import password_login

    activate(client, manager.token)
    assert_error(
        password_login(client, EMAIL, "any password"), 401, "INVALID_CREDENTIALS"
    )


# Manager: emergency contacts


def test_emergency_contacts_sent_for_a_manager_are_ignored(
    client, database, identity, manager, mailbox
):
    from app.models import EmergencyContact, Tenant

    response = activate(client, manager.token, emergencyContacts=CONTACTS)
    assert response.status_code == 201, response.text
    assert count_rows(database, EmergencyContact) == 0
    assert count_rows(database, Tenant) == 0


@pytest.mark.parametrize("sent", ["omitted", "null"])
def test_a_manager_activates_without_emergency_contacts(
    client, database, identity, manager, mailbox, sent
):
    overrides = {} if sent == "omitted" else {"emergencyContacts": None}
    assert activate(client, manager.token, **overrides).status_code == 201


# Manager: link states and token checks


def test_an_unknown_manager_link_is_not_found_without_asking_the_verifier(
    client, database, google, identity, manager, mailbox
):
    before = manager_state(database, manager)
    assert_error(activate(client, "unknown-token"), 404, "INVITATION_NOT_FOUND")
    assert google.verified == []
    assert manager_state(database, manager) == before


def test_a_deleted_managers_link_is_not_found(
    client, database, identity, world, make_manager, mailbox
):
    stored = make_manager(world.owner, [world.prop], deleted=True)
    assert_error(activate(client, stored.token), 404, "INVITATION_NOT_FOUND")


def test_an_expired_manager_link_is_refused_and_nothing_is_saved(
    client, database, google, identity, world, make_manager, mailbox
):
    stored = make_manager(world.owner, [world.prop], expired=True)
    before = manager_state(database, stored)
    assert_error(activate(client, stored.token), 409, "INVITATION_EXPIRED")
    assert google.verified == []
    assert manager_state(database, stored) == before
    assert preview_status(client, stored.token) == "expired"


def test_a_used_manager_link_is_refused(
    client, database, google, identity, manager, mailbox
):
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    before = manager_state(database, manager)
    assert_error(activate(client, manager.token), 409, "INVITATION_USED")
    assert google.verified == []
    assert manager_state(database, manager) == before


def test_a_link_of_an_already_activated_manager_is_refused(
    client, database, identity, world, make_manager, mailbox
):
    stored = make_manager(world.owner, [world.prop], activated=True)
    assert_error(activate(client, stored.token), 409, "INVITATION_USED")


def test_used_wins_over_expired_for_a_manager_link(
    client, database, identity, manager, mailbox
):
    edit_invitation(
        database,
        manager.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(activate(client, manager.token), 409, "INVITATION_USED")


def test_a_manager_link_is_checked_before_the_token_is_verified(
    client, database, google, identity, manager, mailbox
):
    forged = "forged-token"
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    assert_error(activate(client, manager.token, forged), 409, "INVITATION_USED")
    assert google.verified == []


def test_a_rejected_manager_token_leaves_the_link_unused(
    client, database, google, manager, mailbox
):
    before = manager_state(database, manager)
    response = activate(client, manager.token, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert manager_state(database, manager) == before
    assert preview_status(client, manager.token) == "valid"


def test_an_unverified_google_email_is_refused_for_a_manager(
    client, database, google, manager, mailbox
):
    google.add("unverified", subject="sub-unv", email=EMAIL, email_verified=False)
    before = manager_state(database, manager)
    response = activate(client, manager.token, "unverified")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")
    assert manager_state(database, manager) == before


def test_a_subject_linked_to_an_account_is_refused_for_a_manager(
    client, database, identity, manager, mailbox
):
    make_google_user(database, subject=SUBJECT, email="elsewhere@example.com")
    before = manager_state(database, manager)
    response = activate(client, manager.token)
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)
    assert manager_state(database, manager) == before
    assert user_by_subject(database, SUBJECT).id != manager.user_id


@pytest.mark.parametrize("who", ["owner", "manager", "tenant", "admin"])
def test_an_email_of_any_existing_account_is_refused_for_a_manager(
    client, database, identity, manager, make_user, mailbox, who
):
    from app.schemas.auth import UserRole

    make_user(email=EMAIL, role=UserRole(who))
    before = manager_state(database, manager)
    response = activate(client, manager.token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert manager_state(database, manager) == before
    assert preview_status(client, manager.token) == "valid"


def test_the_email_of_another_activated_manager_is_taken(
    client, database, google, identity, world, manager, make_manager, mailbox
):
    other = make_manager(world.owner, [world.prop], name="Other Manager")
    google.add("second", subject="sub-second", email=EMAIL)
    assert activate(client, manager.token).status_code == 201
    before = manager_state(database, other)
    response = activate(client, other.token, "second")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert manager_state(database, other) == before


def test_the_unverified_email_is_reported_before_a_taken_email_for_a_manager(
    client, database, google, manager, make_user, mailbox
):
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL, email_verified=False)
    response = activate(client, manager.token, "both")
    assert_error(response, 422, "GOOGLE_EMAIL_UNVERIFIED", "idToken")


def test_a_linked_subject_is_reported_before_a_taken_email_for_a_manager(
    client, database, google, manager, make_user, mailbox
):
    make_google_user(database, subject="sub-both", email="elsewhere@example.com")
    make_user(email=EMAIL)
    google.add("both", subject="sub-both", email=EMAIL)
    response = activate(client, manager.token, "both")
    assert_error(response, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED", ANY_FIELD)


@pytest.mark.parametrize("value", ["", None, 5])
def test_an_unusable_id_token_is_a_validation_failure_for_a_manager(
    client, database, google, manager, mailbox, value
):
    response = activate(client, manager.token, value)
    assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert google.verified == []


# Manager: notifications


def test_a_manager_activation_notifies_the_inviting_owner(
    client, database, identity, world, manager, mailbox
):
    assert activate(client, manager.token, name="Dewi Manager").status_code == 201
    item = only(client, world.owner_in, "managerActivated")
    assert_item(item, "managerActivated", actorName="Dewi Manager")
    assert types(client, world.owner_in) == ["managerActivated"]


def test_a_manager_activation_notification_has_no_property_room_or_tenant(
    client, database, identity, world, manager, mailbox
):
    activate(client, manager.token, name="Dewi Manager")
    item = only(client, world.owner_in, "managerActivated")
    for field in ("rentBill", "complaint", "tenant", "room", "property"):
        assert item[field] is None
    (row,) = stored_for(database, world.owner)
    assert row["property_id"] is None


def test_a_manager_activation_notifies_nobody_else(
    client, database, identity, world, manager, mailbox, make_user, sign_in
):
    stranger = sign_in(make_user(name="Other Owner"))
    activate(client, manager.token, name="Dewi Manager")
    assert stored_for(database, world.colleague) == []
    assert stored_for(database, manager.user) == []
    assert items(client, stranger) == []
    assert len(stored_rows(database)) == 1


@pytest.mark.parametrize(
    "case",
    [
        "unknown_link",
        "used_link",
        "expired_link",
        "forged_token",
        "unverified_email",
        "linked_subject",
        "taken_email",
    ],
)
def test_a_refused_manager_activation_creates_no_notification(
    client, database, google, identity, world, manager, make_user, mailbox, case
):
    link, id_token = manager.token, ID_TOKEN
    if case == "unknown_link":
        link = "unknown-token"
    elif case == "used_link":
        edit_invitation(database, link, used_at=datetime.now(UTC))
    elif case == "expired_link":
        edit_invitation(
            database, link, expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    elif case == "forged_token":
        id_token = "forged-token"
    elif case == "unverified_email":
        google.add("unverified", subject="sub-unv", email=EMAIL, email_verified=False)
        id_token = "unverified"
    elif case == "linked_subject":
        make_google_user(database, subject=SUBJECT, email="elsewhere@example.com")
    else:
        make_user(email=EMAIL)
    response = activate(client, link, id_token, name="Dewi Manager")
    assert response.status_code >= 400
    assert stored_rows(database) == []


def test_replaying_a_manager_activation_creates_no_second_notification(
    client, database, identity, world, manager, mailbox
):
    activate(client, manager.token, name="Dewi Manager")
    assert activate(client, manager.token, name="Dewi Manager").status_code == 409
    assert len(stored_for(database, world.owner)) == 1


# The link kind decides what the activation does


def test_a_tenant_link_activates_a_tenant_and_a_manager_link_a_manager(
    client, database, google, identity, tenant, manager, mailbox
):
    google.add("second", subject="sub-second", email="second@example.com")
    assert activate(client, tenant.token).json()["account"]["role"] == "tenant"
    assert activate(client, manager.token, "second").json()["account"]["role"] == (
        "manager"
    )
    assert user_by_subject(database, SUBJECT).id == tenant.id
    assert user_by_subject(database, "sub-second").id == manager.user_id
