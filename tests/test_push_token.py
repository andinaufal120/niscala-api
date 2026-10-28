"""Registering the push token of the current session."""

import pytest
from notification_support import (
    PUSH_TOKEN,
    assert_error,
    register_token,
    revoke_session,
    role,
)

ROLES = ["tenant", "owner", "manager"]


def put_token(client, signed_in, token):
    return client.put(PUSH_TOKEN, json={"token": token}, headers=signed_in.headers)


def stored_token(read_session, signed_in):
    return read_session(signed_in.session_id).push_token


@pytest.fixture
def owner_in(make_user, sign_in):
    return sign_in(make_user(name="Rina Owner"))


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, database):
    response = client.put(PUSH_TOKEN, json={"token": "abc"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, database):
    response = client.put(
        PUSH_TOKEN, json={"token": "abc"}, headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ROLES)
def test_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, read_session, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(put_token(client, session, "abc"), 403, "EMAIL_NOT_VERIFIED")
    assert stored_token(read_session, session) is None


def test_an_admin_is_forbidden(client, database, make_user, sign_in, read_session):
    session = sign_in(make_user(role=role("admin")))
    assert_error(put_token(client, session, "abc"), 403, "FORBIDDEN")
    assert stored_token(read_session, session) is None


def test_an_admin_is_refused_before_the_body_is_checked(
    client, database, make_user, sign_in
):
    session = sign_in(make_user(role=role("admin")))
    response = client.put(PUSH_TOKEN, json={}, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


# Registering


@pytest.mark.parametrize("name", ROLES)
def test_registering_answers_no_content(
    client, database, make_user, sign_in, read_session, name
):
    session = sign_in(make_user(role=role(name)))
    response = put_token(client, session, "fcm-token-1")
    assert response.status_code == 204
    assert response.content == b""
    assert stored_token(read_session, session) == "fcm-token-1"


def test_a_new_session_has_no_token(owner_in, read_session):
    assert stored_token(read_session, owner_in) is None


def test_registering_again_replaces_the_token(client, database, owner_in, read_session):
    register_token(client, owner_in, "first")
    register_token(client, owner_in, "second")
    assert stored_token(read_session, owner_in) == "second"


def test_registering_the_same_token_again_keeps_it(
    client, database, owner_in, read_session
):
    register_token(client, owner_in, "same")
    register_token(client, owner_in, "same")
    assert stored_token(read_session, owner_in) == "same"


def test_the_token_is_trimmed(client, database, owner_in, read_session):
    register_token(client, owner_in, "  fcm:token-123 \n")
    assert stored_token(read_session, owner_in) == "fcm:token-123"


def test_the_token_keeps_its_inner_characters(client, database, owner_in, read_session):
    token = "dXNlci0x:APA91b-Gq_Zz.9~+/=x"
    register_token(client, owner_in, token)
    assert stored_token(read_session, owner_in) == token


@pytest.mark.parametrize("length", [1, 512, 1024])
def test_a_token_of_1_to_1024_characters_is_accepted(
    client, database, owner_in, read_session, length
):
    token = "t" * length
    register_token(client, owner_in, token)
    assert stored_token(read_session, owner_in) == token


def test_a_token_of_1024_characters_after_trimming_is_accepted(
    client, database, owner_in, read_session
):
    register_token(client, owner_in, " " + "t" * 1024 + " ")
    assert stored_token(read_session, owner_in) == "t" * 1024


# Which session holds the token


def test_the_token_belongs_to_the_current_session_only(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, device_name="Pixel 8")
    tablet = sign_in(user, device_name="Galaxy Tab")
    register_token(client, phone, "phone-token")
    assert stored_token(read_session, phone) == "phone-token"
    assert stored_token(read_session, tablet) is None


def test_every_session_of_a_user_keeps_its_own_token(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, device_name="Pixel 8")
    tablet = sign_in(user, device_name="Galaxy Tab")
    register_token(client, phone, "phone-token")
    register_token(client, tablet, "tablet-token")
    register_token(client, phone, "phone-token-2")
    assert stored_token(read_session, phone) == "phone-token-2"
    assert stored_token(read_session, tablet) == "tablet-token"


def test_the_token_of_another_user_is_untouched(
    client, database, owner_in, make_user, sign_in, read_session
):
    other = sign_in(make_user(name="Other Owner"))
    register_token(client, other, "other-token")
    register_token(client, owner_in, "my-token")
    assert stored_token(read_session, other) == "other-token"
    assert stored_token(read_session, owner_in) == "my-token"


def test_the_token_stays_when_the_settings_are_saved(
    client, database, owner_in, read_session
):
    from notification_support import default_items, put_settings

    register_token(client, owner_in, "kept")
    assert put_settings(client, owner_in, default_items("owner")).status_code == 200
    assert stored_token(read_session, owner_in) == "kept"


def test_a_session_ended_by_the_user_cannot_register_a_token(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, device_name="Pixel 8")
    revoke_session(database, phone.session_id)
    response = put_token(client, phone, "late")
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")
    assert stored_token(read_session, phone) is None


# Invalid tokens


@pytest.mark.parametrize(
    "token",
    ["", " ", "   ", "\n\t", "a" * 1025, " " + "a" * 1025 + " ", None, 12345, ["abc"]],
    ids=[
        "empty",
        "space",
        "spaces",
        "control_whitespace",
        "too_long",
        "too_long_trimmed",
        "null",
        "number",
        "array",
    ],
)
def test_an_invalid_token_is_rejected_on_the_token_field(
    client, database, owner_in, read_session, token
):
    response = put_token(client, owner_in, token)
    assert_error(response, 422, "VALIDATION_FAILED", "token")
    assert stored_token(read_session, owner_in) is None


def test_a_missing_token_is_rejected_on_the_token_field(client, database, owner_in):
    response = client.put(PUSH_TOKEN, json={}, headers=owner_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "token")


def test_a_missing_body_is_rejected(client, database, owner_in):
    response = client.put(PUSH_TOKEN, headers=owner_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_rejected_token_keeps_the_registered_one(
    client, database, owner_in, read_session
):
    register_token(client, owner_in, "good")
    put_token(client, owner_in, "")
    put_token(client, owner_in, "a" * 1025)
    assert stored_token(read_session, owner_in) == "good"
