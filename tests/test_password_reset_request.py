"""Asking for a password-reset link."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import OpenApiDoc
from password_reset_support import (
    PASSWORD,
    REQUESTS,
    all_reset_rows,
    assert_close,
    assert_error_code,
    last_reset_token,
    request_reset,
    reset_rows,
    snapshot,
)
from user_account_support import (
    get_row,
    invitation_base,
    login,
    read_user,
    set_columns,
    set_password,
    set_status,
    token_in,
)

EMAIL = "rina@example.com"


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email=EMAIL)
    set_password(database, user)
    return user


def assert_nothing_sent_or_stored(database, mailbox) -> None:
    assert mailbox.is_empty
    assert all_reset_rows(database) == []


# Contract


def test_the_path_declares_exactly_a_post(openapi: OpenApiDoc) -> None:
    methods = {
        m
        for m in openapi.document["paths"][REQUESTS]
        if m in {"get", "put", "post", "delete", "patch"}
    }
    assert methods == {"post"}


def test_the_operation_is_tagged_auth_and_declares_no_security(
    openapi: OpenApiDoc,
) -> None:
    operation = openapi.operation("post", REQUESTS)
    assert operation["tags"] == ["auth"]
    assert not operation.get("security")


def test_the_operation_answers_202_without_a_body_besides_the_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("post", REQUESTS)["responses"]
    assert set(responses) - {"422"} == {"202"}
    assert "content" not in responses["202"]


def test_the_request_body_is_a_password_reset_request_input(
    openapi: OpenApiDoc,
) -> None:
    assert openapi.request_schema_ref("post", REQUESTS) == "PasswordResetRequestInput"
    schema = openapi.component("PasswordResetRequestInput")
    assert schema["required"] == ["email"]


# Eligible account


def test_an_eligible_account_gets_202_with_an_empty_body(
    client, database, owner, mailbox
):
    response = request_reset(client, EMAIL)
    assert response.status_code == 202
    assert response.content == b""


def test_exactly_one_email_is_sent_to_the_account_address(
    client, database, owner, mailbox
):
    request_reset(client, EMAIL)
    assert len(mailbox.reset_links) == 1
    assert mailbox.reset_links[0][0] == EMAIL
    assert mailbox.codes == []
    assert mailbox.links == []
    assert mailbox.notices == []


def test_the_link_starts_with_the_configured_base_and_carries_a_token(
    client, database, owner, mailbox
):
    request_reset(client, EMAIL)
    url = mailbox.reset_links[0][1]
    assert url.startswith(invitation_base())
    assert token_in(url)


@pytest.mark.parametrize(
    "typed",
    [
        "RINA@EXAMPLE.COM",
        "Rina@Example.com",
        "  rina@example.com",
        "rina@example.com  ",
        "  Rina@Example.COM  ",
    ],
)
def test_the_email_is_trimmed_and_compared_without_case(
    client, database, owner, mailbox, typed
):
    response = request_reset(client, typed)
    assert response.status_code == 202
    assert [to for to, _ in mailbox.reset_links] == [EMAIL]
    assert len(reset_rows(database, owner.id)) == 1


def test_one_token_row_is_stored_for_the_account(client, database, owner, mailbox):
    request_reset(client, EMAIL)
    (row,) = reset_rows(database, owner.id)
    assert row.user_id == owner.id
    assert row.used_at is None
    assert row.replaced_at is None
    assert_close(row.created_at, datetime.now(UTC), 60)


def test_the_link_is_valid_for_thirty_minutes(client, database, owner, mailbox):
    request_reset(client, EMAIL)
    (row,) = reset_rows(database, owner.id)
    assert_close(row.expires_at, datetime.now(UTC) + timedelta(minutes=30), 60)
    assert_close(row.expires_at, row.created_at + timedelta(minutes=30), 5)


def test_only_a_hash_of_the_token_is_stored(client, database, owner, mailbox):
    request_reset(client, EMAIL)
    token = last_reset_token(mailbox)
    (row,) = reset_rows(database, owner.id)
    assert row.token_hash
    assert row.token_hash != token
    assert token not in row.token_hash
    assert token not in str([getattr(row, c.name) for c in row.__table__.columns])


def test_every_request_issues_a_different_token(client, database, owner, mailbox):
    request_reset(client, EMAIL)
    request_reset(client, EMAIL)
    first, second = (token_in(url) for _, url in mailbox.reset_links)
    assert first != second


def test_the_request_works_without_any_session(client, database, owner, mailbox):
    assert "Authorization" not in client.headers
    assert request_reset(client, EMAIL).status_code == 202
    assert len(mailbox.reset_links) == 1


def test_a_logged_in_caller_can_request_a_reset(
    client, database, owner, mailbox, sign_in
):
    signed_in = sign_in(owner)
    response = request_reset(client, EMAIL, headers=signed_in.headers)
    assert response.status_code == 202
    assert len(mailbox.reset_links) == 1


def test_a_logged_in_caller_can_request_a_reset_for_another_account(
    client, database, owner, mailbox, sign_in, make_user
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    set_password(database, other)
    signed_in = sign_in(owner)
    assert (
        request_reset(client, "dewi@example.com", headers=signed_in.headers).status_code
        == 202
    )
    assert [to for to, _ in mailbox.reset_links] == ["dewi@example.com"]


def test_an_account_with_an_unverified_email_is_eligible(
    client, database, make_user, mailbox
):
    user = make_user(name="Rina Owner", email=EMAIL, email_verified=False)
    set_password(database, user)
    assert request_reset(client, EMAIL).status_code == 202
    assert [to for to, _ in mailbox.reset_links] == [EMAIL]
    assert len(reset_rows(database, user.id)) == 1


def test_the_link_is_sent_to_the_current_address_after_an_email_change(
    client, database, owner, mailbox
):
    from app.models import UserAccount

    set_columns(database, UserAccount, owner.id, email="rina.new@example.org")
    assert request_reset(client, EMAIL).status_code == 202
    assert mailbox.is_empty
    assert request_reset(client, "rina.new@example.org").status_code == 202
    assert [to for to, _ in mailbox.reset_links] == ["rina.new@example.org"]


def test_eligible_tenants_and_managers_get_a_link(
    client,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    mailbox,
):
    landlord = make_user(name="Landlord")
    tenant = make_verified_tenant(
        make_room(make_property(landlord)), email="budi@example.com"
    )
    set_password(database, tenant.user)
    manager = make_manager(
        landlord, activated=True, email="mira@example.com", password=PASSWORD
    )
    request_reset(client, "budi@example.com")
    request_reset(client, "mira@example.com")
    assert [to for to, _ in mailbox.reset_links] == [
        "budi@example.com",
        "mira@example.com",
    ]
    assert len(reset_rows(database, tenant.id)) == 1
    assert len(reset_rows(database, manager.user_id)) == 1


def test_the_request_does_not_touch_the_failed_login_count(
    client, database, owner, mailbox
):
    from app.models import LoginFailure

    for _ in range(3):
        assert login(client, EMAIL, "wrong password").status_code == 401
    request_reset(client, EMAIL)
    request_reset(client, "nobody@example.com")
    assert get_row(database, LoginFailure, EMAIL).failed_attempts == 3
    assert get_row(database, LoginFailure, "nobody@example.com") is None


def test_the_request_does_not_change_the_account(client, database, owner, mailbox):
    before = read_user(database, owner.id)
    request_reset(client, EMAIL)
    after = read_user(database, owner.id)
    assert after.password_hash == before.password_hash
    assert after.status == before.status
    assert login(client, EMAIL).status_code == 200


# Replacing the previous link


def test_a_new_request_replaces_the_previous_link(client, database, owner, mailbox):
    request_reset(client, EMAIL)
    request_reset(client, EMAIL)
    first, second = reset_rows(database, owner.id)
    assert first.replaced_at is not None
    assert second.replaced_at is None
    assert second.used_at is None
    assert len(mailbox.reset_links) == 2


def test_three_requests_leave_only_the_newest_link_live(
    client, database, owner, mailbox
):
    for _ in range(3):
        request_reset(client, EMAIL)
    rows = reset_rows(database, owner.id)
    assert [r.replaced_at is None for r in rows] == [False, False, True]


def test_a_request_for_one_account_does_not_replace_another_accounts_link(
    client, database, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    set_password(database, other)
    request_reset(client, "dewi@example.com")
    request_reset(client, EMAIL)
    (row,) = reset_rows(database, other.id)
    assert row.replaced_at is None


# Ineligible accounts and the indistinguishable answer


def test_an_unknown_email_gets_202_and_nothing_is_sent_or_stored(
    client, database, owner, mailbox
):
    response = request_reset(client, "nobody@example.com")
    assert response.status_code == 202
    assert response.content == b""
    assert_nothing_sent_or_stored(database, mailbox)


def test_an_account_without_a_password_receives_nothing(
    client, database, make_user, mailbox
):
    make_user(email=EMAIL, password_hash=None)
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_suspended_account_receives_nothing(client, database, owner, mailbox):
    set_status(database, owner, "inactive")
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_deleted_account_receives_nothing(client, database, make_user, mailbox):
    user = make_user(email=EMAIL, deleted=True)
    set_password(database, user)
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_deleted_tenant_receives_nothing(
    client,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    mailbox,
):
    tenant = make_verified_tenant(
        make_room(make_property(make_user())), email=EMAIL, deleted=True
    )
    set_password(database, tenant.user)
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_manager_whose_records_are_all_deleted_receives_nothing(
    client, database, make_user, make_manager, mailbox
):
    make_manager(
        make_user(), activated=True, email=EMAIL, password=PASSWORD, deleted=True
    )
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_manager_with_a_live_record_somewhere_receives_a_link(
    client, database, make_user, make_manager, mailbox
):
    first = make_manager(
        make_user(name="Owner One"),
        activated=True,
        email=EMAIL,
        password=PASSWORD,
        deleted=True,
    )
    make_manager(make_user(name="Owner Two"), activated=True, user=first.user)
    assert request_reset(client, EMAIL).status_code == 202
    assert [to for to, _ in mailbox.reset_links] == [EMAIL]


def test_an_invited_tenant_who_has_not_activated_receives_nothing(
    client, database, make_user, make_property, make_room, make_tenant, mailbox
):
    make_tenant(make_room(make_property(make_user())), email=EMAIL)
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_an_invited_tenant_who_has_not_activated_and_has_no_email_receives_nothing(
    client, database, make_user, make_property, make_room, make_tenant, mailbox
):
    make_tenant(make_room(make_property(make_user())))
    assert request_reset(client, EMAIL).status_code == 202
    assert_nothing_sent_or_stored(database, mailbox)


def test_the_answer_is_identical_for_every_kind_of_email(
    client,
    database,
    owner,
    make_user,
    make_manager,
    make_property,
    make_room,
    make_tenant,
    mailbox,
):
    suspended = make_user(email="suspended@example.com", status="inactive")
    set_password(database, suspended)
    deleted = make_user(email="deleted@example.com", deleted=True)
    set_password(database, deleted)
    make_user(email="google@example.com", password_hash=None)
    make_tenant(
        make_room(make_property(make_user(name="Landlord"))),
        email="invited@example.com",
    )
    emails = [
        EMAIL,
        "nobody@example.com",
        "suspended@example.com",
        "deleted@example.com",
        "google@example.com",
        "invited@example.com",
    ]
    answers = [snapshot(request_reset(client, email)) for email in emails]
    assert len({repr(answer) for answer in answers}) == 1
    assert answers[0][0] == 202
    assert answers[0][1] == b""
    assert len(mailbox.reset_links) == 1


def test_an_ineligible_request_leaves_an_existing_link_alone(
    client, database, owner, mailbox
):
    request_reset(client, EMAIL)
    request_reset(client, "nobody@example.com")
    (row,) = reset_rows(database, owner.id)
    assert row.replaced_at is None


def test_a_request_for_a_suspended_account_leaves_its_earlier_link_alone(
    client, database, owner, mailbox
):
    request_reset(client, EMAIL)
    set_status(database, owner, "inactive")
    request_reset(client, EMAIL)
    (row,) = reset_rows(database, owner.id)
    assert row.replaced_at is None
    assert len(mailbox.reset_links) == 1


# Validation


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing_email"),
        pytest.param({"email": ""}, id="empty_email"),
        pytest.param({"email": None}, id="null_email"),
        pytest.param({"email": 123}, id="numeric_email"),
        pytest.param({"email": "not-an-email"}, id="no_at_sign"),
        pytest.param({"email": "rina@"}, id="no_domain"),
        pytest.param({"email": "   "}, id="blank_email"),
    ],
)
def test_an_invalid_body_is_rejected_with_the_email_field(
    client, database, mailbox, body
):
    response = client.post(REQUESTS, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["field"] == "email"
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_request_without_a_body_is_rejected(client, database, mailbox):
    response = client.post(REQUESTS)
    assert_error_code(response, 422, "VALIDATION_FAILED")
    assert_nothing_sent_or_stored(database, mailbox)


def test_a_login_with_the_old_password_still_works_after_a_request(
    client, database, owner, mailbox
):
    request_reset(client, EMAIL)
    assert login(client, EMAIL).status_code == 200
