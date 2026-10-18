"""Previewing a tenant invitation link."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

PREVIEW_URL = "/invitations/previews"
PREVIEW_FIELDS = {
    "status",
    "role",
    "inviterName",
    "properties",
    "roomNumber",
    "expiresAt",
    "name",
    "emergencyContactsRequired",
}
STORED_CONTACTS = [
    ("Siti", "Ibu", "081234567890"),
    ("Agus", "Kakak", "08571234567"),
]


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def edit_invitation(database, token: str, **columns) -> None:
    from app.models import Invitation

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with Session(database) as db:
        row = db.scalars(
            select(Invitation).where(Invitation.token_hash == token_hash)
        ).one()
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def preview(client, token: str, **kwargs):
    return client.post(PREVIEW_URL, json={"token": token}, **kwargs)


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def room(owner, make_property, make_room):
    prop = make_property(owner, name="Kos Melati", address="Jl. Melati 5")
    return make_room(prop, number="A1")


@pytest.fixture
def tenant(room, make_tenant):
    return make_tenant(room, name="Budi Tenant", contacts=STORED_CONTACTS)


# Success


def test_preview_of_a_valid_link_describes_the_invitation(client, database, tenant):
    response = preview(client, tenant.token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PREVIEW_FIELDS
    assert body["status"] == "valid"
    assert body["role"] == "tenant"
    assert body["inviterName"] == "Rina Owner"
    assert body["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]
    assert body["roomNumber"] == "A1"
    assert body["name"] == "Budi Tenant"
    assert body["emergencyContactsRequired"] is False


def test_preview_expires_at_is_the_invitation_expiry(client, database, tenant):
    body = preview(client, tenant.token).json()
    assert parse_time(body["expiresAt"]) == tenant.invitation.expires_at
    assert parse_time(body["expiresAt"]) - datetime.now(UTC) > timedelta(days=6)


def test_preview_is_public_and_ignores_a_valid_bearer_token(
    client, database, tenant, make_user, sign_in
):
    headers = sign_in(make_user()).headers
    response = preview(client, tenant.token, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "valid"


def test_preview_ignores_a_bearer_token_of_an_unverified_account(
    client, database, tenant, make_user, sign_in
):
    headers = sign_in(make_user(email_verified=False)).headers
    assert preview(client, tenant.token, headers=headers).status_code == 200


def test_preview_ignores_an_invalid_bearer_token(client, database, tenant):
    headers = {"Authorization": "Bearer garbage"}
    assert preview(client, tenant.token, headers=headers).status_code == 200


def test_preview_changes_nothing_and_can_be_repeated(client, database, tenant):
    from app.models import Invitation, Tenant

    first = preview(client, tenant.token)
    second = preview(client, tenant.token)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with Session(database) as db:
        invitation = db.scalars(select(Invitation)).one()
        assert invitation.used_at is None
        assert invitation.invalidated_at is None
        assert db.get(Tenant, tenant.id).activated_at is None


def test_preview_names_the_owner_of_the_property_not_another_owner(
    client, database, make_user, make_property, make_room, make_tenant
):
    other_owner = make_user(name="Other Owner")
    make_room(make_property(other_owner, name="Elsewhere"), number="Z9")
    mine = make_user(name="Hadi Owner")
    room = make_room(make_property(mine, name="Kos Kenanga", address="Jl. K 1"), "B2")
    stored = make_tenant(room)
    body = preview(client, stored.token).json()
    assert body["inviterName"] == "Hadi Owner"
    assert body["properties"] == [{"name": "Kos Kenanga", "address": "Jl. K 1"}]
    assert body["roomNumber"] == "B2"


# Emergency contacts required


def test_preview_requires_emergency_contacts_when_none_are_stored(
    client, database, room, make_tenant
):
    stored = make_tenant(room)
    assert preview(client, stored.token).json()["emergencyContactsRequired"] is True


def test_preview_requires_emergency_contacts_when_only_one_is_stored(
    client, database, room, make_tenant
):
    stored = make_tenant(room, contacts=STORED_CONTACTS[:1])
    assert preview(client, stored.token).json()["emergencyContactsRequired"] is True


@pytest.mark.parametrize("count", [2, 3, 4])
def test_preview_does_not_require_emergency_contacts_when_two_or_more_are_stored(
    client, database, room, make_tenant, count
):
    contacts = [(f"C{n}", "Teman", f"08123456789{n}") for n in range(count)]
    stored = make_tenant(room, contacts=contacts)
    assert preview(client, stored.token).json()["emergencyContactsRequired"] is False


# Link states


def test_preview_of_an_expired_link_reports_expired_with_the_same_details(
    client, database, room, make_tenant
):
    stored = make_tenant(room, name="Budi Tenant", expired=True)
    body = preview(client, stored.token).json()
    assert body["status"] == "expired"
    assert body["role"] == "tenant"
    assert body["inviterName"] == "Rina Owner"
    assert body["roomNumber"] == "A1"
    assert body["name"] == "Budi Tenant"


def test_preview_of_a_link_about_to_expire_is_still_valid(client, database, tenant):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert preview(client, tenant.token).json()["status"] == "valid"


def test_preview_of_a_link_that_expired_a_moment_ago_is_expired(
    client, database, tenant
):
    edit_invitation(
        database, tenant.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert preview(client, tenant.token).json()["status"] == "expired"


def test_preview_of_a_used_link_reports_used(client, database, tenant):
    edit_invitation(database, tenant.token, used_at=datetime.now(UTC))
    body = preview(client, tenant.token).json()
    assert body["status"] == "used"
    assert body["name"] == "Budi Tenant"
    assert body["roomNumber"] == "A1"


def test_preview_of_an_invalidated_link_reports_used(client, database, tenant):
    edit_invitation(database, tenant.token, invalidated_at=datetime.now(UTC))
    assert preview(client, tenant.token).json()["status"] == "used"


def test_preview_of_a_link_of_an_activated_tenant_reports_used(
    client, database, room, make_tenant
):
    stored = make_tenant(room, activated=True)
    assert preview(client, stored.token).json()["status"] == "used"


def test_used_wins_over_expired(client, database, tenant):
    edit_invitation(
        database,
        tenant.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert preview(client, tenant.token).json()["status"] == "used"


def test_an_invalidated_expired_link_reports_used(client, database, room, make_tenant):
    stored = make_tenant(room, expired=True)
    edit_invitation(database, stored.token, invalidated_at=datetime.now(UTC))
    assert preview(client, stored.token).json()["status"] == "used"


def test_a_regenerated_link_makes_the_old_one_used_and_the_new_one_valid(
    client, database, tenant
):
    from app.services.invitations import create_invitation

    with Session(database) as db:
        _, new_token = create_invitation(db, tenant.id)
        db.commit()
    assert preview(client, tenant.token).json()["status"] == "used"
    new = preview(client, new_token)
    assert new.status_code == 200
    assert new.json()["status"] == "valid"
    assert new.json()["name"] == "Budi Tenant"


def test_preview_of_a_regenerated_link_shows_the_new_expiry(client, database, tenant):
    from app.services.invitations import create_invitation

    with Session(database) as db:
        row, new_token = create_invitation(db, tenant.id)
        expires_at = row.expires_at
        db.commit()
    body = preview(client, new_token).json()
    assert parse_time(body["expiresAt"]) == expires_at


# Not found


def test_preview_of_an_unknown_token_is_not_found(client, database, tenant):
    assert_error(preview(client, "unknown-token"), 404, "INVITATION_NOT_FOUND")


def test_preview_does_not_match_the_stored_hash_as_a_token(client, database, tenant):
    assert_error(
        preview(client, tenant.invitation.token_hash), 404, "INVITATION_NOT_FOUND"
    )


def test_preview_of_a_token_with_changed_case_is_not_found(client, database, tenant):
    assert_error(preview(client, tenant.token.swapcase()), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_deleted_tenants_link_is_not_found(
    client, database, room, make_tenant
):
    stored = make_tenant(room, deleted=True)
    assert_error(preview(client, stored.token), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_deleted_tenants_expired_link_is_not_found(
    client, database, room, make_tenant
):
    stored = make_tenant(room, deleted=True, expired=True)
    assert_error(preview(client, stored.token), 404, "INVITATION_NOT_FOUND")


# Validation


def test_preview_with_an_empty_token_is_a_validation_failure(client, database):
    assert_error(preview(client, ""), 422, "VALIDATION_FAILED", "token")


def test_preview_without_a_token_is_a_validation_failure(client, database):
    response = client.post(PREVIEW_URL, json={})
    assert_error(response, 422, "VALIDATION_FAILED", "token")
