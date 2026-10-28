"""Checking a password-reset link before the new password is typed."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import OpenApiDoc
from password_reset_support import (
    PREVIEWS,
    assert_error_code,
    complete_reset,
    expire_token,
    preview_reset,
    request_reset,
    reset_rows,
    set_columns,
    start_reset,
)
from user_account_support import set_password, set_status

EMAIL = "rina@example.com"


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email=EMAIL)
    set_password(database, user)
    return user


@pytest.fixture
def token(client, owner, mailbox) -> str:
    return start_reset(client, mailbox, EMAIL)


# Contract


def test_the_path_declares_exactly_a_post(openapi: OpenApiDoc) -> None:
    methods = {
        m
        for m in openapi.document["paths"][PREVIEWS]
        if m in {"get", "put", "post", "delete", "patch"}
    }
    assert methods == {"post"}


def test_the_operation_is_tagged_auth_and_declares_no_security(
    openapi: OpenApiDoc,
) -> None:
    operation = openapi.operation("post", PREVIEWS)
    assert operation["tags"] == ["auth"]
    assert not operation.get("security")


def test_the_operation_answers_200_besides_the_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("post", PREVIEWS)["responses"]
    assert set(responses) - {"422"} == {"200"}
    assert openapi.response_schema_ref("post", PREVIEWS, 200) == "PasswordResetPreview"


def test_the_request_body_is_a_token_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("post", PREVIEWS) == "TokenInput"


def test_the_preview_schema_has_only_an_email(openapi: OpenApiDoc) -> None:
    schema = openapi.component("PasswordResetPreview")
    assert set(schema["properties"]) == {"email"}
    assert schema["required"] == ["email"]


# Valid link


def test_a_valid_link_returns_the_account_email(client, database, owner, token):
    response = preview_reset(client, token)
    assert response.status_code == 200
    assert response.json() == {"email": EMAIL}


def test_the_email_is_the_stored_normalized_one(client, database, owner, mailbox):
    token = start_reset(client, mailbox, "  RINA@Example.COM ")
    assert preview_reset(client, token).json() == {"email": EMAIL}


def test_previewing_does_not_consume_the_link(client, database, owner, token):
    for _ in range(3):
        assert preview_reset(client, token).status_code == 200
    (row,) = reset_rows(database, owner.id)
    assert row.used_at is None
    assert row.replaced_at is None
    assert complete_reset(client, token).status_code == 204


def test_previewing_changes_nothing_in_the_database(client, database, owner, token):
    (before,) = reset_rows(database, owner.id)
    preview_reset(client, token)
    (after,) = reset_rows(database, owner.id)
    assert (after.used_at, after.replaced_at, after.expires_at) == (
        before.used_at,
        before.replaced_at,
        before.expires_at,
    )


def test_the_preview_works_without_any_session(client, database, owner, token):
    assert "Authorization" not in client.headers
    assert preview_reset(client, token).status_code == 200


def test_a_logged_in_caller_can_preview(client, database, owner, token, sign_in):
    headers = sign_in(owner).headers
    response = client.post(PREVIEWS, json={"token": token}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"email": EMAIL}


def test_a_link_for_an_unverified_account_previews(
    client, database, make_user, mailbox
):
    user = make_user(name="Rina Owner", email=EMAIL, email_verified=False)
    set_password(database, user)
    token = start_reset(client, mailbox, EMAIL)
    assert preview_reset(client, token).json() == {"email": EMAIL}


def test_each_account_previews_its_own_email(
    client, database, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    set_password(database, other)
    mine = start_reset(client, mailbox, EMAIL)
    theirs = start_reset(client, mailbox, "dewi@example.com")
    assert preview_reset(client, mine).json() == {"email": EMAIL}
    assert preview_reset(client, theirs).json() == {"email": "dewi@example.com"}


# Expiry


def test_a_link_older_than_thirty_minutes_is_expired(client, database, owner, token):
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    assert_error_code(preview_reset(client, token), 409, "PASSWORD_RESET_EXPIRED")


def test_an_expired_preview_changes_nothing(client, database, owner, token):
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    preview_reset(client, token)
    (after,) = reset_rows(database, owner.id)
    assert after.used_at is None
    assert after.replaced_at is None


def test_a_link_just_inside_the_window_still_previews(client, database, owner, token):
    from app.models import PasswordResetToken

    (row,) = reset_rows(database, owner.id)
    set_columns(
        database,
        PasswordResetToken,
        row.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=20),
    )
    assert preview_reset(client, token).status_code == 200


# Used and replaced


def test_a_replaced_link_is_used(client, database, owner, mailbox):
    first = start_reset(client, mailbox, EMAIL)
    second = start_reset(client, mailbox, EMAIL)
    assert_error_code(preview_reset(client, first), 409, "PASSWORD_RESET_USED")
    assert preview_reset(client, second).status_code == 200


def test_a_link_used_to_reset_the_password_is_used(client, database, owner, token):
    complete_reset(client, token)
    assert_error_code(preview_reset(client, token), 409, "PASSWORD_RESET_USED")


def test_used_wins_over_expired_for_a_used_link(client, database, owner, token):
    complete_reset(client, token)
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    assert_error_code(preview_reset(client, token), 409, "PASSWORD_RESET_USED")


def test_used_wins_over_expired_for_a_replaced_link(client, database, owner, mailbox):
    first = start_reset(client, mailbox, EMAIL)
    request_reset(client, EMAIL)
    expire_token(database, reset_rows(database, owner.id)[0].id)
    assert_error_code(preview_reset(client, first), 409, "PASSWORD_RESET_USED")


# Unknown and ineligible


def test_an_unknown_token_is_not_found(client, database):
    response = preview_reset(client, "this-token-was-never-issued")
    assert_error_code(response, 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_token_that_differs_in_one_character_is_not_found(
    client, database, owner, token
):
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert_error_code(preview_reset(client, changed), 404, "PASSWORD_RESET_NOT_FOUND")


def test_the_error_names_no_field(client, database):
    response = preview_reset(client, "this-token-was-never-issued")
    assert response.json()["field"] is None


def test_a_link_is_not_found_once_the_account_was_deleted(
    client, database, owner, token
):
    from app.models import UserAccount

    set_columns(database, UserAccount, owner.id, deleted_at=datetime.now(UTC))
    assert_error_code(preview_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_the_tenant_was_deleted(
    client,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    mailbox,
):
    from app.models import Tenant

    tenant = make_verified_tenant(
        make_room(make_property(make_user())), email="budi@example.com"
    )
    set_password(database, tenant.user)
    token = start_reset(client, mailbox, "budi@example.com")
    set_columns(database, Tenant, tenant.id, deleted_at=datetime.now(UTC))
    assert_error_code(preview_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_every_manager_record_was_deleted(
    client, database, make_user, make_manager, mailbox
):
    from app.models import Manager

    manager = make_manager(
        make_user(), activated=True, email="mira@example.com", password="x" * 12
    )
    token = start_reset(client, mailbox, "mira@example.com")
    set_columns(database, Manager, manager.id, deleted_at=datetime.now(UTC))
    assert_error_code(preview_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_the_account_was_suspended(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    assert_error_code(preview_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_the_password_was_removed(
    client, database, owner, token
):
    from app.models import UserAccount

    set_columns(database, UserAccount, owner.id, password_hash=None)
    assert_error_code(preview_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_reactivating_a_suspended_account_makes_the_link_work_again(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    assert preview_reset(client, token).status_code == 404
    set_status(database, owner, "active")
    assert preview_reset(client, token).json() == {"email": EMAIL}


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
    response = client.post(PREVIEWS, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["field"] == "token"


def test_a_request_without_a_body_is_rejected(client, database):
    response = client.post(PREVIEWS)
    assert_error_code(response, 422, "VALIDATION_FAILED")
