"""Confirming an email change with the emailed link."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import OpenApiDoc
from user_account_support import (
    EMAIL_CHANGES,
    all_change_requests,
    assert_close,
    assert_error,
    assert_error_code,
    change_email,
    change_requests,
    confirm_change,
    delete_account,
    edit_account,
    expire_change_request,
    get_account,
    last_token,
    listed_ids,
    login,
    read_user,
    sessions_of,
    set_columns,
    set_password,
)

NEW = "new.address@example.org"


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email="rina@example.com")
    set_password(database, user)
    return user


def start(client, admin_in, user, mailbox, new: str = NEW) -> str:
    """Ask for an email change and return the token of its link."""
    response = change_email(client, admin_in.headers, user, new)
    assert response.status_code == 200, response.text
    return last_token(mailbox)


# Contract


def test_the_path_declares_exactly_a_post(openapi: OpenApiDoc) -> None:
    methods = {
        m
        for m in openapi.document["paths"][EMAIL_CHANGES]
        if m in {"get", "put", "post", "delete", "patch"}
    }
    assert methods == {"post"}


def test_the_operation_is_tagged_auth(openapi: OpenApiDoc) -> None:
    assert openapi.operation("post", EMAIL_CHANGES)["tags"] == ["auth"]


def test_the_operation_declares_no_security(openapi: OpenApiDoc) -> None:
    assert not openapi.operation("post", EMAIL_CHANGES).get("security")


def test_the_operation_answers_204_besides_the_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("post", EMAIL_CHANGES)["responses"]
    assert set(responses) - {"422"} == {"204"}
    assert "content" not in responses["204"]


def test_the_request_body_is_a_token_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("post", EMAIL_CHANGES) == "TokenInput"


def test_the_operation_has_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("post", EMAIL_CHANGES).get("parameters", []) == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/user-accounts"),
        ("get", "/user-accounts/{userAccountId}"),
        ("put", "/user-accounts/{userAccountId}"),
        ("delete", "/user-accounts/{userAccountId}"),
    ],
)
def test_the_user_account_operations_still_require_bearer_auth(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


# Success


def test_a_valid_link_answers_204_without_a_body(
    client, database, admin_in, owner, mailbox
):
    response = confirm_change(client, start(client, admin_in, owner, mailbox))
    assert response.status_code == 204
    assert response.content == b""


def test_confirming_replaces_the_login_email(
    client, database, admin_in, owner, mailbox
):
    confirm_change(client, start(client, admin_in, owner, mailbox))
    assert read_user(database, owner.id).email == NEW
    body = get_account(client, admin_in.headers, owner.id).json()
    assert body["email"] == NEW
    assert body["pendingEmail"] is None
    assert body["pendingEmailExpiresAt"] is None


def test_the_new_email_is_stored_normalized(client, database, admin_in, owner, mailbox):
    confirm_change(
        client, start(client, admin_in, owner, mailbox, "  New.Address@Example.ORG ")
    )
    assert read_user(database, owner.id).email == NEW


def test_the_request_is_marked_used(client, database, admin_in, owner, mailbox):
    confirm_change(client, start(client, admin_in, owner, mailbox))
    (row,) = change_requests(database, owner.id)
    assert_close(row.used_at, datetime.now(UTC), 60)


def test_login_works_with_the_new_email_and_no_longer_with_the_old_one(
    client, database, admin_in, owner, mailbox
):
    confirm_change(client, start(client, admin_in, owner, mailbox))
    assert login(client, NEW).status_code == 200
    assert login(client, "NEW.address@EXAMPLE.org").status_code == 200
    assert_error(login(client, "rina@example.com"), 401, "INVALID_CREDENTIALS")


def test_sessions_stay_open(client, database, admin_in, owner, mailbox, sign_in):
    session = sign_in(owner)
    confirm_change(client, start(client, admin_in, owner, mailbox))
    response = client.get("/me", headers=session.headers)
    assert response.status_code == 200
    assert response.json()["email"] == NEW
    assert sessions_of(database, owner.id)[0].revoked_at is None


@pytest.mark.parametrize("verified", [True, False])
def test_the_verification_state_of_the_email_is_left_as_it_was(
    client, database, admin_in, make_user, mailbox, verified
):
    user = make_user(email="rina@example.com", email_verified=verified)
    confirm_change(client, start(client, admin_in, user, mailbox))
    assert read_user(database, user.id).email_verified is verified


def test_the_name_and_status_of_the_account_are_untouched(
    client, database, admin_in, owner, mailbox
):
    confirm_change(client, start(client, admin_in, owner, mailbox))
    row = read_user(database, owner.id)
    assert (row.name, row.status) == ("Rina Owner", "active")


def test_confirming_does_not_touch_another_accounts_pending_change(
    client, database, admin_in, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    start(client, admin_in, other, mailbox, "dewi.new@example.org")
    confirm_change(client, start(client, admin_in, owner, mailbox))
    assert read_user(database, other.id).email == "dewi@example.com"
    body = get_account(client, admin_in.headers, other.id).json()
    assert body["pendingEmail"] == "dewi.new@example.org"


def test_the_list_search_follows_the_new_email(
    client, database, admin_in, owner, mailbox
):
    confirm_change(client, start(client, admin_in, owner, mailbox))
    assert listed_ids(client, admin_in.headers, email="new.address") == [str(owner.id)]
    assert listed_ids(client, admin_in.headers, email="rina@") == []


def test_a_link_for_an_inactive_account_still_confirms(
    client, database, admin_in, owner, mailbox
):
    response = change_email(client, admin_in.headers, owner, NEW, status="inactive")
    assert response.status_code == 200
    assert confirm_change(client, last_token(mailbox)).status_code == 204
    row = read_user(database, owner.id)
    assert (row.email, row.status) == (NEW, "inactive")


def test_the_link_works_without_any_session(client, database, admin_in, owner, mailbox):
    token = start(client, admin_in, owner, mailbox)
    assert "Authorization" not in client.headers
    assert confirm_change(client, token).status_code == 204


@pytest.mark.parametrize("kind", ["tenant", "manager"])
def test_a_tenant_or_manager_link_confirms(
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
        target = make_verified_tenant(make_room(make_property(landlord))).user
    else:
        target = make_manager(landlord, activated=True).user
    assert (
        confirm_change(client, start(client, admin_in, target, mailbox)).status_code
        == 204
    )
    assert read_user(database, target.id).email == NEW


# Single use


def test_using_the_link_twice_fails_the_second_time(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    assert confirm_change(client, token).status_code == 204
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == NEW


def test_a_used_link_stays_used_when_another_change_was_made_since(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    confirm_change(client, token)
    start(client, admin_in, owner, mailbox, "third@example.org")
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == NEW


def test_a_replaced_link_is_used(client, database, admin_in, owner, mailbox):
    first = start(client, admin_in, owner, mailbox)
    second = start(client, admin_in, owner, mailbox, "second@example.org")
    assert_error_code(confirm_change(client, first), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == "rina@example.com"
    assert confirm_change(client, second).status_code == 204


def test_a_cancelled_link_is_used(client, database, admin_in, owner, mailbox):
    token = start(client, admin_in, owner, mailbox)
    edit_account(client, admin_in.headers, owner)
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")
    assert read_user(database, owner.id).email == "rina@example.com"


# Expiry


def test_a_link_older_than_seven_days_is_expired(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    (row,) = change_requests(database, owner.id)
    expire_change_request(database, row.id)
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_EXPIRED")
    assert read_user(database, owner.id).email == "rina@example.com"
    assert change_requests(database, owner.id)[0].used_at is None


def test_a_link_that_is_still_valid_just_before_expiry_confirms(
    client, database, admin_in, owner, mailbox
):
    from app.models import EmailChangeRequest

    token = start(client, admin_in, owner, mailbox)
    (row,) = change_requests(database, owner.id)
    set_columns(
        database,
        EmailChangeRequest,
        row.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert confirm_change(client, token).status_code == 204


def test_used_wins_over_expired_for_a_used_link(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    confirm_change(client, token)
    (row,) = change_requests(database, owner.id)
    expire_change_request(database, row.id)
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")


def test_used_wins_over_expired_for_a_replaced_link(
    client, database, admin_in, owner, mailbox
):
    first = start(client, admin_in, owner, mailbox)
    start(client, admin_in, owner, mailbox, "second@example.org")
    expire_change_request(database, change_requests(database, owner.id)[0].id)
    assert_error_code(confirm_change(client, first), 409, "EMAIL_CHANGE_USED")


def test_used_wins_over_expired_for_a_cancelled_link(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    edit_account(client, admin_in.headers, owner)
    expire_change_request(database, change_requests(database, owner.id)[0].id)
    assert_error_code(confirm_change(client, token), 409, "EMAIL_CHANGE_USED")


# Unknown and deleted


def test_an_unknown_token_is_not_found(client, database):
    response = confirm_change(client, "this-token-was-never-issued")
    assert_error_code(response, 404, "EMAIL_CHANGE_NOT_FOUND")


def test_a_token_that_differs_in_one_character_is_not_found(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert_error_code(confirm_change(client, changed), 404, "EMAIL_CHANGE_NOT_FOUND")
    assert read_user(database, owner.id).email == "rina@example.com"


def test_a_token_is_not_found_when_the_account_was_deleted(
    client, database, admin_in, owner, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    assert_error_code(confirm_change(client, token), 404, "EMAIL_CHANGE_NOT_FOUND")
    assert read_user(database, owner.id).email == "rina@example.com"


def test_a_token_is_not_found_when_the_tenant_was_deleted(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    mailbox,
):
    from app.models import Tenant

    tenant = make_verified_tenant(make_room(make_property(make_user())))
    token = start(client, admin_in, tenant.user, mailbox)
    set_columns(database, Tenant, tenant.id, deleted_at=datetime.now(UTC))
    assert_error_code(confirm_change(client, token), 404, "EMAIL_CHANGE_NOT_FOUND")


def test_a_token_is_not_found_when_every_manager_record_was_deleted(
    client, database, admin_in, make_user, make_manager, mailbox
):
    from app.models import Manager

    manager = make_manager(make_user(), activated=True)
    token = start(client, admin_in, manager.user, mailbox)
    set_columns(database, Manager, manager.id, deleted_at=datetime.now(UTC))
    assert_error_code(confirm_change(client, token), 404, "EMAIL_CHANGE_NOT_FOUND")


# New email taken in the meantime


def test_an_email_taken_in_the_meantime_is_refused_and_the_link_stays_unused(
    client, database, admin_in, owner, make_user, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    make_user(email=NEW)
    response = confirm_change(client, token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    assert read_user(database, owner.id).email == "rina@example.com"
    (row,) = change_requests(database, owner.id)
    assert row.used_at is None
    assert_error(
        confirm_change(client, token), 409, "EMAIL_ALREADY_REGISTERED", "email"
    )


def test_an_email_taken_by_a_deleted_account_in_the_meantime_is_refused(
    client, database, admin_in, owner, make_user, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    make_user(email=NEW, deleted=True)
    response = confirm_change(client, token)
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_the_second_of_two_pending_changes_to_one_address_is_refused(
    client, database, admin_in, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    other_token = start(client, admin_in, other, mailbox)
    token = start(client, admin_in, owner, mailbox)
    assert confirm_change(client, other_token).status_code == 204
    assert_error(
        confirm_change(client, token), 409, "EMAIL_ALREADY_REGISTERED", "email"
    )
    assert read_user(database, owner.id).email == "rina@example.com"


def test_nothing_else_changes_after_a_refused_confirmation(
    client, database, admin_in, owner, make_user, mailbox
):
    token = start(client, admin_in, owner, mailbox)
    make_user(email=NEW)
    confirm_change(client, token)
    assert len(all_change_requests(database)) == 1
    assert get_account(client, admin_in.headers, owner.id).json()["pendingEmail"] == NEW


# Validation


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing_token"),
        pytest.param({"token": ""}, id="empty_token"),
        pytest.param({"token": None}, id="null_token"),
        pytest.param({"token": 123}, id="numeric_token"),
    ],
)
def test_an_invalid_body_is_rejected_with_the_token_field(client, database, body):
    response = client.post(EMAIL_CHANGES, json=body)
    assert_error(response, 422, "VALIDATION_FAILED", "token")


def test_a_request_without_a_body_is_rejected(client, database):
    response = client.post(EMAIL_CHANGES)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
