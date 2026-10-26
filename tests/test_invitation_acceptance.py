"""Previewing and accepting an invitation with an existing account."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from manager_invitation_support import (
    ACCEPTANCE_PREVIEW_URL,
    ACCEPTANCE_URL,
    assignments_of,
    code_count,
    edit_invitation,
    install_hook,
    preview,
    preview_status,
    stored_record,
    stored_user,
)
from manager_support import (
    PROPERTIES,
    assert_error,
    fetch_all,
    get_manager,
    list_managers,
    regenerate,
    role,
    state,
    token_of,
)

PASSWORD = "T7#vq9-lorem-ipsum"
PREVIEW_FIELDS = {
    "invitation",
    "accountName",
    "accountEmail",
    "accountRole",
    "canAccept",
    "blocker",
    "activeLease",
}
ROLES_WITHOUT_MANAGER = ["owner", "admin", "tenant"]


def check(client, token: str, headers: dict | None = None):
    return client.post(ACCEPTANCE_PREVIEW_URL, json={"token": token}, headers=headers)


def accept(client, token: str, headers: dict | None = None):
    return client.post(ACCEPTANCE_URL, json={"token": token}, headers=headers)


def accept_ok(client, token: str, headers: dict) -> None:
    response = accept(client, token, headers)
    assert response.status_code == 204, response.text


def snapshot(database) -> dict:
    """Everything a failed acceptance must leave untouched."""
    return {**state(database), "codes": code_count(database)}


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def melati(owner, make_property):
    return make_property(owner, name="Kos Melati", address="Jl. Melati 5")


@pytest.fixture
def anggrek(owner, make_property):
    return make_property(owner, name="Kos Anggrek", address="Jl. Anggrek 7")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def other_owner(make_user):
    return make_user(name="Dewi Owner")


@pytest.fixture
def elsewhere(other_owner, make_property):
    return make_property(other_owner, name="Kos Elsewhere", address="Jl. E 9")


@pytest.fixture
def manager(owner, melati, anggrek, make_manager):
    """The placeholder record an Owner invited a new person with."""
    return make_manager(
        owner,
        [melati, anggrek],
        name="Mira Manager",
        nickname="Bu Mira",
        phone="081298765432",
    )


@pytest.fixture
def caller(other_owner, elsewhere, make_manager, sign_in):
    """A Manager who already works for another Owner and is signed in."""
    stored = make_manager(
        other_owner,
        [elsewhere],
        name="Citra Caller",
        email="citra.caller@example.com",
        password=PASSWORD,
        activated=True,
    )
    return SimpleNamespace(
        stored=stored,
        user=stored.user,
        id=stored.user_id,
        headers=sign_in(stored.user).headers,
    )


@pytest.fixture
def far_room(make_user, make_property, make_room):
    far_owner = make_user(name="Far Owner")
    return make_room(make_property(far_owner, name="Kos Jauh"), number="Z9")


@pytest.fixture
def make_caller(make_user, make_verified_tenant, far_room, sign_in):
    """Build a signed-in caller of the given kind."""

    def build(kind: str, **options):
        if kind == "tenant":
            user = make_verified_tenant(far_room, name="Tomi Tenant", **options).user
        else:
            user = make_user(name=f"Some {kind}", role=role(kind))
        return SimpleNamespace(user=user, id=user.id, headers=sign_in(user).headers)

    return build


@pytest.fixture
def tenant_target(melati, make_room, make_tenant):
    """A Tenant invitation of the Owner."""
    return make_tenant(make_room(melati, number="A1"), name="Budi Tenant")


# Authentication


@pytest.mark.parametrize("call", [check, accept])
def test_a_request_without_a_session_is_rejected(
    client, database, manager, call, sent_emails
):
    assert_error(call(client, manager.token), 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("call", [check, accept])
def test_a_request_with_a_garbage_token_is_rejected(
    client, database, manager, call, sent_emails
):
    response = call(client, manager.token, {"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("call", [check, accept])
def test_the_session_is_checked_before_the_link(client, database, call):
    assert_error(call(client, "unknown-token"), 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("call", [check, accept])
def test_an_unverified_account_is_rejected(
    client, database, manager, make_user, sign_in, call
):
    user = make_user(role=role("manager"), email_verified=False)
    headers = sign_in(user).headers
    before = snapshot(database)
    response = call(client, manager.token, headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
    assert snapshot(database) == before


@pytest.mark.parametrize("call", [check, accept])
def test_the_verification_check_comes_before_the_link_lookup(
    client, database, make_user, sign_in, call
):
    user = make_user(email_verified=False)
    response = call(client, "unknown-token", sign_in(user).headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


# Preview


def test_a_manager_with_a_valid_link_can_accept(client, database, manager, caller):
    response = check(client, manager.token, caller.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PREVIEW_FIELDS
    assert body["accountName"] == "Citra Caller"
    assert body["accountEmail"] == "citra.caller@example.com"
    assert body["accountRole"] == "manager"
    assert body["canAccept"] is True
    assert body["blocker"] is None
    assert body["activeLease"] is None


def test_the_preview_carries_the_same_invitation_as_the_public_preview(
    client, database, manager, caller
):
    public = preview(client, manager.token).json()
    body = check(client, manager.token, caller.headers).json()
    assert body["invitation"] == public
    assert body["invitation"]["role"] == "manager"
    assert body["invitation"]["status"] == "valid"
    assert body["invitation"]["inviterName"] == "Rina Owner"
    assert [p["name"] for p in body["invitation"]["properties"]] == [
        "Kos Anggrek",
        "Kos Melati",
    ]


def test_the_preview_changes_nothing_and_can_be_repeated(
    client, database, manager, caller
):
    before = snapshot(database)
    first = check(client, manager.token, caller.headers)
    second = check(client, manager.token, caller.headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert snapshot(database) == before


def test_the_preview_names_the_calling_account_not_the_invited_one(
    client, database, manager, caller
):
    body = check(client, manager.token, caller.headers).json()
    assert body["accountName"] != "Mira Manager"
    assert body["invitation"]["name"] == "Mira Manager"


def test_the_preview_of_an_unknown_token_is_not_found(client, database, caller):
    response = check(client, "unknown-token", caller.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")


@pytest.mark.parametrize("expired", [False, True])
def test_the_preview_of_a_deleted_managers_link_is_not_found(
    client, database, owner, melati, make_manager, caller, expired
):
    stored = make_manager(owner, [melati], deleted=True, expired=expired)
    response = check(client, stored.token, caller.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")


def test_the_preview_of_a_deleted_tenants_link_is_not_found(
    client, database, melati, make_room, make_tenant, caller
):
    stored = make_tenant(make_room(melati, number="A1"), deleted=True)
    response = check(client, stored.token, caller.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")


def test_an_expired_link_cannot_be_accepted_and_has_no_blocker(
    client, database, owner, melati, make_manager, caller
):
    stored = make_manager(owner, [melati], expired=True)
    body = check(client, stored.token, caller.headers).json()
    assert body["invitation"]["status"] == "expired"
    assert body["canAccept"] is False
    assert body["blocker"] is None
    assert body["activeLease"] is None


@pytest.mark.parametrize("how", ["used", "invalidated", "activated", "both"])
def test_a_used_link_cannot_be_accepted_and_has_no_blocker(
    client, database, owner, melati, make_manager, caller, how
):
    options = {
        "used": {"used": True},
        "invalidated": {"invalidated": True},
        "activated": {"activated": True},
        "both": {"used": True, "expired": True},
    }[how]
    stored = make_manager(owner, [melati], **options)
    body = check(client, stored.token, caller.headers).json()
    assert body["invitation"]["status"] == "used"
    assert body["canAccept"] is False
    assert body["blocker"] is None
    assert body["activeLease"] is None


def test_a_replaced_link_cannot_be_accepted_but_the_new_one_can(
    client, database, manager, caller, owner_in
):
    new_token = token_of(regenerate(client, owner_in.headers, manager.id).json()["url"])
    old = check(client, manager.token, caller.headers).json()
    new = check(client, new_token, caller.headers).json()
    assert old["canAccept"] is False
    assert old["invitation"]["status"] == "used"
    assert new["canAccept"] is True
    assert new["invitation"]["status"] == "valid"


@pytest.mark.parametrize("kind", ROLES_WITHOUT_MANAGER)
def test_a_manager_link_previewed_by_another_role_is_a_role_mismatch(
    client, database, manager, make_caller, kind
):
    who = make_caller(kind)
    body = check(client, manager.token, who.headers).json()
    assert body["accountRole"] == kind
    assert body["accountName"] == who.user.name
    assert body["accountEmail"] == who.user.email
    assert body["canAccept"] is False
    assert body["blocker"] == "roleMismatch"
    assert body["activeLease"] is None


def test_a_tenant_with_an_active_lease_gets_a_role_mismatch_for_a_manager_link(
    client, database, manager, make_caller
):
    who = make_caller("tenant")
    body = check(client, manager.token, who.headers).json()
    assert body["blocker"] == "roleMismatch"
    assert body["activeLease"] is None


@pytest.mark.parametrize("kind", ["owner", "admin"])
def test_a_tenant_link_previewed_by_owner_or_admin_is_a_role_mismatch(
    client, database, tenant_target, make_caller, kind
):
    body = check(client, tenant_target.token, make_caller(kind).headers).json()
    assert body["invitation"]["role"] == "tenant"
    assert body["canAccept"] is False
    assert body["blocker"] == "roleMismatch"
    assert body["activeLease"] is None


def test_a_tenant_link_previewed_by_a_manager_is_a_role_mismatch(
    client, database, tenant_target, caller
):
    body = check(client, tenant_target.token, caller.headers).json()
    assert body["accountRole"] == "manager"
    assert body["canAccept"] is False
    assert body["blocker"] == "roleMismatch"
    assert body["activeLease"] is None


def test_a_tenant_with_an_active_lease_is_blocked_and_the_lease_is_described(
    client, database, tenant_target, make_caller
):
    end = date.today() + timedelta(days=200)
    who = make_caller(
        "tenant", start_date=date.today() - timedelta(days=30), end_date=end
    )
    body = check(client, tenant_target.token, who.headers).json()
    assert body["accountRole"] == "tenant"
    assert body["canAccept"] is False
    assert body["blocker"] == "activeLease"
    assert body["activeLease"] == {
        "propertyName": "Kos Jauh",
        "roomNumber": "Z9",
        "endDate": end.isoformat(),
    }


def test_an_active_lease_without_an_end_date_has_a_null_end_date(
    client, database, tenant_target, make_caller
):
    who = make_caller("tenant", start_date=date.today() - timedelta(days=30))
    body = check(client, tenant_target.token, who.headers).json()
    assert body["blocker"] == "activeLease"
    assert body["activeLease"]["endDate"] is None
    assert body["activeLease"]["propertyName"] == "Kos Jauh"
    assert body["activeLease"]["roomNumber"] == "Z9"


def test_a_tenant_whose_lease_ended_is_not_blocked(
    client, database, tenant_target, make_caller
):
    who = make_caller("tenant", lease_ended=True)
    body = check(client, tenant_target.token, who.headers).json()
    assert body["blocker"] is None
    assert body["activeLease"] is None
    assert body["canAccept"] is True


# Accept: success


def test_accepting_answers_with_no_content(client, database, manager, caller):
    response = accept(client, manager.token, caller.headers)
    assert response.status_code == 204, response.text
    assert response.content == b""


def test_the_record_keeps_its_id_and_moves_to_the_calling_account(
    client, database, owner, manager, caller
):
    from app.models import Manager

    accept(client, manager.token, caller.headers)
    record = stored_record(database, manager.id)
    assert record.id == manager.id
    assert record.user_id == caller.id
    assert record.owner_id == owner.id
    assert record.deleted_at is None
    assert len(fetch_all(database, Manager)) == 2


def test_the_record_is_marked_activated_and_the_invitation_used(
    client, database, manager, caller
):
    from manager_support import invitation_rows

    before = datetime.now(UTC)
    accept(client, manager.token, caller.headers)
    record = stored_record(database, manager.id)
    (invitation,) = invitation_rows(database, manager.id)
    assert before - timedelta(seconds=5) <= record.activated_at <= datetime.now(UTC)
    assert before - timedelta(seconds=5) <= invitation.used_at <= datetime.now(UTC)
    assert invitation.invalidated_at is None


def test_the_assignments_of_the_placeholder_move_to_the_caller(
    client, database, melati, anggrek, elsewhere, manager, caller
):
    accept(client, manager.token, caller.headers)
    assert assignments_of(database, caller.id) == {
        melati.id,
        anggrek.id,
        elsewhere.id,
    }
    assert assignments_of(database, manager.user_id) == set()


def test_the_caller_keeps_the_assignments_of_other_owners(
    client, database, elsewhere, manager, caller
):
    accept_ok(client, manager.token, caller.headers)
    assert elsewhere.id in assignments_of(database, caller.id)
    other = stored_record(database, caller.stored.id)
    assert other.user_id == caller.id
    assert other.activated_at is not None
    assert other.deleted_at is None


def test_the_caller_can_use_the_properties_of_the_inviting_owner(
    client, database, melati, anggrek, elsewhere, manager, caller
):
    before = client.get(PROPERTIES, headers=caller.headers).json()["items"]
    assert {item["id"] for item in before} == {str(elsewhere.id)}
    accept(client, manager.token, caller.headers)
    after = client.get(PROPERTIES, headers=caller.headers).json()["items"]
    assert {item["id"] for item in after} == {
        str(melati.id),
        str(anggrek.id),
        str(elsewhere.id),
    }


def test_the_placeholder_account_stays_without_assignments_or_credentials(
    client, database, manager, caller
):
    accept(client, manager.token, caller.headers)
    placeholder = stored_user(database, manager.user_id)
    assert placeholder is not None
    assert placeholder.email is None
    assert placeholder.password_hash is None
    assert placeholder.name == "Mira Manager"
    assert assignments_of(database, placeholder.id) == set()


def test_the_owner_sees_the_caller_as_the_active_manager(
    client, database, manager, caller, owner_in, melati, anggrek
):
    accept(client, manager.token, caller.headers)
    response = get_manager(client, owner_in.headers, manager.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(manager.id)
    assert body["accountStatus"] == "active"
    assert body["name"] == "Citra Caller"
    assert body["email"] == "citra.caller@example.com"
    assert body["invitation"] is None
    assert [p["id"] for p in body["properties"]] == [str(anggrek.id), str(melati.id)]


def test_the_nickname_and_phone_the_owner_entered_are_kept(
    client, database, manager, caller, owner_in
):
    accept_ok(client, manager.token, caller.headers)
    body = get_manager(client, owner_in.headers, manager.id).json()
    assert body["nickname"] == "Bu Mira"
    assert body["phone"] == "081298765432"


def test_the_owner_list_shows_one_active_entry_for_the_caller(
    client, database, manager, caller, owner_in
):
    accept(client, manager.token, caller.headers)
    (item,) = list_managers(client, owner_in.headers).json()["items"]
    assert item["id"] == str(manager.id)
    assert item["accountStatus"] == "active"
    assert item["email"] == "citra.caller@example.com"


def test_the_other_owners_view_of_the_caller_is_unchanged(
    client, database, manager, caller, other_owner, elsewhere, sign_in
):
    headers = sign_in(other_owner).headers
    before = get_manager(client, headers, caller.stored.id).json()
    accept_ok(client, manager.token, caller.headers)
    assert get_manager(client, headers, caller.stored.id).json() == before
    assert before["properties"][0]["id"] == str(elsewhere.id)


def test_the_callers_account_sessions_and_password_are_untouched(
    client, database, manager, caller, sent_emails
):
    before = state(database)
    caller_before = stored_user(database, caller.id)
    accept_ok(client, manager.token, caller.headers)
    after = state(database)
    assert after["users"] == before["users"]
    assert after["sessions"] == before["sessions"]
    caller_after = stored_user(database, caller.id)
    assert caller_after.name == caller_before.name == "Citra Caller"
    assert caller_after.email == caller_before.email
    assert caller_after.password_hash == caller_before.password_hash
    assert sent_emails == []


def test_the_callers_session_keeps_working(client, database, manager, caller):
    accept_ok(client, manager.token, caller.headers)
    assert client.get("/me", headers=caller.headers).status_code == 200


def test_the_used_link_previews_as_used_and_cannot_be_replayed(
    client, database, manager, caller
):
    assert accept(client, manager.token, caller.headers).status_code == 204
    before = snapshot(database)
    assert preview_status(client, manager.token) == "used"
    assert_error(accept(client, manager.token, caller.headers), 409, "INVITATION_USED")
    assert snapshot(database) == before


def test_the_acceptance_preview_after_acceptance_cannot_accept_again(
    client, database, manager, caller
):
    accept_ok(client, manager.token, caller.headers)
    body = check(client, manager.token, caller.headers).json()
    assert body["invitation"]["status"] == "used"
    assert body["canAccept"] is False
    assert body["blocker"] is None


def test_accepting_a_renewed_link_works_and_the_old_one_is_used(
    client, database, manager, caller, owner_in
):
    new_token = token_of(regenerate(client, owner_in.headers, manager.id).json()["url"])
    assert_error(accept(client, manager.token, caller.headers), 409, "INVITATION_USED")
    assert accept(client, new_token, caller.headers).status_code == 204
    assert stored_record(database, manager.id).user_id == caller.id


def test_accepting_an_expired_link_renewed_by_the_owner_works(
    client, database, owner, melati, make_manager, caller, owner_in
):
    stored = make_manager(owner, [melati], expired=True)
    new_token = token_of(regenerate(client, owner_in.headers, stored.id).json()["url"])
    assert accept(client, new_token, caller.headers).status_code == 204


def test_a_deleted_earlier_record_of_the_caller_under_the_owner_does_not_block(
    client, database, owner, melati, manager, caller, make_manager
):
    old = make_manager(owner, [], user=caller.user, activated=True, deleted=True)
    assert accept(client, manager.token, caller.headers).status_code == 204
    assert stored_record(database, manager.id).user_id == caller.id
    assert stored_record(database, old.id).deleted_at is not None


def test_another_pending_invitation_of_the_owner_is_left_alone(
    client, database, owner, melati, manager, caller, make_manager
):
    other = make_manager(owner, [melati], name="Other Manager")
    accept(client, manager.token, caller.headers)
    assert preview_status(client, other.token) == "valid"
    assert stored_record(database, other.id).user_id == other.user_id


# Accept: failures


def test_an_unknown_token_is_not_found(client, database, manager, caller):
    before = snapshot(database)
    response = accept(client, "unknown-token", caller.headers)
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert snapshot(database) == before


@pytest.mark.parametrize("expired", [False, True])
def test_a_deleted_managers_token_is_not_found(
    client, database, owner, melati, make_manager, caller, expired
):
    stored = make_manager(owner, [melati], deleted=True, expired=expired)
    before = snapshot(database)
    assert_error(
        accept(client, stored.token, caller.headers), 404, "INVITATION_NOT_FOUND"
    )
    assert snapshot(database) == before


@pytest.mark.parametrize("how", ["used", "invalidated", "activated"])
def test_a_used_link_is_refused(
    client, database, owner, melati, make_manager, caller, how
):
    stored = make_manager(owner, [melati], **{how: True})
    before = snapshot(database)
    assert_error(accept(client, stored.token, caller.headers), 409, "INVITATION_USED")
    assert snapshot(database) == before


def test_used_wins_over_expired(client, database, manager, caller):
    edit_invitation(
        database,
        manager.token,
        used_at=datetime.now(UTC) - timedelta(days=8),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(accept(client, manager.token, caller.headers), 409, "INVITATION_USED")


def test_an_expired_link_is_refused(
    client, database, owner, melati, make_manager, caller
):
    stored = make_manager(owner, [melati], expired=True)
    before = snapshot(database)
    response = accept(client, stored.token, caller.headers)
    assert_error(response, 409, "INVITATION_EXPIRED")
    assert snapshot(database) == before
    assert preview_status(client, stored.token) == "expired"


def test_a_link_that_expired_a_moment_ago_is_refused(client, database, manager, caller):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert_error(
        accept(client, manager.token, caller.headers), 409, "INVITATION_EXPIRED"
    )


def test_a_link_about_to_expire_is_accepted(client, database, manager, caller):
    edit_invitation(
        database, manager.token, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert accept(client, manager.token, caller.headers).status_code == 204


@pytest.mark.parametrize("kind", ROLES_WITHOUT_MANAGER)
def test_a_manager_link_is_refused_for_another_role(
    client, database, manager, make_caller, kind
):
    who = make_caller(kind)
    before = snapshot(database)
    response = accept(client, manager.token, who.headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before
    assert preview_status(client, manager.token) == "valid"
    assert assignments_of(database, who.id) == set()


@pytest.mark.parametrize("kind", ["owner", "admin"])
def test_a_tenant_link_is_refused_for_an_owner_or_admin(
    client, database, tenant_target, make_caller, kind
):
    who = make_caller(kind)
    before = snapshot(database)
    response = accept(client, tenant_target.token, who.headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before


def test_a_tenant_link_is_refused_for_a_manager(
    client, database, tenant_target, caller
):
    before = snapshot(database)
    response = accept(client, tenant_target.token, caller.headers)
    assert_error(response, 409, "INVITATION_ROLE_MISMATCH")
    assert snapshot(database) == before


def test_a_tenant_link_is_refused_for_a_tenant_with_an_active_lease(
    client, database, tenant_target, make_caller
):
    who = make_caller("tenant", start_date=date.today() - timedelta(days=30))
    before = snapshot(database)
    response = accept(client, tenant_target.token, who.headers)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert snapshot(database) == before
    assert preview_status(client, tenant_target.token) == "valid"


def test_the_link_is_checked_before_the_role(client, database, manager, make_caller):
    who = make_caller("owner")
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    assert_error(accept(client, manager.token, who.headers), 409, "INVITATION_USED")
    edit_invitation(
        database,
        manager.token,
        used_at=None,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert_error(accept(client, manager.token, who.headers), 409, "INVITATION_EXPIRED")


def test_a_manager_who_already_works_for_the_owner_is_refused(
    client, database, owner, melati, manager, caller, make_manager
):
    make_manager(owner, [], user=caller.user, activated=True)
    before = snapshot(database)
    response = accept(client, manager.token, caller.headers)
    assert_error(response, 409, "MANAGER_ALREADY_ADDED")
    assert snapshot(database) == before
    assert preview_status(client, manager.token) == "valid"
    assert stored_record(database, manager.id).user_id == manager.user_id


def test_the_link_is_checked_before_the_manager_is_found_to_be_added_already(
    client, database, owner, melati, manager, caller, make_manager
):
    make_manager(owner, [], user=caller.user, activated=True)
    edit_invitation(database, manager.token, used_at=datetime.now(UTC))
    assert_error(accept(client, manager.token, caller.headers), 409, "INVITATION_USED")


def test_a_failed_acceptance_does_not_call_the_hook(
    client, database, owner, melati, manager, caller, make_manager, monkeypatch
):
    calls = install_hook(monkeypatch)
    make_manager(owner, [], user=caller.user, activated=True)
    assert accept(client, manager.token, caller.headers).status_code == 409
    assert accept(client, "unknown-token", caller.headers).status_code == 404
    assert calls.records == []


# Notification hook


def test_the_hook_is_called_once_with_the_record_on_success(
    client, database, manager, caller, monkeypatch
):
    calls = install_hook(monkeypatch)
    assert accept(client, manager.token, caller.headers).status_code == 204
    assert calls.record_ids == [manager.id]


@pytest.mark.parametrize("kind", ROLES_WITHOUT_MANAGER)
def test_the_hook_is_not_called_for_a_role_mismatch(
    client, database, manager, make_caller, monkeypatch, kind
):
    calls = install_hook(monkeypatch)
    assert accept(client, manager.token, make_caller(kind).headers).status_code == 409
    assert calls.records == []


@pytest.mark.parametrize("how", ["used", "expired"])
def test_the_hook_is_not_called_for_a_refused_link(
    client, database, owner, melati, make_manager, caller, monkeypatch, how
):
    calls = install_hook(monkeypatch)
    stored = make_manager(owner, [melati], **{how: True})
    assert accept(client, stored.token, caller.headers).status_code == 409
    assert calls.records == []


def test_the_hook_is_not_called_for_a_replay(
    client, database, manager, caller, monkeypatch
):
    calls = install_hook(monkeypatch)
    accept(client, manager.token, caller.headers)
    accept(client, manager.token, caller.headers)
    assert calls.record_ids == [manager.id]


def test_acceptance_succeeds_when_the_hook_raises(
    client, database, manager, caller, owner_in, monkeypatch
):
    calls = install_hook(monkeypatch, error=RuntimeError("notification down"))
    response = accept(client, manager.token, caller.headers)
    assert response.status_code == 204, response.text
    assert calls.record_ids == [manager.id]
    assert stored_record(database, manager.id).user_id == caller.id
    assert stored_record(database, manager.id).activated_at is not None
    body = get_manager(client, owner_in.headers, manager.id).json()
    assert body["accountStatus"] == "active"
    assert preview_status(client, manager.token) == "used"
