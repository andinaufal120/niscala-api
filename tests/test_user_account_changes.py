"""Editing a user account as an Admin: name, status and email."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from user_account_support import (
    ACCOUNT_FIELDS,
    account_url,
    all_change_requests,
    assert_close,
    assert_error,
    change_email,
    change_requests,
    confirm_change,
    edit_account,
    edit_body,
    expire_change_request,
    get_account,
    invitation_base,
    last_token,
    login,
    parse_time,
    read_user,
    refresh,
    sessions_of,
    set_password,
    token_in,
)

NEW = "new.address@example.org"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email="rina@example.com")
    set_password(database, user)
    return user


def detail(client, admin_in, user) -> dict:
    response = get_account(client, admin_in.headers, user.id)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def deleted_target(
    request, make_user, make_property, make_room, make_verified_tenant, make_manager
):
    """A deleted account, once per way an account can be deleted."""
    landlord = make_user(name="Landlord")
    if request.param == "account":
        return make_user(name="Gone", email="gone@example.com", deleted=True)
    if request.param == "tenant":
        room = make_room(make_property(landlord))
        return make_verified_tenant(
            room, name="Gone", email="gone@example.com", deleted=True
        ).user
    return make_manager(
        landlord, activated=True, name="Gone", email="gone@example.com", deleted=True
    ).user


ALL_DELETED_WAYS = pytest.mark.parametrize(
    "deleted_target", ["account", "tenant", "manager"], indirect=True
)


# Name and status


def test_a_new_name_applies_at_once_and_the_response_is_the_updated_account(
    client, database, admin_in, owner
):
    response = edit_account(client, admin_in.headers, owner, name="Rina Baru")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ACCOUNT_FIELDS
    assert body["id"] == str(owner.id)
    assert body["name"] == "Rina Baru"
    assert body["email"] == "rina@example.com"
    assert body["status"] == "active"
    assert read_user(database, owner.id).name == "Rina Baru"
    assert detail(client, admin_in, owner)["name"] == "Rina Baru"


def test_the_name_is_trimmed(client, database, admin_in, owner):
    response = edit_account(client, admin_in.headers, owner, name="  Rina Baru  ")
    assert response.status_code == 200
    assert response.json()["name"] == "Rina Baru"
    assert read_user(database, owner.id).name == "Rina Baru"


def test_a_name_change_sends_no_email_and_keeps_sessions(
    client, database, admin_in, owner, sign_in, mailbox
):
    session = sign_in(owner)
    edit_account(client, admin_in.headers, owner, name="Rina Baru")
    assert mailbox.is_empty
    assert all_change_requests(database) == []
    assert client.get("/me", headers=session.headers).status_code == 200


def test_the_response_keeps_the_links_of_the_account(
    client, database, admin_in, make_user, make_property
):
    owner = make_user(name="Rina Owner")
    prop = make_property(owner, name="Kos Melati")
    response = edit_account(client, admin_in.headers, owner, name="Rina Baru")
    assert response.json()["properties"] == [{"id": str(prop.id), "name": "Kos Melati"}]


def test_an_account_can_be_made_inactive(client, database, admin_in, owner):
    response = edit_account(client, admin_in.headers, owner, status="inactive")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "inactive"
    assert read_user(database, owner.id).status == "inactive"
    assert detail(client, admin_in, owner)["status"] == "inactive"


def test_an_inactive_account_can_be_made_active_again(
    client, database, admin_in, make_user
):
    suspended = make_user(status="inactive")
    response = edit_account(client, admin_in.headers, suspended, status="active")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert read_user(database, suspended.id).status == "active"


def test_name_and_status_change_together(client, database, admin_in, owner):
    response = edit_account(
        client, admin_in.headers, owner, name="Rina Baru", status="inactive"
    )
    body = response.json()
    assert (body["name"], body["status"]) == ("Rina Baru", "inactive")


def test_submitting_the_current_values_changes_nothing(
    client, database, admin_in, owner, mailbox
):
    before = detail(client, admin_in, owner)
    response = edit_account(client, admin_in.headers, owner)
    assert response.status_code == 200
    assert response.json() == before
    assert detail(client, admin_in, owner) == before
    assert all_change_requests(database) == []
    assert mailbox.is_empty


@pytest.mark.parametrize("kind", ["tenant", "manager", "admin"])
def test_every_role_can_be_renamed_and_suspended(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    kind,
):
    landlord = make_user(name="Landlord")
    if kind == "tenant":
        target = make_verified_tenant(make_room(make_property(landlord))).user
    elif kind == "manager":
        target = make_manager(landlord, activated=True).user
    else:
        target = make_user(role=role("admin"))
    response = edit_account(
        client, admin_in.headers, target, name="Nama Baru", status="inactive"
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == kind
    assert response.json()["name"] == "Nama Baru"
    assert response.json()["status"] == "inactive"


# Deactivation and sessions


def test_deactivating_revokes_every_session_of_the_account(
    client, database, admin_in, owner, sign_in
):
    first, second = sign_in(owner), sign_in(owner)
    edit_account(client, admin_in.headers, owner, status="inactive")
    rows = sessions_of(database, owner.id)
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    for session in (first, second):
        response = client.get("/me", headers=session.headers)
        assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_deactivated_account_cannot_refresh(
    client, database, admin_in, owner, sign_in
):
    session = sign_in(owner)
    edit_account(client, admin_in.headers, owner, status="inactive")
    response = refresh(client, session.tokens.refresh_token)
    assert_error(response, 401, "REFRESH_TOKEN_INVALID")


def test_deactivating_leaves_the_sessions_of_other_accounts_alone(
    client, database, admin, admin_in, owner, make_user, sign_in
):
    bystander = sign_in(make_user())
    response = edit_account(client, admin_in.headers, owner, status="inactive")
    assert response.status_code == 200
    assert client.get("/me", headers=bystander.headers).status_code == 200
    assert client.get("/me", headers=admin_in.headers).status_code == 200


def test_reactivating_does_not_revive_the_old_sessions(
    client, database, admin_in, owner, sign_in
):
    session = sign_in(owner)
    edit_account(client, admin_in.headers, owner, status="inactive")
    edit_account(client, admin_in.headers, owner, status="active")
    assert_error(
        client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    assert_error(
        refresh(client, session.tokens.refresh_token), 401, "REFRESH_TOKEN_INVALID"
    )
    assert login(client, "rina@example.com").status_code == 200


def test_reactivating_at_any_time_works(client, database, admin_in, owner):
    for _ in range(3):
        assert (
            edit_account(client, admin_in.headers, owner, status="inactive").status_code
            == 200
        )
        assert (
            edit_account(client, admin_in.headers, owner, status="active").status_code
            == 200
        )


def test_deactivating_an_inactive_account_succeeds_and_changes_nothing(
    client, database, admin_in, owner, sign_in
):
    sign_in(owner)
    edit_account(client, admin_in.headers, owner, status="inactive")
    revoked_at = sessions_of(database, owner.id)[0].revoked_at
    response = edit_account(client, admin_in.headers, owner, status="inactive")
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert sessions_of(database, owner.id)[0].revoked_at == revoked_at


def test_keeping_an_account_active_does_not_end_its_sessions(
    client, database, admin_in, owner, sign_in
):
    session = sign_in(owner)
    response = edit_account(client, admin_in.headers, owner, status="active")
    assert response.status_code == 200
    assert client.get("/me", headers=session.headers).status_code == 200
    assert sessions_of(database, owner.id)[0].revoked_at is None


# Admins editing admins


def test_an_admin_cannot_deactivate_their_own_account(
    client, database, admin, admin_in, mailbox
):
    response = edit_account(client, admin_in.headers, admin, status="inactive")
    assert_error(response, 409, "CANNOT_MODIFY_OWN_ACCOUNT")
    assert read_user(database, admin.id).status == "active"
    assert client.get("/me", headers=admin_in.headers).status_code == 200
    assert sessions_of(database, admin.id)[0].revoked_at is None


def test_a_refused_self_deactivation_applies_nothing_of_the_request(
    client, database, admin, admin_in, mailbox
):
    response = edit_account(
        client,
        admin_in.headers,
        admin,
        name="Changed Name",
        email="changed@example.com",
        status="inactive",
    )
    assert_error(response, 409, "CANNOT_MODIFY_OWN_ACCOUNT")
    row = read_user(database, admin.id)
    assert (row.name, row.email) == ("Ade Admin", "ade@example.com")
    assert all_change_requests(database) == []
    assert mailbox.is_empty


def test_an_admin_can_send_active_for_their_own_account_with_a_new_name(
    client, database, admin, admin_in
):
    response = edit_account(client, admin_in.headers, admin, name="Ade Baru")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Ade Baru"
    assert response.json()["status"] == "active"


def test_an_admin_can_start_an_email_change_on_their_own_account(
    client, database, admin, admin_in, mailbox
):
    response = change_email(client, admin_in.headers, admin, NEW)
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == NEW
    assert response.json()["email"] == "ade@example.com"
    assert mailbox.notices == [("ade@example.com", NEW)]


def test_an_admin_can_edit_another_admin(client, database, admin_in, make_user):
    other = make_user(role=role("admin"), name="Other Admin")
    response = edit_account(client, admin_in.headers, other, name="Renamed Admin")
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Admin"


def test_an_admin_can_deactivate_another_admin(
    client, database, admin_in, make_user, sign_in
):
    other = make_user(role=role("admin"))
    session = sign_in(other)
    response = edit_account(client, admin_in.headers, other, status="inactive")
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert_error(
        client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )


# Not found, deleted and validation


def test_an_unknown_account_is_not_found(client, database, admin_in, owner):
    response = client.put(
        account_url(uuid4()), headers=admin_in.headers, json=edit_body(owner)
    )
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_tenant_that_has_not_activated_is_not_found(
    client, database, admin_in, owner, make_tenant, make_property, make_room
):
    pending = make_tenant(make_room(make_property(owner)), name="Belum Aktif")
    response = edit_account(client, admin_in.headers, pending.user, name="Baru")
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_manager_that_has_not_activated_is_not_found(
    client, database, admin_in, owner, make_manager, mailbox
):
    pending = make_manager(owner, name="Belum Aktif")
    response = client.put(
        account_url(pending.user_id),
        headers=admin_in.headers,
        json={"name": "Baru", "email": "baru@example.com", "status": "active"},
    )
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")
    assert all_change_requests(database) == []
    assert mailbox.is_empty


@ALL_DELETED_WAYS
def test_a_deleted_account_cannot_be_edited(
    client, database, admin_in, deleted_target, mailbox
):
    response = edit_account(
        client, admin_in.headers, deleted_target, name="Revived", status="active"
    )
    assert_error(response, 409, "USER_ACCOUNT_DELETED")
    assert read_user(database, deleted_target.id).name == "Gone"


@ALL_DELETED_WAYS
def test_a_deleted_account_cannot_get_an_email_change(
    client, database, admin_in, deleted_target, mailbox
):
    response = change_email(client, admin_in.headers, deleted_target, NEW)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")
    assert all_change_requests(database) == []
    assert mailbox.is_empty


def test_a_deleted_account_is_reported_before_a_duplicate_email(
    client, database, admin_in, make_user
):
    make_user(email="taken@example.com")
    gone = make_user(deleted=True)
    response = change_email(client, admin_in.headers, gone, "taken@example.com")
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_refused_self_deactivation_is_reported_before_a_duplicate_email(
    client, database, admin, admin_in, make_user
):
    make_user(email="taken@example.com")
    response = edit_account(
        client, admin_in.headers, admin, email="taken@example.com", status="inactive"
    )
    assert_error(response, 409, "CANNOT_MODIFY_OWN_ACCOUNT")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"name": ""}, "name", id="empty_name"),
        pytest.param({"name": "   "}, "name", id="blank_name"),
        pytest.param({"name": "B" * 101}, "name", id="name_too_long"),
        pytest.param({"name": None}, "name", id="null_name"),
        pytest.param({"email": "not-an-email"}, "email", id="email_without_at"),
        pytest.param({"email": "budi@"}, "email", id="email_without_domain"),
        pytest.param({"email": ""}, "email", id="empty_email"),
        pytest.param({"email": None}, "email", id="null_email"),
        pytest.param({"status": "deleted"}, "status", id="deleted_status"),
        pytest.param({"status": "suspended"}, "status", id="unknown_status"),
        pytest.param({"status": "Active"}, "status", id="wrong_case_status"),
        pytest.param({"status": None}, "status", id="null_status"),
    ],
)
def test_an_invalid_body_is_rejected_with_the_field_and_saves_nothing(
    client, database, admin_in, owner, mailbox, overrides, field
):
    response = edit_account(client, admin_in.headers, owner, **overrides)
    assert_error(response, 422, "VALIDATION_FAILED", field)
    row = read_user(database, owner.id)
    assert (row.name, row.email, row.status) == (
        "Rina Owner",
        "rina@example.com",
        "active",
    )
    assert mailbox.is_empty


@pytest.mark.parametrize("missing", ["name", "email", "status"])
def test_a_missing_field_is_rejected_with_its_name(
    client, database, admin_in, owner, missing
):
    body = {k: v for k, v in edit_body(owner).items() if k != missing}
    response = client.put(account_url(owner.id), headers=admin_in.headers, json=body)
    assert_error(response, 422, "VALIDATION_FAILED", missing)


def test_a_request_without_a_body_is_rejected(client, database, admin_in, owner):
    response = client.put(account_url(owner.id), headers=admin_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_malformed_account_id_is_a_validation_error(
    client, database, admin_in, owner
):
    response = client.put(
        "/user-accounts/not-a-uuid", headers=admin_in.headers, json=edit_body(owner)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


# Starting an email change


def test_a_new_email_does_not_change_the_login_email(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, NEW)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "rina@example.com"
    assert body["pendingEmail"] == NEW
    assert read_user(database, owner.id).email == "rina@example.com"


def test_the_account_keeps_logging_in_with_the_current_email(
    client, database, admin_in, owner, mailbox
):
    assert change_email(client, admin_in.headers, owner, NEW).status_code == 200
    assert login(client, "rina@example.com").status_code == 200
    assert_error(login(client, NEW), 401, "INVALID_CREDENTIALS")


def test_a_change_request_is_stored_with_the_normalized_address(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, "  New.Address@Example.ORG  ")
    (row,) = change_requests(database, owner.id)
    assert row.user_id == owner.id
    assert row.new_email == NEW
    assert row.used_at is None
    assert row.replaced_at is None
    assert_close(row.created_at, datetime.now(UTC), 30)


def test_the_response_reports_the_normalized_pending_email(
    client, database, admin_in, owner, mailbox
):
    response = change_email(
        client, admin_in.headers, owner, "  New.Address@Example.ORG "
    )
    assert response.json()["pendingEmail"] == NEW


def test_the_pending_change_expires_seven_days_after_it_was_made(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, NEW)
    (row,) = change_requests(database, owner.id)
    assert_close(row.expires_at, row.created_at + timedelta(days=7), 1)
    assert_close(
        parse_time(response.json()["pendingEmailExpiresAt"]), row.expires_at, 1
    )
    assert_close(row.expires_at, datetime.now(UTC) + timedelta(days=7), 60)


def test_the_pending_change_is_reported_by_the_detail(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, NEW)
    body = detail(client, admin_in, owner)
    assert body["pendingEmail"] == NEW
    assert body["pendingEmailExpiresAt"] == response.json()["pendingEmailExpiresAt"]
    assert body["email"] == "rina@example.com"


def test_the_link_goes_to_the_new_address_and_the_notice_to_the_current_one(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, "  New.Address@Example.ORG ")
    assert len(mailbox.links) == 1
    to, url = mailbox.links[0]
    assert to == NEW
    assert url.startswith(invitation_base())
    assert mailbox.notices == [("rina@example.com", NEW)]
    assert mailbox.codes == []


def test_the_link_carries_a_token_that_is_stored_only_as_a_hash(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    token = token_in(mailbox.links[0][1])
    (row,) = change_requests(database, owner.id)
    assert row.token_hash
    assert row.token_hash != token
    assert token not in row.token_hash


def test_every_request_gets_a_different_token(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    change_email(client, admin_in.headers, owner, "second@example.org")
    assert token_in(mailbox.links[0][1]) != token_in(mailbox.links[1][1])
    first, second = change_requests(database, owner.id)
    assert first.token_hash != second.token_hash


def test_name_and_status_changes_in_the_same_request_apply_at_once(
    client, database, admin_in, owner, mailbox
):
    response = change_email(
        client, admin_in.headers, owner, NEW, name="Rina Baru", status="inactive"
    )
    body = response.json()
    assert body["name"] == "Rina Baru"
    assert body["status"] == "inactive"
    assert body["email"] == "rina@example.com"
    assert body["pendingEmail"] == NEW


def test_the_current_email_in_other_case_and_with_spaces_is_not_a_change(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, "  RINA@Example.COM ")
    assert response.status_code == 200
    assert response.json()["email"] == "rina@example.com"
    assert response.json()["pendingEmail"] is None
    assert all_change_requests(database) == []
    assert mailbox.is_empty


def test_the_confirmation_link_works_with_the_token_that_was_emailed(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    assert confirm_change(client, last_token(mailbox)).status_code == 204
    assert read_user(database, owner.id).email == NEW


@pytest.mark.parametrize("kind", ["tenant", "manager"])
def test_a_tenant_or_manager_can_get_an_email_change(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    mailbox,
    kind,
):
    landlord = make_user(name="Landlord")
    if kind == "tenant":
        target = make_verified_tenant(
            make_room(make_property(landlord)), email="old.person@example.com"
        ).user
    else:
        target = make_manager(
            landlord, activated=True, email="old.person@example.com"
        ).user
    response = change_email(client, admin_in.headers, target, NEW)
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == NEW
    assert mailbox.links[0][0] == NEW
    assert mailbox.notices == [("old.person@example.com", NEW)]


# Replacing and cancelling a pending change


def test_a_second_change_replaces_the_first(client, database, admin_in, owner, mailbox):
    change_email(client, admin_in.headers, owner, NEW)
    first_token = last_token(mailbox)
    response = change_email(client, admin_in.headers, owner, "second@example.org")
    second_token = last_token(mailbox)
    assert response.json()["pendingEmail"] == "second@example.org"
    assert first_token != second_token
    assert_error(confirm_change(client, first_token), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == "rina@example.com"
    assert confirm_change(client, second_token).status_code == 204
    assert read_user(database, owner.id).email == "second@example.org"


def test_a_replacing_change_emails_a_new_link_and_a_new_notice(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    change_email(client, admin_in.headers, owner, "second@example.org")
    assert [to for to, _ in mailbox.links] == [NEW, "second@example.org"]
    assert mailbox.notices == [
        ("rina@example.com", NEW),
        ("rina@example.com", "second@example.org"),
    ]


def test_asking_for_the_same_new_address_again_replaces_the_pending_change(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    first_token = last_token(mailbox)
    response = change_email(client, admin_in.headers, owner, NEW)
    assert response.json()["pendingEmail"] == NEW
    assert len(mailbox.links) == 2
    assert len(mailbox.notices) == 2
    assert_error(confirm_change(client, first_token), 409, "EMAIL_CHANGE_USED")
    assert confirm_change(client, last_token(mailbox)).status_code == 204


def test_only_the_newest_change_is_reported_as_pending(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    change_email(client, admin_in.headers, owner, "second@example.org")
    body = detail(client, admin_in, owner)
    assert body["pendingEmail"] == "second@example.org"
    assert_close(
        parse_time(body["pendingEmailExpiresAt"]),
        datetime.now(UTC) + timedelta(days=7),
        60,
    )


def test_submitting_the_current_email_cancels_the_pending_change(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    token = last_token(mailbox)
    response = edit_account(client, admin_in.headers, owner)
    assert response.status_code == 200
    body = response.json()
    assert body["pendingEmail"] is None
    assert body["pendingEmailExpiresAt"] is None
    assert body["email"] == "rina@example.com"
    assert detail(client, admin_in, owner)["pendingEmail"] is None
    assert_error(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == "rina@example.com"


def test_cancelling_a_pending_change_sends_no_email(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    links, notices = list(mailbox.links), list(mailbox.notices)
    assert len(links) == 1
    assert edit_account(client, admin_in.headers, owner).status_code == 200
    assert mailbox.links == links
    assert mailbox.notices == notices
    assert mailbox.codes == []


def test_cancelling_with_the_current_email_in_other_case_also_cancels(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    response = change_email(client, admin_in.headers, owner, " RINA@EXAMPLE.COM ")
    assert response.json()["pendingEmail"] is None


def test_cancelling_still_applies_a_name_change_of_the_same_request(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    response = edit_account(client, admin_in.headers, owner, name="Rina Baru")
    assert response.json()["name"] == "Rina Baru"
    assert response.json()["pendingEmail"] is None


def test_a_change_can_be_started_again_after_a_cancellation(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    edit_account(client, admin_in.headers, owner)
    response = change_email(client, admin_in.headers, owner, NEW)
    assert response.json()["pendingEmail"] == NEW
    assert confirm_change(client, last_token(mailbox)).status_code == 204


def test_a_cancellation_with_nothing_pending_is_a_plain_no_op(
    client, database, admin_in, owner, mailbox
):
    response = edit_account(client, admin_in.headers, owner)
    assert response.status_code == 200
    assert response.json()["pendingEmail"] is None
    assert all_change_requests(database) == []


# Expired changes


def test_an_expired_pending_change_is_not_reported_as_pending(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    (row,) = change_requests(database, owner.id)
    expire_change_request(database, row.id)
    body = detail(client, admin_in, owner)
    assert body["pendingEmail"] is None
    assert body["pendingEmailExpiresAt"] is None
    assert body["email"] == "rina@example.com"


def test_an_edit_after_a_change_expired_reports_nothing_pending(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    (row,) = change_requests(database, owner.id)
    expire_change_request(database, row.id)
    response = edit_account(client, admin_in.headers, owner, name="Rina Baru")
    assert response.json()["pendingEmail"] is None


def test_a_new_change_can_be_started_after_the_previous_one_expired(
    client, database, admin_in, owner, mailbox
):
    change_email(client, admin_in.headers, owner, NEW)
    (row,) = change_requests(database, owner.id)
    expire_change_request(database, row.id)
    response = change_email(client, admin_in.headers, owner, NEW)
    assert response.status_code == 200
    assert response.json()["pendingEmail"] == NEW
    assert confirm_change(client, last_token(mailbox)).status_code == 204


# Duplicate emails


@pytest.mark.parametrize(
    "typed",
    [
        "other@example.com",
        "OTHER@EXAMPLE.COM",
        "Other@Example.com",
        "  other@example.com  ",
    ],
)
def test_an_email_of_another_account_is_refused(
    client, database, admin_in, owner, make_user, mailbox, typed
):
    make_user(email="other@example.com")
    response = change_email(client, admin_in.headers, owner, typed)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_a_refused_email_saves_nothing_of_the_request(
    client, database, admin_in, owner, make_user, mailbox, sign_in
):
    make_user(email="other@example.com")
    session = sign_in(owner)
    response = change_email(
        client,
        admin_in.headers,
        owner,
        "other@example.com",
        name="Rina Baru",
        status="inactive",
    )
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    row = read_user(database, owner.id)
    assert (row.name, row.email, row.status) == (
        "Rina Owner",
        "rina@example.com",
        "active",
    )
    assert all_change_requests(database) == []
    assert mailbox.is_empty
    assert client.get("/me", headers=session.headers).status_code == 200
    assert sessions_of(database, owner.id)[0].revoked_at is None


def test_an_email_of_a_deleted_account_is_refused(
    client, database, admin_in, owner, make_user, mailbox
):
    make_user(email="gone@example.com", deleted=True)
    response = change_email(client, admin_in.headers, owner, "Gone@Example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert mailbox.is_empty


def test_an_email_of_another_admin_is_refused(
    client, database, admin_in, owner, make_user, mailbox
):
    make_user(role=role("admin"), email="second.admin@example.com")
    response = change_email(client, admin_in.headers, owner, "second.admin@example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_a_refused_email_leaves_an_earlier_pending_change_alone(
    client, database, admin_in, owner, make_user, mailbox
):
    make_user(email="other@example.com")
    change_email(client, admin_in.headers, owner, NEW)
    token = last_token(mailbox)
    response = change_email(client, admin_in.headers, owner, "other@example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert detail(client, admin_in, owner)["pendingEmail"] == NEW
    assert confirm_change(client, token).status_code == 204


def test_a_pending_address_of_another_account_does_not_block(
    client, database, admin_in, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    change_email(client, admin_in.headers, other, NEW)
    response = change_email(client, admin_in.headers, owner, NEW)
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == NEW
    assert len(all_change_requests(database)) == 2


def test_the_email_of_the_account_itself_in_other_case_is_not_a_duplicate(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, "RINA@example.com")
    assert response.status_code == 200
