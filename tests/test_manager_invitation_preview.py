"""Previewing a Manager invitation link."""

from datetime import UTC, datetime, timedelta

import pytest
from manager_invitation_support import (
    PREVIEW_FIELDS,
    edit_invitation,
    preview,
    rename_user,
)
from manager_support import (
    assert_error,
    parse_time,
    regenerate,
    remove_manager,
    token_of,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


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
    return make_manager(owner, [melati, anggrek], name="Mira Manager")


# Success


def test_preview_of_a_valid_link_describes_the_invitation(client, database, manager):
    response = preview(client, manager.token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PREVIEW_FIELDS
    assert body["status"] == "valid"
    assert body["role"] == "manager"
    assert body["inviterName"] == "Rina Owner"
    assert body["roomNumber"] is None
    assert body["name"] == "Mira Manager"
    assert body["emergencyContactsRequired"] is False


def test_preview_lists_the_assigned_properties_ordered_by_name(
    client, database, owner, melati, make_property, make_manager
):
    cempaka = make_property(owner, name="Kos Cempaka", address="Jl. Cempaka 1")
    anggrek = make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")
    stored = make_manager(owner, [melati, cempaka, anggrek])
    body = preview(client, stored.token).json()
    assert body["properties"] == [
        {"name": "Kos Anggrek", "address": "Jl. Anggrek 7"},
        {"name": "Kos Cempaka", "address": "Jl. Cempaka 1"},
        {"name": "Kos Melati", "address": "Jl. Melati 5"},
    ]


def test_preview_of_a_single_assigned_property_lists_only_it(
    client, database, owner, melati, make_property, make_manager
):
    make_property(owner, name="Kos Unassigned")
    stored = make_manager(owner, [melati])
    body = preview(client, stored.token).json()
    assert body["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]


def test_preview_leaves_out_deleted_properties(
    client, database, owner, melati, make_property, make_manager
):
    gone = make_property(owner, name="Kos Gone", deleted=True)
    stored = make_manager(owner, [melati, gone])
    body = preview(client, stored.token).json()
    assert [p["name"] for p in body["properties"]] == ["Kos Melati"]


def test_preview_lists_view_only_properties(
    client, database, owner, melati, make_property, make_manager
):
    frozen = make_property(owner, name="Kos Frozen", address="Jl. F 1", view_only=True)
    stored = make_manager(owner, [melati, frozen])
    body = preview(client, stored.token).json()
    assert [p["name"] for p in body["properties"]] == ["Kos Frozen", "Kos Melati"]


def test_preview_shows_only_the_properties_of_the_inviting_owner(
    client, database, owner, melati, make_user, make_property, make_manager
):
    other_owner = make_user(name="Dewi Owner")
    elsewhere = make_property(other_owner, name="Kos Elsewhere", address="Jl. E 9")
    first = make_manager(owner, [melati], name="Mira Manager")
    second = make_manager(other_owner, [elsewhere], user=first.user)
    mine = preview(client, first.token).json()
    theirs = preview(client, second.token).json()
    assert mine["inviterName"] == "Rina Owner"
    assert mine["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]
    assert theirs["inviterName"] == "Dewi Owner"
    assert theirs["properties"] == [{"name": "Kos Elsewhere", "address": "Jl. E 9"}]


def test_preview_expires_at_is_the_invitation_expiry(client, database, manager):
    body = preview(client, manager.token).json()
    assert parse_time(body["expiresAt"]) == manager.invitation.expires_at
    assert parse_time(body["expiresAt"]) - datetime.now(UTC) > timedelta(days=6)


def test_preview_name_is_the_current_name_of_the_account(client, database, manager):
    rename_user(database, manager.user_id, "Mira Renamed")
    assert preview(client, manager.token).json()["name"] == "Mira Renamed"


def test_preview_names_the_owner_who_issued_the_link(
    client, database, make_user, make_property, make_manager
):
    make_property(make_user(name="Other Owner"), name="Elsewhere")
    mine = make_user(name="Hadi Owner")
    stored = make_manager(mine, [make_property(mine, name="Kos Kenanga")])
    assert preview(client, stored.token).json()["inviterName"] == "Hadi Owner"


def test_preview_is_public_and_ignores_a_valid_bearer_token(
    client, database, manager, make_user, sign_in
):
    headers = sign_in(make_user()).headers
    response = preview(client, manager.token, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "valid"


def test_preview_ignores_a_bearer_token_of_an_unverified_account(
    client, database, manager, make_user, sign_in
):
    headers = sign_in(make_user(email_verified=False)).headers
    assert preview(client, manager.token, headers=headers).status_code == 200


def test_preview_ignores_an_invalid_bearer_token(client, database, manager):
    headers = {"Authorization": "Bearer garbage"}
    assert preview(client, manager.token, headers=headers).status_code == 200


def test_preview_changes_nothing_and_can_be_repeated(client, database, manager):
    from app.models import Invitation, Manager

    first = preview(client, manager.token)
    second = preview(client, manager.token)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with Session(database) as db:
        invitation = db.scalars(select(Invitation)).one()
        assert invitation.used_at is None
        assert invitation.invalidated_at is None
        assert db.get(Manager, manager.id).activated_at is None


def test_tenant_previews_keep_working_next_to_manager_previews(
    client, database, owner, melati, make_room, make_tenant, manager
):
    stored = make_tenant(make_room(melati, number="A1"), name="Budi Tenant")
    body = preview(client, stored.token).json()
    assert body["role"] == "tenant"
    assert body["roomNumber"] == "A1"
    assert body["name"] == "Budi Tenant"
    assert preview(client, manager.token).json()["role"] == "manager"


# Link states


def test_preview_of_an_expired_link_reports_expired_with_the_same_details(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], name="Mira Manager", expired=True)
    body = preview(client, stored.token).json()
    assert body["status"] == "expired"
    assert body["role"] == "manager"
    assert body["inviterName"] == "Rina Owner"
    assert body["name"] == "Mira Manager"
    assert body["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]


def test_preview_of_a_link_about_to_expire_is_still_valid(client, database, manager):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert preview(client, manager.token).json()["status"] == "valid"


def test_preview_of_a_link_that_expired_a_moment_ago_is_expired(
    client, database, manager
):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert preview(client, manager.token).json()["status"] == "expired"


def test_preview_of_a_used_link_reports_used(client, database, manager):
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    body = preview(client, manager.token).json()
    assert body["status"] == "used"
    assert body["name"] == "Mira Manager"
    assert [p["name"] for p in body["properties"]] == ["Kos Anggrek", "Kos Melati"]


def test_preview_of_an_invalidated_link_reports_used(client, database, manager):
    edit_invitation(database, manager.token, invalidated_at=datetime.now(UTC))
    assert preview(client, manager.token).json()["status"] == "used"


def test_preview_of_a_link_of_an_activated_manager_reports_used(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], activated=True)
    assert preview(client, stored.token).json()["status"] == "used"


def test_used_wins_over_expired(client, database, manager):
    edit_invitation(
        database,
        manager.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert preview(client, manager.token).json()["status"] == "used"


def test_an_invalidated_expired_link_reports_used(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], expired=True, invalidated=True)
    assert preview(client, stored.token).json()["status"] == "used"


def test_a_used_expired_link_reports_used(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], expired=True, used=True)
    assert preview(client, stored.token).json()["status"] == "used"


def test_a_regenerated_link_makes_the_old_one_used_and_the_new_one_valid(
    client, database, manager, signed_in
):
    response = regenerate(client, signed_in.headers, manager.id)
    assert response.status_code == 201, response.text
    new_token = token_of(response.json()["url"])
    assert preview(client, manager.token).json()["status"] == "used"
    new = preview(client, new_token)
    assert new.status_code == 200
    assert new.json()["status"] == "valid"
    assert new.json()["name"] == "Mira Manager"
    assert new.json()["role"] == "manager"


def test_preview_of_a_regenerated_link_shows_the_new_expiry(
    client, database, manager, signed_in
):
    body = regenerate(client, signed_in.headers, manager.id).json()
    new = preview(client, token_of(body["url"])).json()
    assert parse_time(new["expiresAt"]) == parse_time(body["expiresAt"])


def test_an_expired_link_renewed_by_the_owner_previews_as_valid(
    client, database, owner, melati, make_manager, signed_in
):
    stored = make_manager(owner, [melati], expired=True)
    body = regenerate(client, signed_in.headers, stored.id).json()
    assert preview(client, token_of(body["url"])).json()["status"] == "valid"
    assert preview(client, stored.token).json()["status"] == "used"


# Not found


def test_preview_of_an_unknown_token_is_not_found(client, database, manager):
    assert_error(preview(client, "unknown-token"), 404, "INVITATION_NOT_FOUND")


def test_preview_does_not_match_the_stored_hash_as_a_token(client, database, manager):
    assert_error(
        preview(client, manager.invitation.token_hash), 404, "INVITATION_NOT_FOUND"
    )


def test_preview_of_a_token_with_changed_case_is_not_found(client, database, manager):
    assert_error(preview(client, manager.token.swapcase()), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_deleted_managers_link_is_not_found(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], deleted=True)
    assert_error(preview(client, stored.token), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_deleted_managers_expired_link_is_not_found(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], deleted=True, expired=True)
    assert_error(preview(client, stored.token), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_deleted_managers_used_link_is_not_found(
    client, database, owner, melati, make_manager
):
    stored = make_manager(owner, [melati], deleted=True, used=True)
    assert_error(preview(client, stored.token), 404, "INVITATION_NOT_FOUND")


def test_preview_of_a_link_whose_manager_the_owner_removed_is_not_found(
    client, database, manager, signed_in
):
    assert remove_manager(client, signed_in.headers, manager.id).status_code == 204
    assert_error(preview(client, manager.token), 404, "INVITATION_NOT_FOUND")


def test_removing_one_managers_record_does_not_hide_another_link(
    client, database, owner, melati, make_manager, manager, signed_in
):
    other = make_manager(owner, [melati], name="Other Manager")
    assert remove_manager(client, signed_in.headers, manager.id).status_code == 204
    assert preview(client, other.token).json()["status"] == "valid"
