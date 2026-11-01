"""Who may call the user-account endpoints."""

from uuid import uuid4

import pytest
from user_account_support import (
    account_url,
    assert_error,
    count_rows,
    get_row,
    refresh,
)

BODY = {"name": "Budi Santoso", "email": "budi@example.com", "status": "active"}

REQUESTS = [
    pytest.param("get", "/user-accounts", None, id="list"),
    pytest.param("get", account_url(uuid4()), None, id="get"),
    pytest.param("put", account_url(uuid4()), BODY, id="edit"),
    pytest.param("delete", account_url(uuid4()), None, id="delete"),
]


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_without_a_token_is_rejected(client, database, method, url, body):
    response = client.request(method, url, json=body)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_with_a_garbage_token_is_rejected(
    client, database, method, url, body
):
    response = client.request(
        method, url, json=body, headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_a_request_from_an_unverified_admin_is_rejected(
    client, database, make_user, sign_in, method, url, body
):
    headers = sign_in(make_user(role=role("admin"), email_verified=False)).headers
    response = client.request(method, url, json=body, headers=headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
@pytest.mark.parametrize(("method", "url", "body"), REQUESTS)
def test_every_role_but_the_admin_is_forbidden_everywhere(
    client, database, make_user, sign_in, name, method, url, body
):
    headers = sign_in(make_user(role=role(name))).headers
    response = client.request(method, url, json=body, headers=headers)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
def test_a_forbidden_caller_cannot_read_an_existing_account(
    client, database, make_user, sign_in, admin, name
):
    headers = sign_in(make_user(role=role(name))).headers
    response = client.get(account_url(admin.id), headers=headers)
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
def test_a_forbidden_caller_edits_nothing(
    client, database, make_user, sign_in, mailbox, name
):
    target = make_user(name="Dewi Owner", email="dewi@example.com")
    headers = sign_in(make_user(role=role(name))).headers
    response = client.put(
        account_url(target.id),
        headers=headers,
        json={"name": "Changed", "email": "changed@example.com", "status": "inactive"},
    )
    assert_error(response, 403, "FORBIDDEN")
    from app.models import EmailChangeRequest, UserAccount

    row = get_row(database, UserAccount, target.id)
    assert (row.name, row.email, row.status) == (
        "Dewi Owner",
        "dewi@example.com",
        "active",
    )
    assert count_rows(database, EmailChangeRequest) == 0
    assert mailbox.is_empty


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
def test_a_forbidden_caller_deletes_nothing(client, database, make_user, sign_in, name):
    from app.models import UserAccount

    target = make_user(name="Dewi Owner")
    session = sign_in(target)
    headers = sign_in(make_user(role=role(name))).headers
    response = client.delete(account_url(target.id), headers=headers)
    assert_error(response, 403, "FORBIDDEN")
    row = get_row(database, UserAccount, target.id)
    assert row.deleted_at is None
    assert refresh(client, session.tokens.refresh_token).status_code == 200


def test_an_admin_reading_an_unknown_account_gets_not_found(client, database, admin_in):
    response = client.get(account_url(uuid4()), headers=admin_in.headers)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")
