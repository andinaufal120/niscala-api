"""Setting a new password with a password-reset link."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import OpenApiDoc
from password_reset_support import (
    NEW_PASSWORD,
    PASSWORD,
    RESETS,
    assert_error,
    assert_error_code,
    complete_reset,
    expire_token,
    login,
    preview_reset,
    refresh,
    request_reset,
    reset_rows,
    set_columns,
    start_reset,
    stored_hash,
)
from sqlalchemy.orm import Session
from user_account_support import (
    get_row,
    read_user,
    sessions_of,
    set_password,
    set_status,
)

EMAIL = "rina@example.com"
ME_URL = "/me"
SESSIONS_URL = "/me/sessions"


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email=EMAIL)
    set_password(database, user)
    return user


@pytest.fixture
def token(client, owner, mailbox) -> str:
    return start_reset(client, mailbox, EMAIL)


def assert_password_unchanged(client, database, owner) -> None:
    assert login(client, EMAIL, PASSWORD).status_code == 200
    assert_error_code(login(client, EMAIL, NEW_PASSWORD), 401, "INVALID_CREDENTIALS")


# Contract


def test_the_path_declares_exactly_a_post(openapi: OpenApiDoc) -> None:
    methods = {
        m
        for m in openapi.document["paths"][RESETS]
        if m in {"get", "put", "post", "delete", "patch"}
    }
    assert methods == {"post"}


def test_the_operation_is_tagged_auth_and_declares_no_security(
    openapi: OpenApiDoc,
) -> None:
    operation = openapi.operation("post", RESETS)
    assert operation["tags"] == ["auth"]
    assert not operation.get("security")


def test_the_operation_answers_204_without_a_body_besides_the_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("post", RESETS)["responses"]
    assert set(responses) - {"422"} == {"204"}
    assert "content" not in responses["204"]


def test_the_request_body_is_a_password_reset_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("post", RESETS) == "PasswordResetInput"
    schema = openapi.component("PasswordResetInput")
    assert set(schema["required"]) == {"token", "newPassword"}


def test_the_new_password_is_declared_with_its_length_limits(
    openapi: OpenApiDoc,
) -> None:
    prop = openapi.component("PasswordResetInput")["properties"]["newPassword"]
    assert prop["minLength"] == 8
    assert prop["maxLength"] == 128


# Success


def test_a_valid_link_answers_204_without_a_body(client, database, owner, token):
    response = complete_reset(client, token)
    assert response.status_code == 204
    assert response.content == b""


def test_the_new_password_logs_in_and_the_old_one_does_not(
    client, database, owner, token
):
    complete_reset(client, token)
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200
    assert_error_code(login(client, EMAIL, PASSWORD), 401, "INVALID_CREDENTIALS")


def test_the_stored_hash_verifies_against_the_new_password_only(
    client, database, owner, token
):
    from app.services.passwords import verify_password

    before = stored_hash(database, owner.id)
    complete_reset(client, token)
    after = stored_hash(database, owner.id)
    assert after != before
    assert after != NEW_PASSWORD
    assert verify_password(NEW_PASSWORD, after)
    assert not verify_password(PASSWORD, after)


def test_the_new_password_is_not_trimmed(client, database, owner, token):
    spaced = "  mUk3!xqz-Plover  "
    assert complete_reset(client, token, spaced).status_code == 204
    assert login(client, EMAIL, spaced).status_code == 200
    assert login(client, EMAIL, spaced.strip()).status_code == 401


def test_the_link_works_without_any_session(client, database, owner, token):
    assert "Authorization" not in client.headers
    assert complete_reset(client, token).status_code == 204


def test_the_token_is_marked_used(client, database, owner, token):
    complete_reset(client, token)
    (row,) = reset_rows(database, owner.id)
    assert row.used_at is not None
    assert abs(row.used_at - datetime.now(UTC)) < timedelta(minutes=1)
    assert row.replaced_at is None


def test_the_other_fields_of_the_account_are_untouched(client, database, owner, token):
    complete_reset(client, token)
    row = read_user(database, owner.id)
    assert (row.name, row.email, row.role, row.status) == (
        "Rina Owner",
        EMAIL,
        owner.role,
        "active",
    )


def test_the_new_password_may_equal_the_current_one(client, database, owner, token):
    assert complete_reset(client, token, PASSWORD).status_code == 204
    assert login(client, EMAIL, PASSWORD).status_code == 200


@pytest.mark.parametrize("length", [8, 64, 128])
def test_passwords_of_acceptable_lengths_are_accepted(
    client, database, owner, token, length
):
    password = ("T7#vq9-lorem-ipsum-" * 10)[:length]
    assert complete_reset(client, token, password).status_code == 204
    assert login(client, EMAIL, password).status_code == 200


def test_an_account_of_another_role_can_reset(
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
    for email in ("budi@example.com", "mira@example.com"):
        token = start_reset(client, mailbox, email)
        assert complete_reset(client, token).status_code == 204
        assert login(client, email, NEW_PASSWORD).status_code == 200
    assert manager.user_id


# Single use


def test_using_the_link_twice_fails_the_second_time(client, database, owner, token):
    assert complete_reset(client, token).status_code == 204
    assert_error_code(
        complete_reset(client, token, "T7#vq9-lorem-ipsum"),
        409,
        "PASSWORD_RESET_USED",
    )
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200


def test_a_used_link_cannot_be_previewed(client, database, owner, token):
    complete_reset(client, token)
    assert_error_code(preview_reset(client, token), 409, "PASSWORD_RESET_USED")


def test_a_replaced_link_is_used_and_changes_nothing(client, database, owner, mailbox):
    first = start_reset(client, mailbox, EMAIL)
    second = start_reset(client, mailbox, EMAIL)
    assert_error_code(complete_reset(client, first), 409, "PASSWORD_RESET_USED")
    assert_password_unchanged(client, database, owner)
    assert complete_reset(client, second).status_code == 204
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200


def test_other_unused_links_of_the_account_stop_working(client, database, owner, token):
    from app.models import PasswordResetToken

    with Session(database) as db:
        db.add(
            PasswordResetToken(
                user_id=owner.id,
                token_hash="f" * 64,
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )
        db.commit()
    complete_reset(client, token)
    assert all(
        row.used_at is not None or row.replaced_at is not None
        for row in reset_rows(database, owner.id)
    )


def test_a_new_request_after_completion_issues_a_working_link(
    client, database, owner, token, mailbox
):
    complete_reset(client, token)
    again = start_reset(client, mailbox, EMAIL)
    assert complete_reset(client, again, "T7#vq9-lorem-ipsum").status_code == 204
    assert login(client, EMAIL, "T7#vq9-lorem-ipsum").status_code == 200


def test_completing_does_not_touch_another_accounts_link(
    client, database, owner, make_user, mailbox
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    set_password(database, other)
    other_token = start_reset(client, mailbox, "dewi@example.com")
    mine = start_reset(client, mailbox, EMAIL)
    complete_reset(client, mine)
    assert preview_reset(client, other_token).status_code == 200
    assert complete_reset(client, other_token).status_code == 204


def test_completing_does_not_change_another_accounts_password(
    client, database, owner, make_user, token
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    set_password(database, other)
    before = stored_hash(database, other.id)
    complete_reset(client, token)
    assert stored_hash(database, other.id) == before
    assert login(client, "dewi@example.com", PASSWORD).status_code == 200


# Sessions


def test_every_session_of_the_account_is_revoked(
    client, database, owner, token, sign_in
):
    first = sign_in(owner, device_name="Pixel 8")
    second = sign_in(owner, device_name="Galaxy S24")
    complete_reset(client, token)
    rows = sessions_of(database, owner.id)
    assert {row.id for row in rows} >= {first.session_id, second.session_id}
    assert all(row.revoked_at is not None for row in rows)


def test_access_tokens_of_the_account_stop_working(
    client, database, owner, token, sign_in
):
    signed_in = sign_in(owner)
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    complete_reset(client, token)
    response = client.get(ME_URL, headers=signed_in.headers)
    assert_error_code(response, 401, "ACCESS_TOKEN_INVALID")


def test_refresh_tokens_of_the_account_stop_working(
    client, database, owner, token, sign_in
):
    signed_in = sign_in(owner)
    complete_reset(client, token)
    response = refresh(client, signed_in.tokens.refresh_token)
    assert_error_code(response, 401, "REFRESH_TOKEN_INVALID")


def test_sessions_of_other_users_are_untouched(
    client, database, owner, token, make_user, sign_in
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    bystander = sign_in(other)
    complete_reset(client, token)
    assert client.get(ME_URL, headers=bystander.headers).status_code == 200
    assert refresh(client, bystander.tokens.refresh_token).status_code == 200
    assert all(row.revoked_at is None for row in sessions_of(database, other.id))


def test_a_login_after_the_reset_starts_a_working_session(
    client, database, owner, token, sign_in
):
    sign_in(owner)
    complete_reset(client, token)
    response = login(client, EMAIL, NEW_PASSWORD)
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}
    assert client.get(ME_URL, headers=headers).status_code == 200


def test_a_reset_with_no_open_session_succeeds(client, database, owner, token):
    assert complete_reset(client, token).status_code == 204
    assert sessions_of(database, owner.id) == []


# Email verification


def test_the_email_becomes_verified(client, database, make_user, mailbox):
    user = make_user(name="Rina Owner", email=EMAIL, email_verified=False)
    set_password(database, user)
    token = start_reset(client, mailbox, EMAIL)
    complete_reset(client, token)
    assert read_user(database, user.id).email_verified is True


def test_an_unverified_account_can_use_verified_only_endpoints_after_the_reset(
    client, database, make_user, mailbox
):
    user = make_user(name="Rina Owner", email=EMAIL, email_verified=False)
    set_password(database, user)
    before = login(client, EMAIL, PASSWORD)
    headers = {"Authorization": f"Bearer {before.json()['accessToken']}"}
    assert_error_code(
        client.get(SESSIONS_URL, headers=headers), 403, "EMAIL_NOT_VERIFIED"
    )
    complete_reset(client, start_reset(client, mailbox, EMAIL))
    after = login(client, EMAIL, NEW_PASSWORD)
    headers = {"Authorization": f"Bearer {after.json()['accessToken']}"}
    assert client.get(SESSIONS_URL, headers=headers).status_code == 200
    assert after.json()["account"]["emailVerified"] is True


# Failed login count


def test_the_failed_login_count_is_cleared(client, database, owner, token):
    from app.models import LoginFailure

    for _ in range(3):
        assert login(client, EMAIL, "wrong password").status_code == 401
    assert get_row(database, LoginFailure, EMAIL).failed_attempts == 3
    complete_reset(client, token)
    assert get_row(database, LoginFailure, EMAIL) is None


def test_a_locked_account_can_log_in_right_after_the_reset(
    client, database, owner, mailbox
):
    from app.models import LoginFailure

    for _ in range(5):
        login(client, EMAIL, "wrong password")
    assert_error_code(login(client, EMAIL, PASSWORD), 429, "TOO_MANY_LOGIN_ATTEMPTS")
    token = start_reset(client, mailbox, EMAIL)
    assert complete_reset(client, token).status_code == 204
    assert get_row(database, LoginFailure, EMAIL) is None
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200


def test_the_failed_login_count_of_another_email_is_kept(
    client, database, owner, token
):
    from app.models import LoginFailure

    login(client, "nobody@example.com", "wrong password")
    complete_reset(client, token)
    assert get_row(database, LoginFailure, "nobody@example.com").failed_attempts == 1


def test_a_rejected_password_keeps_the_failed_login_count(
    client, database, owner, token
):
    from app.models import LoginFailure

    login(client, EMAIL, "wrong password")
    complete_reset(client, token, "password123")
    assert get_row(database, LoginFailure, EMAIL).failed_attempts == 1


# Expiry


def test_a_link_older_than_thirty_minutes_is_expired(client, database, owner, token):
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    assert_error_code(complete_reset(client, token), 409, "PASSWORD_RESET_EXPIRED")
    assert_password_unchanged(client, database, owner)
    assert reset_rows(database, owner.id)[0].used_at is None


def test_an_expired_link_leaves_the_sessions_open(
    client, database, owner, token, sign_in
):
    signed_in = sign_in(owner)
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    complete_reset(client, token)
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200


def test_a_link_just_inside_the_window_completes(client, database, owner, token):
    from app.models import PasswordResetToken

    (row,) = reset_rows(database, owner.id)
    set_columns(
        database,
        PasswordResetToken,
        row.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=20),
    )
    assert complete_reset(client, token).status_code == 204


def test_used_wins_over_expired_for_a_used_link(client, database, owner, token):
    complete_reset(client, token)
    (row,) = reset_rows(database, owner.id)
    expire_token(database, row.id)
    assert_error_code(complete_reset(client, token), 409, "PASSWORD_RESET_USED")


def test_used_wins_over_expired_for_a_replaced_link(client, database, owner, mailbox):
    first = start_reset(client, mailbox, EMAIL)
    request_reset(client, EMAIL)
    expire_token(database, reset_rows(database, owner.id)[0].id)
    assert_error_code(complete_reset(client, first), 409, "PASSWORD_RESET_USED")


# Unknown and ineligible


def test_an_unknown_token_is_not_found(client, database):
    response = complete_reset(client, "this-token-was-never-issued")
    assert_error_code(response, 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_token_that_differs_in_one_character_is_not_found(
    client, database, owner, token
):
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert_error_code(complete_reset(client, changed), 404, "PASSWORD_RESET_NOT_FOUND")
    assert_password_unchanged(client, database, owner)


def test_a_link_is_not_found_once_the_account_was_deleted(
    client, database, owner, token
):
    from app.models import UserAccount

    set_columns(database, UserAccount, owner.id, deleted_at=datetime.now(UTC))
    assert_error_code(complete_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")
    assert stored_hash(database, owner.id)


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
    assert_error_code(complete_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_every_manager_record_was_deleted(
    client, database, make_user, make_manager, mailbox
):
    from app.models import Manager

    manager = make_manager(
        make_user(), activated=True, email="mira@example.com", password=PASSWORD
    )
    token = start_reset(client, mailbox, "mira@example.com")
    set_columns(database, Manager, manager.id, deleted_at=datetime.now(UTC))
    assert_error_code(complete_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_link_is_not_found_once_the_password_was_removed(
    client, database, owner, token
):
    from app.models import UserAccount

    set_columns(database, UserAccount, owner.id, password_hash=None)
    assert_error_code(complete_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")
    assert stored_hash(database, owner.id) is None


def test_a_suspended_account_cannot_complete_a_link_issued_earlier(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    assert_error_code(complete_reset(client, token), 404, "PASSWORD_RESET_NOT_FOUND")
    set_status(database, owner, "active")
    assert_password_unchanged(client, database, owner)


def test_a_suspended_account_stays_unable_to_log_in_after_a_refused_completion(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    complete_reset(client, token)
    assert_error_code(login(client, EMAIL, PASSWORD), 403, "ACCOUNT_INACTIVE")
    assert_error_code(login(client, EMAIL, NEW_PASSWORD), 401, "INVALID_CREDENTIALS")


def test_reactivating_a_suspended_account_makes_the_link_work_again(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    assert complete_reset(client, token).status_code == 404
    set_status(database, owner, "active")
    assert complete_reset(client, token).status_code == 204
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200


def test_a_suspended_account_link_past_thirty_minutes_stays_expired_after_reactivation(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    expire_token(database, reset_rows(database, owner.id)[0].id)
    set_status(database, owner, "active")
    assert_error_code(complete_reset(client, token), 409, "PASSWORD_RESET_EXPIRED")


# Password rules


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("T7#vq9", id="six_characters"),
        pytest.param("T7#vq9-", id="seven_characters"),
        pytest.param("x", id="one_character"),
        pytest.param("", id="empty"),
        pytest.param("T7#vq9-lorem-ipsum-" * 10, id="over_128_characters"),
        pytest.param(("T7#vq9-lorem-ipsum-" * 10)[:129], id="129_characters"),
    ],
)
def test_a_password_outside_8_to_128_characters_is_a_field_error(
    client, database, owner, token, password
):
    response = complete_reset(client, token, password)
    assert_error(response, 422, "VALIDATION_FAILED", "newPassword")


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("password123", id="common_password"),
        pytest.param("qwertyuiop", id="common_keyboard_row"),
        pytest.param("PASSWORD123", id="common_password_in_capitals"),
        pytest.param("aaaaaaaa", id="repeated_character"),
        pytest.param("12345678", id="ascending_digits"),
        pytest.param("abcdefgh", id="ascending_letters"),
        pytest.param("87654321", id="descending_digits"),
        pytest.param("hgfedcba", id="descending_letters"),
        pytest.param("T7#vq9-NISCALA-lorem", id="contains_the_app_name"),
        pytest.param("T7#vq9-rina-ipsum", id="contains_the_email_local_part"),
        pytest.param(
            "T7#vq9-RINA-ipsum", id="contains_the_email_local_part_in_capitals"
        ),
        pytest.param("T7#vq9-rina owner-ipsum", id="contains_the_name"),
    ],
)
def test_a_guessable_password_is_rejected_with_the_password_field(
    client, database, owner, token, password
):
    response = complete_reset(client, token, password)
    assert_error(response, 422, "PASSWORD_TOO_COMMON", "newPassword")


def test_a_rejected_password_consumes_nothing(client, database, owner, token, sign_in):
    signed_in = sign_in(owner)
    hash_before = stored_hash(database, owner.id)
    assert complete_reset(client, token, "password123").status_code == 422
    assert complete_reset(client, token, "short").status_code == 422
    (row,) = reset_rows(database, owner.id)
    assert row.used_at is None
    assert row.replaced_at is None
    assert stored_hash(database, owner.id) == hash_before
    assert client.get(ME_URL, headers=signed_in.headers).status_code == 200
    assert preview_reset(client, token).status_code == 200


def test_the_same_link_works_after_a_rejected_password(client, database, owner, token):
    assert complete_reset(client, token, "password123").status_code == 422
    assert complete_reset(client, token, NEW_PASSWORD).status_code == 204
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200


def test_a_rejected_password_for_an_unverified_account_leaves_it_unverified(
    client, database, make_user, mailbox
):
    user = make_user(name="Rina Owner", email=EMAIL, email_verified=False)
    set_password(database, user)
    token = start_reset(client, mailbox, EMAIL)
    complete_reset(client, token, "password123")
    assert read_user(database, user.id).email_verified is False


def test_the_personal_rules_use_the_account_of_the_link(
    client, database, owner, make_user, mailbox
):
    other = make_user(name="Budi Santoso", email="budi.s@example.org")
    set_password(database, other)
    token = start_reset(client, mailbox, "budi.s@example.org")
    assert_error(
        complete_reset(client, token, "T7#vq9-budi.s-ipsum"),
        422,
        "PASSWORD_TOO_COMMON",
        "newPassword",
    )
    assert complete_reset(client, token, "T7#vq9-rina-ipsum").status_code == 204


# Token checks come before the password rules


def test_an_unknown_token_is_reported_before_a_guessable_password(client, database):
    response = complete_reset(client, "this-token-was-never-issued", "password123")
    assert_error_code(response, 404, "PASSWORD_RESET_NOT_FOUND")


def test_a_used_link_is_reported_before_a_guessable_password(
    client, database, owner, token
):
    complete_reset(client, token)
    response = complete_reset(client, token, "password123")
    assert_error_code(response, 409, "PASSWORD_RESET_USED")


def test_an_expired_link_is_reported_before_a_guessable_password(
    client, database, owner, token
):
    expire_token(database, reset_rows(database, owner.id)[0].id)
    response = complete_reset(client, token, "password123")
    assert_error_code(response, 409, "PASSWORD_RESET_EXPIRED")


def test_a_suspended_account_is_reported_before_a_guessable_password(
    client, database, owner, token
):
    set_status(database, owner, "inactive")
    response = complete_reset(client, token, "password123")
    assert_error_code(response, 404, "PASSWORD_RESET_NOT_FOUND")


# Validation


@pytest.mark.parametrize(
    ("body", "field"),
    [
        pytest.param({"newPassword": NEW_PASSWORD}, "token", id="missing_token"),
        pytest.param(
            {"token": "", "newPassword": NEW_PASSWORD}, "token", id="empty_token"
        ),
        pytest.param(
            {"token": None, "newPassword": NEW_PASSWORD}, "token", id="null_token"
        ),
        pytest.param(
            {"token": 123, "newPassword": NEW_PASSWORD}, "token", id="numeric_token"
        ),
        pytest.param({"token": "abc"}, "newPassword", id="missing_password"),
        pytest.param(
            {"token": "abc", "newPassword": None}, "newPassword", id="null_password"
        ),
        pytest.param(
            {"token": "abc", "newPassword": 12345678},
            "newPassword",
            id="numeric_password",
        ),
    ],
)
def test_an_invalid_body_is_rejected_with_the_field(client, database, body, field):
    response = client.post(RESETS, json=body)
    assert_error(response, 422, "VALIDATION_FAILED", field)


def test_a_request_without_a_body_is_rejected(client, database):
    response = client.post(RESETS)
    assert_error_code(response, 422, "VALIDATION_FAILED")


def test_the_old_field_name_for_the_password_is_not_accepted(
    client, database, owner, token
):
    response = client.post(RESETS, json={"token": token, "password": NEW_PASSWORD})
    assert_error(response, 422, "VALIDATION_FAILED", "newPassword")
    assert_password_unchanged(client, database, owner)
